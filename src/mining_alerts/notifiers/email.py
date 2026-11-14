"""SMTP email digest. Works with Gmail using an App Password
(Google Account > Security > App passwords), SMTP_HOST=smtp.gmail.com, SMTP_PORT=587."""
from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage

from ..models import Announcement
from .base import Notifier, meta, plain_digest, summary_line


TAG_STYLE = ("display:inline-block;padding:1px 6px;margin-right:4px;border-radius:3px;"
             "font-size:11px;background:#eef;color:#335")
HIGH_STYLE = TAG_STYLE.replace("#eef;color:#335", "#fde8e8;color:#9b1c1c")


def html_digest(items: list[Announcement], warnings=(), digest: bool = False) -> str:
    from . import group_by_label
    parts = [f"<p><b>{html.escape(summary_line(items, digest))}</b></p>"] if items else []
    for label, is_project, its in group_by_label(items):
        badge = "&#9733; PROJECT" if is_project else "Company"
        parts.append(f"<h3 style='margin-bottom:4px'>{badge}: {html.escape(label)}</h3><ul>")
        for it in its:
            badge = ""
            if it.categories:
                style = HIGH_STYLE if it.is_high_priority else TAG_STYLE
                badge = f"<span style='{style}'>{html.escape(it.categories[0])}</span>"
            m = meta(it)
            parts.append(
                f"<li style='margin-bottom:6px'>{badge}"
                f"<a href='{html.escape(it.url, quote=True)}'>{html.escape(it.title)}</a>"
                + (f"<br><small style='color:#777'>{html.escape(m)}</small>" if m else "") + "</li>")
        parts.append("</ul>")
    if warnings:
        parts.append("<h3 style='color:#9b1c1c'>&#9888; Source health</h3><ul>")
        parts.extend(f"<li>{html.escape(w)}</li>" for w in warnings)
        parts.append("</ul>")
    return "\n".join(parts)


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, to: list[str]):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.to = sender, to

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "EmailNotifier | None":
        if not (env.get("ALERT_EMAIL_TO") and env.get("SMTP_HOST")):
            return None
        return cls(
            host=env["SMTP_HOST"], port=int(env.get("SMTP_PORT", "587")),
            user=env.get("SMTP_USER", ""), password=env.get("SMTP_PASSWORD", ""),
            sender=env.get("ALERT_EMAIL_FROM") or env.get("SMTP_USER", ""),
            to=[a.strip() for a in env["ALERT_EMAIL_TO"].split(",") if a.strip()],
        )

    def build_message(self, items: list[Announcement], warnings=(), digest: bool = False) -> EmailMessage:
        from . import group_by_label
        labels = [g[0] for g in group_by_label(items)]
        if items:
            hot = sorted({i.categories[0] for i in items if i.is_high_priority and i.categories})
            subject = f"[Mining {'digest' if digest else 'alerts'}] {len(items)} new"
            subject += f" ({', '.join(hot)})" if hot else ""
            subject += ": " + ", ".join(labels[:3])
            if len(labels) > 3:
                subject += f" +{len(labels) - 3} more"
        else:
            subject = "[Mining alerts] source health warning"
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.sender, ", ".join(self.to)
        msg.set_content(plain_digest(items, warnings, digest))
        msg.add_alternative(html_digest(items, warnings, digest), subtype="html")
        return msg

    def send(self, items: list[Announcement], warnings=(), digest: bool = False) -> None:
        msg = self.build_message(items, warnings, digest)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)
