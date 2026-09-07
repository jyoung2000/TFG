"""Integration-style tests for IC-LoRA endpoints."""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeCapture


class TestIcLoraListModels:
    def test_empty_directory(self, client):
        r = client.get("/api/ic-lora/list-models")
        assert r.status_code == 200
        assert r.json()["models"] == []

    def test_with_files(self, client, create_fake_ic_lora_files):
        create_fake_ic_lora_files(["canny_control", "depth_control"])
        r = client.get("/api/ic-lora/list-models")
        data = r.json()
        assert len(data["models"]) == 2
        names = [m["name"] for m in data["models"]]
        assert "canny_control" in names
        assert "depth_control" in names

    def test_ignores_non_safetensors(self, client, test_state):
        (test_state.config.ic_lora_dir / "notes.txt").write_text("hello")
        (test_state.config.ic_lora_dir / "model.safetensors").write_bytes(b"\x00" * 1024)

        r = client.get("/api/ic-lora/list-models")
        data = r.json()
        assert len(data["models"]) == 1
        assert data["models"][0]["name"] == "model"


class TestIcLoraDownload:
    def test_download_known_model(self, client):
        r = client.post("/api/ic-lora/download-model", json={"model": "canny"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "complete"
        assert data["already_existed"] is False

    def test_already_exists(self, client, test_state):
        dest = test_state.config.ic_lora_dir / "ltx-2-19b-ic-lora-canny-control.safetensors"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00" * 2_000_000)

        r = client.post("/api/ic-lora/download-model", json={"model": "canny"})
        assert r.status_code == 200
        assert r.json()["already_existed"] is True

    def test_unknown_model(self, client):
        r = client.post("/api/ic-lora/download-model", json={"model": "nonexistent"})
        assert r.status_code == 400

    def test_network_error(self, client, test_state):
        test_state.ic_lora_model_downloader.fail_next = RuntimeError("Connection refused")

        r = client.post("/api/ic-lora/download-model", json={"model": "canny"})
        assert r.status_code == 500
        assert "error" in r.json()


class TestIcLoraExtractConditioning:
    def test_canny_extraction(self, client, test_state):
        video_path = test_state.config.outputs_dir / "test_video.mp4"
        video_path.write_bytes(b"\x00" * 100)
        test_state.video_processor.register_video(str(video_path), FakeCapture(frames=["frame-a"]))

        r = client.post(
            "/api/ic-lora/extract-conditioning",
            json={"video_path": str(video_path), "conditioning_type": "canny", "frame_time": 0},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["conditioning_type"] == "canny"
        assert data["conditioning"].startswith("data:image/jpeg;base64,")

    def test_depth_extraction(self, client, test_state):
        video_path = test_state.config.outputs_dir / "test_video.mp4"
        video_path.write_bytes(b"\x00" * 100)
        test_state.video_processor.register_video(str(video_path), FakeCapture(frames=["frame-a"]))

        r = client.post(
            "/api/ic-lora/extract-conditioning",
            json={"video_path": str(video_path), "conditioning_type": "depth", "frame_time": 0},
        )
        assert r.status_code == 200
        assert r.json()["conditioning_type"] == "depth"

    def test_unreadable_frame(self, client, test_state):
        video_path = test_state.config.outputs_dir / "bad_video.mp4"
        video_path.write_bytes(b"\x00" * 100)
        test_state.video_processor.register_video(str(video_path), FakeCapture(frames=[]))

        r = client.post(
            "/api/ic-lora/extract-conditioning",
            json={"video_path": str(video_path), "conditioning_type": "canny"},
        )
        assert r.status_code == 400


class TestIcLoraGenerate:
    def test_happy_path(self, client, test_state, fake_services):
        video_path = test_state.config.outputs_dir / "input.mp4"
        video_path.write_bytes(b"\x00" * 100)
        lora_path = test_state.config.ic_lora_dir / "test.safetensors"
        lora_path.parent.mkdir(parents=True, exist_ok=True)
        lora_path.write_bytes(b"\x00" * 100)

        te_dir = test_state.config.model_path("text_encoder")
        te_dir.mkdir(parents=True, exist_ok=True)
        (te_dir / "model.safetensors").write_bytes(b"\x00" * 100)
        test_state.state.app_settings.use_local_text_encoder = True

        capture = FakeCapture(frames=["f1", "f2"], fps=24, width=64, height=64)
        test_state.video_processor.register_video(str(video_path), capture)

        r = client.post(
            "/api/ic-lora/generate",
            json={
                "video_path": str(video_path),
                "lora_path": str(lora_path),
                "prompt": "test prompt",
                "conditioning_type": "canny",
            },
        )

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "complete"
        assert Path(data["video_path"]).exists()

        pipeline = fake_services.ic_lora_pipeline
        assert len(pipeline.generate_calls) == 1

    def test_video_not_found(self, client, test_state):
        lora_path = test_state.config.ic_lora_dir / "test.safetensors"
        lora_path.parent.mkdir(parents=True, exist_ok=True)
        lora_path.write_bytes(b"\x00" * 100)

        r = client.post(
            "/api/ic-lora/generate",
            json={"video_path": "/nonexistent/video.mp4", "lora_path": str(lora_path), "prompt": "test"},
        )
        assert r.status_code == 400

    def test_lora_not_found(self, client, test_state):
        video_path = test_state.config.outputs_dir / "input.mp4"
        video_path.write_bytes(b"\x00" * 100)

        r = client.post(
            "/api/ic-lora/generate",
            json={"video_path": str(video_path), "lora_path": "/nonexistent/lora.safetensors", "prompt": "test"},
        )
        assert r.status_code == 400

    def test_empty_prompt_rejected(self, client, test_state):
        video_path = test_state.config.outputs_dir / "input.mp4"
        video_path.write_bytes(b"\x00" * 100)
        lora_path = test_state.config.ic_lora_dir / "test.safetensors"
        lora_path.parent.mkdir(parents=True, exist_ok=True)
        lora_path.write_bytes(b"\x00" * 100)

        r = client.post(
            "/api/ic-lora/generate",
            json={"video_path": str(video_path), "lora_path": str(lora_path), "prompt": ""},
        )
        assert r.status_code == 422

    def test_pipeline_error(self, client, test_state, fake_services):
        video_path = test_state.config.outputs_dir / "input.mp4"
        video_path.write_bytes(b"\x00" * 100)
        lora_path = test_state.config.ic_lora_dir / "test.safetensors"
        lora_path.parent.mkdir(parents=True, exist_ok=True)
        lora_path.write_bytes(b"\x00" * 100)

        test_state.video_processor.register_video(str(video_path), FakeCapture(frames=["f1", "f2"]))
        fake_services.ic_lora_pipeline.raise_on_generate = RuntimeError("GPU OOM")

        r = client.post(
            "/api/ic-lora/generate",
            json={"video_path": str(video_path), "lora_path": str(lora_path), "prompt": "test"},
        )
        assert r.status_code == 500
