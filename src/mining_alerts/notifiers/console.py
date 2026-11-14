from __future__ import annotations

from ..models import Announcement
from .base import Notifier, plain_digest


class ConsoleNotifier(Notifier):
    name = "console"

    def send(self, items: list[Announcement], warnings=()) -> None:
        print(plain_digest(items, warnings))
