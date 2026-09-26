"""LoRA training (phase 7): dataset builder, 12 GB presets, the training job,
the LoRA registry and the Consistency Kit — all against `FakeTrainer` and the
fake vision stack. A real trainer subprocess is exercised only as far as its
command line and config (no GPU here, see docs/RTX_4070_TEST_MATRIX.md).
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from film.training_models import LORA_TARGETS
from film.training_presets import default_config, fits_machine
from services.trainer.catalog import MACHINE_VRAM_MB, trainer_for, trainers_for_target
from services.trainer.subprocess_trainer import AiToolkitTrainer, MusubiTrainer, parse_progress_line
from services.trainer.trainer import TrainerUnavailable, TrainingRequest
from services.wangp_bridge import WanGPBridge

PROJECT = "train-project"


def _write_images(folder: Path, count: int, *, prefix: str = "img", size: tuple[int, int] = (96, 64)) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(count):
        path = folder / f"{prefix}-{i:02d}.png"
        Image.new("RGB", size, (20 * i % 255, 90, 160)).save(path)
        paths.append(path)
    return paths


def _dataset(client, tmp_path: Path, *, count: int = 6, preset: str = "character", trigger: str = "mara_v1") -> dict:
    dataset = client.post("/api/training/datasets", json={"name": "Mara", "preset": preset, "trigger": trigger}).json()
    _write_images(tmp_path / "refs", count)
    imported = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"folder": str(tmp_path / "refs")})
    assert imported.status_code == 200, imported.text
    return imported.json()


def _png_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 40, 40)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _job(client, job_id: str) -> dict:
    return client.get(f"/api/jobs/{job_id}").json()["job"]


class TestDatasets:
    def test_import_from_folder_video_and_history_outputs(self, client, tmp_path: Path, video, fake_services, create_fake_model_files):
        dataset = _dataset(client, tmp_path, count=3)
        assert [item["source"] for item in dataset["items"]] == ["folder"] * 3
        assert all(item["width"] == 96 and item["height"] == 64 for item in dataset["items"])

        # Video frames are sampled through the media probe at the requested rate.
        fake_services.media_probe.duration = 4.0
        with_video = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"video_path": video, "video_fps": 1.0, "video_max_frames": 3}).json()
        assert [i["source"] for i in with_video["items"]].count("video") == 3
        assert with_video["items"][-1]["origin"].endswith("@2.00s")

        # History image outputs become items too, tagged with the job they came from.
        create_fake_model_files(include_zit=True)
        client.post("/api/generate-image", json={"prompt": "A cat", "width": 512, "height": 512, "numSteps": 4})
        job = client.get("/api/jobs", params={"kind": "image_gen", "limit": 1}).json()["jobs"][0]
        with_history = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"job_ids": [job["id"]]}).json()
        history_items = [i for i in with_history["items"] if i["source"] == "history"]
        assert history_items and history_items[0]["origin"] == job["id"]
        # Every item is served back through the media route, and only from inside its dataset.
        media = client.get(f"/api/training/datasets/{dataset['id']}/media", params={"path": history_items[0]["file"]})
        assert media.status_code == 200
        assert client.get(f"/api/training/datasets/{dataset['id']}/media", params={"path": "../../settings.json"}).status_code == 400

    def test_import_from_video_analysis_frames(self, client, tmp_path: Path, video):
        analysis = client.post("/api/video-analysis/import", json={"path": video, "title": "Source"}).json()
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        dataset = client.post("/api/training/datasets", json={"name": "From analysis", "preset": "style", "trigger": "relaystyle"}).json()
        imported = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"analysis_id": analysis["id"]})
        assert imported.status_code == 200, imported.text
        items = imported.json()["items"]
        assert items and all(i["source"] == "analysis" and i["origin"] == analysis["id"] for i in items)
        missing = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"analysis_id": "nope"})
        assert missing.status_code == 404

    def test_nothing_importable_is_an_error_not_an_empty_success(self, client, tmp_path: Path):
        dataset = client.post("/api/training/datasets", json={"name": "Empty"}).json()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "notes.txt").write_text("not an image")
        response = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"folder": str(tmp_path / "docs")})
        assert response.status_code == 400
        assert client.post(f"/api/training/datasets/{dataset['id']}/import", json={"folder": "relative/path"}).status_code == 400

    def test_captions_carry_the_trigger_and_respect_edits(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=4, trigger="mara_v1")
        first = dataset["items"][0]["id"]
        client.put(f"/api/training/datasets/{dataset['id']}/items/{first}", json={"caption": "hand written, mara_v1 smiling"})
        fake_services.vision.caption_override = "A woman in a green jacket stands by a window."
        captioned = client.post(f"/api/training/datasets/{dataset['id']}/caption", json={}).json()
        assert captioned["caption_model"] == "fake-florence"
        by_id = {i["id"]: i for i in captioned["items"]}
        assert by_id[first]["caption"] == "hand written, mara_v1 smiling" and by_id[first]["edited"] is True
        others = [i for i in captioned["items"] if i["id"] != first]
        assert all(i["caption"] == "mara_v1, A woman in a green jacket stands by a window" for i in others)
        assert all(i["edited"] is False for i in others)
        # Style datasets phrase the trigger as a style, and overwrite_edited re-captions everything.
        client.put(f"/api/training/datasets/{dataset['id']}", json={"preset": "style", "trigger": "relaystyle"})
        again = client.post(f"/api/training/datasets/{dataset['id']}/caption", json={"overwrite_edited": True}).json()
        assert all(i["caption"].endswith(", in the style of relaystyle") for i in again["items"])
        # The caption sidecar the trainers read exists beside each image.
        folder = Path(client.get(f"/api/training/datasets/{dataset['id']}").json()["folder"])
        assert (folder / Path(again["items"][0]["file"]).with_suffix(".txt").name).read_text(encoding="utf-8").strip() == again["items"][0]["caption"]

    def test_items_can_be_removed_and_the_dataset_deleted(self, client, tmp_path: Path):
        dataset = _dataset(client, tmp_path, count=4)
        folder = Path(dataset["folder"])
        gone = dataset["items"][0]
        remaining = client.delete(f"/api/training/datasets/{dataset['id']}/items/{gone['id']}").json()
        assert len(remaining["items"]) == 3 and not (folder / gone["file"]).exists()
        assert client.delete(f"/api/training/datasets/{dataset['id']}").status_code == 200
        assert client.get(f"/api/training/datasets/{dataset['id']}").status_code == 404
        assert not folder.exists()


class TestPresetsAndVramGuard:
    def test_defaults_scale_with_preset_and_image_count(self):
        character = default_config("z_image", "character", image_count=12)
        style = default_config("z_image", "style", image_count=12)
        assert style.rank > character.rank and style.steps > character.steps
        assert default_config("z_image", "character", image_count=40).steps > character.steps
        assert character.fp8 is True and character.blocks_to_swap > 0
        assert character.estimated_vram_mb <= MACHINE_VRAM_MB

    def test_image_targets_fit_and_video_targets_are_refused(self):
        for target in ("z_image", "qwen_image", "flux"):
            ok, _ = fits_machine(default_config(target, "character"))
            assert ok, target
        for target in ("wan22", "ltx2"):
            ok, why = fits_machine(default_config(target, "character"))
            assert not ok and "12 GB" in why, target
        # The catalog says the same thing about the trainers themselves.
        assert trainer_for("ltx-trainer").fits_12gb is False
        assert trainer_for("musubi").fits_12gb is True
        assert "ai-toolkit" in {t.id for t in trainers_for_target("flux")}
        assert {t.id for t in trainers_for_target("ltx2")} == {"ltx-trainer"}

    def test_suggest_uses_the_dataset_preset_and_size(self, client, tmp_path: Path):
        dataset = _dataset(client, tmp_path, count=5, preset="object", trigger="lamp")
        config = client.post("/api/training/suggest", json={"dataset_id": dataset["id"], "target": "qwen_image"}).json()
        assert config["target"] == "qwen_image" and config["trainer"] == "musubi"
        assert config["rank"] == 12  # object preset lowers the rank
        assert config["estimated_vram_mb"] <= 12288

    def test_starting_a_video_lora_on_this_card_is_refused_before_any_work(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=4)
        config = default_config("wan22", "character").model_dump()
        response = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "config": config})
        assert response.status_code == 400 and "12 GB" in response.json()["error"]
        assert fake_services.trainer.requests == []
        assert client.get("/api/training/runs").json()["runs"] == []

    def test_status_reports_trainers_and_missing_weights(self, client):
        status = client.get("/api/training/status").json()
        ids = {t["id"]: t for t in status["trainers"]}
        assert ids["musubi"]["fits_12gb"] and not ids["ltx-trainer"]["fits_12gb"]
        assert status["machine_vram_mb"] == 12288 and status["active_run_id"] == ""
        updated = client.put("/api/training/weights/z_image", json={"dit": "/weights/z-image.safetensors", "bogus": "x"}).json()
        assert updated["z_image"] == {"dit": "/weights/z-image.safetensors"}
        assert client.put("/api/training/weights/nope", json={}).status_code == 400


class TestTrainingRuns:
    def test_run_lifecycle_lands_in_history_with_loss_and_samples(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=6, trigger="mara_v1")
        too_small = client.post("/api/training/datasets", json={"name": "tiny"}).json()
        assert client.post("/api/training/runs", json={"dataset_id": too_small["id"]}).status_code == 400

        config = default_config("z_image", "character", image_count=6).model_dump()
        config.update(steps=120, save_every=40, sample_every=60, trainer="fake")
        run = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "name": "Mara LoRA", "config": config}).json()
        assert run["status"] == "complete" and run["step"] == 120
        assert run["loss_history"] and run["loss_history"][0] > run["loss_history"][-1]
        assert [s["step"] for s in run["samples"]] == [60, 120]
        assert len(run["checkpoints"]) == 2 and all(Path(c).is_file() for c in run["checkpoints"])
        assert run["lora_path"].endswith(".safetensors") and Path(run["lora_path"]).is_file()

        request = fake_services.trainer.requests[0]
        assert request.trigger == "mara_v1" and request.sample_prompts[0].startswith("mara_v1")
        assert request.dataset_dir == dataset["folder"]

        job = _job(client, run["job_id"])
        assert job["kind"] == "training" and job["status"] == "complete"
        assert job["model"] == "z_image" and job["inputs"]["dataset_id"] == dataset["id"]
        assert job["metrics"]["loss_history"][-1] == run["loss_history"][-1]
        assert job["metrics"]["final_loss"] == run["loss_history"][-1]
        assert [o["kind"] for o in job["outputs"]][0] == "file"
        assert any(o["path"].endswith(".png") for o in job["outputs"])
        sample = run["samples"][0]["path"]
        assert client.get(f"/api/training/runs/{run['id']}/media", params={"path": sample}).status_code == 200
        assert client.get(f"/api/training/runs/{run['id']}/media", params={"path": "../../../settings.json"}).status_code == 404

        # The finished LoRA is registered with everything a picker needs.
        loras = client.get("/api/training/loras").json()["loras"]
        assert len(loras) == 1
        entry = loras[0]
        assert entry["id"] == run["lora_id"] and entry["target"] == "z_image"
        assert entry["trigger"] == "mara_v1" and entry["dataset_id"] == dataset["id"] and entry["run_id"] == run["id"]
        assert entry["base_model"] and Path(entry["file"]).is_file()
        assert client.get("/api/training/status").json()["active_run_id"] == ""

    def test_failure_is_reported_honestly(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=4)
        fake_services.trainer.fail_at_step = 3
        config = default_config("z_image", "character").model_dump()
        config.update(steps=10, trainer="fake")
        run = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "config": config}).json()
        assert run["status"] == "failed" and "out of memory" in run["error"]
        assert _job(client, run["job_id"])["status"] == "failed"
        assert client.get("/api/training/loras").json()["loras"] == []

    def test_cancel_then_resume_from_the_last_checkpoint(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=4)
        fake_services.trainer.cancel_after = 50
        config = default_config("z_image", "character").model_dump()
        config.update(steps=100, save_every=20, sample_every=0, trainer="fake")
        run = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "config": config}).json()
        assert run["status"] == "cancelled" and run["step"] == 50
        assert run["checkpoints"][-1].endswith("-000040.safetensors")
        assert _job(client, run["job_id"])["status"] == "cancelled"

        fake_services.trainer.cancel_after = None
        resumed = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "resume_run_id": run["id"]}).json()
        assert resumed["status"] == "complete"
        request = fake_services.trainer.requests[-1]
        assert request.resume_from == run["checkpoints"][-1]
        # Resumed from step 40: the fake trainer picks up where the checkpoint left off.
        assert resumed["loss_history"][0] < run["loss_history"][0]
        assert _job(client, resumed["job_id"])["inputs"]["resume_from"] == run["checkpoints"][-1]
        # Finished runs can be deleted; their LoRA stays in the registry.
        assert client.delete(f"/api/training/runs/{run['id']}").status_code == 200
        assert client.get(f"/api/training/runs/{run['id']}").status_code == 404
        assert len(client.get("/api/training/loras").json()["loras"]) == 1

    def test_a_missing_trainer_is_refused_with_the_install_hint(self, client, tmp_path: Path, fake_services):
        dataset = _dataset(client, tmp_path, count=4)
        fake_services.trainer.installed = False
        response = client.post("/api/training/runs", json={"dataset_id": dataset["id"]})
        assert response.status_code == 400 and "ensure-trainer" in response.json()["error"]

    def test_history_cancel_reaches_the_run(self, client, tmp_path: Path, fake_services, test_state):
        """Cancelling the History job cancels the run (registered canceller)."""
        dataset = _dataset(client, tmp_path, count=4)
        # Mark the run cancelled from the job side once it has been created.
        training = test_state.training
        seen: list[str] = []
        original = fake_services.trainer.train

        def train_and_cancel(request, on_progress, is_cancelled):  # noqa: ANN001
            seen.append(request.run_id)
            run = training.get_run(request.run_id)
            assert run.job_id
            client.post(f"/api/jobs/{run.job_id}/cancel")
            return original(request, on_progress, is_cancelled)

        fake_services.trainer.train = train_and_cancel  # type: ignore[method-assign]
        config = default_config("z_image", "character").model_dump()
        config.update(steps=30, trainer="fake")
        run = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "config": config}).json()
        assert seen == [run["id"]]
        assert run["status"] == "cancelled" and run["step"] < 30


class TestRegistry:
    def test_import_update_delete_and_compatibility(self, client, tmp_path: Path):
        external = tmp_path / "downloaded-lora.safetensors"
        external.write_bytes(b"lora")
        entry = client.post("/api/training/loras/import", json={"path": str(external), "target": "qwen_image", "trigger": "ohwx"}).json()
        assert entry["name"] == "downloaded-lora" and entry["target"] == "qwen_image"
        assert Path(entry["file"]).is_file() and Path(entry["file"]).parent.name == LORA_TARGETS["qwen_image"]
        assert client.post("/api/training/loras/import", json={"path": str(tmp_path / "missing.safetensors")}).status_code == 400
        assert client.post("/api/training/loras/import", json={"path": str(external), "target": "nope"}).status_code == 400

        updated = client.put(f"/api/training/loras/{entry['id']}", json={"name": "Ohwx face", "default_multiplier": 0.8}).json()
        assert updated["name"] == "Ohwx face" and updated["default_multiplier"] == 0.8

        # Pickers ask by model id; only LoRAs for that base come back.
        assert [l["id"] for l in client.get("/api/training/loras", params={"model": "qwen_image_20B"}).json()["loras"]] == [entry["id"]]
        assert client.get("/api/training/loras", params={"model": "z_image_turbo"}).json()["loras"] == []
        assert client.get("/api/training/loras", params={"model": "ltx2_22B_distilled"}).json()["loras"] == []
        assert client.get("/api/training/loras", params={"target": "qwen_image"}).json()["loras"][0]["id"] == entry["id"]

        assert client.delete(f"/api/training/loras/{entry['id']}").status_code == 200
        assert client.get("/api/training/loras").json()["loras"] == []
        assert not Path(entry["file"]).exists()

    def test_registry_survives_a_restart_and_drops_missing_files(self, client, tmp_path: Path, test_state):
        external = tmp_path / "a.safetensors"
        external.write_bytes(b"lora")
        other = tmp_path / "b.safetensors"
        other.write_bytes(b"lora-b")
        kept = client.post("/api/training/loras/import", json={"path": str(external), "target": "z_image"}).json()
        lost = client.post("/api/training/loras/import", json={"path": str(other), "name": "lost", "target": "z_image"}).json()
        Path(lost["file"]).unlink()
        registry = json.loads(Path(kept["file"]).parent.parent.joinpath("registry.json").read_text())
        assert {e["id"] for e in registry} == {kept["id"], lost["id"]}
        assert [e.id for e in test_state.training.list_loras()] == [kept["id"]]


class TestWangpSettings:
    """The keys WanGP's wgp.py reads (verified against upstream, session-notes VF-014)."""

    def _bridge(self, tmp_path: Path) -> tuple[WanGPBridge, list[list[dict[str, object]]]]:
        manifests: list[list[dict[str, object]]] = []

        class RecordingBridge(WanGPBridge):
            def __init__(self) -> None:
                super().__init__(enabled=True, root=tmp_path, python_executable=None, config_dir=tmp_path / "cfg", output_dir=tmp_path, video_model_type="ltx2_22B_distilled", image_model_type="z_image", camera_motion_prompts={}, extra_args=())

            def _run_manifest(self, *, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[override]  # noqa: ANN001
                manifests.append(manifest)
                out = tmp_path / "out.mp4"
                out.write_bytes(b"x")
                return [str(out)]

        return RecordingBridge(), manifests

    def test_video_settings_carry_loras_refs_and_end_frame(self, tmp_path: Path):
        bridge, manifests = self._bridge(tmp_path)
        lora = tmp_path / "mara.safetensors"
        lora.write_bytes(b"l")
        ref = tmp_path / "ref.png"
        Image.new("RGB", (8, 8)).save(ref)
        end = tmp_path / "end.png"
        Image.new("RGB", (8, 8)).save(end)
        bridge.generate_video(
            prompt="p", resolution_label="540p", aspect_ratio="16:9", duration_seconds=6, fps=24, steps=8, seed=1, camera_motion="none", negative_prompt="",
            image_path=str(ref), audio_path=None, on_progress=lambda *a: None, is_cancelled=lambda: False,
            loras=[(str(lora), 0.75), (str(tmp_path / "missing.safetensors"), 1.0)], reference_images=[str(ref)], end_frame_path=str(end),
        )
        params = manifests[0][0]["params"]
        assert isinstance(params, dict)
        assert params["activated_loras"] == [str(lora.resolve())]
        assert params["loras_multipliers"] == "0.75"
        assert params["image_refs"] == [str(ref.resolve())]
        assert params["image_end"] == str(end.resolve())
        assert "E" in str(params["image_prompt_type"]) and "S" in str(params["image_prompt_type"])
        assert "I" in str(params["video_prompt_type"])

    def test_image_settings_carry_loras(self, tmp_path: Path):
        bridge, manifests = self._bridge(tmp_path)
        a, b = tmp_path / "a.safetensors", tmp_path / "b.safetensors"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        bridge.generate_images(prompt="p", width=512, height=512, num_steps=4, num_images=1, seed=3, on_progress=lambda *a: None, is_cancelled=lambda: False, loras=[(str(a), 1.0), (str(b), 0.5)])
        params = manifests[0][0]["params"]
        assert isinstance(params, dict)
        assert params["activated_loras"] == [str(a.resolve()), str(b.resolve())] and params["loras_multipliers"] == "1 0.5"

    def test_generate_routes_accept_loras(self, client, create_fake_model_files, tmp_path: Path):
        create_fake_model_files(include_zit=True)
        lora = tmp_path / "x.safetensors"
        lora.write_bytes(b"x")
        response = client.post("/api/generate-image", json={"prompt": "A cat", "width": 512, "height": 512, "numSteps": 4, "loras": [{"name": str(lora), "multiplier": 0.9}]})
        assert response.status_code == 200 and response.json()["status"] == "complete"
        job = client.get("/api/jobs", params={"kind": "image_gen", "limit": 1}).json()["jobs"][0]
        assert job["params"]["loras"] == [{"name": str(lora), "multiplier": 0.9}]


class TestConsistencyKit:
    def _lora(self, client, tmp_path: Path, *, trigger: str = "mara_v1") -> dict:
        path = tmp_path / "mara.safetensors"
        path.write_bytes(b"lora")
        return client.post("/api/training/loras/import", json={"path": str(path), "target": "z_image", "trigger": trigger}).json()

    def _character_shot(self, client, asset: dict) -> tuple[str, str]:
        scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}).json()["id"]
        client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}", json={"character_ids": [asset["id"]]})
        shot_id = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json={"title": "Shot", "duration_seconds": 4.0, "action": "walks in"}).json()["id"]
        return scene_id, shot_id

    def test_asset_lora_binding_reaches_the_prompt_and_the_request(self, client, tmp_path: Path, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        lora = self._lora(client, tmp_path)
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara", "wardrobe": "green jacket"}).json()["asset"]
        asset = client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"lora_id": lora["id"], "lora_trigger": "mara_v1", "lora_multiplier": 0.7, "seed_lock": 4242}).json()["asset"]
        assert asset["lora_id"] == lora["id"] and asset["seed_lock"] == 4242
        scene_id, shot_id = self._character_shot(client, asset)

        queued = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        assert queued.status_code == 200
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 1}).json()["jobs"][0]
        assert job["params"]["loras"] == [{"name": lora["file"], "multiplier": 0.7}]
        assert "mara_v1" in job["params"]["prompt"]
        # Seed lock: the shot inherits the asset's seed when it has none of its own.
        assert job["seed"] == 4242
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        version = project["scenes"][0]["shots"][0]["versions"][0]
        assert version["seed"] == 4242 and version["status"] == "complete"
        assert "mara_v1" in version["prompt"]
        # Consistency score is recorded against the shot's asset reference when one exists;
        # this asset has none, so the metric is honestly absent rather than invented.
        assert "consistency" not in (job["metrics"] or {})

        cleared = client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"clear_seed_lock": True}).json()["asset"]
        assert cleared["seed_lock"] is None

    def test_reference_sheet_uses_one_seed_and_the_bound_lora(self, client, tmp_path: Path, create_fake_model_files, fake_services):
        create_fake_model_files(include_zit=True)
        lora = self._lora(client, tmp_path)
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara", "wardrobe": "green jacket"}).json()["asset"]
        client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"lora_id": lora["id"]})
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/reference-sheet", json={"views": ["front view", "profile view"], "seed": 77})
        assert response.status_code == 200, response.text
        sheet = response.json()
        assert sheet["seed"] == 77 and len(sheet["reference_paths"]) == 2
        assert all(p.startswith("mara_v1, ") for p in sheet["prompts"])
        assert sheet["asset"]["seed_lock"] == 77 and len(sheet["asset"]["reference_images"]) == 2
        calls = fake_services.image_generation_pipeline.generate_calls
        assert len(calls) == 2 and {c["seed"] for c in calls} == {77}
        for path in sheet["reference_paths"]:
            assert client.get(f"/api/film/projects/{PROJECT}/media", params={"path": path}).status_code == 200

    def test_consistency_score_is_measured_against_the_reference(self, client, tmp_path: Path, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara"}).json()["asset"]
        client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": _png_base64(), "name_hint": "front"})
        scene_id, shot_id = self._character_shot(client, asset)
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 1}).json()["jobs"][0]
        assert job["status"] == "complete"
        score = job["metrics"]["consistency"]
        assert 0.0 <= score <= 1.0
        # The reference is also passed to the model as an image ref (no LoRA bound).
        assert len(job["params"]["referenceImagePaths"]) == 1


class TestSubprocessTrainers:
    """No subprocess runs here: only the recipes each trainer would launch."""

    def _request(self, tmp_path: Path, **overrides) -> TrainingRequest:
        base = dict(
            run_id="r1", trainer_id="musubi", target="z_image", dataset_dir=str(tmp_path / "ds"), output_dir=str(tmp_path / "out"), output_name="mara",
            trigger="mara_v1", steps=600, rank=16, learning_rate=1e-4, batch_size=1, resolution=768, buckets=[512, 768], blocks_to_swap=8, fp8=True,
            save_every=100, sample_every=100, sample_prompts=["mara_v1, portrait"], seed=42, resume_from="", weights={},
        )
        base.update(overrides)
        return TrainingRequest(**base)  # type: ignore[arg-type]

    def test_musubi_recipe_fits_12gb(self, tmp_path: Path):
        weights = {}
        for name in ("dit", "vae", "text_encoder"):
            path = tmp_path / f"{name}.safetensors"
            path.write_bytes(b"w")
            weights[name] = str(path)
        trainer = MusubiTrainer(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        commands = trainer.build_command(self._request(tmp_path, weights=weights), work)
        assert len(commands) == 3
        train = commands[-1]
        assert "--fp8_base" in train and "--fp8_scaled" in train and "--blocks_to_swap" in train
        assert train[train.index("--blocks_to_swap") + 1] == "8"
        assert train[train.index("--network_dim") + 1] == "16"
        assert "--gradient_checkpointing" in train and "adamw8bit" in train
        assert (work / "dataset.toml").read_text().count("[[datasets]]") == 1
        assert (work / "sample_prompts.txt").read_text().startswith("mara_v1")

    def test_musubi_refuses_wan22_and_missing_weights(self, tmp_path: Path):
        trainer = MusubiTrainer(tmp_path)
        with pytest.raises(TrainerUnavailable, match="24 GB"):
            trainer.build_command(self._request(tmp_path, target="wan22"), tmp_path)
        with pytest.raises(TrainerUnavailable, match="Weights missing"):
            trainer.build_command(self._request(tmp_path), tmp_path)
        ok, reason = trainer.available()
        assert not ok and "ensure-trainer" in reason

    def test_ai_toolkit_config_quantizes_and_uses_low_vram(self, tmp_path: Path):
        trainer = AiToolkitTrainer(tmp_path)
        work = tmp_path / "work"
        work.mkdir()
        commands = trainer.build_command(self._request(tmp_path, trainer_id="ai-toolkit", target="flux", blocks_to_swap=0), work)
        config = (work / "config.yaml").read_text()
        assert "quantize: true" in config and "low_vram: true" in config
        assert 'trigger_word: "mara_v1"' in config and "linear: 16" in config
        assert commands[-1][-1].endswith("config.yaml")

    def test_progress_lines_from_both_trainers_parse(self):
        assert parse_progress_line("steps:  12%|█▏ | 72/600 [00:41<05:02,  1.75it/s, avr_loss=0.312]") == (72, 600, 0.312, pytest.approx(302.0, abs=1.0))
        parsed = parse_progress_line("mara:  10%|█ | 100/1000 [00:30<04:30,  3.33it/s, lr: 1.0e-04 loss: 3.210e-01]")
        assert parsed is not None and parsed[:3] == (100, 1000, 0.321)
        assert parse_progress_line("loading model") is None
