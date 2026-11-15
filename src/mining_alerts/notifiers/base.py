from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter

from ..models import Announcement


class Notifier(ABC):
    name: str

    @abstractmethod
    def send(self, items: list[Announcement], warnings: list[str] | tuple = (),
             kind: str = "alert") -> None:
        """Deliver one message with all items (+ source-health warnings). Raise on failure.
        kind: "alert" (new items), "digest" (daily digest, may include urgent items too)
        or "weekly" (recap of everything sent in the last 7 days)."""


def fmt_date(item: Announcement) -> str:
    return item.published.strftime("%Y-%m-%d") if item.published else ""


def tag(item: Announcement) -> str:
    """Main category label, e.g. "[M&A]" (empty if uncategorized)."""
    return f"[{item.categories[0]}]" if item.categories else ""


def meta(item: Announcement) -> str:
    """"Newsfile, 2026-11-12 · also: Reuters, Mining.com" """
    parts = [p for p in (item.publisher, fmt_date(item)) if p]
    out = ", ".join(parts)
    if item.also_reported_by:
        extra = item.also_reported_by[:4]
        more = len(item.also_reported_by) - len(extra)
        out += (" · also: " if out else "also: ") + ", ".join(extra) + (f" +{more}" if more > 0 else "")
    return out


def summary_line(items: list[Announcement], kind: str = "alert") -> str:
    counts = Counter(i.categories[0] for i in items if i.categories)
    detail = ", ".join(f"{n} {c}" for c, n in counts.most_common(4))
    if kind == "weekly":
        return f"Weekly recap: {len(items)} announcement(s) in the last 7 days" + (
            f" ({detail})" if detail else "")
    head = "Daily digest: " if kind == "digest" else ""
    return f"{head}{len(items)} new announcement(s)" + (f" ({detail})" if detail else "")

SUBJECT_PREFIX = {"alert": "[Mining alerts]", "digest": "[Mining digest]", "weekly": "[Mining weekly recap]"}


def plain_digest(items: list[Announcement], warnings: list[str] | tuple = (),
                 kind: str = "alert") -> str:
    from . import group_by_label  # local import avoids a cycle
    lines = [summary_line(items, kind) + "\n"] if items else []
    for label, is_project, its in group_by_label(items):
        lines.append(f"{'★ PROJECT' if is_project else 'Company'}: {label}")
        for it in its:
            lines.append(f"  - {' '.join(x for x in (tag(it), it.title) if x)}")
            m = meta(it)
            if m:
                lines.append(f"    {m}")
            lines.append(f"    {it.url}")
        lines.append("")
    if warnings:
        lines.append("⚠ Source health")
        lines.extend(f"  - {w}" for w in warnings)
    return "\n".join(lines)
