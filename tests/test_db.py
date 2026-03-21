"""
Unit tests for the SQLite-backed DB layer (db, sessions, jobs modules).

These tests use an in-memory SQLite database (:memory:) so they never touch
the filesystem and run entirely offline — no ElevenLabs or Anthropic API
calls are made.
"""

import pytest
from datetime import datetime, timedelta, timezone

import app.db as db_module
import app.sessions as sessions_module
import app.jobs as jobs_module
from app.jobs import JobStatus


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db(tmp_path):
    """
    Before each test: point db_module at a fresh temp file and init the schema.
    After each test: reset the shared connection so the next test gets a clean slate.
    """
    db_path = str(tmp_path / "test_spodkast.db")
    db_module._conn = None                 # clear any previous connection
    db_module.init_db(db_path=db_path)
    yield
    # tear-down: close connection
    if db_module._conn is not None:
        db_module._conn.close()
        db_module._conn = None


# ── db.py ───────────────────────────────────────────────────────────────────


class TestInitDB:
    def test_init_creates_tables(self):
        with db_module.get_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"sessions", "episodes", "jobs"}.issubset(tables)

    def test_double_init_is_idempotent(self, tmp_path):
        """Calling init_db twice on the same path must not raise."""
        db_module.init_db(db_path=str(tmp_path / "test_spodkast.db"))


class TestGetConn:
    def test_rollback_on_error(self):
        with pytest.raises(ValueError):
            with db_module.get_conn() as conn:
                conn.execute(
                    "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                    ("aaa", datetime.now(timezone.utc).isoformat()),
                )
                raise ValueError("intentional")

        # Row should not have been committed
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE id = 'aaa'"
            ).fetchone()
        assert row is None


# ── sessions.py ─────────────────────────────────────────────────────────────


SAMPLE_EPISODES = [
    {"index": 1, "title": "Episode One", "summary": "Summary of ep 1"},
    {"index": 2, "title": "Episode Two", "summary": "Summary of ep 2"},
]


class TestSessionsCreate:
    def test_create_returns_session(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        assert len(s.id) == 12
        assert len(s.episodes) == 2
        assert s.operator_message is None

    def test_create_persists_to_db(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message="hello")

        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT id, operator_message FROM sessions WHERE id = ?", (s.id,)
            ).fetchone()
        assert row is not None
        assert row["operator_message"] == "hello"

    def test_create_persists_episodes(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)

        with db_module.get_conn() as conn:
            rows = conn.execute(
                "SELECT idx, title FROM episodes WHERE session_id = ? ORDER BY idx",
                (s.id,),
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["title"] == "Episode One"

    def test_create_with_device_info(self):
        s = sessions_module.create(
            SAMPLE_EPISODES, operator_message=None, device_info="iPhone 15"
        )
        assert s.device_info == "iPhone 15"


class TestSessionsGet:
    def test_get_existing(self):
        created = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        fetched = sessions_module.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert len(fetched.episodes) == 2

    def test_get_missing_returns_none(self):
        assert sessions_module.get("nonexistent") is None

    def test_get_expired_returns_none_and_deletes(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)

        # Force the created_at to be in the distant past
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=sessions_module.SESSION_TTL_HOURS + 1)
        ).isoformat()
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET created_at = ? WHERE id = ?", (cutoff, s.id)
            )

        assert sessions_module.get(s.id) is None

        # Should also be deleted from DB
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (s.id,)
            ).fetchone()
        assert row is None


class TestUpdateEpisodeText:
    def test_update_persists(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.update_episode_text(s.id, 1, "Full script for ep 1")

        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT text FROM episodes WHERE session_id = ? AND idx = ?",
                (s.id, 1),
            ).fetchone()
        assert row["text"] == "Full script for ep 1"

    def test_get_reflects_updated_text(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.update_episode_text(s.id, 2, "Full script for ep 2")

        fetched = sessions_module.get(s.id)
        ep = fetched.get_episode(2)
        assert ep.is_expanded
        assert ep.text == "Full script for ep 2"
        assert ep.word_count > 0


class TestListSessions:
    def test_list_returns_sessions(self):
        sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.create(SAMPLE_EPISODES[:1], operator_message=None)

        listed = sessions_module.list_sessions()
        assert len(listed) >= 2

    def test_list_excludes_expired(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=sessions_module.SESSION_TTL_HOURS + 1)
        ).isoformat()
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET created_at = ? WHERE id = ?", (cutoff, s.id)
            )

        listed = sessions_module.list_sessions()
        ids = [x.id for x in listed]
        assert s.id not in ids


class TestDeleteSession:
    def test_delete_existing(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        assert sessions_module.delete(s.id) is True
        assert sessions_module.get(s.id) is None

    def test_delete_cascades_episodes(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.delete(s.id)

        with db_module.get_conn() as conn:
            rows = conn.execute(
                "SELECT idx FROM episodes WHERE session_id = ?", (s.id,)
            ).fetchall()
        assert rows == []

    def test_delete_missing_returns_false(self):
        assert sessions_module.delete("doesnotexist") is False


# ── jobs.py ─────────────────────────────────────────────────────────────────


class TestJobsCreate:
    def test_create_returns_job(self):
        job = jobs_module.create()
        assert len(job.id) == 12
        assert job.status == JobStatus.PENDING

    def test_create_with_session_link(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1)
        assert job.session_id == s.id
        assert job.episode_idx == 1

    def test_create_persists(self):
        job = jobs_module.create()
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT id, status FROM jobs WHERE id = ?", (job.id,)
            ).fetchone()
        assert row is not None
        assert row["status"] == "pending"


class TestJobsGet:
    def test_get_existing(self):
        job = jobs_module.create()
        fetched = jobs_module.get(job.id)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.status == JobStatus.PENDING

    def test_get_missing_returns_none(self):
        assert jobs_module.get("nothere") is None

    def test_get_expired_returns_none(self):
        job = jobs_module.create()
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=jobs_module.JOB_TTL_HOURS + 1)
        ).isoformat()
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE jobs SET created_at = ? WHERE id = ?", (cutoff, job.id)
            )
        assert jobs_module.get(job.id) is None


class TestJobsUpdate:
    def test_update_status(self):
        job = jobs_module.create()
        jobs_module.update(job.id, status=JobStatus.RUNNING)

        fetched = jobs_module.get(job.id)
        assert fetched.status == JobStatus.RUNNING

    def test_update_done_with_path(self):
        job = jobs_module.create()
        jobs_module.update(
            job.id,
            status=JobStatus.DONE,
            output_path="/output/foo.mp3",
            filename="foo.mp3",
        )
        fetched = jobs_module.get(job.id)
        assert fetched.status == JobStatus.DONE
        assert fetched.output_path == "/output/foo.mp3"
        assert fetched.filename == "foo.mp3"

    def test_update_failed(self):
        job = jobs_module.create()
        jobs_module.update(job.id, status=JobStatus.FAILED, error="TTS timeout")
        fetched = jobs_module.get(job.id)
        assert fetched.status == JobStatus.FAILED
        assert fetched.error == "TTS timeout"

    def test_update_unknown_fields_ignored(self):
        job = jobs_module.create()
        # Should not raise
        jobs_module.update(job.id, bogus_field="value")


class TestListForSession:
    def test_lists_jobs_for_session(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        j1 = jobs_module.create(session_id=s.id, episode_idx=1)
        j2 = jobs_module.create(session_id=s.id, episode_idx=2)

        job_list = jobs_module.list_for_session(s.id)
        ids = {j.id for j in job_list}
        assert j1.id in ids
        assert j2.id in ids

    def test_does_not_return_other_session_jobs(self):
        s1 = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        s2 = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        j1 = jobs_module.create(session_id=s1.id)
        jobs_module.create(session_id=s2.id)

        job_list = jobs_module.list_for_session(s1.id)
        assert all(j.id == j1.id for j in job_list)
