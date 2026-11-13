"""SMTP email digest. Works with Gmail using an App Password
(Google Account > Security > App passwords), SMTP_HOST=smtp.gmail.com, SMTP_PORT=587."""
from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage

from ..models import Announcement
from .base import Notifier, fmt_date, plain_digest


def html_digest(items: list[Announcement]) -> str:
    from . import group_by_label
    parts = [f"<p><b>{len(items)} new announcement(s)</b></p>"]
    for label, is_project, its in group_by_label(items):
        badge = "&#9733; PROJECT" if is_project else "Company"
        parts.append(f"<h3 style='margin-bottom:4px'>{badge}: {html.escape(label)}</h3><ul>")
        for it in its:
            date = fmt_date(it)
            parts.append(
                f"<li><a href='{html.escape(it.url, quote=True)}'>{html.escape(it.title)}</a>"
                + (f" <small>({date})</small>" if date else "")
                + f" <small style='color:#888'>[{html.escape(it.source.split(':')[0])}]</small></li>")
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

    def build_message(self, items: list[Announcement]) -> EmailMessage:
        from . import group_by_label
        labels = [g[0] for g in group_by_label(items)]
        subject = f"[Mining alerts] {len(items)} new: " + ", ".join(labels[:3])
        if len(labels) > 3:
            subject += f" +{len(labels) - 3} more"
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.sender, ", ".join(self.to)
        msg.set_content(plain_digest(items))
        msg.add_alternative(html_digest(items), subtype="html")
        return msg

    def send(self, items: list[Announcement]) -> None:
        msg = self.build_message(items)
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)
