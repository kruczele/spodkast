"""
Tests for idempotent / restartable episode-level LLM processes.

Covers:
 - DB schema: episode_translations table and jobs.language column
 - sessions.get_translation / sessions.upsert_translation
 - jobs.find_done
 - DB migration: adding 'language' column to pre-existing jobs table
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
    """Fresh SQLite DB for each test."""
    db_path = str(tmp_path / "test_restartable.db")
    db_module._conn = None
    db_module.init_db(db_path=db_path)
    yield
    if db_module._conn is not None:
        db_module._conn.close()
        db_module._conn = None


SAMPLE_EPISODES = [
    {"index": 1, "title": "Episode One", "summary": "Summary of ep 1"},
    {"index": 2, "title": "Episode Two", "summary": "Summary of ep 2"},
]


# ── DB schema ────────────────────────────────────────────────────────────────


class TestSchemaIncludesNewTables:
    def test_episode_translations_table_exists(self):
        with db_module.get_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "episode_translations" in tables

    def test_jobs_has_language_column(self):
        with db_module.get_conn() as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
        assert "language" in cols


# ── sessions: translation store ─────────────────────────────────────────────


class TestGetTranslation:
    def test_returns_none_when_no_translation(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        result = sessions_module.get_translation(s.id, 1, "pl")
        assert result is None

    def test_returns_stored_translation(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "pl", "Przetłumaczony tekst")
        result = sessions_module.get_translation(s.id, 1, "pl")
        assert result == "Przetłumaczony tekst"

    def test_language_isolation(self):
        """Different languages are stored and retrieved independently."""
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "pl", "Polish text")
        sessions_module.upsert_translation(s.id, 1, "es", "Spanish text")

        assert sessions_module.get_translation(s.id, 1, "pl") == "Polish text"
        assert sessions_module.get_translation(s.id, 1, "es") == "Spanish text"
        assert sessions_module.get_translation(s.id, 1, "de") is None

    def test_episode_isolation(self):
        """Translations for different episodes are stored independently."""
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "pl", "EP1 Polish")
        sessions_module.upsert_translation(s.id, 2, "pl", "EP2 Polish")

        assert sessions_module.get_translation(s.id, 1, "pl") == "EP1 Polish"
        assert sessions_module.get_translation(s.id, 2, "pl") == "EP2 Polish"


class TestUpsertTranslation:
    def test_upsert_creates_new(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "pl", "First translation")
        assert sessions_module.get_translation(s.id, 1, "pl") == "First translation"

    def test_upsert_replaces_existing(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "pl", "First translation")
        sessions_module.upsert_translation(s.id, 1, "pl", "Updated translation")
        assert sessions_module.get_translation(s.id, 1, "pl") == "Updated translation"

    def test_upsert_persists_to_db(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        sessions_module.upsert_translation(s.id, 1, "es", "Texto en español")

        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT text FROM episode_translations "
                "WHERE session_id = ? AND episode_idx = ? AND language = ?",
                (s.id, 1, "es"),
            ).fetchone()
        assert row is not None
        assert row["text"] == "Texto en español"


# ── jobs: language-aware creation and lookup ─────────────────────────────────


class TestJobsLanguage:
    def test_create_with_language(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1, language="pl")
        assert job.language == "pl"

    def test_create_default_language_is_en(self):
        job = jobs_module.create()
        assert job.language == "en"

    def test_get_preserves_language(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1, language="es")
        fetched = jobs_module.get(job.id)
        assert fetched is not None
        assert fetched.language == "es"

    def test_list_for_session_preserves_language(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        j1 = jobs_module.create(session_id=s.id, episode_idx=1, language="pl")
        j2 = jobs_module.create(session_id=s.id, episode_idx=2, language="en")

        job_list = jobs_module.list_for_session(s.id)
        by_id = {j.id: j for j in job_list}
        assert by_id[j1.id].language == "pl"
        assert by_id[j2.id].language == "en"


class TestFindDone:
    def test_returns_none_when_no_done_job(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        result = jobs_module.find_done(s.id, 1, "en")
        assert result is None

    def test_returns_none_when_job_not_done(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job.id, status=JobStatus.RUNNING)

        result = jobs_module.find_done(s.id, 1, "en")
        assert result is None

    def test_returns_done_job(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(
            job.id,
            status=JobStatus.DONE,
            output_path="/out/ep01.mp3",
            filename="ep01.mp3",
        )

        result = jobs_module.find_done(s.id, 1, "en")
        assert result is not None
        assert result.id == job.id
        assert result.status == JobStatus.DONE

    def test_language_isolation(self):
        """find_done only returns jobs matching the requested language."""
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job_en = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job_en.id, status=JobStatus.DONE, output_path="/out/ep01_en.mp3", filename="ep01_en.mp3")

        job_pl = jobs_module.create(session_id=s.id, episode_idx=1, language="pl")
        jobs_module.update(job_pl.id, status=JobStatus.DONE, output_path="/out/ep01_pl.mp3", filename="ep01_pl.mp3")

        assert jobs_module.find_done(s.id, 1, "en").id == job_en.id
        assert jobs_module.find_done(s.id, 1, "pl").id == job_pl.id
        assert jobs_module.find_done(s.id, 1, "de") is None

    def test_episode_isolation(self):
        """find_done only returns jobs matching the requested episode index."""
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job1 = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job1.id, status=JobStatus.DONE, output_path="/out/ep01.mp3", filename="ep01.mp3")

        assert jobs_module.find_done(s.id, 1, "en").id == job1.id
        assert jobs_module.find_done(s.id, 2, "en") is None

    def test_returns_none_when_expired(self):
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)
        job = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job.id, status=JobStatus.DONE, output_path="/out/ep01.mp3", filename="ep01.mp3")

        # Force expiry
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=jobs_module.JOB_TTL_HOURS + 1)
        ).isoformat()
        with db_module.get_conn() as conn:
            conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", (cutoff, job.id))

        assert jobs_module.find_done(s.id, 1, "en") is None

    def test_prefers_most_recent_done_job(self):
        """When multiple done jobs exist, the most recently created is returned."""
        s = sessions_module.create(SAMPLE_EPISODES, operator_message=None)

        job_old = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job_old.id, status=JobStatus.DONE, output_path="/out/old.mp3", filename="old.mp3")

        job_new = jobs_module.create(session_id=s.id, episode_idx=1, language="en")
        jobs_module.update(job_new.id, status=JobStatus.DONE, output_path="/out/new.mp3", filename="new.mp3")

        result = jobs_module.find_done(s.id, 1, "en")
        assert result.id == job_new.id


# ── DB migration ─────────────────────────────────────────────────────────────


class TestDbMigration:
    def test_migration_adds_language_column_to_existing_db(self, tmp_path):
        """
        Simulate an existing DB created before the 'language' column was added.
        init_db() must add the column without error and existing rows default to 'en'.
        """
        import sqlite3

        db_path = str(tmp_path / "legacy.db")

        # Create a pre-migration jobs table without the 'language' column
        legacy_conn = sqlite3.connect(db_path)
        legacy_conn.executescript("""
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                device_info TEXT, operator_message TEXT
            );
            CREATE TABLE IF NOT EXISTS episodes (
                session_id TEXT NOT NULL, idx INTEGER NOT NULL,
                title TEXT NOT NULL, summary TEXT NOT NULL, text TEXT,
                PRIMARY KEY (session_id, idx)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                episode_idx INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                output_path TEXT,
                filename TEXT,
                error TEXT
            );
        """)
        # Insert a legacy row (no language column)
        legacy_conn.execute(
            "INSERT INTO jobs (id, status, created_at) VALUES ('legacyjob1', 'done', '2024-01-01T00:00:00+00:00')"
        )
        legacy_conn.commit()
        legacy_conn.close()

        # Re-initialise the existing DB through init_db — should migrate cleanly
        db_module._conn = None
        db_module.init_db(db_path=db_path)

        with db_module.get_conn() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            assert "language" in cols

            row = conn.execute("SELECT language FROM jobs WHERE id = 'legacyjob1'").fetchone()
            assert row is not None
            assert row["language"] == "en"  # default applied

    def test_migration_is_idempotent(self, tmp_path):
        """Running init_db() twice on the same path must not raise."""
        db_path = str(tmp_path / "idem.db")
        db_module._conn = None
        db_module.init_db(db_path=db_path)
        if db_module._conn:
            db_module._conn.close()
            db_module._conn = None
        db_module.init_db(db_path=db_path)
