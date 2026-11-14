"""Source interface + shared HTTP session."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import Announcement

DEFAULT_UA = "mining-alerts/0.1 (+https://github.com/; announcement watcher)"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = os.environ.get("HTTP_USER_AGENT", DEFAULT_UA)
    # Retry transient failures and rate limiting (honours Retry-After on 429/503).
    retry = Retry(total=3, connect=2, read=2, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",),
                  respect_retry_after_header=True, raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
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
