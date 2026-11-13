"""Alert channels. Each is enabled by environment variables (see .env.example)."""
from __future__ import annotations

import logging
import os
from collections import defaultdict

from ..models import Announcement
from .base import Notifier
from .console import ConsoleNotifier
from .email import EmailNotifier
from .slack import SlackNotifier
from .telegram import TelegramNotifier

log = logging.getLogger(__name__)

__all__ = ["Notifier", "configured_notifiers", "group_by_label"]


def configured_notifiers(env: dict[str, str] | None = None) -> list[Notifier]:
    env = dict(os.environ if env is None else env)
    notifiers: list[Notifier] = [ConsoleNotifier()]
    for cls in (EmailNotifier, SlackNotifier, TelegramNotifier):
        n = cls.from_env(env)
        if n:
            notifiers.append(n)
    return notifiers


def group_by_label(items: list[Announcement]) -> list[tuple[str, bool, list[Announcement]]]:
    """Group items by company/project label; project groups first, then alphabetically."""
    groups: dict[str, list[Announcement]] = defaultdict(list)
    is_project: dict[str, bool] = {}
    for it in items:
        # Put each item under its most specific label(s) only once per label.
        for m in it.matches:
            if it not in groups[m.label]:
                groups[m.label].append(it)
            is_project[m.label] = is_project.get(m.label, False) or bool(m.project)
    return sorted(((lbl, is_project[lbl], its) for lbl, its in groups.items()),
                  key=lambda g: (not g[1], g[0].lower()))
