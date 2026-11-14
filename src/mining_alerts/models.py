"""Core data types."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                    "oc", "ref", "fbclid", "gclid"}


def canonical_url(url: str) -> str:
    """Strip tracking params / fragments so the same article dedupes across feeds."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                       urlencode(query), ""))


def normalize_title(title: str) -> str:
    # Google News appends " - Publisher" to titles; drop it so syndicated copies collapse.
    title = re.sub(r"\s+-\s+[^-]{2,60}$", "", title.strip())
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass
class Match:
    company_id: str
    company_name: str
    project: str | None = None  # project name if the hit was on a project

    @property
    def label(self) -> str:
        return f"{self.company_name} / {self.project}" if self.project else self.company_name


@dataclass
class Announcement:
    title: str
    url: str
    source: str                      # e.g. "google_news:en", "edgar:LAC"
    published: datetime | None = None
    summary: str = ""
    company_hint: str | None = None  # set when the source itself belongs to one company
    publisher: str = ""              # e.g. "Newsfile", "Reuters" (when the feed says)
    matches: list[Match] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)   # set by classify.categorize
    also_reported_by: list[str] = field(default_factory=list)  # collapsed near-duplicates

    @property
    def is_high_priority(self) -> bool:
        from .classify import HIGH_PRIORITY
        return any(c in HIGH_PRIORITY for c in self.categories)

    @property
    def url_key(self) -> str:
        return _sha("u:" + canonical_url(self.url))

    @property
    def title_key(self) -> str:
        return _sha("t:" + normalize_title(self.title))

    @property
    def is_project_hit(self) -> bool:
        return any(m.project for m in self.matches)

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.summary}"
