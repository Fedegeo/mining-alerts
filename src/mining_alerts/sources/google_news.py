"""Google News RSS search - broad coverage of press releases and trade press."""
from __future__ import annotations

from urllib.parse import quote_plus

from ..watchlist import Company
from .rss import RSSSource

# Google News edition parameters per language.
EDITIONS = {
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    "es": {"hl": "es-419", "gl": "AR", "ceid": "AR:es-419"},
}


def _quoted(terms: list[str]) -> str:
    terms = [t for t in terms if t]
    return " OR ".join(f'"{t}"' for t in terms)


def build_queries(company: Company) -> list[tuple[str, str]]:
    """Return (label, query) pairs: one for the company, one per project."""
    queries: list[tuple[str, str]] = []
    # Multi-word aliases are precise enough on their own; single bare words (e.g. "Orion")
    # are left to the matcher's context filter and not searched directly.
    precise = [a for a in company.aliases if " " in a]
    if precise:
        queries.append((company.id, _quoted(precise)))
    else:  # only single-word aliases: add context words to keep the search on-topic
        q = _quoted(company.aliases or [company.name])
        if company.context:
            q = f"({q}) ({' OR '.join(company.context[:6])})"
        queries.append((company.id, q))
    for p in company.projects:
        q = _quoted(p.aliases or [p.name])
        if p.context:
            q = f"({q}) ({' OR '.join(p.context[:6])})"
        queries.append((f"{company.id}/{p.name}", q))
    return queries


def google_news_url(query: str, lang: str = "en") -> str:
    ed = EDITIONS.get(lang, EDITIONS["en"])
    # when:14d keeps results recent; the pipeline also filters by max_age_days.
    return (f"https://news.google.com/rss/search?q={quote_plus(query + ' when:14d')}"
            f"&hl={ed['hl']}&gl={ed['gl']}&ceid={ed['ceid']}")


def google_news_sources(company: Company) -> list[RSSSource]:
    out = []
    for lang in company.languages:
        for label, query in build_queries(company):
            # No company_hint: search results must still pass the matcher.
            out.append(RSSSource(google_news_url(query, lang), name=f"google_news:{lang}:{label}"))
    return out
