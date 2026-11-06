"""
db.py

Local SQLite database. It stores deadlines, attendance and the status of
each sync, so the app can still show the last good data when the LMS or
the portal is down.

The database lives in %APPDATA%\\UMT Companion\\ (outside the project folder),
so it can never be committed to GitHub by accident.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

APP_FOLDER = Path(os.environ.get("APPDATA", str(Path.home()))) / "UMT Companion"
DB_PATH = APP_FOLDER / "umt_companion.db"


def _now() -> str:
    """Current time as text, e.g. '2026-11-06T11:40:00'."""
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connection():
    """
    Open the database, run the code inside the 'with' block,
    then save (commit) the changes, or undo them if something went wrong.
    """
    APP_FOLDER.mkdir(parents=True, exist_ok=True)     # create the folder the first time
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row                     # lets us read columns by name
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the tables if they don't exist yet. Safe to run every time."""
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS deadlines (
                event_id      INTEGER PRIMARY KEY,
                title         TEXT NOT NULL,
                course        TEXT NOT NULL,
                due           TEXT NOT NULL,
                activity_type TEXT,
                url           TEXT
            );

            CREATE TABLE IF NOT EXISTS attendance (
                assigned_id TEXT PRIMARY KEY,
                course_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                faculty     TEXT,
                attended    INTEGER NOT NULL,
                total       INTEGER NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_status (
                source       TEXT PRIMARY KEY,   -- 'lms' or 'portal'
                last_success TEXT,               -- last time it worked
                last_attempt TEXT,               -- last time we tried
                last_error   TEXT                -- empty if the last try worked
            );
        """)


# ---------- Deadlines ----------

def replace_deadlines(items) -> None:
    """
    Replace ALL saved deadlines with the new list.
    Only called after a successful LMS sync, so old data is never lost on failure.
    """
    rows = [
        (d.event_id, d.title, d.course, d.due.isoformat(), d.activity_type, d.url)
        for d in items
    ]
    with connection() as conn:
        conn.execute("DELETE FROM deadlines")
        conn.executemany("INSERT INTO deadlines VALUES (?, ?, ?, ?, ?, ?)", rows)


def get_deadlines() -> list[dict]:
    """Return all saved deadlines, soonest first. 'due' is converted back to a datetime."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM deadlines ORDER BY due").fetchall()
    return [{**dict(r), "due": datetime.fromisoformat(r["due"])} for r in rows]


# ---------- Attendance ----------

def save_attendance(items) -> None:
    """
    Insert or update each subject. Subjects we didn't get this time keep their old row.
    """
    now = _now()
    rows = [
        (s.assigned_id, s.course_id, s.title, s.faculty, s.attended, s.total, now)
        for s in items
    ]
    with connection() as conn:
        conn.executemany("""
            INSERT INTO attendance
                (assigned_id, course_id, title, faculty, attended, total, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(assigned_id) DO UPDATE SET
                course_id  = excluded.course_id,
                title      = excluded.title,
                faculty    = excluded.faculty,
                attended   = excluded.attended,
                total      = excluded.total,
                updated_at = excluded.updated_at
        """, rows)


def get_attendance() -> list[dict]:
    """Return all saved subjects, sorted by course id."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM attendance ORDER BY course_id").fetchall()
    return [dict(r) for r in rows]


# ---------- Sync status ----------

def record_sync(source: str, ok: bool, message: str) -> None:
    """Remember whether the last sync of 'lms' or 'portal' worked, and why not if it didn't."""
    now = _now()
    with connection() as conn:
        if ok:
            conn.execute("""
                INSERT INTO sync_status (source, last_success, last_attempt, last_error)
                VALUES (?, ?, ?, '')
                ON CONFLICT(source) DO UPDATE SET
                    last_success = excluded.last_success,
                    last_attempt = excluded.last_attempt,
                    last_error   = ''
            """, (source, now, now))
        else:
            conn.execute("""
                INSERT INTO sync_status (source, last_success, last_attempt, last_error)
                VALUES (?, NULL, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempt = excluded.last_attempt,
                    last_error   = excluded.last_error
            """, (source, now, message))


def get_sync_status(source: str) -> dict | None:
    """Return the sync status for 'lms' or 'portal', or None if it never ran."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM sync_status WHERE source = ?", (source,)
        ).fetchone()
    return dict(row) if row else None