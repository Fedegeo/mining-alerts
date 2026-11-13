"""Load the watchlist YAML and match announcements against it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Announcement, Match


def _term_regex(terms: list[str]) -> re.Pattern | None:
    terms = [t for t in terms if t and t.strip()]
    if not terms:
        return None
    # Longest first so "Orion Resource Partners" wins over "Orion"; \b-style boundaries
    # that also work for accented characters.
    alts = "|".join(re.escape(t.strip()) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


@dataclass
class Project:
    name: str
    aliases: list[str]
    context: list[str] = field(default_factory=list)
    status: str = "confirmed"
    notes: str = ""

    def __post_init__(self) -> None:
        self._alias_re = _term_regex(self.aliases or [self.name])
        self._context_re = _term_regex(self.context)

    def matches(self, text: str, company_matched: bool) -> bool:
        if not self._alias_re or not self._alias_re.search(text):
            return False
        if self._context_re is None or company_matched:
            return True
        return bool(self._context_re.search(text))


@dataclass
class Company:
    id: str
    name: str
    aliases: list[str]
    context: list[str] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    status: str = "confirmed"
    notes: str = ""
    google_news: bool = False
    languages: list[str] = field(default_factory=lambda: ["en"])
    rss: list[str] = field(default_factory=list)
    edgar: str | None = None
    asx: str | None = None
    webpages: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._alias_re = _term_regex(self.aliases or [self.name])
        self._context_re = _term_regex(self.context)

    def text_matches(self, text: str) -> bool:
        if not self._alias_re or not self._alias_re.search(text):
            return False
        return self._context_re is None or bool(self._context_re.search(text))


@dataclass
class Watchlist:
    companies: list[Company]
    max_age_days: int = 10

    @classmethod
    def load(cls, path: str | Path) -> "Watchlist":
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        defaults = data.get("defaults", {}) or {}
        companies = []
        seen_ids: set[str] = set()
        for raw in data.get("companies", []) or []:
            raw = dict(raw)
            if raw["id"] in seen_ids:
                raise ValueError(f"duplicate company id in watchlist: {raw['id']}")
            seen_ids.add(raw["id"])
            projects = [Project(**p) for p in raw.pop("projects", []) or []]
            raw.setdefault("languages", defaults.get("languages", ["en"]))
            companies.append(Company(projects=projects, **raw))
        return cls(companies=companies, max_age_days=int(defaults.get("max_age_days", 10)))

    def get(self, company_id: str) -> Company | None:
        return next((c for c in self.companies if c.id == company_id), None)

    def match(self, item: Announcement) -> list[Match]:
        """Return every company/project this item is about (empty list = irrelevant)."""
        text = item.text
        found: list[Match] = []
        for company in self.companies:
            company_hit = company.id == item.company_hint or company.text_matches(text)
            project_hits = [p for p in company.projects if p.matches(text, company_hit)]
            for p in project_hits:
                found.append(Match(company.id, company.name, p.name))
            if company_hit and not project_hits:
                found.append(Match(company.id, company.name))
        return found
