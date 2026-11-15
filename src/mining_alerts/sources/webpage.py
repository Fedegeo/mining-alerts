"""Scrape a company's newsroom page for links (for companies without an RSS feed).

Every link whose href matches `link_pattern` (regex) and has a reasonably long text
is treated as an announcement. The first run is baselined, so only links that appear
later trigger alerts.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from ..models import Announcement
from .base import Source


KNOWN_PAGE_HOSTS = {"investegate.co.uk": "RNS", "lse.co.uk": "RNS"}


def _clean_title(text: str) -> str:
    # RNS headlines are often ALL CAPS - make them readable but keep short acronyms.
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        words = text.lower().split()
        text = " ".join(w.upper() if len(w) <= 3 and w.isalpha() and w in _ACRONYMS else w
                        for w in words)
        text = text[:1].upper() + text[1:]
    return text


_ACRONYMS = {"rns", "agm", "egm", "loi", "pea", "pfs", "dfs", "mre", "us", "uk", "nsr", "ceo", "cfo",
             "tsx", "lse", "aim", "esg", "ni", "q1", "q2", "q3", "q4", "h1", "h2"}


def parse_links(html: str, base_url: str, pattern: str, source: str,
                company_hint: str | None) -> list[Announcement]:
    rx = re.compile(pattern)
    host = urlsplit(base_url).netloc.lower()
    publisher = next((n for h, n in KNOWN_PAGE_HOSTS.items() if host.endswith(h)), "company website")
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = _clean_title(" ".join(a.get_text(" ").split()))
        if len(text) < 15 or not rx.search(href) or href in seen:
            continue
        seen.add(href)
        out.append(Announcement(title=text, url=href, source=source, company_hint=company_hint,
                                publisher=publisher))
    return out


class WebpageSource(Source):
    def __init__(self, url: str, link_pattern: str, company_hint: str | None):
        self.url = url
        self.link_pattern = link_pattern
        self.company_hint = company_hint
        self.name = f"web:{url}"

    def fetch(self, session: requests.Session) -> list[Announcement]:
        resp = session.get(self.url, timeout=self.timeout)
        resp.raise_for_status()
        return parse_links(resp.text, self.url, self.link_pattern, self.name, self.company_hint)
