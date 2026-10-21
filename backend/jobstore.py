"""
A deliberately small persistence layer: one SQLite table holding every
transcription job, its status, and its result once finished. This is what
powers both the "poll until done" job queue and the history view.

Why SQLite and not Postgres/a real queue: this app is meant to run as a
single process (including inside a Colab notebook), and SQLite needs zero
setup — the file just appears in backend/storage/. If you outgrow a single
server, swap this module for Postgres + Celery/RQ and keep the same
function signatures; nothing else in the app needs to change.

Every function opens its own short-lived connection. That's intentionally
simple rather than fast: jobs are created/updated a handful of times each,
never in a tight loop, so connection-per-call costs nothing noticeable and
sidesteps any cross-thread sqlite3 connection sharing issues (background
jobs run in FastAPI's threadpool, on a different thread than the request
that created them).
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import settings

_JSON_FIELDS = {"segments", "key_points", "links_mentioned", "dates_mentioned", "notable_terms", "exports", "warnings", "corrections"}

# Columns added after the original schema. Listed here so existing
# jobs.db files (from an earlier version of this project) get upgraded in
# place instead of throwing "no such column" errors.
_MIGRATION_COLUMNS = {
    "output_language": "TEXT",
    "dates_mentioned": "TEXT",
    "notable_terms": "TEXT",
    "docx_report_id": "TEXT",
    "image_report_id": "TEXT",
    "exports": "TEXT",
    "noise_reduction_applied": "INTEGER",
    "warnings": "TEXT",
    "transcript_native": "TEXT",
    "romanize_note": "TEXT",
    "transcription_model": "TEXT",
    "audio_duration_seconds": "REAL",
    "word_count": "INTEGER",
    # added with Text -> Audio and the spelling fix
    "voice_id": "TEXT",          # the narration voice chosen on the options page
    "transcript_raw": "TEXT",    # the transcript as heard, kept when the spelling fix changed words
    "corrections": "TEXT",       # [{"from": ..., "to": ...}] — what the spelling fix changed
    "labeled_transcript": "TEXT",  # "Speaker 1: ...\n\nSpeaker 2: ..." when speaker labels were requested
    "owner": "TEXT",             # who started it ("user:ravi" / "ip:1.2.3.4") — for the daily limit
}


def _db_path() -> Path:
    return settings.storage_path / "jobs.db"


@contextmanager
def _conn():
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                filename TEXT,
                error TEXT,
                detected_language TEXT,
                transcript TEXT,
                segments TEXT,
                summary TEXT,
                summary_word_target INTEGER,
                key_points TEXT,
                links_mentioned TEXT,
                ai_insights TEXT,
                diarization_available INTEGER,
                source_language_used TEXT,
                target_language TEXT,
                transcript_translated TEXT,
                pdf_report_id TEXT,
                output_language TEXT,
                dates_mentioned TEXT,
                notable_terms TEXT,
                docx_report_id TEXT,
                image_report_id TEXT,
                exports TEXT,
                noise_reduction_applied INTEGER,
                warnings TEXT,
                transcript_native TEXT,
                romanize_note TEXT,
                transcription_model TEXT,
                audio_duration_seconds REAL,
                word_count INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")

        # Upgrade path for a jobs.db created by an earlier version of this
        # project, which won't have the newer columns above.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for col, col_type in _MIGRATION_COLUMNS.items():
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(mode: str, filename: str, owner: str | None = None) -> str:
    job_id = uuid.uuid4().hex
    with _conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, created_at, updated_at, filename, owner) "
            "VALUES (?, ?, 'queued', ?, ?, ?, ?)",
            (job_id, mode, _now(), _now(), filename, owner),
        )
    return job_id


def count_jobs_last_day(owner: str) -> int:
    """How many jobs this person started in the last 24 hours (for the daily limit)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE owner = ? AND created_at >= ?", (owner, since)
        ).fetchone()
    return int(row[0])


def update_job(job_id: str, **fields):
    if not fields:
        return
    fields = dict(fields)
    for key in _JSON_FIELDS:
        if key in fields and not isinstance(fields[key], str):
            fields[key] = json.dumps(fields[key])
    fields["updated_at"] = _now()

    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id]
    with _conn() as conn:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)


def mark_error(job_id: str, message: str):
    update_job(job_id, status="error", error=message)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in _JSON_FIELDS:
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = []
        else:
            d[key] = []
    d["diarization_available"] = bool(d.get("diarization_available"))
    d["noise_reduction_applied"] = bool(d.get("noise_reduction_applied"))
    return d


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 30, offset: int = 0) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_job(job_id: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return cur.rowcount > 0


def add_export(job_id: str, format: str, report_id: str):
    """
    Records an on-demand re-export (see POST /api/jobs/{id}/export) so the
    frontend can show a running list of "downloads you've generated for
    this job" without losing track of earlier ones.
    """
    job = get_job(job_id)
    if not job:
        return
    exports = job.get("exports") or []
    exports.append({"format": format, "report_id": report_id, "created_at": _now()})
    update_job(job_id, exports=exports)
