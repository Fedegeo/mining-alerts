"""Slack (or any Slack-compatible) incoming webhook."""
from __future__ import annotations

import requests

from ..models import Announcement
from .base import Notifier, meta, summary_line


class SlackNotifier(Notifier):
    name = "slack"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "SlackNotifier | None":
        url = env.get("SLACK_WEBHOOK_URL")
        return cls(url) if url else None

    def build_text(self, items: list[Announcement], warnings=()) -> str:
        from . import group_by_label
        lines = [f"*{summary_line(items)}*"] if items else []
        for label, is_project, its in group_by_label(items):
            lines.append(f"\n{':star: ' if is_project else ''}*{label}*")
            for it in its:
                title = it.title.replace("<", "").replace(">", "").replace("|", "-")
                prefix = f"`{it.categories[0]}` " if it.categories else ""
                m = meta(it)
                lines.append(f"• {prefix}<{it.url}|{title}>" + (f"  _{m}_" if m else ""))
        if warnings:
            lines.append("\n:warning: *Source health*")
            lines.extend(f"• {w}" for w in warnings)
        return "\n".join(lines)

    def send(self, items: list[Announcement], warnings=()) -> None:
        resp = requests.post(self.webhook_url, json={"text": self.build_text(items, warnings)},
                             timeout=20)
        resp.raise_for_status()
