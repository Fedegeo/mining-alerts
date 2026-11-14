"""ASX company announcements (e.g. Lithium Energy, ASX:LEL).

Uses the JSON endpoint behind asx.com.au's announcements page. It's unofficial and
may change; failures are logged and the run continues with other sources.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..models import Announcement
from .base import Source

API = "https://asx.api.markitdigital.com/asx-research/1.0/companies/{code}/announcements"
PAGE = "https://www.asx.com.au/markets/trade-our-cash-market/announcements.{code}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_asx(payload: dict, code: str, company_hint: str) -> list[Announcement]:
    items = (payload.get("data") or {}).get("items") or []
    out = []
    for it in items:
        headline = (it.get("headline") or "").strip()
        if not headline:
            continue
        key = it.get("documentKey") or it.get("id") or headline
        # Link to the public announcements page; the doc key makes the URL unique for dedupe.
        url = f"{PAGE.format(code=code.lower())}#{key}"
        sensitive = " [price-sensitive]" if it.get("isPriceSensitive") else ""
        out.append(Announcement(
            title=f"[ASX:{code.upper()}] {headline}{sensitive}", url=url,
            source=f"asx:{code.upper()}", company_hint=company_hint, publisher="ASX",
            published=_parse_dt(it.get("date")),
            summary=", ".join(it.get("announcementTypes") or []),
        ))
    return out


class ASXSource(Source):
    def __init__(self, code: str, company_hint: str):
        self.code = code
        self.company_hint = company_hint
        self.name = f"asx:{code.upper()}"

    def fetch(self, session: requests.Session) -> list[Announcement]:
        resp = session.get(API.format(code=self.code.lower()), params={"count": 20},
                           timeout=self.timeout)
        resp.raise_for_status()
        return parse_asx(resp.json(), self.code, self.company_hint)
