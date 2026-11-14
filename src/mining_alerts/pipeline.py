"""Fetch -> match -> tag -> dedupe -> notify -> remember."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

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
    queued: list[Announcement] = field(default_factory=list)  # held for the daily digest
    digest_sent: int = 0                                 # queued items delivered this run


@dataclass
class Delivery:
    """When to send.

    instant - every new item goes out on the run that finds it (default)
    smart   - project news and high-priority types (M&A, financing, permits...) go out
              immediately; routine company news is collected into one daily digest
    daily   - everything is collected into one daily digest
    """
    mode: str = "instant"
    digest_hour: int = 7          # local hour after which the daily digest is sent
    tz: str = "UTC"

    MODES = ("instant", "smart", "daily")

    def __post_init__(self) -> None:
        if self.mode not in self.MODES:
            raise ValueError(f"ALERT_MODE must be one of {self.MODES}, got {self.mode!r}")
        ZoneInfo(self.tz)  # fail fast on a bad time zone name

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Delivery":
        return cls(mode=env.get("ALERT_MODE", "instant").strip().lower() or "instant",
                   digest_hour=int(env.get("DIGEST_HOUR", "7")),
                   tz=env.get("DIGEST_TZ", "UTC").strip() or "UTC")

    def is_urgent(self, item: Announcement) -> bool:
        if self.mode == "instant":
            return True
        if self.mode == "smart":
            return item.is_project_hit or item.is_high_priority
        return False

    def local_date(self, now: datetime) -> str:
        return now.astimezone(ZoneInfo(self.tz)).date().isoformat()

    def digest_due(self, now: datetime, last_digest: str | None) -> bool:
        local = now.astimezone(ZoneInfo(self.tz))
        return local.hour >= self.digest_hour and last_digest != local.date().isoformat()


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
        now: datetime | None = None, host_delay: dict[str, float] | None = None,
        delivery: "Delivery | None" = None, force_digest: bool = False) -> RunResult:
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

    delivery = delivery or Delivery()
    urgent = _sorted([i for i in to_alert if delivery.is_urgent(i)], now)
    later = [i for i in to_alert if not delivery.is_urgent(i)]
    result.new, result.queued = urgent, later

    if dry_run:
        return result

    # Non-urgent items wait in the queue for the daily digest. They count as "seen"
    # now (so they aren't queued twice) and leave the queue only once delivered.
    if later:
        store.enqueue(later)
        store.mark_seen(later, alerted=True)
    # In instant mode the queue is normally empty; anything left over from an earlier
    # smart/daily setup is flushed straight away.
    digest_due = delivery.mode == "instant" or force_digest or delivery.digest_due(
        now, store.get_value("last_digest"))
    digest_items = store.queued() if digest_due else []

    delivered = True
    outgoing = _sorted(urgent + digest_items, now)
    if outgoing or result.warnings:
        delivered = _deliver(notifiers, outgoing, result, digest=bool(digest_items))
        if delivered:
            store.mark_seen(urgent, alerted=True)
            store.dequeue(digest_items)
            result.digest_sent = len(digest_items)
        else:
            log.error("no alert channel succeeded; items will be retried next run")
    if digest_due and delivered and delivery.mode != "instant":
        store.set_value("last_digest", delivery.local_date(now))
    store.mark_seen(silent, alerted=False)
    for name in ok_sources:
        store.mark_source(name)
        store.record_source_ok(name)
    return result


def _sorted(items: list[Announcement], now: datetime) -> list[Announcement]:
    return sorted(items, key=lambda i: (not i.is_project_hit, not i.is_high_priority,
                                        -(i.published.timestamp() if i.published else now.timestamp())))


def _deliver(notifiers: list[Notifier], items: list[Announcement], result: RunResult,
             digest: bool) -> bool:
    """Send via every channel. True if a real channel (email/slack/...) succeeded - or
    console is the only channel - so a failed email is retried next run."""
    ok: list[str] = []
    for n in notifiers:
        try:
            n.send(items, warnings=result.warnings, digest=digest)
            ok.append(n.name)
        except Exception as exc:
            log.error("notifier %s failed: %s", n.name, exc)
            result.errors[f"notify:{n.name}"] = str(exc)
    real = [n.name for n in notifiers if n.name != "console"]
    return any(name in ok for name in real) or (not real and bool(ok))
