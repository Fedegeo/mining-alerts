"""Load the watchlist YAML and match announcements against it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Announcement, Match


def _term_regex(terms: list[str], prefix: bool = False) -> re.Pattern | None:
    """Case-insensitive whole-word matcher for any of `terms`.

    prefix=True lets a term match the start of a longer word ("drill" -> "drilling",
    "financing" -> "financings"); used for context words, never for names.
    """
    terms = [t for t in terms if t and t.strip()]
    if not terms:
        return None
    # Longest first so "Orion Resource Partners" wins over "Orion"; \b-style boundaries
    # that also work for accented characters.
    alts = "|".join(re.escape(t.strip()) for t in sorted(terms, key=len, reverse=True))
    end = "" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w)(?:{alts}){end}", re.IGNORECASE)


def _vetoed(text: str, exclude_re: re.Pattern | None, strong_re: re.Pattern | None) -> bool:
    """An exclude phrase vetoes the match - unless a full multi-word name is also present
    ("Orion Resource Partners invests in Orion Minerals" is still about Orion RP)."""
    if not exclude_re or not exclude_re.search(text):
        return False
    return not (strong_re and strong_re.search(text))


@dataclass
class Project:
    name: str
    aliases: list[str]
    context: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)  # phrases that veto a match
    status: str = "confirmed"
    notes: str = ""

    def __post_init__(self) -> None:
        self._alias_re = _term_regex(self.aliases or [self.name])
        self._context_re = _term_regex(self.context, prefix=True)
        self._exclude_re = _term_regex(self.exclude)
        self._strong_re = _term_regex([a for a in (self.aliases or [self.name]) if " " in a.strip()])

    def matches(self, text: str, company_matched: bool) -> bool:
        if not self._alias_re or not self._alias_re.search(text):
            return False
        if _vetoed(text, self._exclude_re, self._strong_re):
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
    exclude: list[str] = field(default_factory=list)  # e.g. other companies with similar names
    projects: list[Project] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    status: str = "confirmed"
    notes: str = ""
    google_news: bool = False
    news_query: str | None = None  # optional hand-written Google News query for the company
    languages: list[str] = field(default_factory=lambda: ["en"])
    rss: list[str] = field(default_factory=list)
    edgar: str | None = None
    asx: str | None = None
    webpages: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._alias_re = _term_regex(self.aliases or [self.name])
        self._context_re = _term_regex(self.context, prefix=True)
        self._exclude_re = _term_regex(self.exclude)
        self._strong_re = _term_regex([a for a in (self.aliases or [self.name]) if " " in a.strip()])

    def excluded(self, text: str) -> bool:
        return _vetoed(text, self._exclude_re, self._strong_re)

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

    def lint(self) -> list[tuple[str, str]]:
        """Return (level, message) pairs describing weak spots in the watchlist."""
        out: list[tuple[str, str]] = []
        for c in self.companies:
            if c.status != "confirmed":
                out.append(("CONFIRM", f"{c.name}: marked needs_confirmation"))
            # Short one-word names ("Orion", "Minto") collide with other things; long
            # distinctive ones ("Heliostar") rarely do.
            single = [a for a in c.aliases if " " not in a.strip() and len(a.strip()) < 8]
            if single and not c.context:
                out.append(("RISK", f"{c.name}: one-word alias(es) {single} with no context "
                                    "words - expect false positives"))
            sources = c.google_news or c.rss or c.edgar or c.asx or c.webpages
            if not sources:
                out.append(("ERROR", f"{c.name}: no sources configured - nothing will be fetched"))
            if not (c.rss or c.edgar or c.asx or c.webpages):
                out.append(("INFO", f"{c.name}: only Google News - an official feed would be faster"))
            for p in c.projects:
                if p.status != "confirmed":
                    out.append(("CONFIRM", f"{c.name} / {p.name}: marked needs_confirmation"))
                psingle = [a for a in (p.aliases or [p.name]) if " " not in a.strip()]
                if psingle and not p.context and len(min(psingle, key=len)) < 6:
                    out.append(("RISK", f"{c.name} / {p.name}: short alias {psingle} with no context"))
            for url in c.rss:
                if not url.startswith(("http://", "https://")):
                    out.append(("ERROR", f"{c.name}: rss entry is not a URL: {url}"))
        order = {"ERROR": 0, "RISK": 1, "CONFIRM": 2, "INFO": 3}
        return sorted(out, key=lambda x: order[x[0]])

    def get(self, company_id: str) -> Company | None:
        return next((c for c in self.companies if c.id == company_id), None)

    def match(self, item: Announcement) -> list[Match]:
        """Return every company/project this item is about (empty list = irrelevant)."""
        text = item.text
        found: list[Match] = []
        for company in self.companies:
            own_source = company.id == item.company_hint
            if not own_source and company.excluded(text):
                continue
            company_hit = own_source or company.text_matches(text)
            project_hits = [p for p in company.projects if p.matches(text, company_hit)]
            for p in project_hits:
                found.append(Match(company.id, company.name, p.name))
            if company_hit and not project_hits:
                found.append(Match(company.id, company.name))
        return found
