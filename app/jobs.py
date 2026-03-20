"""
In-memory job store for async TTS synthesis tasks.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional


JOB_TTL_HOURS = 24


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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > timedelta(hours=JOB_TTL_HOURS)


_store: dict[str, SynthesisJob] = {}


def create() -> SynthesisJob:
    _purge_expired()
    job = SynthesisJob(id=uuid.uuid4().hex[:12])
    _store[job.id] = job
    return job


def get(job_id: str) -> Optional[SynthesisJob]:
    return _store.get(job_id)


def update(job_id: str, **kwargs) -> None:
    job = _store.get(job_id)
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)


def _purge_expired() -> None:
    expired = [k for k, v in _store.items() if v.is_expired()]
    for k in expired:
        del _store[k]
