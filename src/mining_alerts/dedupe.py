"""Collapse the same story carried by several outlets ("near-duplicates").

Exact URL / headline duplicates are handled by the store. This module catches the
case where Reuters, Mining.com and the company's own wire release each word the
headline slightly differently.
"""
from __future__ import annotations

from .models import Announcement, normalize_title

_STOP = {"the", "a", "an", "of", "at", "in", "on", "for", "to", "and", "or", "with", "its", "by",
         "from", "as", "is", "de", "la", "el", "en", "y", "del", "los", "las", "inc", "ltd",
         "corp", "corporation", "limited", "announces", "reports", "provides"}

# Preferred originals: the company's own channel, then press-release wires.
_WIRES = ("newsfile", "globenewswire", "business wire", "businesswire", "pr newswire",
          "accesswire", "cision", "rns", "marketscreener")

SIMILARITY = 0.6


def tokens(title: str) -> frozenset[str]:
    return frozenset(w for w in normalize_title(title).split() if w not in _STOP and len(w) > 1)


def similar(a: frozenset[str], b: frozenset[str], threshold: float = SIMILARITY) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    # Jaccard, or containment for a short headline inside a longer one.
    shorter = min(len(a), len(b))
    return inter / len(a | b) >= threshold or (shorter >= 4 and inter / shorter >= 0.85)


def _rank(item: Announcement) -> tuple:
    pub = item.publisher.lower()
    return (
        0 if item.company_hint else 1,
        0 if any(w in pub for w in _WIRES) else 1,
        item.published.timestamp() if item.published else float("inf"),
    )


def collapse(items: list[Announcement]) -> list[Announcement]:
    """Group near-duplicate items; keep the best one, list the others' publishers."""
    clusters: list[tuple[frozenset[str], list[Announcement]]] = []
    for it in items:
        toks = tokens(it.title)
        for ctoks, members in clusters:
            same_topic = {m.label for m in it.matches} & {m.label for x in members for m in x.matches}
            if same_topic and similar(toks, ctoks):
                members.append(it)
                break
        else:
            clusters.append((toks, [it]))

    out = []
    for _, members in clusters:
        members.sort(key=_rank)
        best = members[0]
        others = [m.publisher or m.source.split(":")[0] for m in members[1:]]
        best.also_reported_by = sorted({o for o in others if o and o != best.publisher})
        # Merge tags so the kept item carries everything learned from its copies.
        for m in members[1:]:
            for match in m.matches:
                if match.label not in {x.label for x in best.matches}:
                    best.matches.append(match)
        out.append(best)
    return out


def matches_history(item: Announcement, history: list[frozenset[str]]) -> bool:
    toks = tokens(item.title)
    return any(similar(toks, h) for h in history)
