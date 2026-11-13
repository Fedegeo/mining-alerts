"""Fetch -> match -> dedupe -> notify -> remember."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

from .models import Announcement
from .notifiers import Notifier
from .sources import Source
from .storage import Store
from .watchlist import Watchlist

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    fetched: int = 0
    relevant: int = 0
    new: list[Announcement] = field(default_factory=list)
    baselined_sources: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def run(watchlist: Watchlist, sources: list[Source], store: Store, notifiers: list[Notifier],
        session: requests.Session, *, dry_run: bool = False, baseline: bool = True,
        now: datetime | None = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=watchlist.max_age_days)
    result = RunResult()
    to_alert: list[Announcement] = []
    silent: list[Announcement] = []   # remembered but not alerted
    pending: dict[str, Announcement] = {}  # dedupe within this run (url/title keys)
    new_sources: list[str] = []

    for src in sources:
        try:
            items = src.fetch(session)
        except Exception as exc:  # one broken feed must not stop the run
            log.warning("source %s failed: %s", src.name, exc)
            result.errors[src.name] = str(exc)
            continue
        result.fetched += len(items)
        first_run = baseline and not store.source_known(src.name)
        if first_run:
            result.baselined_sources.append(src.name)
        new_sources.append(src.name)

        for it in items:
            it.matches = watchlist.match(it)
            if not it.matches:
                continue
            result.relevant += 1
            if store.is_seen(it) or it.url_key in pending or it.title_key in pending:
                continue
            pending[it.url_key] = pending[it.title_key] = it
            too_old = it.published is not None and it.published < cutoff
            (silent if first_run or too_old else to_alert).append(it)

    to_alert.sort(key=lambda i: (not i.is_project_hit,
                                 -(i.published.timestamp() if i.published else now.timestamp())))
    result.new = to_alert

    if dry_run:
        return result

    if to_alert:
        ok: list[str] = []
        for n in notifiers:
            try:
                n.send(to_alert)
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
    for name in new_sources:
        store.mark_source(name)
    return result
