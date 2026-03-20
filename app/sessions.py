"""
In-memory session store for Spodkast script review workflow.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


SESSION_TTL_HOURS = 24


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

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.created_at > timedelta(hours=SESSION_TTL_HOURS)

    def get_episode(self, index: int) -> Optional[Episode]:
        return next((ep for ep in self.episodes if ep.index == index), None)


_store: dict[str, Session] = {}


def create(
    episodes: list[dict],  # list of {index, title, summary}
    operator_message: Optional[str],
) -> Session:
    _purge_expired()
    session = Session(
        id=uuid.uuid4().hex[:12],
        episodes=[Episode(index=e["index"], title=e["title"], summary=e["summary"]) for e in episodes],
        operator_message=operator_message,
    )
    _store[session.id] = session
    return session


def get(session_id: str) -> Optional[Session]:
    session = _store.get(session_id)
    if session is None:
        return None
    if session.is_expired():
        del _store[session_id]
        return None
    return session


def update_episode_text(session_id: str, episode_index: int, text: str) -> None:
    session = _store.get(session_id)
    if session is None:
        return
    episode = session.get_episode(episode_index)
    if episode is not None:
        episode.text = text


def _purge_expired() -> None:
    expired = [k for k, v in _store.items() if v.is_expired()]
    for k in expired:
        del _store[k]
