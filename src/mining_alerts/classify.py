"""Rule-based tagging of announcements by type (English + Spanish keywords).

Cheap, offline and predictable. An item can get several tags; the first one is shown
as the main label. Order below = display priority.
"""
from __future__ import annotations

import re

from .models import Announcement

_RULES: list[tuple[str, list[str]]] = [
    ("M&A", [r"acqui(re|res|red|sition)", r"merger", r"merge[sd]?", r"takeover", r"take-over",
             r"arrangement agreement", r"business combination", r"tender offer", r"divest\w*",
             r"(sale|sells?|sold) (of )?(its|the)? ?(interest|stake|project|asset)",
             r"adquisici[oó]n", r"fusi[oó]n", r"compra de"]),
    ("Royalty/Stream", [r"royalt(y|ies)", r"\bstream\b", r"streaming", r"\bNSR\b", r"\bGRR\b",
                        r"production payment", r"regal[ií]a"]),
    ("Financing", [r"financing", r"private placement", r"bought deal", r"(public|share|equity|notes?) offering",
                   r"credit facility", r"\bloan\b", r"\bdebt\b", r"bond", r"prepayment", r"offtake",
                   r"strategic investment", r"funding", r"raises? \$", r"\bDFC\b", r"financiamiento",
                   r"inversi[oó]n"]),
    ("Resource/Study", [r"mineral resource", r"\breserves?\b", r"\bMRE\b", r"\bPEA\b", r"preliminary economic",
                        r"pre-?feasibility", r"feasibility study", r"\bPFS\b", r"\bDFS\b", r"\bBFS\b",
                        r"technical report", r"43-101", r"\bJORC\b", r"scoping study",
                        r"estudio de factibilidad", r"recursos? minerales?"]),
    ("Permits", [r"permit\w*", r"environmental (impact|approval|licen[cs]e)", r"\bEIA\b", r"\bMIA\b",
                 r"\bRIGI\b", r"approv(al|ed|es)", r"licen[cs]e", r"concession", r"record of decision",
                 r"\bROD\b", r"permiso", r"aprobaci[oó]n", r"licencia"]),
    ("Legal", [r"lawsuit", r"litigation", r"\bcourt\b", r"arbitration", r"ruling", r"injunction",
               r"\bsue[sd]?\b", r"judgment", r"receivership", r"insolvency", r"\bCCAA\b", r"demanda"]),
    ("Drilling", [r"\bdrill\w*", r"intercepts?", r"\bg/t\b", r"assays?", r"metres grading",
                  r"meters grading", r"perforaci[oó]n", r"sondaje"]),
    ("Production", [r"production", r"commercial production", r"first (gold|pour|concentrate|production)",
                    r"gold pour", r"ramp-?up", r"construction", r"commissioning", r"restart",
                    r"\bGEOs?\b", r"deliveries", r"guidance", r"producci[oó]n", r"construcci[oó]n"]),
    ("Results", [r"\bQ[1-4]\b", r"quarter(ly)?", r"(financial|operating|annual|interim) results",
                 r"earnings", r"financial statements", r"\bMD&A\b", r"dividend", r"conference call",
                 r"resultados"]),
    ("Management", [r"appoint\w*", r"\bCEO\b", r"\bCFO\b", r"\bCOO\b", r"board of directors",
                    r"resign\w*", r"steps down", r"nombramiento"]),
]

#: Categories that are worth flagging in the subject line / ordering first.
HIGH_PRIORITY = {"M&A", "Royalty/Stream", "Financing", "Resource/Study", "Permits", "Legal"}

_COMPILED = [(name, re.compile("|".join(f"(?:{p})" for p in pats), re.IGNORECASE))
             for name, pats in _RULES]


def categorize(item: Announcement) -> list[str]:
    title, text = item.title, item.text
    cats = []
    if title.startswith("[SEC "):
        cats.append("Filing")
    # Title hits rank ahead of summary-only hits.
    for name, rx in _COMPILED:
        if rx.search(title):
            cats.append(name)
    for name, rx in _COMPILED:
        if name not in cats and rx.search(text):
            cats.append(name)
    return cats
