"""Fetch -> match -> tag -> dedupe -> notify -> remember."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

from . import dedupe
from .classify import categorize
from .models import Announcement
from .notifiers import Notifier
from .sources import Source
from .storage import Store
from .watchlist import Watchlist

log = logging.getLogger(__name__)

#: Warn (once) when a source has failed this many runs in a row.
FAILURE_ALERT_THRESHOLD = 3
#: Near-duplicates of anything alerted within this many days are not re-sent.
HISTORY_DAYS = 7
#: Minimum seconds between requests to the same host (Google News rate-limits bursts).
HOST_DELAY = {"news.google.com": 1.5, "www.sec.gov": 0.5}


@dataclass
class RunResult:
    fetched: int = 0
    relevant: int = 0
    new: list[Announcement] = field(default_factory=list)
    baselined_sources: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)   # source-health warnings sent to the user
    collapsed: int = 0                                   # near-duplicates merged/suppressed


class _HostThrottle:
    def __init__(self, delays: dict[str, float]):
        self.delays, self.last = delays, {}

    def wait(self, src: Source) -> None:
        host = urlsplit(getattr(src, "url", "") or "").netloc
        delay = self.delays.get(host, 0)
        if delay and host in self.last:
            remaining = self.last[host] + delay - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        self.last[host] = time.monotonic()


def run(watchlist: Watchlist, sources: list[Source], store: Store, notifiers: list[Notifier],
        session: requests.Session | None, *, dry_run: bool = False, baseline: bool = True,
        now: datetime | None = None, host_delay: dict[str, float] | None = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=watchlist.max_age_days)
    throttle = _HostThrottle(HOST_DELAY if host_delay is None else host_delay)
    result = RunResult()
    candidates: list[Announcement] = []
    silent: list[Announcement] = []        # remembered but not alerted
    pending: set[str] = set()              # exact url/title keys seen in this run
    ok_sources: list[str] = []

    for src in sources:
        throttle.wait(src)
        try:
            items = src.fetch(session)
        except Exception as exc:  # one broken feed must not stop the run
            log.warning("source %s failed: %s", src.name, exc)
            result.errors[src.name] = str(exc)
            if not dry_run:
                n = store.record_source_failure(src.name, str(exc))
                if n == FAILURE_ALERT_THRESHOLD:
                    result.warnings.append(
                        f"Source '{src.name}' has failed {n} runs in a row: {str(exc)[:200]}")
            continue
        result.fetched += len(items)
        ok_sources.append(src.name)
        first_run = baseline and not store.source_known(src.name)
        if first_run:
            result.baselined_sources.append(src.name)

        for it in items:
            it.matches = watchlist.match(it)
            if not it.matches:
                continue
            result.relevant += 1
            if store.is_seen(it) or it.url_key in pending or it.title_key in pending:
                continue
            pending.update((it.url_key, it.title_key))
            it.categories = categorize(it)
            too_old = it.published is not None and it.published < cutoff
            (silent if first_run or too_old else candidates).append(it)

    # Same story from several outlets -> one alert; and don't re-send a story we
    # already alerted on recently under a different headline.
    history = [dedupe.tokens(t) for t in store.alerted_titles_since(HISTORY_DAYS)]
    to_alert = []
    for it in dedupe.collapse(candidates):
        (silent if dedupe.matches_history(it, history) else to_alert).append(it)
    result.collapsed = len(candidates) - len(to_alert)
    kept = {id(i) for i in to_alert} | {id(i) for i in silent}
    silent.extend(c for c in candidates if id(c) not in kept)  # merged copies

    to_alert.sort(key=lambda i: (not i.is_project_hit, not i.is_high_priority,
                                 -(i.published.timestamp() if i.published else now.timestamp())))
    result.new = to_alert

    if dry_run:
        return result

    if to_alert or result.warnings:
        ok: list[str] = []
        for n in notifiers:
            try:
                n.send(to_alert, warnings=result.warnings)
                ok.append(n.name)
            except Exception as exc:
                log.error("notifier %s failed: %s", n.name, exc)
                result.errors[f"notify:{n.name}"] = str(exc)
        # Remember items only if a real channel (email/slack/...) delivered them - or
        # console is the only channel - so a failed email is retried next run.
        real = [n.name for n in notifiers if n.name != "console"]
        if any(name in ok for name in real) or (not real and ok):
            store.mark_seen(to_alert, alerted=True)
        else:
            log.error("no alert channel succeeded; items will be retried next run")
    store.mark_seen(silent, alerted=False)
    for name in ok_sources:
        store.mark_source(name)
        store.record_source_ok(name)
    return result
