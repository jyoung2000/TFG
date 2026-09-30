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
import time
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
        # F-037, round 3: the startup deadline is LIVENESS-based, not a wall
        # clock. A fixed total (60s, then 300s) kept killing workers that were
        # alive and would have announced themselves — WanGP's cold import
        # measured 55.8s on the RTX 4070 and 375s was observed once under
        # round-2 conditions. The worker emits a stage marker per startup
        # stage and a faulthandler stack dump 120s after the last stage that
        # made progress; a worker producing output is waited for indefinitely,
        # and only one that has said NOTHING for this long is declared dead —
        # at which point the error carries the stage it died in and the dump.
        silence_timeout_s: float = 180.0,
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
            # `--extra-arg=<value>`, never `--extra-arg <value>`: the values are
            # WanGP's own options (e.g. "--attention", "sdpa"), and argparse
            # refuses to consume a token that starts with "-" as a value, so
            # the split form makes the worker fail to start with
            # "argument --extra-arg: expected one argument".
            self._args += [f"--extra-arg={arg}"]
        self._extra_env = dict(extra_env or {})
        self._config_dir = config_dir
        self._silence_timeout = silence_timeout_s
        self._last_output = time.monotonic()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._endpoint: WorkerEndpoint | None = None
        self._ready_file: Path | None = None
        self._tail: deque[str] = deque(maxlen=60)

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._proc

    def endpoint(self) -> WorkerEndpoint | None:
        # Deliberately lock-free: `ensure_started` holds the lock for the whole
        # start (WanGP's import is 26-56 s), and waiting on it here stalled
        # get_status() and with it /health for that long. Two reference reads
        # are atomic; mid-start this answers None ("starting").
        proc, endpoint = self._proc, self._endpoint
        if proc is not None and proc.poll() is None:
            return endpoint
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
        # The port is announced through two channels: the READY line on the
        # merged pipe AND a per-launch ready-file (fresh name every start, so
        # a stale file from a dead worker can never be read). Either one,
        # confirmed by an authorized status probe, counts as started.
        self._config_dir.mkdir(parents=True, exist_ok=True)
        for stale in self._config_dir.glob("worker-*.ready.json"):
            stale.unlink(missing_ok=True)
        ready_file = self._config_dir / f"worker-{secrets.token_hex(6)}.ready.json"
        self._ready_file = ready_file
        proc = subprocess.Popen(
            [self._python, "-u", str(self._script), *self._args, "--ready-file", str(ready_file)],
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
                self._last_output = time.monotonic()
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

        announced = self._await_announcement(proc, ready, port, ready_file)
        endpoint = WorkerEndpoint(base_url=f"http://127.0.0.1:{announced}", token=token)
        self._probe_until_serving(proc, endpoint)
        # Endpoint first: `endpoint()` reads these without the lock.
        self._endpoint = endpoint
        self._proc = proc
        logger.info("WanGP worker started (pid %s) at %s", proc.pid, endpoint.base_url)
        return endpoint

    def _await_announcement(self, proc: subprocess.Popen[str], ready: threading.Event, port: list[int], ready_file: Path) -> int:
        """The worker's port, from the READY line or the ready-file —
        whichever lands first. Readiness must not hinge on one specific line
        crossing the stdout pipe (F-038's silence made that channel suspect).

        The deadline is liveness, not a wall clock: a worker that keeps
        producing output (stage markers, import progress, stack dumps) is
        waited for; one that has said nothing for `silence_timeout_s` is
        dead or wedged — and by then the worker's own stall watchdog has
        already dumped every thread's stack into the tail we report."""
        self._last_output = time.monotonic()
        while True:
            if port:
                return port[0]
            if ready_file.is_file():
                try:
                    payload = json.loads(ready_file.read_text(encoding="utf-8"))
                    return int(payload["port"])
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # written concurrently; re-read on the next tick
            if proc.poll() is not None and ready.is_set():
                raise self._startup_failure(proc, deadline_note=f"silence deadline {self._silence_timeout:.0f}s")
            silence = time.monotonic() - self._last_output
            if silence >= self._silence_timeout:
                raise self._startup_failure(
                    proc,
                    deadline_note=f"no output for {silence:.0f}s (silence deadline {self._silence_timeout:.0f}s) — a live worker keeps talking",
                )
            ready.wait(0.15)

    def _probe_until_serving(self, proc: subprocess.Popen[str], endpoint: WorkerEndpoint) -> None:
        """An announced port is a claim; an authorized 200 from
        GET /api/wangp/status is the proof the worker actually serves."""
        client = LoopbackHTTPClient()
        deadline = time.monotonic() + 30
        headers = {"Authorization": f"Bearer {endpoint.token}"}
        while True:
            try:
                response = client.get(f"{endpoint.base_url}/api/wangp/status", headers=headers, timeout=5)
                if response.status_code == 200:
                    return
                if response.status_code == 401:
                    raise self._startup_failure(proc, deadline_note="the status probe was refused (401) — something else answers on that port, or the token did not reach the worker")
            except (ConnectionError, HttpTimeoutError):
                pass
            if proc.poll() is not None:
                raise self._startup_failure(proc, deadline_note="the worker exited between announcing its port and serving")
            if time.monotonic() >= deadline:
                raise self._startup_failure(proc, deadline_note="the announced port never answered the status probe (30s)")
            time.sleep(0.1)

    def _startup_failure(self, proc: subprocess.Popen[str], *, deadline_note: str) -> WanGPWorkerError:
        """Kill the worker and build an error that carries everything four
        round-2 localisation attempts lacked: how the child ended (exit code,
        or that we killed a still-running one), which deadline governed, and
        the tail of its output — where the worker's stage markers and
        faulthandler stack dumps land, so a stall names the exact stage."""
        exited_code = proc.poll()
        if exited_code is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # Give the drain thread a beat to flush the last lines into the tail.
        time.sleep(0.2)
        how = f"exit code {exited_code}" if exited_code is not None else "still running — killed"
        tail = list(self._tail)[-12:]
        detail = "\n  ".join(tail) if tail else "no output at all"
        return WanGPWorkerError(f"The WanGP worker did not start ({how}; {deadline_note}). Last output:\n  {detail}")

    def stop(self) -> None:
        with self._lock:
            proc, self._proc, self._endpoint = self._proc, None, None
            ready_file, self._ready_file = self._ready_file, None
        if ready_file is not None:
            ready_file.unlink(missing_ok=True)
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

    def held_vram_mb(self) -> int:
        # Never start the worker just to ask: no worker, nothing held.
        endpoint = self._launcher.endpoint()
        if endpoint is None:
            return 0
        self._use(endpoint)
        return super().held_vram_mb()

    def _transport_alive(self) -> bool:
        # A worker that exited will never answer: fail now, not after the
        # status-poll patience window.
        return self._launcher.endpoint() is not None

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
