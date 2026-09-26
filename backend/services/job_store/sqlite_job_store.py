"""SQLite persistence for jobs.

Same reasoning as the knowledge store: an append-mostly log that grows with
every render, read by filter and sort, updated in place by progress ticks.
`sqlite3` is in the standard library; WAL mode keeps readers (the History
poll, the SSE stream) off the writer's back. Schema changes are numbered
migrations in `_MIGRATIONS`, recorded in `schema_migrations`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, cast

from services.job_store.job_models import Job, JobOutput, now_ms

logger = logging.getLogger(__name__)

_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            kind            TEXT NOT NULL,
            status          TEXT NOT NULL,
            progress        REAL NOT NULL DEFAULT 0,
            phase           TEXT NOT NULL DEFAULT '',
            title           TEXT NOT NULL DEFAULT '',
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL,
            started_at      INTEGER,
            finished_at     INTEGER,
            model           TEXT NOT NULL DEFAULT '',
            provider        TEXT NOT NULL DEFAULT 'local',
            seed            INTEGER,
            prompt          TEXT NOT NULL DEFAULT '',
            negative_prompt TEXT NOT NULL DEFAULT '',
            spec_json       TEXT NOT NULL DEFAULT '{}',
            params_json     TEXT NOT NULL DEFAULT '{}',
            inputs_json     TEXT NOT NULL DEFAULT '{}',
            outputs_json    TEXT NOT NULL DEFAULT '[]',
            metrics_json    TEXT NOT NULL DEFAULT '{}',
            parent_job_id   TEXT NOT NULL DEFAULT '',
            project_id      TEXT NOT NULL DEFAULT '',
            shot_id         TEXT NOT NULL DEFAULT '',
            error           TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC, id);
        CREATE INDEX IF NOT EXISTS jobs_kind_idx ON jobs (kind, created_at DESC);
        CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS jobs_project_idx ON jobs (project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS jobs_parent_idx ON jobs (parent_job_id);
        """,
    ),
]

_COLUMNS = (
    "id", "kind", "status", "progress", "phase", "title", "created_at", "updated_at", "started_at",
    "finished_at", "model", "provider", "seed", "prompt", "negative_prompt", "spec_json", "params_json",
    "inputs_json", "outputs_json", "metrics_json", "parent_job_id", "project_id", "shot_id", "error",
)


def _row_to_job(row: sqlite3.Row) -> Job:
    outputs_raw = cast(list[dict[str, Any]], json.loads(str(row["outputs_json"]) or "[]"))
    return Job(
        id=str(row["id"]),
        kind=row["kind"],
        status=row["status"],
        progress=float(row["progress"]),
        phase=str(row["phase"]),
        title=str(row["title"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        started_at=int(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=int(row["finished_at"]) if row["finished_at"] is not None else None,
        model=str(row["model"]),
        provider=str(row["provider"]),
        seed=int(row["seed"]) if row["seed"] is not None else None,
        prompt=str(row["prompt"]),
        negative_prompt=str(row["negative_prompt"]),
        spec=cast(dict[str, Any], json.loads(str(row["spec_json"]) or "{}")),
        params=cast(dict[str, Any], json.loads(str(row["params_json"]) or "{}")),
        inputs=cast(dict[str, Any], json.loads(str(row["inputs_json"]) or "{}")),
        outputs=[JobOutput.model_validate(item) for item in outputs_raw],
        metrics=cast(dict[str, Any], json.loads(str(row["metrics_json"]) or "{}")),
        parent_job_id=str(row["parent_job_id"]),
        project_id=str(row["project_id"]),
        shot_id=str(row["shot_id"]),
        error=str(row["error"]),
    )


def _job_to_params(job: Job) -> tuple[object, ...]:
    return (
        job.id, job.kind, job.status, job.progress, job.phase, job.title, job.created_at, job.updated_at,
        job.started_at, job.finished_at, job.model, job.provider, job.seed, job.prompt, job.negative_prompt,
        json.dumps(job.spec, sort_keys=True), json.dumps(job.params, sort_keys=True),
        json.dumps(job.inputs, sort_keys=True), json.dumps([o.model_dump() for o in job.outputs]),
        json.dumps(job.metrics, sort_keys=True), job.parent_job_id, job.project_id, job.shot_id, job.error,
    )


def encode_cursor(job: Job) -> str:
    return f"{job.created_at}:{job.id}"


def decode_cursor(cursor: str) -> tuple[int, str] | None:
    created, _, job_id = cursor.partition(":")
    if not created.isdigit() or not job_id:
        return None
    return int(created), job_id


class SqliteJobStore:
    """Thread-safe: one connection per call, serialised by a lock; WAL on disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _migrate(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
                )
                applied = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
                for version, sql in _MIGRATIONS:
                    if version in applied:
                        continue
                    connection.executescript(sql)
                    connection.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (version, now_ms())
                    )
                    logger.info("jobs.sqlite migrated to schema %s", version)
                connection.commit()
            finally:
                connection.close()

    def schema_version(self) -> int:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
                return int(row[0]) if row and row[0] is not None else 0
            finally:
                connection.close()

    def insert(self, job: Job) -> Job:
        placeholders = ", ".join("?" for _ in _COLUMNS)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(
                    f"INSERT INTO jobs ({', '.join(_COLUMNS)}) VALUES ({placeholders})", _job_to_params(job)
                )
                connection.commit()
            finally:
                connection.close()
        return job

    def update(self, job: Job) -> Job:
        assignments = ", ".join(f"{column} = ?" for column in _COLUMNS[1:])
        params = _job_to_params(job)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*params[1:], job.id))
                connection.commit()
            finally:
                connection.close()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            finally:
                connection.close()
        return _row_to_job(row) if row is not None else None

    def delete(self, job_id: str) -> bool:
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                connection.commit()
                return cursor.rowcount > 0
            finally:
                connection.close()

    def list(
        self,
        *,
        kind: str = "",
        status: str = "",
        statuses: tuple[str, ...] = (),
        project_id: str = "",
        parent_job_id: str | None = None,
        search: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> tuple[list[Job], str]:
        """Newest first. Returns the page and the cursor for the next one ("" at the end)."""
        clauses: list[str] = []
        params: list[object] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if statuses:
            clauses.append(f"status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if parent_job_id is not None:
            clauses.append("parent_job_id = ?")
            params.append(parent_job_id)
        if search:
            clauses.append("(prompt LIKE ? OR title LIKE ? OR model LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        decoded = decode_cursor(cursor) if cursor else None
        if decoded is not None:
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend([decoded[0], decoded[0], decoded[1]])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(500, limit))
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    f"SELECT * FROM jobs {where} ORDER BY created_at DESC, id DESC LIMIT ?", (*params, limit + 1)
                ).fetchall()
            finally:
                connection.close()
        jobs = [_row_to_job(row) for row in rows]
        next_cursor = ""
        if len(jobs) > limit:
            jobs = jobs[:limit]
            next_cursor = encode_cursor(jobs[-1])
        return jobs, next_cursor

    def count(self, *, status: str = "") -> int:
        with self._lock:
            connection = self._connect()
            try:
                if status:
                    row = connection.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (status,)).fetchone()
                else:
                    row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
                return int(row[0]) if row else 0
            finally:
                connection.close()

    def mark_interrupted(self, message: str) -> int:
        """Anything still queued/running belongs to a process that no longer exists."""
        stamp = now_ms()
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, finished_at = ?, updated_at = ? "
                    "WHERE status IN ('queued', 'running')",
                    (message, stamp, stamp),
                )
                connection.commit()
                return cursor.rowcount
            finally:
                connection.close()
