"""Persistence for the knowledge engine.

SQLite rather than the JSON documents the rest of the app uses, and the reason
is the access pattern rather than taste: this is an append-only log that grows
with every render and is read by aggregation ("how often did this model
succeed?"). Rewriting a JSON array on every event would be O(n) per write and
would lose data on a crash mid-write. `sqlite3` is in the standard library, so
this adds a file, not a dependency or a service.

Everything else stays where it is. This store holds knowledge only; projects,
analyses and settings are untouched.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence, cast

from film.knowledge_models import (
    EVENT_CATEGORIES,
    KnowledgeEvent,
    Observation,
)

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    created_at    INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    category      TEXT NOT NULL,
    project_id    TEXT NOT NULL DEFAULT '',
    scene_id      TEXT NOT NULL DEFAULT '',
    shot_id       TEXT NOT NULL DEFAULT '',
    version_number INTEGER,
    model         TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    task          TEXT NOT NULL DEFAULT '',
    execution_mode TEXT NOT NULL DEFAULT '',
    prompt        TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    outcome       TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    error         TEXT NOT NULL DEFAULT '',
    rating        INTEGER,
    note          TEXT NOT NULL DEFAULT ''
);

-- The three queries that matter: by model, by project, and most recent first.
CREATE INDEX IF NOT EXISTS events_model_idx ON events (model, created_at DESC);
CREATE INDEX IF NOT EXISTS events_project_idx ON events (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS events_created_idx ON events (created_at DESC);

CREATE TABLE IF NOT EXISTS observations (
    id            TEXT PRIMARY KEY,
    model         TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    task          TEXT NOT NULL DEFAULT '',
    kind          TEXT NOT NULL,
    statement     TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    sample_size   INTEGER NOT NULL DEFAULT 0,
    first_seen    INTEGER NOT NULL DEFAULT 0,
    last_seen     INTEGER NOT NULL DEFAULT 0,
    evidence      TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS observations_model_idx ON observations (model);
"""


class KnowledgeStore:
    """Thread-safe SQLite access. One connection per call, WAL for concurrency."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connect() as connection:
            # WAL lets the generation worker append while the UI reads.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT version FROM schema_info").fetchone()
            existing = {str(col[1]) for col in connection.execute("PRAGMA table_info(events)").fetchall()}
            # v2: Reproduce evidence columns. Additive, so v1 rows keep working.
            for column, definition in (
                ("seed", "INTEGER"),
                ("target", "TEXT NOT NULL DEFAULT ''"),
                ("spec_keys_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("metrics_json", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if column not in existing:
                    connection.execute(f"ALTER TABLE events ADD COLUMN {column} {definition}")
            if row is None:
                connection.execute("INSERT INTO schema_info (version) VALUES (?)", (_SCHEMA_VERSION,))
            elif int(row["version"]) < _SCHEMA_VERSION:
                connection.execute("UPDATE schema_info SET version = ?", (_SCHEMA_VERSION,))

    # ---- events ----------------------------------------------------------

    def record(self, event: KnowledgeEvent) -> KnowledgeEvent:
        event.id = event.id or f"ev-{uuid.uuid4().hex[:16]}"
        event.category = EVENT_CATEGORIES.get(event.kind, event.category)
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO events (
                    id, created_at, kind, category, project_id, scene_id, shot_id, version_number,
                    model, provider, task, execution_mode, prompt, negative_prompt,
                    outcome, duration_seconds, error, rating, note,
                    seed, target, spec_keys_json, metrics_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.id, event.created_at, event.kind, event.category,
                    event.project_id, event.scene_id, event.shot_id, event.version_number,
                    event.model, event.provider, event.task, event.execution_mode,
                    event.prompt, event.negative_prompt, event.outcome,
                    event.duration_seconds, event.error, event.rating, event.note,
                    event.seed, event.target, json.dumps(sorted(event.spec_keys)), json.dumps(event.metrics, sort_keys=True),
                ),
            )
        return event

    def events(
        self,
        *,
        model: str = "",
        project_id: str = "",
        kinds: Sequence[str] = (),
        target: str = "",
        limit: int = 200,
    ) -> list[KnowledgeEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if model:
            clauses.append("model = ?")
            params.append(model)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if kinds:
            clauses.append(f"kind IN ({','.join('?' * len(kinds))})")
            params.extend(kinds)
        if target:
            clauses.append("target = ?")
            params.append(target)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def event_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])

    def known_models(self) -> list[tuple[str, str, str]]:
        """(model, provider, task) for everything that has been used."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT model, provider, task, MAX(created_at) AS last
                   FROM events WHERE model <> ''
                   GROUP BY model, provider, task ORDER BY last DESC"""
            ).fetchall()
        return [(row["model"], row["provider"], row["task"]) for row in rows]

    def model_totals(self, model: str) -> dict[str, float | int | None]:
        """Counts and averages for one model, computed in SQL rather than Python."""
        with self._connect() as connection:
            row = connection.execute(
                """SELECT
                     SUM(kind = 'generation_completed') AS successes,
                     SUM(kind = 'generation_failed') AS failures,
                     SUM(kind = 'generation_cancelled') AS cancellations,
                     SUM(kind = 'version_approved') AS approvals,
                     SUM(kind = 'version_rejected') AS rejections,
                     AVG(duration_seconds) AS average_seconds,
                     AVG(rating) AS average_rating,
                     MAX(created_at) AS last_used_at,
                     COUNT(*) AS runs
                   FROM events WHERE model = ?""",
                (model,),
            ).fetchone()
        return {
            "successes": int(row["successes"] or 0),
            "failures": int(row["failures"] or 0),
            "cancellations": int(row["cancellations"] or 0),
            "approvals": int(row["approvals"] or 0),
            "rejections": int(row["rejections"] or 0),
            "average_seconds": round(row["average_seconds"], 2) if row["average_seconds"] is not None else None,
            "average_rating": round(row["average_rating"], 2) if row["average_rating"] is not None else None,
            "last_used_at": int(row["last_used_at"] or 0),
            "runs": int(row["runs"] or 0),
        }

    # ---- observations ----------------------------------------------------

    def put_observation(self, observation: Observation) -> Observation:
        observation.id = observation.id or f"ob-{uuid.uuid4().hex[:16]}"
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO observations (
                    id, model, provider, task, kind, statement, confidence,
                    support_count, contradiction_count, sample_size, first_seen, last_seen, evidence
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    observation.id, observation.model, observation.provider, observation.task,
                    observation.kind, observation.statement, observation.confidence,
                    observation.support_count, observation.contradiction_count, observation.sample_size,
                    observation.first_seen, observation.last_seen,
                    json.dumps(observation.evidence_event_ids),
                ),
            )
        return observation

    def observations(self, *, model: str = "") -> list[Observation]:
        with self._connect() as connection:
            if model:
                rows = connection.execute("SELECT * FROM observations WHERE model = ?", (model,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM observations").fetchall()
        return [_observation_from_row(row) for row in rows]

    def replace_observations(self, model: str, observations: Sequence[Observation]) -> None:
        """Swap one model's derived knowledge atomically after a re-derivation."""
        with self._connect() as connection:
            connection.execute("DELETE FROM observations WHERE model = ?", (model,))
            for observation in observations:
                observation.id = observation.id or f"ob-{uuid.uuid4().hex[:16]}"
                connection.execute(
                    """INSERT INTO observations (
                        id, model, provider, task, kind, statement, confidence,
                        support_count, contradiction_count, sample_size, first_seen, last_seen, evidence
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        observation.id, observation.model, observation.provider, observation.task,
                        observation.kind, observation.statement, observation.confidence,
                        observation.support_count, observation.contradiction_count, observation.sample_size,
                        observation.first_seen, observation.last_seen,
                        json.dumps(observation.evidence_event_ids),
                    ),
                )

    # ---- wholesale operations -------------------------------------------

    def clear(self, *, model: str = "", project_id: str = "") -> int:
        """Forget everything, or one model's, or one project's. Returns rows removed."""
        with self._connect() as connection:
            if model:
                removed = connection.execute("DELETE FROM events WHERE model = ?", (model,)).rowcount
                connection.execute("DELETE FROM observations WHERE model = ?", (model,))
            elif project_id:
                removed = connection.execute("DELETE FROM events WHERE project_id = ?", (project_id,)).rowcount
            else:
                removed = connection.execute("DELETE FROM events").rowcount
                connection.execute("DELETE FROM observations")
        return max(0, removed)


def _event_from_row(row: sqlite3.Row) -> KnowledgeEvent:
    return KnowledgeEvent(
        id=row["id"], created_at=row["created_at"], kind=row["kind"], category=row["category"],
        project_id=row["project_id"], scene_id=row["scene_id"], shot_id=row["shot_id"],
        version_number=row["version_number"], model=row["model"], provider=row["provider"],
        task=row["task"], execution_mode=row["execution_mode"], prompt=row["prompt"],
        negative_prompt=row["negative_prompt"], outcome=row["outcome"],
        duration_seconds=row["duration_seconds"], error=row["error"], rating=row["rating"],
        note=row["note"],
        seed=_int_or_none(_column(row, "seed")),
        target=str(_column(row, "target") or ""),
        spec_keys=[str(k) for k in cast(list[object], json.loads(str(_column(row, "spec_keys_json") or "[]")))],
        metrics={str(k): float(v) for k, v in cast(dict[str, object], json.loads(str(_column(row, "metrics_json") or "{}"))).items() if isinstance(v, (int, float))},
    )


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _column(row: sqlite3.Row, name: str) -> object:
    """A column that may be absent on a row read before the v2 migration."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def _observation_from_row(row: sqlite3.Row) -> Observation:
    evidence: list[str] = []
    try:
        decoded = json.loads(row["evidence"])
        if isinstance(decoded, list):
            evidence = [str(item) for item in cast(list[object], decoded)]
    except (TypeError, json.JSONDecodeError):
        evidence = []
    return Observation(
        id=row["id"], model=row["model"], provider=row["provider"], task=row["task"],
        kind=row["kind"], statement=row["statement"], confidence=row["confidence"],
        support_count=row["support_count"], contradiction_count=row["contradiction_count"],
        sample_size=row["sample_size"], first_seen=row["first_seen"], last_seen=row["last_seen"],
        evidence_event_ids=evidence,
    )
