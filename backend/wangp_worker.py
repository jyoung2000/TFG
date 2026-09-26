"""WanGP worker: runs WanGP in ITS OWN Python environment, next to the backend.

Why this exists: WanGP needs ~100 packages (gradio, pinned diffusers, …) that
are not in `backend/uv.lock`. Installing them into the backend venv means the
next `uv sync` prunes them and the first render fails with
"No module named 'gradio'"; locking them into the backend drags WanGP's pins
into every backend dependency decision. So WanGP gets its own venv
(`Wan2GP/.venv`, see scripts/ensure-wangp-venv.*) and this script runs there.
The backend starts it (services/wangp_worker_bridge.py) and drives it over
loopback HTTP with the same `/api/wangp/*` protocol the container server
speaks, so the manifest the backend builds is exactly what WanGP receives.

Deliberately standard library only — the WanGP venv is not guaranteed to have
anything the backend has — plus the bridge module, which is also stdlib-only
and is loaded by file path so the backend's `services` package (and its
imports) never load here.

Lifecycle: binds 127.0.0.1 on an ephemeral port, prints
``TFG_WANGP_WORKER_READY <port>`` once listening, and exits when its stdin
reaches EOF — i.e. when the backend that owns the pipe exits or crashes — so
a dead backend never leaves an orphan holding VRAM. Every request must carry
the bearer token the backend put in ``TFG_WANGP_WORKER_TOKEN``.
"""

from __future__ import annotations

import argparse
import hmac
import importlib.util
import json
import logging
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.parse import urlparse

READY_PREFIX = "TFG_WANGP_WORKER_READY"
TOKEN_ENV = "TFG_WANGP_WORKER_TOKEN"
_MAX_BODY_BYTES = 8 * 1024 * 1024

logger = logging.getLogger("wangp_worker")


def _load_bridge_module() -> ModuleType:
    """Load services/wangp_bridge.py by path under a private name, so the
    backend's `services/__init__.py` (and everything it imports) never runs
    inside the WanGP environment."""
    path = Path(__file__).resolve().parent / "services" / "wangp_bridge.py"
    spec = importlib.util.spec_from_file_location("tfg_wangp_bridge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load the WanGP bridge from {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses can resolve the module's annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _Job:
    id: str
    status: str = "queued"  # queued | running | complete | failed | cancelled
    phase: str = ""
    progress: float | None = None
    outputs: list[str] = field(default_factory=list[str])
    error: str = ""
    cancelled: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "outputs": list(self.outputs),
            "error": self.error,
        }


class Worker:
    """One manifest at a time — the GPU is the bottleneck, exactly as on the
    container server (handlers/wangp_server_handler.py)."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._jobs: dict[str, _Job] = {}
        self._active = ""
        self._lock = threading.Lock()
        self._status: dict[str, object] = {"available": False, "reason": "WanGP worker is loading its libraries", "loading": True}

    # The first import of WanGP (torch, gradio, …) takes a while; do it once in
    # the background so /status stays instant and the first render is warm.
    def warm_up(self) -> None:
        def run() -> None:
            try:
                status = self._bridge.get_status()
                snapshot: dict[str, object] = {"available": bool(status.available), "reason": status.reason or "", "loading": False}
            except Exception as exc:  # noqa: BLE001 - reported through /status
                snapshot = {"available": False, "reason": f"Unable to import WanGP API: {exc}", "loading": False}
            with self._lock:
                self._status = snapshot
            logger.info("WanGP worker status: %s", snapshot)

        threading.Thread(target=run, name="wangp-warm-up", daemon=True).start()

    def status(self) -> dict[str, object]:
        with self._lock:
            return {**self._status, "busy": bool(self._active), "active_job": self._active}

    def definitions(self) -> list[dict[str, object]]:
        return cast(list[dict[str, object]], self._bridge.list_model_definitions())

    def submit(self, manifest: list[dict[str, object]], media_suffixes: list[str]) -> tuple[int, dict[str, object]]:
        if not manifest:
            return 400, {"error": "Empty manifest"}
        for entry in manifest:
            if not isinstance(entry.get("params"), dict):
                return 400, {"error": "Every manifest entry needs a params object"}
        with self._lock:
            if self._active:
                return 409, {"error": "The WanGP worker is busy with another job"}
            job = _Job(id=uuid.uuid4().hex[:12])
            self._jobs[job.id] = job
            self._active = job.id
        suffixes = {s if s.startswith(".") else f".{s}" for s in media_suffixes} or {".mp4", ".png", ".jpg", ".webp"}
        threading.Thread(target=self._run, args=(job, manifest, suffixes), name=f"wangp-job-{job.id}", daemon=True).start()
        return 200, job.payload()

    def get(self, job_id: str) -> tuple[int, dict[str, object]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return (404, {"error": "Job not found"}) if job is None else (200, job.payload())

    def cancel(self, job_id: str) -> tuple[int, dict[str, object]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return 404, {"error": "Job not found"}
            job.cancelled = True
            if job.status == "queued":
                job.status, job.error = "cancelled", "Cancelled"
                if self._active == job.id:
                    self._active = ""
            return 200, job.payload()

    def _run(self, job: _Job, manifest: list[dict[str, object]], suffixes: set[str]) -> None:
        with self._lock:
            if job.cancelled:
                return
            job.status, job.phase = "running", "starting"

        def on_progress(phase: str, progress: int, _current: int | None, _total: int | None) -> None:
            with self._lock:
                job.phase, job.progress = phase, float(progress)

        def is_cancelled() -> bool:
            with self._lock:
                return job.cancelled

        try:
            outputs = cast(
                list[str],
                self._bridge.run_manifest(manifest=manifest, media_suffixes=suffixes, on_progress=on_progress, is_cancelled=is_cancelled),
            )
        except Exception as exc:  # noqa: BLE001 - the job carries the reason
            cancelled = is_cancelled() or "cancelled" in str(exc).lower()
            with self._lock:
                job.status = "cancelled" if cancelled else "failed"
                job.error = "Cancelled" if cancelled else str(exc)
                self._active = ""
            return
        with self._lock:
            job.status, job.phase, job.progress = "complete", "complete", 100.0
            job.outputs = list(outputs)
            self._active = ""


def _make_handler(worker: Worker, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TFGWanGPWorker/1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            logger.debug("%s - %s", self.address_string(), format % args)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {token}".encode("utf-8"))

        def _send(self, code: int, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > _MAX_BODY_BYTES:
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                parsed = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                return None
            return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if not self._authorized():
                self._send(401, {"error": "Unauthorized"})
                return
            path = urlparse(self.path).path
            if path == "/api/wangp/status":
                self._send(200, worker.status())
            elif path == "/api/wangp/definitions":
                self._send(200, {"definitions": worker.definitions()})
            elif path.startswith("/api/wangp/jobs/"):
                self._send(*worker.get(path.rsplit("/", 1)[-1]))
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            if not self._authorized():
                self._send(401, {"error": "Unauthorized"})
                return
            path = urlparse(self.path).path
            body = self._body()
            if body is None:
                self._send(400, {"error": "Body must be a JSON object under 8 MB"})
                return
            if path == "/api/wangp/manifest":
                manifest = body.get("manifest")
                suffixes = body.get("media_suffixes", [])
                if not isinstance(manifest, list) or not isinstance(suffixes, list):
                    self._send(400, {"error": "manifest and media_suffixes must be lists"})
                    return
                entries = [cast(dict[str, object], e) for e in cast(list[object], manifest) if isinstance(e, dict)]
                self._send(*worker.submit(entries, [str(s) for s in cast(list[object], suffixes)]))
            elif path.startswith("/api/wangp/jobs/") and path.endswith("/cancel"):
                self._send(*worker.cancel(path.split("/")[-2]))
            else:
                self._send(404, {"error": "Not found"})

    return Handler


def _exit_when_stdin_closes() -> None:
    """The backend holds our stdin pipe; EOF means it is gone (exit, crash or
    kill), so leave rather than keep a GPU model resident as an orphan."""
    try:
        while sys.stdin.read(4096):
            pass
    except (OSError, ValueError):
        pass
    logger.info("Backend pipe closed — WanGP worker exiting")
    os._exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Wan2GP checkout (the folder with wgp.py)")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--video-model-type", default="ltx2_22B_distilled")
    parser.add_argument("--image-model-type", default="z_image")
    parser.add_argument("--extra-arg", action="append", default=[], help="Passed to WanGP's session (repeatable)")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < 16:
        print(f"{TOKEN_ENV} must be set by the backend that starts this worker", file=sys.stderr)
        return 2

    bridge_module = _load_bridge_module()
    bridge = bridge_module.WanGPBridge(
        enabled=True,
        root=Path(args.root),
        python_executable=sys.executable,
        config_dir=Path(args.config_dir),
        output_dir=Path(args.output_dir),
        video_model_type=args.video_model_type,
        image_model_type=args.image_model_type,
        camera_motion_prompts={},
        extra_args=tuple(args.extra_arg),
    )
    worker = Worker(bridge)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(worker, token))
    server.daemon_threads = True
    threading.Thread(target=_exit_when_stdin_closes, name="wangp-parent-watch", daemon=True).start()
    worker.warm_up()
    print(f"{READY_PREFIX} {server.server_address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
