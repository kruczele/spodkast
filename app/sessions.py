"""
SQLite-backed session store for Spodkast script review workflow.

Replaces the previous in-memory dict so sessions survive process restarts
and are accessible from any device that shares the same database file (or a
replicated one).

Public API is identical to the original in-memory version so the rest of the
codebase requires no changes.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db import get_conn


SESSION_TTL_HOURS = 24 * 7  # 7 days — longer-lived now that we have persistence


# ── domain objects ─────────────────────────────────────────────────────────


@dataclass
class Episode:
    index: int
    title: str
    summary: str          # from conspect, always present
    text: str | None = None  # None until expanded via phase 2

    @property
    def is_expanded(self) -> bool:
        return self.text is not None

    @property
    def word_count(self) -> int:
        return len(self.text.split()) if self.text else 0

    @property
    def preview(self) -> str:
        src = self.text if self.text else self.summary
        return src[:200].rstrip() + ("…" if len(src) > 200 else "")


@dataclass
class Session:
    id: str
    episodes: list[Episode]
    operator_message: Optional[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    device_info: Optional[str] = None

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > timedelta(hours=SESSION_TTL_HOURS)

    def get_episode(self, index: int) -> Optional[Episode]:
        return next((ep for ep in self.episodes if ep.index == index), None)


# ── helpers ────────────────────────────────────────────────────────────────


def _row_to_session(row, episodes: list[Episode]) -> Session:
    """Convert a DB row + episode list into a Session dataclass."""
    created_at = datetime.fromisoformat(row["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return Session(
        id=row["id"],
        episodes=episodes,
        operator_message=row["operator_message"],
        created_at=created_at,
        device_info=row["device_info"],
    )


def _load_episodes(conn, session_id: str) -> list[Episode]:
    rows = conn.execute(
        "SELECT idx, title, summary, text FROM episodes WHERE session_id = ? ORDER BY idx",
        (session_id,),
    ).fetchall()
    return [Episode(index=r["idx"], title=r["title"], summary=r["summary"], text=r["text"]) for r in rows]


# ── public API ─────────────────────────────────────────────────────────────


def create(
    episodes: list[dict],            # list of {index, title, summary}
    operator_message: Optional[str],
    device_info: Optional[str] = None,
) -> Session:
    """Persist a new session and return it."""
    _purge_expired()

    session_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, device_info, operator_message) VALUES (?, ?, ?, ?)",
            (session_id, now, device_info, operator_message),
        )
        conn.executemany(
            "INSERT INTO episodes (session_id, idx, title, summary, text) VALUES (?, ?, ?, ?, NULL)",
            [(session_id, e["index"], e["title"], e["summary"]) for e in episodes],
        )

    return Session(
        id=session_id,
        episodes=[
            Episode(index=e["index"], title=e["title"], summary=e["summary"])
            for e in episodes
        ],
        operator_message=operator_message,
        created_at=datetime.fromisoformat(now),
        device_info=device_info,
    )


def get(session_id: str) -> Optional[Session]:
    """Return the session or None (also deletes it if expired)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, created_at, device_info, operator_message FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            return None

        episodes = _load_episodes(conn, session_id)
        session = _row_to_session(row, episodes)

        if session.is_expired():
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None

        return session


def update_episode_text(session_id: str, episode_index: int, text: str) -> None:
    """Persist expanded episode text."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE episodes SET text = ? WHERE session_id = ? AND idx = ?",
            (text, session_id, episode_index),
        )


def get_translation(session_id: str, episode_index: int, language: str) -> Optional[str]:
    """Return a previously stored translation, or None if not found."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT text FROM episode_translations "
            "WHERE session_id = ? AND episode_idx = ? AND language = ?",
            (session_id, episode_index, language),
        ).fetchone()
    return row["text"] if row else None


def upsert_translation(session_id: str, episode_index: int, language: str, text: str) -> None:
    """Store (or replace) a translated episode script."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO episode_translations (session_id, episode_idx, language, text, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, episode_idx, language) DO UPDATE SET text = excluded.text, created_at = excluded.created_at",
            (session_id, episode_index, language, text, now),
        )


def list_sessions(limit: int = 100, offset: int = 0) -> list[Session]:
    """
    Return recent sessions (newest first), useful for cross-device browsing.

    Each session is returned with its full episode list.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, device_info, operator_message "
            "FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

        sessions_out: list[Session] = []
        for row in rows:
            episodes = _load_episodes(conn, row["id"])
            s = _row_to_session(row, episodes)
            if not s.is_expired():
                sessions_out.append(s)

        return sessions_out


def delete(session_id: str) -> bool:
    """Delete a session and all its episodes (cascaded). Returns True if it existed."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0


# ── maintenance ────────────────────────────────────────────────────────────


def _purge_expired() -> None:
    """Delete sessions that have exceeded SESSION_TTL_HOURS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
