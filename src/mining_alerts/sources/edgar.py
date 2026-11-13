"""SEC EDGAR filings (8-K, 6-K, 40-F, 10-Q...) for US/cross-listed companies.

SEC requires a descriptive User-Agent with contact info: set SEC_USER_AGENT,
e.g. "MiningAlerts yourname@example.com".
"""
from __future__ import annotations

import logging
import os

import requests

from ..models import Announcement
from .rss import parse_feed
from .base import Source

log = logging.getLogger(__name__)

# Forms that usually carry news. Skip ownership filings (Forms 3/4/5, 13G...).
NEWS_FORMS = ("8-K", "6-K", "40-F", "10-K", "10-Q", "20-F", "425", "S-1", "F-10", "SUPPL")


class EdgarSource(Source):
    def __init__(self, ticker_or_cik: str, company_hint: str):
        self.ticker = ticker_or_cik
        self.company_hint = company_hint
        self.name = f"edgar:{ticker_or_cik}"
        self.url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                    f"&CIK={ticker_or_cik}&type=&dateb=&owner=exclude&count=40&output=atom")

    def fetch(self, session: requests.Session) -> list[Announcement]:
        ua = os.environ.get("SEC_USER_AGENT")
        if not ua:
            log.warning("SEC_USER_AGENT not set; SEC may reject requests for %s", self.name)
        headers = {"User-Agent": ua} if ua else {}
        resp = session.get(self.url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        items = parse_feed(resp.content, self.name, self.company_hint)
        out = []
        for it in items:
            # EDGAR titles look like "8-K - Current report"; keep news-bearing forms only.
            form = it.title.split(" - ", 1)[0].strip()
            if form.upper().startswith(NEWS_FORMS):
                it.title = f"[SEC {form}] {it.title.split(' - ', 1)[-1]}"
                out.append(it)
        return out
