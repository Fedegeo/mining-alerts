"""Telegram bot message (handy for phone push alerts)."""
from __future__ import annotations

import html

import requests

from ..models import Announcement
from .base import Notifier, summary_line


class TelegramNotifier(Notifier):
    name = "telegram"
    LIMIT = 3900  # Telegram max is 4096 chars per message

    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, chat_id

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "TelegramNotifier | None":
        if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
            return cls(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"])
        return None

    def build_messages(self, items: list[Announcement], warnings=()) -> list[str]:
        from . import group_by_label
        chunks, cur = [], (f"<b>{html.escape(summary_line(items))}</b>\n" if items else "")
        for label, is_project, its in group_by_label(items):
            block = f"\n{'⭐ ' if is_project else ''}<b>{html.escape(label)}</b>\n" + "".join(
                f"• {('[' + html.escape(it.categories[0]) + '] ') if it.categories else ''}"
                f"<a href=\"{html.escape(it.url, quote=True)}\">{html.escape(it.title)}</a>\n"
                for it in its)
            if len(cur) + len(block) > self.LIMIT:
                chunks.append(cur)
                cur = ""
            cur += block
        if warnings:
            block = "\n⚠️ <b>Source health</b>\n" + "".join(f"• {html.escape(w)}\n" for w in warnings)
            if len(cur) + len(block) > self.LIMIT:
                chunks.append(cur)
                cur = ""
            cur += block
        chunks.append(cur)
        return chunks

    def send(self, items: list[Announcement], warnings=()) -> None:
        for text in self.build_messages(items, warnings):
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True}, timeout=20)
            resp.raise_for_status()
