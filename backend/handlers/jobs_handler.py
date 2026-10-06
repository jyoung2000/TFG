"""Unified job lifecycle.

Every handler that does work on the user's behalf opens a job here, reports
progress, and closes it with outputs or an error. History reads only this
store, so a job that is not recorded here does not exist as far as the user
can see.

Locking: this handler owns its own lock (the SQLite store serialises writes
anyway) and never takes the app lock, so it is safe to call from inside
handlers that hold the app lock. Thumbnail generation — the one slow step —
runs before the lock is taken.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from _routes._errors import HTTPError
from api_types import ImportJobsRequest, ImportJobsResponse
from server_utils.path_policy import is_within
from services.job_store.job_models import (
    TERMINAL_STATUSES,
    Job,
    JobKind,
    JobOutput,
    JobStatus,
    now_ms,
)
from services.job_store.sqlite_job_store import SqliteJobStore
from services.job_store.thumbnails import describe_output
from services.media_probe.media_probe import MediaProbe

logger = logging.getLogger(__name__)

Canceller = Callable[[Job], bool]
Rerunner = Callable[[Job], None]

_INTERRUPTED = "Interrupted: the app was restarted while this job was running"
_PROGRESS_MIN_INTERVAL_S = 0.25


class JobsHandler:
    def __init__(self, *, database: Path, thumbs_dir: Path, outputs_dir: Path, probe: MediaProbe) -> None:
        self._store = SqliteJobStore(database)
        self._thumbs_dir = thumbs_dir
        self._outputs_dir = outputs_dir
        self._probe = probe
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._seq = 0
        #: Recent (seq, job_id) pairs so an SSE client can catch up after a reconnect.
        self._recent: deque[tuple[int, str]] = deque(maxlen=512)
        self._last_progress_write: dict[str, float] = {}
        self._cancellers: dict[str, Canceller] = {}
        self._rerunners: dict[str, Rerunner] = {}
        self._scope = threading.local()

    @property
    def store(self) -> SqliteJobStore:
        return self._store

    @property
    def thumbs_dir(self) -> Path:
        return self._thumbs_dir

    # ---- lineage scope ----------------------------------------------------

    @contextmanager
    def parent(self, job_id: str) -> Iterator[None]:
        """Jobs started inside this block become children of `job_id`."""
        previous = getattr(self._scope, "parent", "")
        self._scope.parent = job_id
        try:
            yield
        finally:
            self._scope.parent = previous

    def current_parent(self) -> str:
        return str(getattr(self._scope, "parent", "") or "")

    # ---- lifecycle --------------------------------------------------------

    def start(
        self,
        kind: JobKind,
        *,
        title: str = "",
        model: str = "",
        provider: str = "local",
        seed: int | None = None,
        prompt: str = "",
        negative_prompt: str = "",
        params: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        spec: dict[str, Any] | None = None,
        parent_job_id: str = "",
        project_id: str = "",
        shot_id: str = "",
        status: JobStatus = "running",
        job_id: str = "",
    ) -> Job:
        stamp = now_ms()
        job = Job(
            kind=kind,
            status=status,
            title=title,
            model=model,
            provider=provider or "local",
            seed=seed,
            prompt=prompt,
            negative_prompt=negative_prompt,
            params=dict(params or {}),
            inputs=dict(inputs or {}),
            spec=dict(spec or {}),
            parent_job_id=parent_job_id or self.current_parent(),
            project_id=project_id,
            shot_id=shot_id,
            started_at=stamp if status == "running" else None,
        )
        if job_id:
            job.id = job_id
        with self._lock:
            self._store.insert(job)
            self._notify(job.id)
        return job

    def queue(self, kind: JobKind, **kwargs: Any) -> Job:
        kwargs.pop("status", None)
        return self.start(kind, status="queued", **kwargs)

    def _load(self, job_id: str) -> Job:
        job = self._store.get(job_id)
        if job is None:
            raise HTTPError(404, f"Unknown job: {job_id}")
        return job

    def mark_running(self, job_id: str, *, phase: str = "") -> Job:
        with self._lock:
            job = self._load(job_id)
            if job.status != "queued":
                return job
            job.status = "running"
            job.started_at = now_ms()
            job.updated_at = job.started_at
            if phase:
                job.phase = phase
            self._store.update(job)
            self._notify(job.id)
            return job

    def progress(self, job_id: str, progress: float, phase: str = "") -> None:
        """Cheap to call from a per-step callback: writes are rate limited."""
        if not job_id:
            return
        now = time.monotonic()
        with self._lock:
            last = self._last_progress_write.get(job_id, 0.0)
            job = self._store.get(job_id)
            if job is None or job.status not in ("queued", "running"):
                return
            clamped = max(0.0, min(100.0, float(progress)))
            phase_changed = bool(phase) and phase != job.phase
            if not phase_changed and now - last < _PROGRESS_MIN_INTERVAL_S and clamped < 100.0:
                return
            if job.status == "queued":
                job.status = "running"
                job.started_at = now_ms()
            job.progress = clamped
            if phase:
                job.phase = phase
            job.updated_at = now_ms()
            self._store.update(job)
            self._last_progress_write[job_id] = now
            self._notify(job.id)

    def annotate(self, job_id: str, **fields: Any) -> Job:
        """Set metadata learned after the job started (model, seed, prompt, inputs, spec)."""
        with self._lock:
            job = self._load(job_id)
            for key, value in fields.items():
                if key in ("params", "inputs", "spec", "metrics") and isinstance(value, dict):
                    merged = dict(getattr(job, key))
                    merged.update(value)  # pyright: ignore[reportUnknownArgumentType]
                    setattr(job, key, merged)
                elif hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = now_ms()
            self._store.update(job)
            self._notify(job.id)
            return job

    def complete(
        self,
        job_id: str,
        outputs: Sequence[str] = (),
        *,
        metrics: dict[str, Any] | None = None,
    ) -> Job:
        """Idempotent: a second completion only merges metrics and any new outputs."""
        described = [describe_output(Path(p), self._thumbs_dir, self._probe) for p in outputs if p]
        with self._lock:
            job = self._load(job_id)
            known = {o.path for o in job.outputs}
            job.outputs.extend(o for o in described if o.path not in known)
            if metrics:
                job.metrics.update(metrics)
            if job.status in TERMINAL_STATUSES:
                if job.status != "complete":
                    # A late success after a cancel/fail is still a success.
                    job.status = "complete"
                    job.error = ""
            else:
                job.status = "complete"
            job.progress = 100.0
            job.phase = "complete"
            job.finished_at = job.finished_at or now_ms()
            job.updated_at = now_ms()
            if job.started_at and "seconds" not in job.metrics:
                job.metrics["seconds"] = round((job.finished_at - job.started_at) / 1000, 2)
            self._store.update(job)
            self._notify(job.id)
            return job

    def fail(self, job_id: str, error: str, *, metrics: dict[str, Any] | None = None) -> Job:
        with self._lock:
            job = self._load(job_id)
            if job.status in TERMINAL_STATUSES:
                if metrics:
                    job.metrics.update(metrics)
                    self._store.update(job)
                return job
            job.status = "failed"
            job.error = error or "Failed"
            job.phase = "failed"
            job.finished_at = now_ms()
            job.updated_at = job.finished_at
            if metrics:
                job.metrics.update(metrics)
            self._store.update(job)
            self._notify(job.id)
            return job

    def mark_cancelled(self, job_id: str, *, reason: str = "Cancelled") -> Job:
        with self._lock:
            job = self._load(job_id)
            if job.status in TERMINAL_STATUSES:
                return job
            job.status = "cancelled"
            job.error = reason
            job.phase = "cancelled"
            job.finished_at = now_ms()
            job.updated_at = job.finished_at
            self._store.update(job)
            self._notify(job.id)
            return job

    # ---- control ----------------------------------------------------------

    def register_canceller(self, kind: JobKind, canceller: Canceller) -> None:
        self._cancellers[kind] = canceller

    def register_rerunner(self, kind: JobKind, rerunner: Rerunner) -> None:
        self._rerunners[kind] = rerunner

    def cancel(self, job_id: str) -> Job:
        job = self._load(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        if job.status == "queued":
            canceller = self._cancellers.get(job.kind)
            if canceller is not None:
                canceller(job)
            return self.mark_cancelled(job_id, reason="Cancelled before start")
        canceller = self._cancellers.get(job.kind)
        if canceller is None or not canceller(job):
            raise HTTPError(409, f"A running {job.kind} job cannot be cancelled from History")
        return self.annotate(job_id, phase="cancelling")

    def rerun(self, job_id: str, run: Callable[[Callable[[], None]], None]) -> Job:
        """Create a fresh job with the same parameters and seed and hand it to `run`
        (typically the background task runner). The original becomes its parent."""
        source = self._load(job_id)
        rerunner = self._rerunners.get(source.kind)
        if rerunner is None:
            raise HTTPError(400, f"{source.kind} jobs cannot be re-run from History")
        job = self.queue(
            source.kind,
            title=source.title,
            model=source.model,
            provider=source.provider,
            seed=source.seed,
            prompt=source.prompt,
            negative_prompt=source.negative_prompt,
            params=dict(source.params),
            inputs=dict(source.inputs),
            spec=dict(source.spec),
            parent_job_id=source.id,
            project_id=source.project_id,
            shot_id=source.shot_id,
        )

        def _go() -> None:
            try:
                rerunner(job)
            except HTTPError as exc:
                self.fail(job.id, str(exc.detail))
            except Exception as exc:  # noqa: BLE001 - the job must end in a state
                self.fail(job.id, str(exc))

        run(_go)
        return job

    # ---- queries ----------------------------------------------------------

    def get(self, job_id: str) -> Job:
        return self._load(job_id)

    def children(self, job_id: str) -> list[Job]:
        jobs, _ = self._store.list(parent_job_id=job_id, limit=500)
        return jobs

    def lineage(self, job_id: str) -> list[Job]:
        """Ancestors first, the job itself last."""
        chain: list[Job] = []
        seen: set[str] = set()
        current: Job | None = self._store.get(job_id)
        while current is not None and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            current = self._store.get(current.parent_job_id) if current.parent_job_id else None
        chain.reverse()
        return chain

    def list(
        self,
        *,
        kind: str = "",
        status: str = "",
        project_id: str = "",
        search: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> tuple[list[Job], str]:
        statuses: tuple[str, ...] = ()
        if status == "active":
            statuses = ("queued", "running")
            status = ""
        return self._store.list(
            kind=kind, status=status, statuses=statuses, project_id=project_id, search=search, limit=limit, cursor=cursor
        )

    def delete(self, job_id: str, *, files: bool = False) -> list[str]:
        """Remove the record and, on request, the files it produced. Only files
        inside the outputs directory are ever deleted."""
        job = self._load(job_id)
        if job.status in ("queued", "running"):
            raise HTTPError(409, "Cancel the job before deleting it")
        removed: list[str] = []
        if files:
            for output in job.outputs:
                for candidate in (output.path, output.thumb):
                    if not candidate:
                        continue
                    path = Path(candidate)
                    if is_within(self._outputs_dir, path) and path.is_file():
                        try:
                            path.unlink()
                            removed.append(str(path))
                        except OSError as exc:
                            logger.warning("Could not delete %s: %s", path, exc)
        else:
            for output in job.outputs:
                if output.thumb:
                    path = Path(output.thumb)
                    if is_within(self._thumbs_dir, path) and path.is_file():
                        path.unlink(missing_ok=True)
        with self._lock:
            self._store.delete(job_id)
            self._notify(job_id)
        return removed

    def recover_interrupted(self) -> int:
        with self._lock:
            count = self._store.mark_interrupted(_INTERRUPTED)
            if count:
                logger.info("Marked %s interrupted job(s) as failed", count)
                self._notify("*")
            return count

    # ---- change feed ------------------------------------------------------

    def _notify(self, job_id: str) -> None:
        self._seq += 1
        self._recent.append((self._seq, job_id))
        self._condition.notify_all()

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def wait_for_changes(self, since: int, timeout: float) -> tuple[int, list[str]]:
        """Block until something changed after `since` (or `timeout` seconds).
        Returns the new sequence number and the ids that changed; "*" means
        everything and the client should refetch."""
        with self._condition:
            if self._seq <= since:
                self._condition.wait(timeout)
            if self._seq <= since:
                return self._seq, []
            oldest = self._recent[0][0] if self._recent else self._seq
            if since < oldest - 1:
                return self._seq, ["*"]
            changed: list[str] = []
            for seq, job_id in self._recent:
                if seq > since and job_id not in changed:
                    changed.append(job_id)
            return self._seq, changed

    def snapshot(self, job_ids: Sequence[str]) -> list[Job]:
        jobs: list[Job] = []
        for job_id in job_ids:
            job = self._store.get(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    # ---- legacy import ----------------------------------------------------

    def import_quick_history(self, req: ImportJobsRequest) -> ImportJobsResponse:
        """One-time import of the localStorage Quick-mode history. Idempotent:
        an entry whose video path is already recorded is skipped."""
        imported = 0
        skipped = 0
        for entry in req.entries:
            path = entry.video_path.strip()
            if not path:
                skipped += 1
                continue
            existing, _ = self._store.list(search="", limit=500, kind="video_gen")
            if any(o.path == path for job in existing for o in job.outputs):
                skipped += 1
                continue
            job = Job(
                kind="video_gen",
                status="complete",
                progress=100.0,
                phase="complete",
                title=entry.prompt[:80],
                model=str(entry.params.get("model", "")),
                provider="local",
                seed=entry.seed,
                prompt=entry.prompt,
                negative_prompt=entry.negative_prompt,
                params=dict(entry.params),
                inputs={"imported_from": "ltx-quick-history"},
            )
            if entry.created_at > 0:
                job.created_at = entry.created_at
                job.started_at = entry.created_at
                job.finished_at = entry.created_at
                job.updated_at = entry.created_at
            job.outputs = [describe_output(Path(path), self._thumbs_dir, self._probe)]
            with self._lock:
                self._store.insert(job)
                self._notify(job.id)
            imported += 1
        return ImportJobsResponse(imported=imported, skipped=skipped)

    # ---- helpers for callers ---------------------------------------------

    @staticmethod
    def output_paths(job: Job) -> list[str]:
        return [o.path for o in job.outputs]

    @staticmethod
    def describe(output: JobOutput) -> str:
        return f"{output.kind} {output.width}x{output.height}"
