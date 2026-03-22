"""
Minimalistic SQLite database layer for Spodkast session persistence.

Schema
------
sessions
    id          TEXT PRIMARY KEY   -- 12-char hex UUID
    created_at  TEXT NOT NULL      -- ISO-8601 UTC timestamp
    device_info TEXT               -- optional; free-form JSON from caller
    operator_message TEXT          -- Claude's message to the operator (may be NULL)

episodes
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
    idx         INTEGER NOT NULL   -- episode index within the session (1-based)
    title       TEXT NOT NULL
    summary     TEXT NOT NULL      -- always present (from conspect)
    text        TEXT               -- NULL until expanded
    PRIMARY KEY (session_id, idx)

episode_translations
    session_id  TEXT    NOT NULL
    episode_idx INTEGER NOT NULL
    language    TEXT    NOT NULL   -- BCP-47 language code (e.g. 'pl', 'es')
    text        TEXT    NOT NULL   -- translated/localized script
    created_at  TEXT    NOT NULL   -- ISO-8601 UTC timestamp
    PRIMARY KEY (session_id, episode_idx, language)

jobs
    id          TEXT PRIMARY KEY   -- 12-char hex UUID
    session_id  TEXT               -- NULL allowed (job may not be tied to a live session)
    episode_idx INTEGER            -- NULL allowed
    language    TEXT NOT NULL      -- language code for which audio was synthesized
    status      TEXT NOT NULL      -- pending | running | done | failed
    created_at  TEXT NOT NULL      -- ISO-8601 UTC timestamp
    output_path TEXT               -- set when done
    filename    TEXT               -- set when done
    error       TEXT               -- set when failed

Usage
-----
    from app.db import init_db, get_conn

    init_db()                       # call once at startup
    with get_conn() as conn:        # yields a sqlite3.Connection
        conn.execute(...)
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from loguru import logger

# ── module-level state ──────────────────────────────────────────────────────

_DB_PATH: str = "./spodkast.db"
_lock = threading.Lock()


def configure(db_path: str) -> None:
    """Override the database path before calling init_db()."""
    global _DB_PATH
    _DB_PATH = db_path


# ── schema ──────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    device_info      TEXT,
    operator_message TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    title       TEXT    NOT NULL,
    summary     TEXT    NOT NULL,
    text        TEXT,
    PRIMARY KEY (session_id, idx)
);

CREATE TABLE IF NOT EXISTS episode_translations (
    session_id  TEXT    NOT NULL,
    episode_idx INTEGER NOT NULL,
    language    TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (session_id, episode_idx, language),
    FOREIGN KEY (session_id, episode_idx) REFERENCES episodes(session_id, idx) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT    PRIMARY KEY,
    session_id  TEXT,
    episode_idx INTEGER,
    language    TEXT    NOT NULL DEFAULT 'en',
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL,
    output_path TEXT,
    filename    TEXT,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs (session_id);
"""


# ── connection factory ──────────────────────────────────────────────────────

def _make_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _DB_PATH,
        check_same_thread=False,   # we manage our own locking
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Module-level shared connection (SQLite with WAL is safe for multi-reader)
_conn: sqlite3.Connection | None = None


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply incremental schema migrations for databases that pre-date the
    current schema version.  Each migration is guarded so it only runs once
    (SQLite's ALTER TABLE is idempotent-by-catch pattern).
    """
    # Migration 1: add `language` column to `jobs` (introduced with restartable LLM processes)
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "language" not in existing_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
        logger.info("Migration: added 'language' column to jobs table")

    # Ensure the composite index exists (safe to run after language column is present)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_session_ep_lang "
        "ON jobs (session_id, episode_idx, language)"
    )


def init_db(db_path: str | None = None) -> None:
    """
    Initialise the database: create the file (if needed) and apply the schema.
    Call exactly once during application startup.

    Args:
        db_path: Override the database file path.  If omitted the value set via
                 configure() (or the built-in default) is used.
    """
    global _conn, _DB_PATH

    if db_path is not None:
        _DB_PATH = db_path

    # Ensure parent directory exists
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with _lock:
        _conn = _make_connection()
        _conn.executescript(_SCHEMA_SQL)
        _apply_migrations(_conn)
        _conn.commit()

    logger.info(f"📦 Spodkast DB initialised at {_DB_PATH!r}")


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield the shared SQLite connection inside a serialised lock.

    Usage::

        with get_conn() as conn:
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (...))

    The connection is NOT auto-committed — callers must call conn.commit() or
    rely on the context manager's finally block which commits on clean exit.
    """
    if _conn is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")

    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise
