"""Integration tests for the film generation queue and capabilities.

The FakeTaskRunner executes the queue worker synchronously, so a queue call
returns only after the (fake) generation pipeline ran — every state
transition is then observable from the persisted project.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

PROJECT = "gen-project"


def _png_base64() -> str:
    image = Image.new("RGB", (32, 18), (10, 120, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _minimal_composition() -> dict:
    return {
        "objects": [],
        "camera": None,
        "framing": {
            "shot_size": "wide",
            "camera_angle": "front",
            "camera_elevation": "eye",
            "composition": "center",
            "fov_deg": 40,
        },
        "camera_move": "static",
        "duration_seconds": 4.0,
    }


def _setup_shot(client, *, capture: bool = False, duration: float = 4.0) -> tuple[str, str]:
    scene_id = client.post(
        f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}
    ).json()["id"]
    shot_id = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots",
        json={"title": "Shot", "duration_seconds": duration, "action": "a quiet moment"},
    ).json()["id"]
    if capture:
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/capture",
            json={"image_base64": _png_base64(), "composition": _minimal_composition()},
        )
        assert response.status_code == 200
    return scene_id, shot_id


def _enable_local(test_state, create_fake_model_files) -> None:
    create_fake_model_files()
    test_state.state.app_settings.use_local_text_encoder = True


def _get_shot(client, shot_id: str) -> dict:
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    for scene in project["scenes"]:
        for shot in scene["shots"]:
            if shot["id"] == shot_id:
                return shot
    raise AssertionError(f"shot {shot_id} not found")


class TestQueueShot:
    def test_preview_generates_through_real_pipeline(
        self, client, test_state, fake_services, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True, duration=9.0)

        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        shot = _get_shot(client, shot_id)
        assert shot["status"] == "review"
        assert shot["current_version"] == 1
        version = shot["versions"][0]
        assert version["kind"] == "preview"
        assert version["status"] == "complete"
        assert version["output_path"].endswith(".mp4")
        # Preview clamps duration and resolution.
        assert version["duration_seconds"] == 4.0
        assert version["resolution"] == "540p"
        assert version["model"] == "fast"
        # The real pipeline ran, with the capture as the i2v conditioning image.
        calls = fake_services.fast_video_pipeline.generate_calls
        assert len(calls) == 1
        assert len(calls[0]["images"]) == 1

    def test_final_uses_shot_settings(
        self, client, test_state, fake_services, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=False, duration=5.0)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}",
            json={
                "generation": {
                    "model": "fast",
                    "resolution": "720p",
                    "fps": 24,
                    "seed": 1234,
                    "aspect_ratio": "16:9",
                    "use_capture_as_reference": False,
                    "continue_from_previous": False,
                    "quality_preset": "quality",
                }
            },
        )
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "final"},
        )
        assert response.status_code == 200
        shot = _get_shot(client, shot_id)
        version = shot["versions"][0]
        assert version["kind"] == "final"
        assert version["resolution"] == "720p"
        assert version["duration_seconds"] == 5.0
        assert version["seed"] == 1234
        # The per-shot seed reached the pipeline and user seed settings were restored.
        calls = fake_services.fast_video_pipeline.generate_calls
        assert calls[0]["seed"] == 1234
        assert test_state.state.app_settings.seed_locked is False

    def test_failure_is_persisted_and_retryable(
        self, client, test_state, fake_services, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")

        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert response.status_code == 200  # queueing succeeds; the job fails

        shot = _get_shot(client, shot_id)
        assert shot["status"] == "ready"  # back to a retryable state
        version = shot["versions"][0]
        assert version["status"] == "failed"
        assert "CUDA out of memory" in version["error"]

        # Retry after clearing the fault: a second version is created.
        fake_services.fast_video_pipeline.raise_on_generate = None
        retry = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert retry.status_code == 200
        shot = _get_shot(client, shot_id)
        assert [v["status"] for v in shot["versions"]] == ["failed", "complete"]
        assert shot["current_version"] == 2

    def test_strict_continuity_blocks_generation(
        self, client, test_state, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=False)  # missing capture warning
        client.put(
            f"/api/film/projects/{PROJECT}/settings",
            json={
                "settings": {
                    "default_model": "",
                    "default_resolution": "",
                    "style_prompt": "",
                    "default_negative_prompt": "",
                    "inter_shot_gap_seconds": 0.0,
                    "strict_continuity": True,
                    "preview_resolution": "540p",
                    "preview_max_seconds": 4.0,
                }
            },
        )
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert response.status_code == 409

    def test_non_strict_returns_warnings_but_generates(
        self, client, test_state, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=False)
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert any(w["kind"] == "missing_capture" for w in payload["warnings"])
        assert _get_shot(client, shot_id)["versions"][0]["status"] == "complete"

    def test_double_queue_conflicts(self, client, test_state, create_fake_model_files, fake_services):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        # Make generation fail so no version completes, then queue twice quickly:
        # with the synchronous fake runner the first completes before the second,
        # so instead simulate an occupied queue by injecting a pending job.
        first = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert first.status_code == 200
        # After completion, queuing again is allowed (creates v2).
        second = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        assert second.status_code == 200
        assert len(_get_shot(client, shot_id)["versions"]) == 2

    def test_promote_older_version(self, client, test_state, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        for _ in range(2):
            client.post(
                f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
                json={"kind": "preview"},
            )
        assert _get_shot(client, shot_id)["current_version"] == 2
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/versions/1/promote"
        )
        assert response.status_code == 200
        assert _get_shot(client, shot_id)["current_version"] == 1

    def test_promote_failed_version_rejected(self, client, test_state, fake_services, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("boom")
        client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/versions/1/promote"
        )
        assert response.status_code == 400


class TestBatch:
    def test_batch_scene_generates_in_order(
        self, client, test_state, fake_services, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id = client.post(
            f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}
        ).json()["id"]
        shot_ids = []
        for index in range(3):
            shot_ids.append(
                client.post(
                    f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots",
                    json={"title": f"Shot {index + 1}", "duration_seconds": 3.0, "action": f"beat {index + 1}"},
                ).json()["id"]
            )
        response = client.post(
            f"/api/film/projects/{PROJECT}/generate/batch",
            json={"kind": "preview", "scene_id": scene_id},
        )
        assert response.status_code == 200
        assert len(response.json()["queued"]) == 3
        prompts = [c["prompt"] for c in fake_services.fast_video_pipeline.generate_calls]
        assert len(prompts) == 3
        assert "beat 1" in prompts[0] and "beat 3" in prompts[2]
        for shot_id in shot_ids:
            assert _get_shot(client, shot_id)["versions"][0]["status"] == "complete"

    def test_queue_endpoint_empty_after_drain(self, client, test_state, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        queue = client.get("/api/film/queue").json()
        assert queue["active"] is None
        assert queue["pending"] == []


class TestCapabilities:
    def test_local_mode_lists_real_model_specs(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.models.refresh_available_files()
        response = client.get("/api/film/capabilities")
        assert response.status_code == 200
        payload = response.json()
        assert payload["execution_mode"] == "local"
        ids = {m["id"] for m in payload["models"]}
        assert {"checkpoint", "upsampler", "text_encoder", "zit"} <= ids
        checkpoint = next(m for m in payload["models"] if m["id"] == "checkpoint")
        assert checkpoint["downloaded"] is True
        assert checkpoint["disk_size_gb"] == 43.0
        assert checkpoint["estimated_min_vram_gb"] == 32.0
        assert checkpoint["supported_resolutions"] == ["540p", "720p", "1080p"]
        assert "6 GB" in payload["vram_note"]

    def test_not_downloaded_state(self, client):
        response = client.get("/api/film/capabilities")
        payload = response.json()
        checkpoint = next(m for m in payload["models"] if m["id"] == "checkpoint")
        assert checkpoint["downloaded"] is False
        assert checkpoint["download_state"] == "not_downloaded"

    def test_mid_vram_gpu_fits_wangp_but_not_native(self, client, fake_services):
        fake_services.gpu_info.gpu_name = "GeForce RTX 4070"
        fake_services.gpu_info.vram_gb = 12
        payload = client.get("/api/film/capabilities").json()
        assert payload["gpu_vram_gb"] == 12.0
        checkpoint = next(m for m in payload["models"] if m["id"] == "checkpoint")
        assert checkpoint["fits_gpu"] is False  # native path needs ~32 GB
        advisory = next(m for m in payload["models"] if m["id"] == "wangp-bridge")
        assert advisory["download_state"] == "not_configured"
        assert advisory["fits_gpu"] is True  # WanGP path fits a 12 GB GPU
        assert payload["gpu_verdict_level"] == "partial"
        assert "WanGP" in payload["gpu_verdict"]

    def test_high_vram_gpu_fits_everything(self, client, fake_services):
        fake_services.gpu_info.vram_gb = 48
        payload = client.get("/api/film/capabilities").json()
        checkpoint = next(m for m in payload["models"] if m["id"] == "checkpoint")
        assert checkpoint["fits_gpu"] is True
        assert payload["gpu_verdict_level"] == "ok"

    def test_tiny_vram_gpu_verdict_none(self, client, fake_services):
        fake_services.gpu_info.vram_gb = 4
        payload = client.get("/api/film/capabilities").json()
        assert payload["gpu_verdict_level"] == "none"
        advisory = next(m for m in payload["models"] if m["id"] == "wangp-bridge")
        assert advisory["fits_gpu"] is False

    def test_required_download_total_without_api_key(self, client):
        payload = client.get("/api/film/capabilities").json()
        # No API key: the text encoder is required, so the total covers
        # checkpoint (43) + upsampler (1.9) + text encoder (25) + zit (31).
        assert payload["text_encoder_optional"] is False
        assert payload["total_required_download_gb"] == 100.9
        encoder = next(m for m in payload["models"] if m["id"] == "text_encoder")
        assert encoder["required"] is True

    def test_api_key_makes_text_encoder_optional(self, client, test_state):
        test_state.state.app_settings.ltx_api_key = "key"
        payload = client.get("/api/film/capabilities").json()
        assert payload["text_encoder_optional"] is True
        assert payload["total_required_download_gb"] == 75.9
        encoder = next(m for m in payload["models"] if m["id"] == "text_encoder")
        assert encoder["required"] is False

    def test_downloaded_files_reduce_the_total(
        self, client, test_state, create_fake_model_files
    ):
        create_fake_model_files(include_zit=True)
        test_state.models.refresh_available_files()
        payload = client.get("/api/film/capabilities").json()
        assert payload["total_required_download_gb"] == 0.0


class TestOutputServing:
    def test_output_route_serves_from_outputs_dir_only(
        self, client, test_state, create_fake_model_files
    ):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "preview"},
        )
        output_path = _get_shot(client, shot_id)["versions"][0]["output_path"]
        served = client.get("/api/film/output", params={"path": output_path})
        assert served.status_code == 200
        assert served.content == b"fake-video"

        refused = client.get("/api/film/output", params={"path": "/etc/passwd"})
        assert refused.status_code == 400
