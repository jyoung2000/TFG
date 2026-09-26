"""The container side of the remote WanGP bridge (phase 9).

Exposes the in-process `WanGPBridge` over HTTP so a desktop running
`RemoteWanGPBridge` can drive it: status, model definitions, input uploads,
manifest jobs with progress and cancel, and output download. One manifest
runs at a time (the card is the bottleneck); every job is also a History
job on this backend, so the container's own History shows what it rendered.
"""

from __future__ import annotations

import base64
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, cast

from _routes._errors import HTTPError
from handlers.base import StateHandlerBase
from handlers.jobs_handler import JobsHandler
from server_utils.path_policy import is_within
from services.interfaces import TaskRunner
from services.wangp_bridge import WanGPBridge
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 512 * 1024 * 1024


@dataclass
class ManifestJob:
    id: str
    status: str = "queued"  # queued | running | complete | failed | cancelled
    phase: str = ""
    progress: float | None = None
    outputs: list[str] = field(default_factory=list[str])
    error: str = ""
    cancelled: bool = False
    job_id: str = ""


class WanGPServerHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        *,
        bridge: WanGPBridge,
        outputs_dir: Path,
        task_runner: TaskRunner,
        jobs: JobsHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._bridge = bridge
        self._outputs_dir = outputs_dir
        self._uploads = outputs_dir / "remote_inputs"
        self._tasks = task_runner
        self._jobs = jobs
        self._manifests: dict[str, ManifestJob] = {}
        self._active: str = ""
        self._io = threading.RLock()

    # ---- read ---------------------------------------------------------------------------

    def status(self) -> dict[str, object]:
        status = self._bridge.get_status()
        with self._io:
            active = self._active
        return {"available": status.available, "reason": status.reason, "busy": bool(active), "active_job": active}

    def definitions(self) -> list[dict[str, object]]:
        return self._bridge.list_model_definitions()

    # ---- uploads ------------------------------------------------------------------------

    def upload(self, name: str, data_base64: str) -> str:
        safe = Path(name).name or "input"
        try:
            data = base64.b64decode(data_base64, validate=True)
        except ValueError as exc:
            raise HTTPError(400, "data_base64 is not valid base64") from exc
        if not data:
            raise HTTPError(400, "Empty upload")
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPError(413, "Upload exceeds 512 MB")
        self._uploads.mkdir(parents=True, exist_ok=True)
        target = self._uploads / f"{uuid.uuid4().hex[:10]}-{safe}"
        target.write_bytes(data)
        return str(target)

    # ---- jobs ---------------------------------------------------------------------------

    def submit(self, manifest: list[dict[str, Any]], media_suffixes: list[str]) -> ManifestJob:
        if not manifest:
            raise HTTPError(400, "Empty manifest")
        status = self._bridge.get_status()
        if not status.available:
            raise HTTPError(503, status.reason or "WanGP is not available on this backend")
        for entry in manifest:
            params = entry.get("params")
            if not isinstance(params, dict):
                raise HTTPError(400, "Every manifest entry needs a params object")
            self._check_paths(cast(dict[str, object], params))
        with self._io:
            if self._active:
                raise HTTPError(409, "The remote WanGP is busy with another job")
            job = ManifestJob(id=uuid.uuid4().hex[:12])
            self._manifests[job.id] = job
            self._active = job.id
        if self._jobs is not None:
            first = cast(dict[str, object], manifest[0].get("params", {}))
            history = self._jobs.start(
                "video_gen" if any(s in (".mp4", ".webm", ".mov") for s in media_suffixes) else "image_gen",
                title=f"remote · {str(first.get('prompt', ''))[:70]}",
                model=str(first.get("model_type", "") or first.get("model", "") or "wangp"),
                provider="wangp-remote",
                prompt=str(first.get("prompt", "")),
                params={k: v for k, v in first.items() if k != "prompt"},
                inputs={"remote_job": job.id},
            )
            job.job_id = history.id
            self._jobs.mark_running(history.id, phase="queued")
        suffixes = {s if s.startswith(".") else f".{s}" for s in media_suffixes} or {".mp4", ".png", ".jpg", ".webp"}
        self._tasks.run_background(
            lambda: self._run(job.id, manifest, suffixes),
            task_name=f"wangp-remote-{job.id}",
            on_error=lambda exc: self._fail(job.id, str(exc)),
        )
        return job

    def get(self, job_id: str) -> ManifestJob:
        with self._io:
            job = self._manifests.get(job_id)
        if job is None:
            raise HTTPError(404, "Remote job not found")
        return job

    def cancel(self, job_id: str) -> ManifestJob:
        job = self.get(job_id)
        with self._io:
            job.cancelled = True
            if job.status == "queued":
                job.status = "cancelled"
                job.error = "Cancelled"
                if self._active == job_id:
                    self._active = ""
        return job

    def output_path(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise HTTPError(400, "Output path must be absolute")
        resolved = candidate.resolve()
        if not is_within(self._outputs_dir, resolved) or not resolved.is_file():
            raise HTTPError(404, "Output not found")
        return resolved

    # ---- internals ----------------------------------------------------------------------

    def _check_paths(self, params: dict[str, object]) -> None:
        """Manifest inputs must be files this backend uploaded (never arbitrary paths)."""
        from services.wangp_remote_bridge import referenced_files

        for raw in referenced_files([{"params": params}]):
            path = Path(raw)
            if not path.is_absolute() or not is_within(self._uploads, path.resolve()) or not path.is_file():
                raise HTTPError(400, f"Manifest input is not an uploaded file: {raw}")

    def _run(self, job_id: str, manifest: list[dict[str, Any]], suffixes: set[str]) -> None:
        job = self.get(job_id)
        with self._io:
            if job.cancelled:
                return
            job.status = "running"
            job.phase = "starting"

        def on_progress(phase: str, progress: int, _eta: int | None, _detail: int | None) -> None:
            with self._io:
                job.phase = phase
                job.progress = float(progress)
            if job.job_id and self._jobs is not None:
                self._jobs.progress(job.job_id, float(progress), phase)

        def is_cancelled() -> bool:
            with self._io:
                return job.cancelled

        try:
            outputs = self._bridge.run_manifest(manifest=manifest, media_suffixes=suffixes, on_progress=on_progress, is_cancelled=is_cancelled)
        except Exception as exc:  # noqa: BLE001 - the job carries the reason
            cancelled = is_cancelled() or "cancelled" in str(exc).lower()
            with self._io:
                job.status = "cancelled" if cancelled else "failed"
                job.error = "Cancelled" if cancelled else str(exc)
                if self._active == job_id:
                    self._active = ""
            if job.job_id and self._jobs is not None:
                if cancelled:
                    self._jobs.mark_cancelled(job.job_id)
                else:
                    self._jobs.fail(job.job_id, job.error)
            return
        with self._io:
            job.status = "complete"
            job.phase = "complete"
            job.progress = 100.0
            job.outputs = list(outputs)
            if self._active == job_id:
                self._active = ""
        if job.job_id and self._jobs is not None:
            self._jobs.complete(job.job_id, list(outputs))

    def _fail(self, job_id: str, message: str) -> None:
        with self._io:
            job = self._manifests.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = message
            if self._active == job_id:
                self._active = ""
        if job.job_id and self._jobs is not None:
            self._jobs.fail(job.job_id, message)
