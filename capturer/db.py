"""SQLite storage for captured posts and generated ideas."""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode     TEXT UNIQUE NOT NULL,
    url           TEXT NOT NULL,
    creator       TEXT,
    caption       TEXT,
    posted_at     TEXT,
    duration_sec  REAL,
    like_count    INTEGER,
    comment_count INTEGER,
    transcript    TEXT,
    analysis      TEXT,          -- JSON blob of PostAnalysis
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
    error         TEXT,
    source        TEXT NOT NULL DEFAULT 'url',      -- url | extension
    media_source  TEXT,                             -- yt-dlp | direct | screenshots | none
    captured_at   TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    hook          TEXT,
    angle         TEXT,
    format        TEXT,
    outline       TEXT,
    rationale     TEXT,
    source_ids    TEXT,          -- JSON list of post ids the idea drew on
    status        TEXT NOT NULL DEFAULT 'new',      -- new | used | discarded
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_captured ON posts(captured_at);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _synchronized(method):
    """The local server touches the database from several threads; serialise access."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after the first release to existing databases."""
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(posts)")}
        for column, ddl in (
            ("source", "TEXT NOT NULL DEFAULT 'url'"),
            ("media_source", "TEXT"),
        ):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE posts ADD COLUMN {column} {ddl}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- posts -----------------------------------------------------------

    @_synchronized
    def upsert_pending(self, shortcode: str, url: str, source: str = "url") -> int:
        """Create a pending row (or return the existing one's id)."""
        now = _now()
        self.conn.execute(
            "INSERT OR IGNORE INTO posts (shortcode, url, status, source, captured_at, updated_at)"
            " VALUES (?, ?, 'pending', ?, ?, ?)",
            (shortcode, url, source, now, now),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT id FROM posts WHERE shortcode = ?", (shortcode,)).fetchone()
        return int(row["id"])

    def post_summary(self, row: sqlite3.Row) -> dict[str, Any]:
        """Small JSON-friendly view used by the local server and the extension popup."""
        a = analysis_of(row)
        return {
            "id": row["id"],
            "shortcode": row["shortcode"],
            "url": row["url"],
            "creator": row["creator"],
            "status": row["status"],
            "error": row["error"],
            "source": row["source"],
            "media_source": row["media_source"],
            "captured_at": row["captured_at"],
            "topic": a.get("topic"),
            "hook": a.get("hook"),
            "format": a.get("format"),
            "why_it_works": a.get("why_it_works"),
            "remix_ideas": a.get("remix_ideas", []),
        }

    @_synchronized
    def get_post(self, key: int | str) -> sqlite3.Row | None:
        if isinstance(key, int) or str(key).isdigit():
            return self.conn.execute("SELECT * FROM posts WHERE id = ?", (int(key),)).fetchone()
        return self.conn.execute("SELECT * FROM posts WHERE shortcode = ?", (key,)).fetchone()

    @_synchronized
    def mark_done(
        self,
        post_id: int,
        *,
        creator: str | None,
        caption: str | None,
        posted_at: str | None,
        duration_sec: float | None,
        like_count: int | None,
        comment_count: int | None,
        transcript: str,
        analysis: dict[str, Any],
        media_source: str | None = None,
    ) -> None:
        self.conn.execute(
            """UPDATE posts SET creator=?, caption=?, posted_at=?, duration_sec=?,
                   like_count=?, comment_count=?, transcript=?, analysis=?, media_source=?,
                   status='done', error=NULL, updated_at=?
               WHERE id=?""",
            (
                creator, caption, posted_at, duration_sec, like_count, comment_count,
                transcript, json.dumps(analysis, ensure_ascii=False), media_source, _now(), post_id,
            ),
        )
        self.conn.commit()

    @_synchronized
    def mark_failed(self, post_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE posts SET status='failed', error=?, updated_at=? WHERE id=?",
            (error[:2000], _now(), post_id),
        )
        self.conn.commit()

    @_synchronized
    def list_posts(self, *, status: str | None = "done", limit: int = 50, since: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM posts"
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if since:
            clauses.append("captured_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY captured_at DESC LIMIT ?"
        params.append(limit)
        return list(self.conn.execute(sql, params).fetchall())

    @_synchronized
    def search_posts(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        like = f"%{query}%"
        return list(
            self.conn.execute(
                """SELECT * FROM posts WHERE status='done' AND
                   (caption LIKE ? OR transcript LIKE ? OR analysis LIKE ? OR creator LIKE ?)
                   ORDER BY captured_at DESC LIMIT ?""",
                (like, like, like, like, limit),
            ).fetchall()
        )

    # ---- ideas -----------------------------------------------------------

    @_synchronized
    def add_ideas(self, ideas: Iterable[dict[str, Any]]) -> list[int]:
        ids = []
        now = _now()
        for idea in ideas:
            cur = self.conn.execute(
                """INSERT INTO ideas (title, hook, angle, format, outline, rationale, source_ids, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
                (
                    idea.get("title", ""),
                    idea.get("hook"),
                    idea.get("angle"),
                    idea.get("format"),
                    idea.get("outline"),
                    idea.get("rationale"),
                    json.dumps(idea.get("source_ids", [])),
                    now,
                ),
            )
            ids.append(int(cur.lastrowid))
        self.conn.commit()
        return ids

    @_synchronized
    def list_ideas(self, *, status: str | None = "new", limit: int = 50) -> list[sqlite3.Row]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM ideas WHERE status=? ORDER BY created_at DESC, id DESC LIMIT ?", (status, limit)
            )
        else:
            rows = self.conn.execute("SELECT * FROM ideas ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        return list(rows.fetchall())

    @_synchronized
    def set_idea_status(self, idea_id: int, status: str) -> bool:
        cur = self.conn.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
        self.conn.commit()
        return cur.rowcount > 0

    # ---- stats -----------------------------------------------------------

    @_synchronized
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.conn.execute("SELECT status, COUNT(*) AS n FROM posts GROUP BY status"):
            out[f"posts_{row['status']}"] = int(row["n"])
        for row in self.conn.execute("SELECT status, COUNT(*) AS n FROM ideas GROUP BY status"):
            out[f"ideas_{row['status']}"] = int(row["n"])
        return out


def analysis_of(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["analysis"]
    return json.loads(raw) if raw else {}
