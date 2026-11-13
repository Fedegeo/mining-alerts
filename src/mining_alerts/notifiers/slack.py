"""Slack (or any Slack-compatible) incoming webhook."""
from __future__ import annotations

import requests

from ..models import Announcement
from .base import Notifier, fmt_date


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "SlackNotifier | None":
        url = env.get("SLACK_WEBHOOK_URL")
        return cls(url) if url else None

    def build_text(self, items: list[Announcement]) -> str:
        from . import group_by_label
        lines = [f"*{len(items)} new announcement(s)*"]
        for label, is_project, its in group_by_label(items):
            lines.append(f"\n{':star: ' if is_project else ''}*{label}*")
            for it in its:
                date = fmt_date(it)
                title = it.title.replace("<", "").replace(">", "").replace("|", "-")
                lines.append(f"• <{it.url}|{title}>" + (f" _{date}_" if date else ""))
        return "\n".join(lines)

    def send(self, items: list[Announcement]) -> None:
        resp = requests.post(self.webhook_url, json={"text": self.build_text(items)}, timeout=20)
        resp.raise_for_status()
