"""Build all sources from the watchlist."""
from __future__ import annotations

from ..watchlist import Watchlist
from .asx import ASXSource
from .base import Source, make_session
from .edgar import EdgarSource
from .google_news import google_news_sources
from .rss import RSSSource
from .webpage import WebpageSource

__all__ = ["Source", "make_session", "build_sources"]


def build_sources(watchlist: Watchlist) -> list[Source]:
    sources: list[Source] = []
    for c in watchlist.companies:
        if c.google_news:
            sources.extend(google_news_sources(c))
        for url in c.rss:
            sources.append(RSSSource(url, company_hint=c.id, name=f"rss:{c.id}:{url}"))
        if c.edgar:
            sources.append(EdgarSource(c.edgar, company_hint=c.id))
        if c.asx:
            sources.append(ASXSource(c.asx, company_hint=c.id))
        for page in c.webpages:
            sources.append(WebpageSource(page["url"], page.get("link_pattern", "."), c.id))
    # Same URL may be requested by two companies (e.g. shared project) - keep one.
    unique: dict[str, Source] = {}
    for s in sources:
        unique.setdefault(getattr(s, "url", s.name), s)
    return list(unique.values())
