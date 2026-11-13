from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Announcement


class Notifier(ABC):
    name: str

    @abstractmethod
    def send(self, items: list[Announcement]) -> None:
        """Deliver one digest containing all new items. Raise on failure."""


def fmt_date(item: Announcement) -> str:
    return item.published.strftime("%Y-%m-%d") if item.published else ""


def plain_digest(items: list[Announcement]) -> str:
    from . import group_by_label  # local import avoids a cycle
    lines = [f"{len(items)} new announcement(s)\n"]
    for label, is_project, its in group_by_label(items):
        lines.append(f"{'★ PROJECT' if is_project else 'Company'}: {label}")
        for it in its:
            date = fmt_date(it)
            lines.append(f"  - {it.title}" + (f" ({date})" if date else ""))
            lines.append(f"    {it.url}")
        lines.append("")
    return "\n".join(lines)
