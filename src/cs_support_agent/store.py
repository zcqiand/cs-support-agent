"""store.py —— SQLite thin DAO（树锚点 M03.F01 / M00.F01.I02 / M01.F03.I02）。

四表：sessions / messages / kb_articles / tickets。
不引 ORM；db_path 传 ":memory:" 可内存跑（测试）。
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL DEFAULT 'web',
  user_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'live',
  clarified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  citations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS kb_articles(
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets(
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- 内部 ----

    def _row(self, cur: sqlite3.Cursor) -> dict | None:
        r = cur.fetchone()
        return dict(r) if r is not None else None

    def _rows(self, cur: sqlite3.Cursor) -> list[dict]:
        return [dict(r) for r in cur.fetchall()]

    # ---- sessions ----

    def create_session(self, channel: str = "web", user_name: str = "") -> dict:
        sid = _new_id()
        ts = now_iso()
        self._conn.execute(
            "INSERT INTO sessions(id, channel, user_name, status, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (sid, channel, user_name, "live", ts, ts),
        )
        self._conn.commit()
        return self.get_session(sid)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
        return self._row(cur)

    def update_session(self, session_id: str, fields: dict) -> None:
        fields = dict(fields)
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(f"UPDATE sessions SET {cols} WHERE id=?", (*fields.values(), session_id))
        self._conn.commit()

    # ---- messages ----

    def append_message(
        self, session_id: str, role: str, content: str, citations_json: str = "[]"
    ) -> None:
        self._conn.execute(
            "INSERT INTO messages(session_id, role, content, citations_json, created_at)"
            " VALUES(?,?,?,?,?)",
            (session_id, role, content, citations_json, now_iso()),
        )
        self._conn.commit()

    def get_messages(self, session_id: str, limit: int = 200) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id LIMIT ?",
            (session_id, limit),
        )
        return self._rows(cur)

    # ---- kb_articles ----

    def upsert_kb_article(self, kb_id: str, category: str, title: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO kb_articles(id, category, title, content, updated_at)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET category=excluded.category,"
            " title=excluded.title, content=excluded.content, updated_at=excluded.updated_at",
            (kb_id, category, title, content, now_iso()),
        )
        self._conn.commit()

    def list_kb_articles(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM kb_articles ORDER BY category, id")
        return self._rows(cur)

    def get_kb_article(self, kb_id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM kb_articles WHERE id=?", (kb_id,))
        return self._row(cur)

    # ---- tickets ----

    def create_ticket(self, session_id: str, title: str, description: str) -> dict:
        tid = _new_id()
        self._conn.execute(
            "INSERT INTO tickets(id, session_id, title, description, status, created_at)"
            " VALUES(?,?,?,?, 'open', ?)",
            (tid, session_id, title, description, now_iso()),
        )
        self._conn.commit()
        cur = self._conn.execute("SELECT * FROM tickets WHERE id=?", (tid,))
        return self._row(cur)  # type: ignore[return-value]

    def list_tickets(self) -> list[dict]:
        cur = self._conn.execute("SELECT * FROM tickets ORDER BY created_at DESC, id")
        return self._rows(cur)
