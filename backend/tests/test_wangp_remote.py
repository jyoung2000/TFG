"""Remote WanGP (phase 9): the container-side routes and the desktop-side
bridge, exercised end to end through the real FastAPI app — the bridge's
HTTP client is an adapter over the test client, so both halves run for real."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PIL import Image

from services.http_client import HttpResponseLike
from services.wangp_remote_bridge import RemoteWanGPBridge, referenced_files


class _Response:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def status_code(self) -> int:
        return int(self._raw.status_code)

    @property
    def text(self) -> str:
        return str(self._raw.text)

    @property
    def headers(self) -> dict[str, str]:
        return dict(self._raw.headers)

    @property
    def content(self) -> bytes:
        return bytes(self._raw.content)

    def json(self) -> object:
        try:
            return self._raw.json()
        except ValueError:
            return {}


class TestClientHTTP:
    """`HTTPClient` over the Starlette test client: URLs keep their path only."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.calls: list[tuple[str, str]] = []

    def _path(self, url: str) -> str:
        return url.split("://", 1)[1].split("/", 1)[1] if "://" in url else url

    def post(self, url: str, headers: dict[str, str] | None = None, json_payload: Any = None, data: Any = None, timeout: int = 30) -> HttpResponseLike:
        self.calls.append(("post", url))
        return _Response(self._client.post("/" + self._path(url), json=json_payload, headers=headers or {}))

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> HttpResponseLike:
        self.calls.append(("get", url))
        return _Response(self._client.get("/" + self._path(url), headers=headers or {}))

    def put(self, url: str, data: Any = None, headers: dict[str, str] | None = None, timeout: int = 300) -> HttpResponseLike:
        self.calls.append(("put", url))
        return _Response(self._client.put("/" + self._path(url), content=data, headers=headers or {}))


def _bridge(client, tmp_path: Path) -> tuple[RemoteWanGPBridge, TestClientHTTP]:
    http = TestClientHTTP(client)
    local_outputs = tmp_path / "desktop-outputs"
    bridge = RemoteWanGPBridge(http=http, base_url="http://container:8000", token="", output_dir=local_outputs, video_model_type="ltx2_22B_distilled", image_model_type="z_image", camera_motion_prompts={}, poll_seconds=0)
    return bridge, http


class TestServerRoutes:
    def test_status_and_definitions_follow_the_local_bridge(self, client, fake_services):
        assert client.get("/api/wangp/status").json()["available"] is False
        fake_services.wangp_bridge.available = True
        status = client.get("/api/wangp/status").json()
        assert status["available"] is True and status["busy"] is False
        assert client.get("/api/wangp/definitions").json()["definitions"][0]["id"] == "ltx2_22B_distilled"

    def test_manifest_inputs_must_be_uploaded_files(self, client, fake_services, tmp_path: Path):
        fake_services.wangp_bridge.available = True
        secret = tmp_path / "secret.png"
        secret.write_bytes(b"x")
        r = client.post("/api/wangp/manifest", json={"manifest": [{"id": 1, "params": {"prompt": "p", "image_start": str(secret)}}], "media_suffixes": [".mp4"]})
        assert r.status_code == 400 and "not an uploaded file" in r.json()["error"]
        assert client.post("/api/wangp/manifest", json={"manifest": [], "media_suffixes": []}).status_code == 400

    def test_unavailable_bridge_refuses_jobs(self, client):
        r = client.post("/api/wangp/manifest", json={"manifest": [{"id": 1, "params": {"prompt": "p"}}], "media_suffixes": [".mp4"]})
        assert r.status_code == 503

    def test_output_route_serves_only_outputs(self, client, test_state, tmp_path: Path):
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"x")
        assert client.get("/api/wangp/output", params={"path": str(outside)}).status_code == 404
        assert client.get("/api/wangp/output", params={"path": "relative.mp4"}).status_code == 400
        inside = test_state.config.outputs_dir / "render.mp4"
        inside.write_bytes(b"ok")
        assert client.get("/api/wangp/output", params={"path": str(inside)}).content == b"ok"


class TestRemoteBridge:
    def test_generate_video_round_trip_uploads_inputs_and_downloads_the_result(self, client, fake_services, tmp_path: Path):
        fake_services.wangp_bridge.available = True
        bridge, http = _bridge(client, tmp_path)
        assert bridge.get_status().available is True
        assert bridge.list_model_definitions()[0]["id"] == "ltx2_22B_distilled"
        start = tmp_path / "start.png"
        Image.new("RGB", (8, 8), "red").save(start)
        lora = tmp_path / "mara.safetensors"
        lora.write_bytes(b"lora")
        phases: list[str] = []
        output = bridge.generate_video(
            prompt="a walk", resolution_label="540p", aspect_ratio="16:9", duration_seconds=6, fps=24, steps=8, seed=1, camera_motion="none", negative_prompt="",
            image_path=str(start), audio_path=None, on_progress=lambda phase, *_: phases.append(phase), is_cancelled=lambda: False,
            loras=[(str(lora), 0.8)],
        )
        # The desktop has a local copy of the container's render.
        assert Path(output).is_file() and Path(output).parent == tmp_path / "desktop-outputs"
        assert Path(output).read_bytes().startswith(b"\x00\x00\x00\x18ftypmp42")
        # The container rendered from uploaded copies, never from desktop paths.
        manifest = fake_services.wangp_bridge.manifests[-1]
        params = manifest[0]["params"]
        assert isinstance(params, dict)
        uploads = fake_services.wangp_bridge._output_dir / "remote_inputs"  # noqa: SLF001 - test peeks at the fake's folder
        assert Path(str(params["image_start"])).parent == uploads and Path(str(params["image_start"])).name.endswith("start.png")
        assert [Path(p).name.endswith("mara.safetensors") for p in params["activated_loras"]] == [True]
        assert params["loras_multipliers"] == "0.8"
        assert "uploading_inputs" in phases and phases[-1] == "complete"
        posted = [url for method, url in http.calls if method == "post"]
        assert posted.count("http://container:8000/api/wangp/upload") == 2
        # And the container's own History recorded the remote job.
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 1}).json()["jobs"][0]
        assert job["provider"] == "wangp-remote" and job["status"] == "complete"

    def test_generate_images_round_trip(self, client, fake_services, tmp_path: Path):
        fake_services.wangp_bridge.available = True
        bridge, _ = _bridge(client, tmp_path)
        outputs = bridge.generate_images(prompt="p", width=512, height=512, num_steps=8, num_images=1, seed=3, on_progress=lambda *a: None, is_cancelled=lambda: False)
        assert len(outputs) == 1 and Path(outputs[0]).suffix == ".png"
        with Image.open(outputs[0]) as image:
            assert image.size == (64, 64)

    def test_remote_failure_and_unreachable_status_are_reported(self, client, fake_services, tmp_path: Path):
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.fail_with = "CUDA out of memory"
        bridge, _ = _bridge(client, tmp_path)
        try:
            bridge.generate_images(prompt="p", width=512, height=512, num_steps=8, num_images=1, seed=3, on_progress=lambda *a: None, is_cancelled=lambda: False)
        except RuntimeError as exc:
            assert "CUDA out of memory" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected the remote failure to surface")
        fake_services.wangp_bridge.available = False
        fake_services.wangp_bridge.reason = "Missing wgp.py"
        status = bridge.get_status()
        assert status.available is False and "Missing wgp.py" in status.reason

    def test_missing_input_file_fails_before_submitting(self, client, fake_services, tmp_path: Path):
        fake_services.wangp_bridge.available = True
        bridge, http = _bridge(client, tmp_path)
        try:
            bridge.generate_video(prompt="p", resolution_label="540p", aspect_ratio="16:9", duration_seconds=6, fps=24, steps=8, seed=1, camera_motion="none", negative_prompt="", image_path=str(tmp_path / "missing.png"), audio_path=None, on_progress=lambda *a: None, is_cancelled=lambda: False)
        except RuntimeError as exc:
            assert "not found" in str(exc)
        assert not any(url.endswith("/api/wangp/manifest") for _m, url in http.calls)

    def test_referenced_files_lists_every_path_key(self):
        manifest = [{"params": {"image_start": "/a.png", "image_refs": ["/b.png", "/c.png"], "activated_loras": ["/l.safetensors"], "prompt": "x"}}]
        assert referenced_files(manifest) == ["/a.png", "/b.png", "/c.png", "/l.safetensors"]
        assert base64.b64decode(base64.b64encode(b"x")) == b"x"
