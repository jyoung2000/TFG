"""WanGP in its own environment: the real worker script, spawned as a real
process and driven over real loopback HTTP, against a fake WanGP checkout
(a tiny `shared/api.py`). No mocks — the process boundary is the thing
under test: manifests cross it intact, WanGP's own import errors come back
through it, cancel works across it, and the worker dies with its parent."""

from __future__ import annotations

import json
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
        startup_timeout_s=30,
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
