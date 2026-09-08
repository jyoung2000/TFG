"""Quick Mode → Film Maker conversion and seed reporting."""

from __future__ import annotations

from pathlib import Path

PROJECT = "quick-project"


def _fake_clip(tmp_path: Path) -> Path:
    clip = tmp_path / "outputs" / "quick_clip.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"fake-video")
    return clip


class TestImportGeneration:
    def test_converts_clip_into_scene_1_shot_1_version_1(self, client, tmp_path: Path):
        clip = _fake_clip(tmp_path)
        response = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={
                "prompt": "A lone fisherman rows through fog at dawn",
                "negative_prompt": "blurry, text",
                "output_path": str(clip),
                "model": "fast",
                "resolution": "540p",
                "duration_seconds": 5,
                "fps": 24,
                "seed": 1234,
                "aspect_ratio": "9:16",
                "title": "Shot 1",
                "project_name": "Fog at dawn",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["version_number"] == 1
        project = payload["project"]
        assert project["name"] == "Fog at dawn"
        assert len(project["scenes"]) == 1
        scene = project["scenes"][0]
        assert scene["id"] == payload["scene_id"]
        assert scene["title"] == "Scene 1"
        shot = scene["shots"][0]
        assert shot["id"] == payload["shot_id"]
        assert shot["title"] == "Shot 1"
        assert shot["status"] == "review"
        assert shot["current_version"] == 1
        # Everything needed to remake the clip is preserved on the shot...
        assert shot["visual_prompt"] == "A lone fisherman rows through fog at dawn"
        assert shot["prompt_locked"] is True
        assert shot["negative_prompt"] == "blurry, text"
        assert shot["duration_seconds"] == 5.0
        assert shot["generation"]["model"] == "fast"
        assert shot["generation"]["resolution"] == "540p"
        assert shot["generation"]["seed"] == 1234
        assert shot["generation"]["aspect_ratio"] == "9:16"
        # ...and on version 1, which points at the original output.
        version = shot["versions"][0]
        assert version["status"] == "complete"
        assert version["kind"] == "final"
        assert version["output_path"] == str(clip)
        assert version["seed"] == 1234
        assert version["model"] == "fast"
        assert version["resolution"] == "540p"
        assert version["duration_seconds"] == 5.0

        # The persisted store is the source of truth: a fresh GET sees it.
        stored = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert stored["scenes"][0]["shots"][0]["versions"][0]["output_path"] == str(clip)

    def test_second_import_appends_scene(self, client, tmp_path: Path):
        clip = _fake_clip(tmp_path)
        for _ in range(2):
            client.post(
                f"/api/film/projects/{PROJECT}/import-generation",
                json={"prompt": "again", "output_path": str(clip)},
            )
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert [s["title"] for s in project["scenes"]] == ["Scene 1", "Scene 2"]
        assert project["scenes"][1]["order"] == 1

    def test_missing_output_rejected(self, client, tmp_path: Path):
        response = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={"prompt": "x", "output_path": str(tmp_path / "nope.mp4")},
        )
        assert response.status_code == 400
        assert "not found" in response.text.lower()

    def test_relative_output_rejected(self, client):
        response = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={"prompt": "x", "output_path": "relative/clip.mp4"},
        )
        assert response.status_code == 400

    def test_empty_prompt_rejected(self, client, tmp_path: Path):
        clip = _fake_clip(tmp_path)
        response = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={"prompt": "   ", "output_path": str(clip)},
        )
        assert response.status_code == 400

    def test_imported_shot_can_be_regenerated_through_the_queue(
        self, client, test_state, tmp_path: Path, create_fake_model_files
    ):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        clip = _fake_clip(tmp_path)
        payload = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={"prompt": "remake me", "output_path": str(clip), "seed": 99, "duration_seconds": 2},
        ).json()
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{payload['scene_id']}/shots/{payload['shot_id']}/generate",
            json={"kind": "final"},
        )
        assert response.status_code == 200, response.text
        shot = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]
        assert [v["number"] for v in shot["versions"]] == [1, 2]
        assert shot["versions"][1]["status"] == "complete"
        assert shot["versions"][1]["seed"] == 99  # per-shot seed is honoured on remake
        assert shot["versions"][1]["prompt"] == "remake me"


class TestSeedReporting:
    def test_generate_response_includes_seed(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        test_state.state.app_settings.seed_locked = True
        test_state.state.app_settings.locked_seed = 4242
        response = client.post(
            "/api/generate",
            json={"prompt": "seed check", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "complete"
        assert payload["seed"] == 4242
