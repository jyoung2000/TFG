"""WanGP in its own environment: the real worker script, spawned as a real
process and driven over real loopback HTTP, against a fake WanGP checkout
(a tiny `shared/api.py`). No mocks — the process boundary is the thing
under test: manifests cross it intact, WanGP's own import errors come back
through it, cancel works across it, and the worker dies with its parent."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from services.wangp_worker_bridge import (
    LoopbackHTTPClient,
    SubprocessWorkerLauncher,
    WanGPWorkerError,
    WorkerWanGPBridge,
    select_wangp_mode,
    separate_interpreter,
)

_FAKE_API = '''
import json, os, queue, threading, time
from pathlib import Path
from types import SimpleNamespace

# Simulate WanGP's slow first import: torch + gradio + CUDA DLLs take ~1 min and
# hold the GIL. FAKE_WANGP_IMPORT_DELAY makes that cost controllable in tests.
time.sleep(float(os.environ.get("FAKE_WANGP_IMPORT_DELAY", "0")))


class _Events:
    def __init__(self):
        self._q = queue.Queue()

    def put(self, event):
        self._q.put(event)

    def get(self, timeout=None):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None


class _Job:
    def __init__(self, manifest, output_dir, delay):
        self.events = _Events()
        self.done = False
        self._cancel = False
        self._result = None
        threading.Thread(target=self._run, args=(manifest, output_dir, delay), daemon=True).start()

    def _run(self, manifest, output_dir, delay):
        self.events.put(SimpleNamespace(kind="progress", data=SimpleNamespace(phase="inference", progress=40, current_step=1, total_steps=2, status="")))
        deadline = time.time() + delay
        while time.time() < deadline:
            if self._cancel:
                self._result = SimpleNamespace(success=False, generated_files=[])
                self.done = True
                return
            time.sleep(0.02)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "last_manifest.json").write_text(json.dumps(manifest))
        out = out_dir / f"fake-{int(time.time() * 1000)}.mp4"
        out.write_bytes(b"fake-wangp-video")
        self._result = SimpleNamespace(success=True, generated_files=[str(out)])
        self.done = True

    def cancel(self):
        self._cancel = True

    def result(self):
        return self._result


class WanGPSession:
    def __init__(self, root, config_path, output_dir, cli_args):
        self._out = output_dir
        self._delay = float(os.environ.get("FAKE_WANGP_DELAY", "0.1"))

    def submit_manifest(self, manifest):
        return _Job(manifest, self._out, self._delay)
'''


def _checkout(tmp_path: Path, *, api: str = _FAKE_API) -> Path:
    root = tmp_path / "Wan2GP"
    (root / "shared").mkdir(parents=True)
    (root / "defaults").mkdir()
    (root / "ckpts").mkdir()
    (root / "wgp.py").write_text("# fake\n")
    (root / "shared" / "__init__.py").write_text("")
    (root / "shared" / "api.py").write_text(api)
    (root / "defaults" / "ltx2_22B_distilled.json").write_text(
        json.dumps({"model": {"name": "LTX-2 distilled", "architecture": "ltx2_22B", "URLs": ["https://example.invalid/ltx2_distilled_int8.safetensors"]}})
    )
    return root


def _bridge(tmp_path: Path, root: Path, *, delay: float = 0.1) -> tuple[WorkerWanGPBridge, SubprocessWorkerLauncher]:
    launcher = SubprocessWorkerLauncher(
        python=sys.executable,
        root=root,
        output_dir=tmp_path / "outputs",
        config_dir=tmp_path / "cfg",
        video_model_type="ltx2_22B_distilled",
        image_model_type="z_image",
        extra_env={"FAKE_WANGP_DELAY": str(delay)},
        silence_timeout_s=30,
    )
    bridge = WorkerWanGPBridge(
        launcher=launcher,
        root=root,
        python_executable=sys.executable,
        config_dir=tmp_path / "cfg",
        output_dir=tmp_path / "outputs",
        video_model_type="ltx2_22B_distilled",
        image_model_type="z_image",
        camera_motion_prompts={},
        poll_seconds=0.05,
    )
    return bridge, launcher


def _render(bridge: WorkerWanGPBridge, **overrides: object) -> str:
    phases: list[str] = []
    kwargs: dict[str, object] = {
        "prompt": "a rain-soaked neon alley",
        "resolution_label": "540p",
        "aspect_ratio": "16:9",
        "duration_seconds": 2,
        "fps": 24,
        "steps": 8,
        "seed": 1234,
        "camera_motion": "none",
        "negative_prompt": "",
        "image_path": None,
        "audio_path": None,
        "on_progress": lambda phase, *_: phases.append(phase),
        "is_cancelled": lambda: False,
        **overrides,
    }
    return bridge.generate_video(**kwargs)  # type: ignore[arg-type]


def _wait_status(bridge: WorkerWanGPBridge, *, loading_done: bool = True, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        endpoint = bridge.launcher.endpoint()
        assert endpoint is not None
        body = LoopbackHTTPClient().get(f"{endpoint.base_url}/api/wangp/status", headers={"Authorization": f"Bearer {endpoint.token}"}).json()
        assert isinstance(body, dict)
        if not loading_done or not body.get("loading"):
            return
        time.sleep(0.05)
    raise AssertionError("worker never finished loading")


class TestModeSelection:
    def test_separate_env_selects_the_worker_and_shared_env_stays_in_process(self, tmp_path: Path):
        root = tmp_path / "Wan2GP"
        venv_python = str(tmp_path / "Wan2GP" / ".venv" / "bin" / "python")
        assert select_wangp_mode(remote_url="", enabled=True, root=root, python=venv_python, current="/app/.venv/bin/python") == "worker"
        # Packaged app / container: one environment, WanGP imported in-process.
        assert select_wangp_mode(remote_url="", enabled=True, root=root, python="/app/.venv/bin/python", current="/app/.venv/bin/python") == "in_process"
        assert select_wangp_mode(remote_url="", enabled=False, root=root, python=venv_python, current="/x/python") == "in_process"
        assert select_wangp_mode(remote_url="http://gpu-box:8000", enabled=True, root=root, python=venv_python, current="/x") == "remote"

    def test_venvs_sharing_a_base_python_still_count_as_separate(self, tmp_path: Path):
        base = tmp_path / "python3.12"
        base.write_text("")
        a, b = tmp_path / "a" / "python", tmp_path / "b" / "python"
        for link in (a, b):
            link.parent.mkdir()
            link.symlink_to(base)
        assert separate_interpreter(str(a), str(b)) is True
        assert separate_interpreter(str(a), str(a)) is False


class TestWorkerProcess:
    def test_render_crosses_the_process_boundary_with_the_manifest_intact(self, tmp_path: Path):
        root = _checkout(tmp_path)
        bridge, launcher = _bridge(tmp_path, root)
        try:
            # Status and model discovery need no process: they read the checkout.
            assert bridge.get_status().available is True
            assert [d["id"] for d in bridge.list_model_definitions()] == ["ltx2_22B_distilled"]
            assert bridge.weights_installed("ltx2_22B_distilled") is False
            assert launcher.endpoint() is None

            output = _render(bridge)
            assert Path(output).read_bytes() == b"fake-wangp-video"
            assert Path(output).parent == tmp_path / "outputs"  # read in place, not downloaded
            manifest = json.loads((tmp_path / "outputs" / "last_manifest.json").read_text())
            params = manifest[0]["params"]
            assert params["model_type"] == "ltx2_22B_distilled" and params["prompt"] == "a rain-soaked neon alley"
            assert params["seed"] == 1234 and params["resolution"] == "960x544"
            # A second render reuses the same process.
            pid = launcher.process.pid if launcher.process else None
            _render(bridge, prompt="second")
            assert launcher.process is not None and launcher.process.pid == pid
        finally:
            launcher.stop()

    def test_wangp_import_errors_in_its_own_env_come_back_verbatim(self, tmp_path: Path):
        root = _checkout(tmp_path, api="raise ModuleNotFoundError(\"No module named 'gradio'\")\n")
        bridge, launcher = _bridge(tmp_path, root)
        try:
            launcher.ensure_started()
            _wait_status(bridge)
            status = bridge.get_status()
            assert status.available is False
            assert status.reason is not None and "gradio" in status.reason and sys.executable in status.reason
            with pytest.raises(RuntimeError, match="gradio"):
                _render(bridge)
        finally:
            launcher.stop()

    def test_cancel_reaches_the_worker(self, tmp_path: Path):
        root = _checkout(tmp_path)
        bridge, launcher = _bridge(tmp_path, root, delay=30)
        started = time.time()
        calls = {"n": 0}

        def is_cancelled() -> bool:
            calls["n"] += 1
            return calls["n"] > 3

        try:
            with pytest.raises(RuntimeError, match="cancelled"):
                _render(bridge, is_cancelled=is_cancelled)
            assert time.time() - started < 15
            assert not (tmp_path / "outputs" / "last_manifest.json").exists()
        finally:
            launcher.stop()

    def test_every_request_needs_the_token(self, tmp_path: Path):
        root = _checkout(tmp_path)
        _, launcher = _bridge(tmp_path, root)
        try:
            endpoint = launcher.ensure_started()
            client = LoopbackHTTPClient()
            assert client.get(f"{endpoint.base_url}/api/wangp/status").status_code == 401
            assert client.get(f"{endpoint.base_url}/api/wangp/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert client.post(f"{endpoint.base_url}/api/wangp/manifest", json_payload={"manifest": []}).status_code == 401
            ok = client.get(f"{endpoint.base_url}/api/wangp/status", headers={"Authorization": f"Bearer {endpoint.token}"})
            assert ok.status_code == 200
        finally:
            launcher.stop()

    def test_worker_exits_when_the_parent_pipe_closes(self, tmp_path: Path):
        root = _checkout(tmp_path)
        _, launcher = _bridge(tmp_path, root)
        launcher.ensure_started()
        proc = launcher.process
        assert proc is not None and proc.stdin is not None
        proc.stdin.close()  # what the OS does when the backend dies
        assert proc.wait(timeout=10) == 0

    def test_a_dead_worker_is_restarted_on_the_next_render(self, tmp_path: Path):
        root = _checkout(tmp_path)
        bridge, launcher = _bridge(tmp_path, root)
        try:
            _render(bridge)
            first = launcher.process
            assert first is not None
            first.kill()
            first.wait(timeout=10)
            assert launcher.endpoint() is None
            _render(bridge, prompt="after a crash")
            assert launcher.process is not None and launcher.process.pid != first.pid
        finally:
            launcher.stop()

    def test_missing_environment_is_actionable(self, tmp_path: Path):
        root = _checkout(tmp_path)
        launcher = SubprocessWorkerLauncher(
            python=str(tmp_path / "nope" / "python"),
            root=root,
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
        )
        with pytest.raises(WanGPWorkerError, match="ensure-wangp-venv"):
            launcher.ensure_started()
        bridge = WorkerWanGPBridge(
            launcher=launcher,
            root=root,
            python_executable=str(tmp_path / "nope" / "python"),
            config_dir=tmp_path / "cfg",
            output_dir=tmp_path / "outputs",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            camera_motion_prompts={},
        )
        status = bridge.get_status()
        assert status.available is False and status.reason is not None and "ensure-wangp-venv" in status.reason

class TestExtraArgForwarding:
    """F-035: the launcher's argument construction must survive argparse.

    `WANGP_EXTRA_ARGS` carries WanGP's *own* options — `_resolve_wangp_extra_args`
    appends ("--attention", "sdpa") for the embedded interpreter — and argparse
    refuses to consume a token that starts with "-" as a value. Passing them as
    separate tokens made the worker fail to start with
    "argument --extra-arg: expected one argument", so no render ever ran.
    """

    def test_option_like_extra_args_reach_the_worker_and_it_starts(self, tmp_path: Path):
        root = _checkout(tmp_path)
        launcher = SubprocessWorkerLauncher(
            python=sys.executable,
            root=root,
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            # Exactly what _resolve_wangp_extra_args() produces on this machine.
            extra_args=("--attention", "sdpa"),
            extra_env={"FAKE_WANGP_DELAY": "0.1"},
            silence_timeout_s=30,
        )
        bridge = WorkerWanGPBridge(
            launcher=launcher,
            root=root,
            python_executable=sys.executable,
            config_dir=tmp_path / "cfg",
            output_dir=tmp_path / "outputs",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            camera_motion_prompts={},
            poll_seconds=0.05,
        )
        try:
            endpoint = launcher.ensure_started()  # red before the fix: WanGPWorkerError
            assert endpoint.token and endpoint.base_url.startswith("http://127.0.0.1:")
            # The options arrive intact, as options.
            assert launcher._args.count("--extra-arg=--attention") == 1
            assert "--extra-arg=sdpa" in launcher._args
            assert not any(a == "--extra-arg" for a in launcher._args)
            _wait_status(bridge)
            output = _render(bridge)
            assert Path(output).read_bytes() == b"fake-wangp-video"
        finally:
            launcher.stop()

class TestWorkerReadiness:
    """F-036: READY must mean "can serve", not "process launched".

    WanGP's first import costs ~1 minute on this card and loads torch's CUDA
    DLLs. The worker used to kick that off in a background thread and print
    TFG_WANGP_WORKER_READY immediately, so the launcher reported a started
    worker whose HTTP server could not answer for the whole import: every
    request timed out (including a plain GET /status) and the first render
    failed with "WanGP worker: timed out on /api/wangp/manifest".

    FAKE_WANGP_IMPORT_DELAY stands in for that import cost.
    """

    def test_ready_is_announced_only_after_the_import_finishes(self, tmp_path: Path):
        root = _checkout(tmp_path)
        launcher = SubprocessWorkerLauncher(
            python=sys.executable,
            root=root,
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            extra_env={"FAKE_WANGP_DELAY": "0.1", "FAKE_WANGP_IMPORT_DELAY": "6"},
            silence_timeout_s=30,
        )
        try:
            t0 = time.time()
            endpoint = launcher.ensure_started()
            announced_after = time.time() - t0
            # RED before the fix: READY arrives in ~0.1s, before the import.
            assert announced_after >= 5, f"announced ready after only {announced_after:.1f}s, import still running"
            # ...and it really can serve, not just claim to.
            body = LoopbackHTTPClient().get(
                f"{endpoint.base_url}/api/wangp/status",
                headers={"Authorization": f"Bearer {endpoint.token}"},
                timeout=10,
            ).json()
            assert isinstance(body, dict) and body["loading"] is False
        finally:
            launcher.stop()

class TestLauncherDeadlineIsLivenessBased:
    """F-037, round 3: the startup deadline is liveness, not a wall clock.

    This replaces round 2's constant assertion (default >= 300s), which its
    own debug report marked "applied, INEFFECTIVE — not a fix": a fixed total
    kills a worker that is alive and would have announced itself (60s raced a
    55.8s cold import; 375s was observed once), and no constant is safe on a
    slower disk. Behavioural red on the pre-fix launcher, recorded in the
    round-3 debug report: a worker printing a line every 0.4s was killed at
    1.7s by `startup_timeout_s=1.5` ("still running — killed; startup
    deadline 2s").
    """

    def _launcher(self, tmp_path: Path, script: Path, silence: float) -> SubprocessWorkerLauncher:
        return SubprocessWorkerLauncher(
            python=sys.executable,
            root=_checkout(tmp_path),
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            silence_timeout_s=silence,
            script=script,
        )

    def test_a_worker_that_keeps_talking_is_waited_for_past_the_silence_window(self, tmp_path: Path):
        chatty = tmp_path / "chatty.py"
        chatty.write_text(
            "import json, os, sys, time\n"
            "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
            "for i in range(12):\n"
            "    print(f'still importing, tick {i}', file=sys.stderr, flush=True)\n"
            "    time.sleep(0.4)\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        body = json.dumps({'available': True, 'reason': '', 'loading': False, 'busy': False, 'active_job': ''}).encode()\n"
            "        self.send_response(200)\n"
            "        self.send_header('Content-Length', str(len(body)))\n"
            "        self.end_headers()\n"
            "        self.wfile.write(body)\n"
            "    def log_message(self, *a):\n"
            "        pass\n"
            "srv = ThreadingHTTPServer(('127.0.0.1', 0), H)\n"
            "print(f'TFG_WANGP_WORKER_READY {srv.server_address[1]}', flush=True)\n"
            "srv.serve_forever()\n"
        )
        launcher = self._launcher(tmp_path, chatty, silence=1.5)
        try:
            # 12 ticks x 0.4s = ~5s of startup, every gap far below 1.5s of
            # silence: a liveness deadline waits; the old fixed 1.5s killed it.
            endpoint = launcher.ensure_started()
            assert endpoint.base_url.startswith("http://127.0.0.1:")
        finally:
            launcher.stop()

    def test_a_silent_but_running_worker_is_declared_dead_at_the_silence_window(self, tmp_path: Path):
        mute = tmp_path / "mute.py"
        mute.write_text(
            "import sys, time\n"
            "print('one line, then nothing', file=sys.stderr, flush=True)\n"
            "time.sleep(120)\n"
        )
        launcher = self._launcher(tmp_path, mute, silence=1.5)
        t0 = time.time()
        with pytest.raises(WanGPWorkerError) as excinfo:
            launcher.ensure_started()
        assert time.time() - t0 < 10, "a silent worker must not be waited on for a wall-clock eternity"
        message = str(excinfo.value)
        assert "no output for" in message and "still running — killed" in message, message
        assert "one line, then nothing" in message, message


class TestLauncherFailureDetail:
    """Round 3, task 1a: a worker that fails to start must never fail silently.

    Four round-2 attempts could not localise F-038 because the only signal was
    "The WanGP worker did not start (no output)" — no exit code, no timeout, no
    tail. The launcher error must carry all three.
    """

    def test_error_names_exit_code_deadline_and_output_tail(self, tmp_path: Path):
        crasher = tmp_path / "crasher.py"
        crasher.write_text(
            "import sys\n"
            "print('stage: loading doom', file=sys.stderr, flush=True)\n"
            "print('boom: cannot find the flux capacitor', file=sys.stderr, flush=True)\n"
            "sys.exit(7)\n"
        )
        launcher = SubprocessWorkerLauncher(
            python=sys.executable,
            root=_checkout(tmp_path),
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            silence_timeout_s=15,
            script=crasher,
        )
        with pytest.raises(WanGPWorkerError) as excinfo:
            launcher.ensure_started()
        message = str(excinfo.value)
        assert "exit code 7" in message, message
        assert "flux capacitor" in message, message
        assert "15" in message, message  # the deadline that governed


class TestStartupIsolation:
    """Round 3, F-038: the WanGP import must run on a pristine main thread.

    py-spy caught the round-2 wedge with the main thread inside a DLL load
    (create_module under numpy) while the worker had already bound an HTTP
    server (whose stdlib server_bind performs a reverse-DNS getfqdn) and
    started the stdin watcher — the two variables every succeeding
    standalone repro lacked. The import now happens before any thread or
    socket exists; the server binds afterwards, without getfqdn; and the
    orphan guard arms only after READY.
    """

    def test_worker_reaches_ready_even_when_reverse_dns_hangs(self, tmp_path: Path):
        """A hung socket.getfqdn (broken resolver, the classic http.server
        stall on Windows) must not sit between launch and READY."""
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "sitecustomize.py").write_text(
            "import socket, time\n"
            "def _hang(name=''):\n"
            "    time.sleep(300)\n"
            "    return name\n"
            "socket.getfqdn = _hang\n"
        )
        root = _checkout(tmp_path)
        launcher = SubprocessWorkerLauncher(
            python=sys.executable,
            root=root,
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            # The launcher strips PYTHONPATH, then applies extra_env — so this
            # re-injects sitecustomize into the real child interpreter.
            extra_env={"PYTHONPATH": str(site_dir), "FAKE_WANGP_DELAY": "0.1"},
            silence_timeout_s=20,
        )
        try:
            t0 = time.time()
            endpoint = launcher.ensure_started()
            assert time.time() - t0 < 15, "startup waited on a DNS lookup"
            body = LoopbackHTTPClient().get(
                f"{endpoint.base_url}/api/wangp/status",
                headers={"Authorization": f"Bearer {endpoint.token}"},
                timeout=10,
            ).json()
            assert isinstance(body, dict) and body["available"] is True
        finally:
            launcher.stop()

    def test_backend_death_during_startup_never_skips_ready(self, tmp_path: Path):
        """The orphan guard arms after READY: a worker whose parent pipe is
        already gone still finishes starting (so the failure mode is visible)
        and then exits by itself instead of lingering — it must never die
        silently *before* READY because the guard fired first."""
        root = _checkout(tmp_path)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
        env.update({"TFG_WANGP_WORKER_TOKEN": "x" * 32, "PYTHONUNBUFFERED": "1"})
        import subprocess

        proc = subprocess.Popen(
            [
                sys.executable, "-u", str(Path(__file__).resolve().parent.parent / "wangp_worker.py"),
                "--root", str(root),
                "--output-dir", str(tmp_path / "outputs"),
                "--config-dir", str(tmp_path / "cfg"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(root),
            env=env,
            text=True,
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.close()  # the backend is already gone
        out = proc.stdout.read()  # EOF when the worker exits by itself
        assert proc.wait(timeout=60) == 0
        assert "TFG_WANGP_WORKER_READY" in out, out


class TestReadinessProbe:
    """Round 3, F-038: readiness must not hang on the stdout pipe alone.

    The launcher accepts the ready-file the worker writes next to its config
    dir and confirms with a real authorized GET /api/wangp/status before
    declaring the worker started — a worker that serves but whose READY line
    never crosses the pipe still counts as up.
    """

    def test_launcher_accepts_ready_file_plus_live_status_without_the_ready_line(self, tmp_path: Path):
        silent_server = tmp_path / "silent_server.py"
        silent_server.write_text(
            "import json, os, sys\n"
            "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        body = json.dumps({'available': True, 'reason': '', 'loading': False, 'busy': False, 'active_job': ''}).encode()\n"
            "        self.send_response(200)\n"
            "        self.send_header('Content-Type', 'application/json')\n"
            "        self.send_header('Content-Length', str(len(body)))\n"
            "        self.end_headers()\n"
            "        self.wfile.write(body)\n"
            "    def log_message(self, *a):\n"
            "        pass\n"
            "srv = ThreadingHTTPServer(('127.0.0.1', 0), H)\n"
            "args = sys.argv[1:]\n"
            "ready = args[args.index('--ready-file') + 1]\n"
            "tmp = ready + '.tmp'\n"
            "with open(tmp, 'w') as f:\n"
            "    json.dump({'port': srv.server_address[1], 'pid': os.getpid()}, f)\n"
            "os.replace(tmp, ready)\n"
            "srv.serve_forever()\n"
        )
        launcher = SubprocessWorkerLauncher(
            python=sys.executable,
            root=_checkout(tmp_path),
            output_dir=tmp_path / "outputs",
            config_dir=tmp_path / "cfg",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            silence_timeout_s=20,
            script=silent_server,
        )
        try:
            endpoint = launcher.ensure_started()
            body = LoopbackHTTPClient().get(
                f"{endpoint.base_url}/api/wangp/status",
                headers={"Authorization": f"Bearer {endpoint.token}"},
                timeout=10,
            ).json()
            assert isinstance(body, dict) and body["available"] is True
        finally:
            launcher.stop()


class _SteppingBridge:
    """Emits one step-level progress event, then holds the job until released."""

    def __init__(self) -> None:
        import threading as _threading

        self.release = _threading.Event()
        self.reported = _threading.Event()

    def run_manifest(self, *, manifest, media_suffixes, on_progress, is_cancelled):  # noqa: ARG002
        on_progress("inference_stage_1", 40, 3, 8)
        self.reported.set()
        self.release.wait(5)
        return []


class TestWorkerStepProgress:
    def test_job_payload_carries_wangps_step_counts(self):
        """F-054 (round 4): the worker dropped current/total steps, so the app's
        progress bar fell back to a 45 s guess and froze at 95%."""
        import wangp_worker

        bridge = _SteppingBridge()
        worker = wangp_worker.Worker(bridge)
        code, job = worker.submit([{"params": {"prompt": "p"}}], [".mp4"])
        assert code == 200
        assert bridge.reported.wait(5)
        try:
            _, payload = worker.get(str(job["id"]))
            assert payload["phase"] == "inference_stage_1"
            assert (payload["current_step"], payload["total_steps"]) == (3, 8)
        finally:
            bridge.release.set()


class TestStatusNeverWaitsForAWorkerStart:
    """B1: the installed app "starts, then stops answering".

    `SubprocessWorkerLauncher.ensure_started` holds the launcher lock for the
    whole worker start - WanGP's import alone is 26-56 s on the RTX 4070 - and
    `endpoint()` took the same lock, so `get_status()` (and with it `/health`)
    blocked until the import finished. MEASURED in the installed app's session
    log: "Server running" at 21:05:57.768, first health answer at 21:06:23.631,
    the instant the worker announced "WanGP import finished". The same stall
    recurs whenever a crashed worker is restarted.
    """

    def test_status_answers_while_a_start_holds_the_lock(self, tmp_path: Path):
        import threading

        root = _checkout(tmp_path)
        bridge, launcher = _bridge(tmp_path, root)
        answered = threading.Event()
        with launcher._lock:  # noqa: SLF001 - stands in for a slow ensure_started()
            worker = threading.Thread(target=lambda: (bridge.get_status(), answered.set()), daemon=True)
            worker.start()
            assert answered.wait(2.0), "get_status() waited for the worker start to finish"
        assert launcher.endpoint() is None
