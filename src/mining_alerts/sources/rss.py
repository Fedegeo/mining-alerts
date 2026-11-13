"""Generic RSS 2.0 / Atom feed source (stdlib parser, no feedparser dependency)."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from ..models import Announcement
from .base import Source

ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)          # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_bytes: bytes, source: str, company_hint: str | None = None) -> list[Announcement]:
    root = ET.fromstring(xml_bytes)
    items: list[Announcement] = []

    for it in root.iter("item"):                    # RSS 2.0
        title = strip_html(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(Announcement(
            title=title, url=link, source=source, company_hint=company_hint,
            published=parse_date(it.findtext("pubDate")),
            summary=strip_html(it.findtext("description"))[:1000],
        ))

    for entry in root.iter(f"{ATOM}entry"):         # Atom
        title = strip_html(entry.findtext(f"{ATOM}title"))
        # Note: don't use `or` here - childless Elements are falsy.
        link_el = entry.find(f"{ATOM}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href", "").strip() if link_el is not None else ""
        if not title or not link:
            continue
        summary = entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content") or ""
        items.append(Announcement(
            title=title, url=link, source=source, company_hint=company_hint,
            published=parse_date(entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published")),
            summary=strip_html(summary)[:1000],
        ))
    return items


class RSSSource(Source):
    def __init__(self, url: str, company_hint: str | None = None, name: str | None = None):
        self.url = url
        self.company_hint = company_hint
        self.name = name or f"rss:{url}"

    def fetch(self, session: requests.Session) -> list[Announcement]:
        resp = session.get(self.url, timeout=self.timeout)
        resp.raise_for_status()
        return parse_feed(resp.content, self.name, self.company_hint)
