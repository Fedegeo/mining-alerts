"""Source interface + shared HTTP session."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

import requests

from ..models import Announcement

DEFAULT_UA = "mining-alerts/0.1 (+https://github.com/; announcement watcher)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = os.environ.get("HTTP_USER_AGENT", DEFAULT_UA)
    return s


class Source(ABC):
    #: Stable identifier, used for first-run baselining and logs.
    name: str
    timeout = 25

    @abstractmethod
    def fetch(self, session: requests.Session) -> list[Announcement]:
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"
