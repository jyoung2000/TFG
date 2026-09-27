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

Lifecycle (order is load-bearing — F-038): WanGP's first import (torch,
gradio, CUDA DLLs) runs FIRST, on a pristine main thread, before any other
thread exists and before any socket is bound. Round 2 caught that import
wedged inside a Windows ``LoadLibrary`` (py-spy: ``create_module`` under
numpy, CPU flat) only in the launched worker — whose pre-import environment
differed from every succeeding standalone repro by exactly two things: a
thread blocked on the stdin pipe and a bound HTTP server. Both now come
after the import. Then the server binds 127.0.0.1 on an ephemeral port
(skipping stdlib's reverse-DNS ``getfqdn``), the port is announced through
BOTH channels — the ``TFG_WANGP_WORKER_READY <port>`` line on stdout and an
atomically written ready-file — and only then does the orphan guard arm:
the worker exits when its stdin reaches EOF, i.e. when the backend that
owns the pipe is gone, so a dead backend never leaves an orphan holding
VRAM. Every request must carry the bearer token the backend put in
``TFG_WANGP_WORKER_TOKEN``.
"""

from __future__ import annotations

import argparse
import faulthandler
import hmac
import importlib.util
import json
import logging
import os
import socketserver
import sys
import threading
import time
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

_STARTED_AT = time.monotonic()
#: While True, every stage marker re-arms a one-shot faulthandler dump 120s
#: out — so the dump fires exactly 120s after the LAST stage that made
#: progress, i.e. precisely when a stage has stalled, and carries every
#: thread's stack. One-shot, not repeating: the launcher treats output as
#: liveness, and a wedged worker that kept dumping stacks forever would
#: never fall silent long enough to be declared dead.
_watchdog_armed = False
_WATCHDOG_DELAY_S = 120.0


def _trace(stage: str) -> None:
    """One flushed, timestamped stage marker to stderr (the launcher merges
    stderr into the pipe it drains and keeps as the error tail).

    Round 2's F-038 burned four localisation attempts on a worker whose only
    failure signal was "did not start (no output)": with zero markers there
    was no way to tell an argparse death from a wedged DLL load. Every
    startup stage now announces itself, so a stall names the stage it
    stalled in."""
    print(f"[wangp-worker +{time.monotonic() - _STARTED_AT:8.3f}s] {stage}", file=sys.stderr, flush=True)
    if _watchdog_armed:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(_WATCHDOG_DELAY_S, repeat=False, exit=False, file=sys.stderr)


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

    # The first import of WanGP (torch, gradio, …) takes ~1 minute and holds the
    # GIL while its CUDA DLLs load. It must therefore finish BEFORE we print
    # TFG_WANGP_WORKER_READY: announcing readiness first makes the launcher
    # report a started worker whose ThreadingHTTPServer cannot answer for the
    # whole import, so every request (including a plain GET /status) times out
    # and the first render fails with "timed out on /api/wangp/manifest".
    def warm_up(self) -> None:
        try:
            status = self._bridge.get_status()
            snapshot: dict[str, object] = {"available": bool(status.available), "reason": status.reason or "", "loading": False}
        except Exception as exc:  # noqa: BLE001 - reported through /status
            snapshot = {"available": False, "reason": f"Unable to import WanGP API: {exc}", "loading": False}
        with self._lock:
            self._status = snapshot
        logger.info("WanGP worker status: %s", snapshot)

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


class _WorkerHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without stdlib's `server_bind` getfqdn call: that
    is a reverse-DNS lookup which hangs for minutes on machines with broken
    resolvers (the classic slow http.server startup on Windows), and nothing
    here needs a server name — the worker serves loopback only."""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def _write_ready_file(path: str, port: int) -> None:
    """Announce the port through the filesystem too (atomically), so the
    launcher's readiness does not depend on the stdout pipe delivering one
    specific line."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    os.replace(tmp, target)


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
    parser.add_argument("--ready-file", default="", help="Also announce the port by writing this file atomically")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    # A wedged startup must dump every thread's stack instead of going silent:
    # crash tracebacks via enable(), and a stall watchdog re-armed by every
    # stage marker (see _trace; disarmed once READY is out). faulthandler's
    # watchdog is a C thread that needs no GIL, so it fires even when the
    # main thread is stuck inside a DLL load holding the GIL — exactly the
    # F-038 state py-spy caught (create_module under numpy, CPU flat).
    faulthandler.enable(file=sys.stderr)
    global _watchdog_armed
    _watchdog_armed = True
    _trace(f"started (python {sys.version.split()[0]}, pid {os.getpid()})")
    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < 16:
        print(f"{TOKEN_ENV} must be set by the backend that starts this worker", file=sys.stderr)
        return 2

    _trace("loading the bridge module")
    bridge_module = _load_bridge_module()
    _trace("bridge module loaded")
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

    # F-038: the heavy import runs on a pristine main thread — no other
    # thread, no bound socket — matching the environment of every standalone
    # repro that succeeded on the round-2 box. The stdin watcher and the HTTP
    # server come strictly after it.
    _trace("importing WanGP (shared.api — torch, gradio, CUDA DLLs; the slow part)")
    worker.warm_up()
    _trace("WanGP import finished")
    warm_session = getattr(bridge, "warm_session", None)
    if callable(warm_session) and worker.status().get("available"):
        # Pull wgp.py (heavier still) in now too, so the first render does
        # not pay for it inside its job thread (round-2 F-038 note (a)).
        _trace("constructing the WanGP session (wgp.py)")
        session_error = str(warm_session() or "")
        _trace("WanGP session ready" if not session_error else f"WanGP session failed (renders will report it): {session_error}")

    server = _WorkerHTTPServer(("127.0.0.1", args.port), _make_handler(worker, token))
    port = int(server.server_address[1])
    _trace(f"http server bound on 127.0.0.1:{port}")
    if args.ready_file:
        _write_ready_file(args.ready_file, port)
        _trace(f"ready file written: {args.ready_file}")
    print(f"{READY_PREFIX} {port}", flush=True)
    _watchdog_armed = False
    faulthandler.cancel_dump_traceback_later()
    # Armed only now: a blocking read on the launcher's pipe never sits under
    # the import, and a backend that died during startup is still honoured —
    # the read returns EOF immediately and the worker leaves.
    threading.Thread(target=_exit_when_stdin_closes, name="wangp-parent-watch", daemon=True).start()
    _trace("orphan guard armed — serving")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
