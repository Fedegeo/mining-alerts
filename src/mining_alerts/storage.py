"""SQLite store of announcements already seen/alerted, so we never alert twice."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Announcement

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    key        TEXT PRIMARY KEY,           -- url_key or title_key
    title      TEXT,
    url        TEXT,
    source     TEXT,
    matches    TEXT,
    alerted    INTEGER NOT NULL DEFAULT 0, -- 0 = baselined/irrelevant, 1 = sent in an alert
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    name       TEXT PRIMARY KEY,
    first_run  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_health (
    name                 TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT,
    last_ok              TEXT,
    last_failure         TEXT
);
CREATE TABLE IF NOT EXISTS digest_queue (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,              -- Announcement as JSON
    queued_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring databases created by older versions up to date."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(seen)")}
        if "payload" not in cols:  # added for the weekly recap
            self.conn.execute("ALTER TABLE seen ADD COLUMN payload TEXT")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- sources (for first-run baselining) ---
    def source_known(self, name: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sources WHERE name=?", (name,)).fetchone() is not None

    def mark_source(self, name: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO sources VALUES (?, ?)", (name, _now()))
        self.conn.commit()

    # --- announcements ---
    def is_seen(self, item: Announcement) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE key IN (?, ?)",
                                (item.url_key, item.title_key)).fetchone()
        return row is not None

    def mark_seen(self, items: list[Announcement], alerted: bool) -> None:
        now = _now()
        rows = []
        for it in items:
            labels = "; ".join(m.label for m in it.matches)
            payload = json.dumps(it.to_dict()) if alerted else None
            for key in (it.url_key, it.title_key):
                rows.append((key, it.title, it.url, it.source, labels, int(alerted), now, payload))
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen (key, title, url, source, matches, alerted, first_seen, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        self.conn.commit()

    def alerted_since(self, days: int, now: datetime | None = None) -> list[Announcement]:
        """Every item sent (or queued for the digest) in the last `days` days."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            "SELECT payload FROM seen WHERE alerted=1 AND payload IS NOT NULL AND first_seen >= ? "
            "GROUP BY url ORDER BY first_seen", (cutoff,)).fetchall()
        return [Announcement.from_dict(json.loads(r[0])) for r in rows]

    def alerted_titles_since(self, days: int) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.conn.execute("SELECT DISTINCT title FROM seen WHERE alerted=1 AND first_seen >= ?",
                                 (cutoff,)).fetchall()
        return [r[0] for r in rows]

    # --- source health ---
    def record_source_ok(self, name: str) -> None:
        self.conn.execute(
            "INSERT INTO source_health (name, consecutive_failures, last_ok) VALUES (?, 0, ?) "
            "ON CONFLICT(name) DO UPDATE SET consecutive_failures=0, last_ok=excluded.last_ok",
            (name, _now()))
        self.conn.commit()

    def record_source_failure(self, name: str, error: str) -> int:
        """Record a failure and return the new consecutive-failure count."""
        self.conn.execute(
            "INSERT INTO source_health (name, consecutive_failures, last_error, last_failure) "
            "VALUES (?, 1, ?, ?) ON CONFLICT(name) DO UPDATE SET "
            "consecutive_failures=consecutive_failures+1, last_error=excluded.last_error, "
            "last_failure=excluded.last_failure", (name, error[:500], _now()))
        self.conn.commit()
        return self.conn.execute("SELECT consecutive_failures FROM source_health WHERE name=?",
                                 (name,)).fetchone()[0]

    def source_health(self) -> list[tuple]:
        return self.conn.execute(
            "SELECT name, consecutive_failures, last_ok, last_failure, last_error FROM source_health "
            "ORDER BY consecutive_failures DESC, name").fetchall()

    # --- daily digest queue ---
    def enqueue(self, items: list[Announcement]) -> None:
        now = _now()
        self.conn.executemany("INSERT OR IGNORE INTO digest_queue VALUES (?, ?, ?)",
                              [(it.url_key, json.dumps(it.to_dict()), now) for it in items])
        self.conn.commit()

    def queued(self) -> list[Announcement]:
        rows = self.conn.execute("SELECT payload FROM digest_queue ORDER BY queued_at").fetchall()
        return [Announcement.from_dict(json.loads(r[0])) for r in rows]

    def dequeue(self, items: list[Announcement]) -> None:
        self.conn.executemany("DELETE FROM digest_queue WHERE key=?", [(it.url_key,) for it in items])
        self.conn.commit()

    def get_value(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_value(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO kv VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))
        self.conn.commit()

    def recent_alerts(self, limit: int = 50) -> list[tuple]:
        return self.conn.execute(
            "SELECT first_seen, matches, title, url FROM seen WHERE alerted=1 "
            "GROUP BY url ORDER BY first_seen DESC LIMIT ?", (limit,)).fetchall()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
