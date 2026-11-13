"""SQLite state: messages the bot saw, commands for the phone, dedup, small meta."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA = """
-- Every message that @-mentioned the bot and was read off the screen.
-- Kept so that something can reply to it later (quote reply needs quote_key).
CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    at         REAL NOT NULL,
    chat       TEXT NOT NULL,
    sender     TEXT NOT NULL,
    text       TEXT NOT NULL,
    quote_key  TEXT NOT NULL
);

-- Commands for the phone. pending -> sent (phone fetched it) -> done/failed.
-- Never re-sent automatically: the phone may have acted and only the result
-- got lost, and sending twice into a customer group is worse than once.
CREATE TABLE IF NOT EXISTS commands (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    type        TEXT NOT NULL,
    args        TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '{}',
    expires_at  REAL NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending',
    sent_at     REAL,
    result      TEXT,
    CHECK (state IN ('pending', 'sent', 'done', 'failed', 'lost', 'expired'))
);
CREATE INDEX IF NOT EXISTS ix_commands_state ON commands (state, created_at);

-- Recent notifications from allow-listed apps (newest 500), so tools can ask "what came in?".
CREATE TABLE IF NOT EXISTS notifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL NOT NULL,
    app       TEXT NOT NULL,
    chat      TEXT NOT NULL,
    title     TEXT NOT NULL,
    text      TEXT NOT NULL,
    mentioned INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_events (event_id TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- dedup ---------------------------------------------------------------

    def first_time(self, event_id: str) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO seen_events VALUES (?, ?)", (event_id, time.time()))
        return cur.rowcount == 1

    def prune(self, days: int = 14) -> None:
        self.conn.execute("DELETE FROM seen_events WHERE at < ?", (time.time() - days * 86400,))

    # -- messages ------------------------------------------------------------

    def add_message(self, *, chat: str, sender: str, text: str, quote_key: str) -> str:
        mid = uuid.uuid4().hex[:12]
        self.conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                          (mid, time.time(), chat, sender, text, quote_key))
        return mid

    def message(self, prefix: str) -> dict | None:
        """Look a message up by id or a unique id prefix."""
        rows = self.conn.execute("SELECT * FROM messages WHERE id LIKE ?", (prefix + "%",)).fetchall()
        return dict(rows[0]) if len(rows) == 1 else None

    def recent_messages(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM messages ORDER BY at DESC LIMIT ?", (limit,))]

    # -- notifications -------------------------------------------------------

    def add_notification(self, *, app: str, chat: str, title: str, text: str, mentioned: bool) -> None:
        self.conn.execute("INSERT INTO notifications (at, app, chat, title, text, mentioned) VALUES (?, ?, ?, ?, ?, ?)",
                          (time.time(), app, chat, title, text[:2000], int(mentioned)))
        self.conn.execute("DELETE FROM notifications WHERE id <= (SELECT max(id) FROM notifications) - 500")

    def recent_notifications(self, limit: int = 20, app: str = "") -> list[dict]:
        if app:
            rows = self.conn.execute("SELECT * FROM notifications WHERE app = ? ORDER BY id DESC LIMIT ?", (app, limit))
        else:
            rows = self.conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # -- commands ------------------------------------------------------------

    def enqueue(self, ctype: str, args: dict, *, ttl_s: int, context: dict | None = None,
                command_id: str | None = None) -> dict:
        now = time.time()
        cid = command_id or uuid.uuid4().hex
        args = dict(args, expires_at=int((now + ttl_s) * 1000))
        self.conn.execute(
            "INSERT INTO commands (id, created_at, type, args, context, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cid, now, ctype, json.dumps(args, ensure_ascii=False),
             json.dumps(context or {}, ensure_ascii=False), now + ttl_s))
        return {"id": cid, "type": ctype, "args": args}

    def take_pending(self) -> list[dict]:
        now = time.time()
        out = []
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for r in self.conn.execute(
                    "SELECT * FROM commands WHERE state = 'pending' AND expires_at > ? ORDER BY created_at",
                    (now,)).fetchall():
                self.conn.execute("UPDATE commands SET state = 'sent', sent_at = ? WHERE id = ?", (now, r["id"]))
                out.append({"id": r["id"], "type": r["type"], "args": json.loads(r["args"])})
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return out

    def command(self, command_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["args"], d["context"] = json.loads(d["args"]), json.loads(d["context"])
        return d

    def finish(self, command_id: str, ok: bool, result: dict) -> dict | None:
        cmd = self.command(command_id)
        if cmd is not None:
            self.conn.execute("UPDATE commands SET state = ?, result = ? WHERE id = ?",
                              ("done" if ok else "failed",
                               json.dumps(result, ensure_ascii=False), command_id))
        return cmd

    def sweep(self, *, lost_after_s: int = 180) -> list[dict]:
        """Commands that need a human: sent but never answered (lost), or never fetched (expired)."""
        now = time.time()
        out = []
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for state, where, arg in (("lost", "state = 'sent' AND sent_at < ?", now - lost_after_s),
                                      ("expired", "state = 'pending' AND expires_at <= ?", now)):
                for r in self.conn.execute(f"SELECT id FROM commands WHERE {where}", (arg,)).fetchall():
                    self.conn.execute("UPDATE commands SET state = ? WHERE id = ?", (state, r["id"]))
                    cmd = self.command(r["id"])
                    cmd["state"] = state
                    out.append(cmd)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return out

    def count(self, state: str) -> int:
        return self.conn.execute("SELECT count(*) FROM commands WHERE state = ?", (state,)).fetchone()[0]

    # -- meta ----------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                          (key, value))
