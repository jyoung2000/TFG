"""WanGP in its own environment, driven from the backend over loopback HTTP.

`WorkerWanGPBridge` is used when WanGP has a dedicated interpreter
(`Wan2GP/.venv`, or `WANGP_PYTHON`) that differs from the backend's. It
starts `backend/wangp_worker.py` under that interpreter and speaks the same
`/api/wangp/*` protocol as `RemoteWanGPBridge` — so every setting the local
bridge builds (resolutions, LoRAs, guide videos) is unchanged — with two
differences that follow from sharing a filesystem: inputs are passed by path
instead of uploaded, and outputs are read in place instead of downloaded.

Model discovery (`defaults/*.json` + `ckpts/`) is plain file reading, so it
runs here without starting the worker; only a render needs the process.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal, Protocol, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

from services.http_client.http_client import HttpTimeoutError
from services.services_utils import JSONValue, RequestData
from services.wangp_bridge import CancelledCallback, ProgressCallback, WanGPBridge, WanGPBridgeStatus
from services.wangp_remote_bridge import RemoteWanGPBridge, RemoteWanGPError

logger = logging.getLogger(__name__)

WORKER_SCRIPT = Path(__file__).resolve().parent.parent / "wangp_worker.py"
READY_PREFIX = "TFG_WANGP_WORKER_READY"
TOKEN_ENV = "TFG_WANGP_WORKER_TOKEN"
#: Variables that would point the WanGP interpreter at the backend's packages.
_ISOLATION_STRIP = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__")

WanGPMode = Literal["remote", "worker", "in_process"]


def separate_interpreter(python: str | None, current: str | None = None) -> bool:
    """True when `python` is a different interpreter from the running one.

    Compared by absolute path WITHOUT resolving symlinks: two venvs built from
    the same base Python both symlink to it, and must still count as separate
    environments (they have separate site-packages)."""
    if not python:
        return False
    here = current if current is not None else sys.executable
    return os.path.normcase(os.path.abspath(python)) != os.path.normcase(os.path.abspath(here))


def select_wangp_mode(*, remote_url: str, enabled: bool, root: Path | None, python: str | None, current: str | None = None) -> WanGPMode:
    """How the backend reaches WanGP. A remote URL wins; otherwise a dedicated
    WanGP interpreter means the isolated worker; otherwise (packaged app,
    container: one shared environment) WanGP is imported in-process."""
    if remote_url:
        return "remote"
    if enabled and root is not None and separate_interpreter(python, current):
        return "worker"
    return "in_process"


# ---- loopback HTTP ------------------------------------------------------------------------


@dataclass(frozen=True)
class _LoopbackResponse:
    status_code: int
    content: bytes
    headers: Mapping[str, str]

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> object:
        return json.loads(self.text or "null")


class LoopbackHTTPClient:
    """`HTTPClient` for 127.0.0.1 only. Uses urllib with proxies disabled:
    an `HTTP(S)_PROXY` in the user's environment must never capture the
    backend↔worker traffic (it would fail, or worse, carry the token off-box)."""

    def __init__(self) -> None:
        self._opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))

    def _send(self, method: str, url: str, headers: dict[str, str] | None, body: bytes | None, timeout: int) -> _LoopbackResponse:
        req = urllib_request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self._opener.open(req, timeout=timeout) as response:
                return _LoopbackResponse(response.status, response.read(), dict(response.headers.items()))
        except urllib_error.HTTPError as exc:
            return _LoopbackResponse(exc.code, exc.read(), dict(exc.headers.items()) if exc.headers else {})
        except (TimeoutError, socket.timeout) as exc:
            raise HttpTimeoutError(str(exc)) from exc
        except urllib_error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise HttpTimeoutError(str(exc)) from exc
            raise ConnectionError(f"WanGP worker unreachable: {exc.reason}") from exc

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> _LoopbackResponse:
        return self._send("GET", url, headers, None, timeout)

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json_payload: Mapping[str, JSONValue] | None = None,
        data: RequestData = None,
        timeout: int = 30,
    ) -> _LoopbackResponse:
        if json_payload is not None:
            body = json.dumps(json_payload).encode("utf-8")
        elif isinstance(data, str):
            body = data.encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        else:
            body = b"{}"
        return self._send("POST", url, headers, body, timeout)

    def put(self, url: str, data: RequestData = None, headers: dict[str, str] | None = None, timeout: int = 300) -> _LoopbackResponse:
        body = data.encode("utf-8") if isinstance(data, str) else data if isinstance(data, bytes) else None
        return self._send("PUT", url, headers, body, timeout)


# ---- process lifecycle --------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerEndpoint:
    base_url: str
    token: str


class WanGPWorkerLauncher(Protocol):
    def ensure_started(self) -> WorkerEndpoint:
        """Start the worker if it is not running; block until it listens."""
        ...

    def endpoint(self) -> WorkerEndpoint | None:
        """The live endpoint, or None when no worker is running."""
        ...

    def stop(self) -> None: ...


class WanGPWorkerError(RuntimeError):
    """The worker could not be started; `str()` is user-facing."""


class SubprocessWorkerLauncher:
    """Runs `wangp_worker.py` under the WanGP interpreter.

    The worker's stdin is a pipe only we hold, so it exits by itself when this
    process ends for any reason. Its output is drained continuously (a full
    pipe would stall WanGP mid-render) into the log and a short tail kept for
    startup errors. A worker that died (e.g. a driver crash) is restarted on
    the next render."""

    def __init__(
        self,
        *,
        python: str,
        root: Path,
        output_dir: Path,
        config_dir: Path,
        video_model_type: str,
        image_model_type: str,
        extra_args: Sequence[str] = (),
        extra_env: Mapping[str, str] | None = None,
        startup_timeout_s: float = 60.0,
        script: Path = WORKER_SCRIPT,
    ) -> None:
        self._python = python
        self._root = root
        self._script = script
        self._args = [
            "--root", str(root),
            "--output-dir", str(output_dir),
            "--config-dir", str(config_dir),
            "--video-model-type", video_model_type,
            "--image-model-type", image_model_type,
        ]
        for arg in extra_args:
            self._args += ["--extra-arg", arg]
        self._extra_env = dict(extra_env or {})
        self._timeout = startup_timeout_s
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._endpoint: WorkerEndpoint | None = None
        self._tail: deque[str] = deque(maxlen=30)

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._proc

    def endpoint(self) -> WorkerEndpoint | None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self._endpoint
            return None

    def ensure_started(self) -> WorkerEndpoint:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._endpoint is not None:
                return self._endpoint
            return self._start_locked()

    def _start_locked(self) -> WorkerEndpoint:
        if not Path(self._python).exists():
            raise WanGPWorkerError(f"The WanGP environment's Python was not found at {self._python}. Run scripts/ensure-wangp-venv.ps1 (Windows) or .sh.")
        token = secrets.token_urlsafe(32)
        env = {k: v for k, v in os.environ.items() if k not in _ISOLATION_STRIP}
        env.update({TOKEN_ENV: token, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        env.update(self._extra_env)
        creationflags = cast(int, getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._tail.clear()
        proc = subprocess.Popen(
            [self._python, "-u", str(self._script), *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(self._root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        ready = threading.Event()
        port: list[int] = []

        def drain(stream: IO[str]) -> None:
            for line in stream:
                text = line.rstrip()
                if not port and text.startswith(READY_PREFIX):
                    try:
                        port.append(int(text.split()[1]))
                    except (IndexError, ValueError):
                        pass
                    ready.set()
                    continue
                if text:
                    self._tail.append(text)
                    logger.info("[wangp] %s", text)
            ready.set()  # EOF: the process ended

        assert proc.stdout is not None
        threading.Thread(target=drain, args=(proc.stdout,), name="wangp-worker-output", daemon=True).start()
        if not ready.wait(self._timeout) or not port:
            proc.kill()
            proc.wait(timeout=5)
            detail = " | ".join(list(self._tail)[-6:]) or "no output"
            raise WanGPWorkerError(f"The WanGP worker did not start ({detail})")
        self._proc = proc
        self._endpoint = WorkerEndpoint(base_url=f"http://127.0.0.1:{port[0]}", token=token)
        logger.info("WanGP worker started (pid %s) at %s", proc.pid, self._endpoint.base_url)
        return self._endpoint

    def stop(self) -> None:
        with self._lock:
            proc, self._proc, self._endpoint = self._proc, None, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # the worker exits on EOF
            proc.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait(timeout=5)


# ---- the bridge ---------------------------------------------------------------------------


class WorkerWanGPBridge(RemoteWanGPBridge):
    def __init__(
        self,
        *,
        launcher: WanGPWorkerLauncher,
        root: Path,
        python_executable: str,
        config_dir: Path,
        output_dir: Path,
        video_model_type: str,
        image_model_type: str,
        camera_motion_prompts: dict[str, str],
        http: LoopbackHTTPClient | None = None,
        poll_seconds: float = 0.5,
    ) -> None:
        super().__init__(
            http=http or LoopbackHTTPClient(),
            base_url="",
            token="",
            output_dir=output_dir,
            video_model_type=video_model_type,
            image_model_type=image_model_type,
            camera_motion_prompts=camera_motion_prompts,
            poll_seconds=poll_seconds,
        )
        # Local checkout: model discovery reads it directly (see list_model_definitions).
        self._root = root
        self._python = python_executable
        self._config_dir = config_dir
        self._launcher = launcher

    @property
    def launcher(self) -> WanGPWorkerLauncher:
        return self._launcher

    def warm_up(self) -> None:
        """Start the worker in the background so its first (slow) WanGP import
        happens before the first render, and status reflects the real env."""

        def run() -> None:
            try:
                self._launcher.ensure_started()
            except Exception as exc:  # noqa: BLE001 - surfaced by get_status/renders
                logger.warning("WanGP worker warm-up failed: %s", exc)

        threading.Thread(target=run, name="wangp-worker-warm-up", daemon=True).start()

    def get_status(self) -> WanGPBridgeStatus:
        root = self._root
        if not (root / "wgp.py").exists():
            return WanGPBridgeStatus(available=False, root=root, python_executable=self._python, reason=f"Missing {root / 'wgp.py'}")
        if not (root / "shared" / "api.py").exists():
            return WanGPBridgeStatus(available=False, root=root, python_executable=self._python, reason=f"Missing {root / 'shared' / 'api.py'}")
        if not self._python or not Path(self._python).exists():
            return WanGPBridgeStatus(
                available=False,
                root=root,
                python_executable=self._python,
                reason=f"WanGP environment not found at {self._python}. Run scripts/ensure-wangp-venv.ps1 (Windows) or .sh.",
            )
        endpoint = self._launcher.endpoint()
        if endpoint is None:
            # Files are in place; the worker starts on first use (or warm-up).
            return WanGPBridgeStatus(available=True, root=root, python_executable=self._python)
        self._use(endpoint)
        try:
            payload = self._get_json("/api/wangp/status", timeout=5)
        except RemoteWanGPError as exc:
            return WanGPBridgeStatus(available=False, root=root, python_executable=self._python, reason=f"WanGP worker not responding: {exc}")
        if bool(payload.get("loading", False)):
            return WanGPBridgeStatus(available=True, root=root, python_executable=self._python)
        available = bool(payload.get("available", False))
        reason = str(payload.get("reason", "") or "")
        return WanGPBridgeStatus(
            available=available,
            root=root,
            python_executable=self._python,
            reason=None if available else (f"WanGP environment ({self._python}): {reason}" if reason else "WanGP worker reports unavailable"),
        )

    def list_model_definitions(self) -> list[dict[str, object]]:
        return WanGPBridge.list_model_definitions(self)

    def _use(self, endpoint: WorkerEndpoint) -> None:
        self._base_url = endpoint.base_url
        self._token = endpoint.token

    def _run_manifest(
        self,
        *,
        manifest: list[dict[str, object]],
        media_suffixes: set[str],
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> list[str]:
        on_progress("starting_wangp", 1, None, None)
        try:
            endpoint = self._launcher.ensure_started()
        except WanGPWorkerError as exc:
            raise RuntimeError(str(exc)) from exc
        self._use(endpoint)
        try:
            return super()._run_manifest(manifest=manifest, media_suffixes=media_suffixes, on_progress=on_progress, is_cancelled=is_cancelled)
        except RemoteWanGPError as exc:
            raise RuntimeError(f"WanGP worker: {exc}") from exc

    # Same machine, same filesystem: nothing to upload or download.
    def _upload_referenced_files(self, entry: dict[str, object]) -> dict[str, object]:
        return entry

    def _download(self, remote_path: str) -> str:
        return remote_path
