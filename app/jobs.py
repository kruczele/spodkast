"""
SQLite-backed job store for async TTS synthesis tasks.

Replaces the previous in-memory dict so jobs survive process restarts.
Public API is identical to the original version.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from app.db import get_conn


JOB_TTL_HOURS = 24 * 7  # keep jobs for 7 days


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class SynthesisJob:
    id: str
    status: JobStatus = JobStatus.PENDING
    error: Optional[str] = None
    output_path: Optional[str] = None
    filename: Optional[str] = None
    session_id: Optional[str] = None
    episode_idx: Optional[int] = None
    language: str = "en"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > timedelta(hours=JOB_TTL_HOURS)


# ── helpers ────────────────────────────────────────────────────────────────


def _row_to_job(row) -> SynthesisJob:
    created_at = datetime.fromisoformat(row["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return SynthesisJob(
        id=row["id"],
        status=JobStatus(row["status"]),
        error=row["error"],
        output_path=row["output_path"],
        filename=row["filename"],
        session_id=row["session_id"],
        episode_idx=row["episode_idx"],
        language=row["language"] if row["language"] else "en",
        created_at=created_at,
    )


# ── public API ─────────────────────────────────────────────────────────────


def create(
    session_id: Optional[str] = None,
    episode_idx: Optional[int] = None,
    language: str = "en",
) -> SynthesisJob:
    """Create and persist a new synthesis job, then return it."""
    _purge_expired()

    job_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, session_id, episode_idx, language, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, session_id, episode_idx, language, JobStatus.PENDING.value, now),
        )

    return SynthesisJob(
        id=job_id,
        status=JobStatus.PENDING,
        session_id=session_id,
        episode_idx=episode_idx,
        language=language,
        created_at=datetime.fromisoformat(now),
    )


def get(job_id: str) -> Optional[SynthesisJob]:
    """Retrieve a job by ID, or None if not found / expired."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, session_id, episode_idx, language, status, created_at, output_path, filename, error "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if row is None:
        return None

    job = _row_to_job(row)
    return None if job.is_expired() else job


def find_done(session_id: str, episode_idx: int, language: str) -> Optional[SynthesisJob]:
    """Return an existing completed job for the given episode+language, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, session_id, episode_idx, language, status, created_at, output_path, filename, error "
            "FROM jobs WHERE session_id = ? AND episode_idx = ? AND language = ? AND status = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id, episode_idx, language, JobStatus.DONE.value),
        ).fetchone()

    if row is None:
        return None

    job = _row_to_job(row)
    return None if job.is_expired() else job


def update(job_id: str, **kwargs) -> None:
    """Update arbitrary columns on a job row."""
    if not kwargs:
        return

    # Map dataclass field names to column names (identical in this case)
    allowed = {"status", "error", "output_path", "filename"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return

    # Coerce enum values to strings for storage
    if "status" in filtered and isinstance(filtered["status"], JobStatus):
        filtered["status"] = filtered["status"].value

    set_clause = ", ".join(f"{col} = ?" for col in filtered)
    values = list(filtered.values()) + [job_id]

    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)


def list_for_session(session_id: str) -> list[SynthesisJob]:
    """Return all non-expired jobs for a given session (newest first)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, session_id, episode_idx, language, status, created_at, output_path, filename, error "
            "FROM jobs WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()

    return [_row_to_job(r) for r in rows if not _row_to_job(r).is_expired()]


# ── maintenance ────────────────────────────────────────────────────────────


def _purge_expired() -> None:
    """Delete jobs older than JOB_TTL_HOURS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=JOB_TTL_HOURS)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
