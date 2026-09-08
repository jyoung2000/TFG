"""Continuity levels + fixes, production queue controls, restart recovery,
quality profiles, and model removal."""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeServices

PROJECT = "hardening-project"


def _scene(client, **kwargs) -> dict:
    response = client.post(f"/api/film/projects/{PROJECT}/scenes", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def _shot(client, scene_id: str, **kwargs) -> dict:
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def _asset(client, kind: str, name: str, **kwargs) -> dict:
    response = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": kind, "name": name, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def _update_shot(client, scene_id: str, shot_id: str, **kwargs) -> dict:
    response = client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def _continuity(client, shot_id: str) -> dict:
    response = client.get(f"/api/film/projects/{PROJECT}/continuity/{shot_id}")
    assert response.status_code == 200, response.text
    return response.json()


class TestContinuityLevels:
    def test_clean_shot_is_good(self, client):
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        report = _continuity(client, shot["id"])
        assert report == {"level": "good", "warnings": []}
        # Composed in 3D but never captured → minor (generation expects a capture).
        _update_shot(
            client, scene["id"], shot["id"],
            composition={"objects": [], "camera": None},
        )
        report = _continuity(client, shot["id"])
        assert report["level"] == "minor"
        assert report["warnings"][0]["kind"] == "missing_capture"
        fixed = client.post(
            f"/api/film/projects/{PROJECT}/continuity/{shot['id']}/fix", json={"kind": "missing_capture"}
        ).json()
        assert fixed["fixed"] is True and fixed["report"]["level"] == "good"

    def test_levels_escalate_to_worst_warning(self, client):
        sarah = _asset(client, "character", "Sarah")
        john = _asset(client, "character", "John")
        scene = _scene(client, character_ids=[john["id"]])
        shot = _shot(client, scene["id"])
        # minor: character not in the scene's cast
        _update_shot(client, scene["id"], shot["id"], characters=[{"asset_id": sarah["id"]}])
        report = _continuity(client, shot["id"])
        assert report["level"] == "minor"
        assert report["warnings"][0]["kind"] == "character_not_in_scene"
        assert report["warnings"][0]["severity"] == "minor"
        assert report["warnings"][0]["auto_fixable"] is True
        assert "Sarah" in report["warnings"][0]["fix"]
        # significant: location mismatch on top
        cafe = _asset(client, "location", "Cafe")
        alley = _asset(client, "location", "Alley")
        client.put(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}", json={"location_id": cafe["id"]})
        _update_shot(client, scene["id"], shot["id"], location_id=alley["id"])
        assert _continuity(client, shot["id"])["level"] == "significant"
        # broken: invalid duration
        _update_shot(client, scene["id"], shot["id"], duration_seconds=0)
        report = _continuity(client, shot["id"])
        assert report["level"] == "broken"
        assert {w["kind"] for w in report["warnings"]} == {
            "character_not_in_scene",
            "location_mismatch",
            "duration_invalid",
        }

    def test_fixes_repair_each_kind(self, client):
        sarah = _asset(client, "character", "Sarah")
        john = _asset(client, "character", "John")
        cafe = _asset(client, "location", "Cafe")
        alley = _asset(client, "location", "Alley")
        scene = _scene(client, character_ids=[john["id"]], location_id=cafe["id"])
        shot = _shot(client, scene["id"])
        _update_shot(
            client, scene["id"], shot["id"],
            characters=[{"asset_id": sarah["id"]}], location_id=alley["id"], duration_seconds=0,
        )
        assert _continuity(client, shot["id"])["level"] == "broken"

        for kind in ("duration_invalid", "location_mismatch", "character_not_in_scene"):
            response = client.post(
                f"/api/film/projects/{PROJECT}/continuity/{shot['id']}/fix", json={"kind": kind}
            )
            assert response.status_code == 200, response.text
            assert response.json()["fixed"] is True

        final = client.get(f"/api/film/projects/{PROJECT}/continuity/{shot['id']}").json()
        assert final == {"level": "good", "warnings": []}
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        stored_scene = project["scenes"][0]
        assert sarah["id"] in stored_scene["character_ids"]
        assert stored_scene["shots"][0]["location_id"] == cafe["id"]
        assert stored_scene["shots"][0]["duration_seconds"] == 4.0

    def test_fix_missing_asset_removes_dangling_reference(self, client):
        ghost = _asset(client, "character", "Ghost")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        _update_shot(client, scene["id"], shot["id"], characters=[{"asset_id": ghost["id"]}])
        client.delete(f"/api/film/projects/{PROJECT}/assets/{ghost['id']}")
        report = _continuity(client, shot["id"])
        # Deleting an asset may already scrub references; if not, the fix must.
        if report["level"] != "good":
            assert report["level"] == "broken"
            fixed = client.post(
                f"/api/film/projects/{PROJECT}/continuity/{shot['id']}/fix", json={"kind": "missing_asset"}
            ).json()
            assert fixed["fixed"] is True
            assert fixed["report"]["level"] == "good"

    def test_wardrobe_change_is_not_auto_fixable(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        sarah = _asset(client, "character", "Sarah", wardrobe="red coat")
        scene = _scene(client, character_ids=[sarah["id"]])
        first = _shot(client, scene["id"])
        second = _shot(client, scene["id"])
        for shot in (first, second):
            _update_shot(client, scene["id"], shot["id"], characters=[{"asset_id": sarah["id"]}])
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{first['id']}/generate", json={"kind": "preview"})
        client.put(f"/api/film/projects/{PROJECT}/assets/{sarah['id']}", json={"wardrobe": "blue dress"})
        report = _continuity(client, second["id"])
        assert report["level"] == "significant"
        warning = next(w for w in report["warnings"] if w["kind"] == "wardrobe_change")
        assert warning["auto_fixable"] is False
        fixed = client.post(
            f"/api/film/projects/{PROJECT}/continuity/{second['id']}/fix", json={"kind": "wardrobe_change"}
        ).json()
        assert fixed["fixed"] is False
        assert "creative decision" in fixed["message"]

    def test_project_wide_summary(self, client):
        scene = _scene(client)
        good = _shot(client, scene["id"])
        bad = _shot(client, scene["id"])
        _update_shot(client, scene["id"], bad["id"], duration_seconds=0)
        summary = client.get(f"/api/film/projects/{PROJECT}/continuity").json()
        assert summary["level"] == "broken"
        assert summary["counts"] == {"good": 1, "minor": 0, "significant": 0, "broken": 1}
        by_shot = {s["shot_id"]: s for s in summary["shots"]}
        assert by_shot[good["id"]]["level"] == "good"
        assert by_shot[bad["id"]]["level"] == "broken"
        assert by_shot[bad["id"]]["warning_count"] == 1


class TestQueueControls:
    def _prepared_shots(self, client, count: int) -> tuple[str, list[str]]:
        scene = _scene(client)
        return scene["id"], [_shot(client, scene["id"], description=f"beat {i}")["id"] for i in range(count)]

    def test_pause_holds_jobs_and_resume_drains(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        scene_id, shots = self._prepared_shots(client, 2)
        paused = client.post("/api/film/queue/pause").json()
        assert paused["status"] == "paused"
        assert paused["queue"]["paused"] is True
        for shot_id in shots:
            client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        queue = client.get("/api/film/queue").json()
        assert queue["active"] is None
        assert [j["shot_id"] for j in queue["pending"]] == shots
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert all(s["status"] == "queued" for s in project["scenes"][0]["shots"])
        # Resume: the fake task runner drains synchronously.
        resumed = client.post("/api/film/queue/resume").json()
        assert resumed["queue"]["paused"] is False
        assert resumed["queue"]["pending"] == []
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert all(s["versions"][0]["status"] == "complete" for s in project["scenes"][0]["shots"])

    def test_cancel_one_and_prioritize(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        scene_id, shots = self._prepared_shots(client, 3)
        client.post("/api/film/queue/pause")
        for shot_id in shots:
            client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        prioritized = client.post(f"/api/film/queue/{shots[2]}/prioritize").json()["queue"]
        assert [j["shot_id"] for j in prioritized["pending"]] == [shots[2], shots[0], shots[1]]
        cancelled = client.post(f"/api/film/queue/{shots[0]}/cancel").json()["queue"]
        assert [j["shot_id"] for j in cancelled["pending"]] == [shots[2], shots[1]]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        shot0 = next(s for s in project["scenes"][0]["shots"] if s["id"] == shots[0])
        assert shot0["versions"][0]["status"] == "cancelled"
        assert shot0["status"] != "queued"
        assert client.post("/api/film/queue/unknown/cancel").status_code == 404
        assert client.post("/api/film/queue/unknown/prioritize").status_code == 404
        client.post("/api/film/queue/resume")

    def test_restart_recovery_fails_stuck_jobs(self, client, test_state):
        """A process that died mid-generation leaves 'generating' on disk; a
        fresh handler must turn that into a failed, retryable version."""
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        store = test_state.film.store
        project = store.load(PROJECT)
        target = project.scenes[0].shots[0]
        from film.film_models import ShotVersion

        target.versions.append(ShotVersion(number=1, kind="preview", status="generating", prompt="x"))
        target.status = "generating"
        store.save(project)

        recovered = test_state.film_generation.recover_interrupted_jobs()
        assert recovered == 1
        stored = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]
        assert stored["id"] == shot["id"]
        assert stored["status"] == "composed"
        assert stored["versions"][0]["status"] == "failed"
        assert "restarted" in stored["versions"][0]["error"]
        # Idempotent.
        assert test_state.film_generation.recover_interrupted_jobs() == 0

    def test_queue_reports_progress_fields(self, client):
        queue = client.get("/api/film/queue").json()
        assert queue["paused"] is False
        assert queue["progress"] is None
        assert queue["phase"] == ""


class TestQualityProfiles:
    def test_profiles_recommend_by_vram(self, client, fake_services: FakeServices):
        fake_services.gpu_info.vram_gb = 12  # RTX 4070 class
        caps = client.get("/api/film/capabilities").json()
        profiles = {p["id"]: p for p in caps["profiles"]}
        assert set(profiles) == {"fast_preview", "balanced", "quality", "custom"}
        assert profiles["balanced"]["recommended"] is True
        assert profiles["balanced"]["model"] == "fast" and profiles["balanced"]["resolution"] == "720p"
        assert profiles["quality"]["model"] == "pro"
        fake_services.gpu_info.vram_gb = 24
        caps = client.get("/api/film/capabilities").json()
        assert next(p for p in caps["profiles"] if p["recommended"])["id"] == "quality"
        fake_services.gpu_info.vram_gb = 6
        caps = client.get("/api/film/capabilities").json()
        assert next(p for p in caps["profiles"] if p["recommended"])["id"] == "fast_preview"

    def test_final_render_uses_project_profile_unless_shot_overrides(
        self, client, test_state, create_fake_model_files, fake_services: FakeServices
    ):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        # Project default "balanced" → fast @ 720p.
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/generate", json={"kind": "final"})
        version = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["versions"][-1]
        assert (version["model"], version["resolution"]) == ("fast", "720p")
        # Shot preset "quality" → pro @ 1080p.
        _update_shot(client, scene["id"], shot["id"], generation={"quality_preset": "quality"})
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/generate", json={"kind": "final"})
        version = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["versions"][-1]
        assert (version["model"], version["resolution"]) == ("pro", "1080p")
        # Explicit resolution on the shot wins (custom), model falls back to the profile.
        _update_shot(client, scene["id"], shot["id"], generation={"quality_preset": "quality", "resolution": "540p"})
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/generate", json={"kind": "final"})
        version = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["versions"][-1]
        assert (version["model"], version["resolution"]) == ("pro", "540p")
        # Project default switches everything left on "project".
        client.put(
            f"/api/film/projects/{PROJECT}/settings",
            json={"settings": {"default_quality_preset": "fast_preview"}},
        )
        _update_shot(client, scene["id"], shot["id"], generation={"quality_preset": "project"})
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/generate", json={"kind": "final"})
        version = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["versions"][-1]
        assert (version["model"], version["resolution"]) == ("fast", "540p")


class TestModelRemoval:
    def test_remove_and_redownload_cycle(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        before = client.get("/api/models/status").json()
        assert next(m for m in before["models"] if "Upscaler" in m["description"])["downloaded"] is True
        response = client.delete("/api/models/upsampler")
        assert response.status_code == 200, response.text
        assert response.json()["downloaded"] is False
        after = client.get("/api/models/status").json()
        upsampler = next(m for m in after["models"] if "Upscaler" in m["description"])
        assert upsampler["downloaded"] is False
        assert not test_state.config.model_path("upsampler").exists()
        # Film capabilities agree and the download total now includes it again.
        caps = client.get("/api/film/capabilities").json()
        row = next(m for m in caps["models"] if m["id"] == "upsampler")
        assert row["download_state"] == "not_downloaded"

    def test_unknown_and_traversal_rejected(self, client):
        assert client.delete("/api/models/nope").status_code == 404
        assert client.delete("/api/models/..%2F..%2Fetc").status_code in (404, 400)

    def test_removal_refused_while_downloading(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        test_state.downloads.start_download({"checkpoint": ("x", 1)})
        assert client.delete("/api/models/checkpoint").status_code == 409


class TestSchemaAdditions:
    def test_old_project_json_gets_new_defaults(self, client, test_state):
        """Projects saved before quality presets existed load with the new
        defaults (additive schema change, no migration needed)."""
        store = test_state.film.store
        project_dir = store.project_dir("legacy-preset")
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "project.json").write_text(
            json.dumps({"schema_version": 1, "id": "legacy-preset", "settings": {"preview_resolution": "540p"}}),
            encoding="utf-8",
        )
        payload = client.get("/api/film/projects/legacy-preset").json()["project"]
        assert payload["settings"]["default_quality_preset"] == "balanced"
        scene = client.post("/api/film/projects/legacy-preset/scenes", json={}).json()
        shot = client.post(f"/api/film/projects/legacy-preset/scenes/{scene['id']}/shots", json={}).json()
        assert shot["generation"]["quality_preset"] == "project"
        assert Path(project_dir / "project.json").is_file()
