"""Reproduce feeds the storyboard, the composer (3D) and the assets.

Found by a read of the code (2026-09-30):
- image reproduce computed `spec.layout3d` + depth that nothing used, and its
  "Send to Composer" button was disabled - there was no way to turn an image
  job into a storyboard shot;
- video reproduce built its film project with `reconstruct`, not the 3D
  storyboard seeding, so reproduced shots had no composition or blockout;
- the character assets `reconstruct` creates had no reference images;
- composer figures seeded from a layout were never linked to the shot's cast;
- a picked video take did not become the film shot's current version.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from tests.test_video_reproduce import _analysed


def _image_job(client, create_fake_model_files, tmp_path: Path) -> dict:
    create_fake_model_files(include_zit=True)
    client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
    source = tmp_path / "reference.png"
    Image.new("RGB", (128, 72), (30, 30, 220)).save(source)
    imported = client.post("/api/reproduce/import", json={"path": str(source)}).json()
    return client.post(f"/api/reproduce/{imported['id']}/analyze").json()


class TestImageJobToStoryboard:
    def test_an_image_job_becomes_a_composed_shot_with_cast_assets(self, client, create_fake_model_files, tmp_path, test_state):
        job = _image_job(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        r = client.post(f"/api/reproduce/{job['id']}/storyboard", json={})
        assert r.status_code == 200, r.text
        link = r.json()
        project = test_state.film.get_project(link["project_id"])
        found = project.find_shot(link["shot_id"])
        assert found is not None
        _, shot = found
        done = client.get(f"/api/reproduce/{job['id']}").json()
        # The prompt and the chosen image travel with the shot.
        assert shot.visual_prompt == done["prompt"] and shot.prompt_locked
        assert shot.capture_path and test_state.film.store.resolve_media_path(project.id, shot.capture_path).is_file()
        # The job's 3D layout seeded the composer.
        assert shot.composition is not None and shot.blockout_path
        figures = [o for o in shot.composition.objects if o.type == "figure"]
        assert figures, "the detected person became no composer figure"
        # The person became a character asset with a reference image, cast on
        # the shot, and the composer figure is linked to it.
        cast = [project.asset(c.asset_id) for c in shot.characters]
        assert cast and all(a is not None and a.kind == "character" for a in cast)
        refs = cast[0].reference_images  # type: ignore[union-attr]
        assert refs and test_state.film.store.resolve_media_path(project.id, refs[0]).is_file()
        assert figures[0].asset_id == cast[0].id  # type: ignore[union-attr]

    def test_sending_again_updates_the_same_shot(self, client, create_fake_model_files, tmp_path):
        job = _image_job(client, create_fake_model_files, tmp_path)
        first = client.post(f"/api/reproduce/{job['id']}/storyboard", json={}).json()
        second = client.post(f"/api/reproduce/{job['id']}/storyboard", json={}).json()
        assert (second["project_id"], second["shot_id"]) == (first["project_id"], first["shot_id"])


class TestVideoReproduceSeedsTheStoryboard:
    def test_reproduced_shots_are_composed_and_edits_survive(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot_id = analysed["shots"][0]["id"]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [shot_id]})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        project = test_state.film.get_project(job["project_id"])
        film_shot = project.find_shot(job["shots"][0]["film_shot_id"])[1]  # type: ignore[index]
        assert film_shot.composition is not None and film_shot.blockout_path

        # A composer edit is not overwritten by the next run.
        film_shot.composition.duration_seconds = 9.25
        test_state.film.store.save(project)
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [shot_id]})
        again = test_state.film.get_project(job["project_id"]).find_shot(film_shot.id)[1]  # type: ignore[index]
        assert again.composition is not None and again.composition.duration_seconds == 9.25

    def test_reconstructed_characters_get_a_reference_frame(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [analysed["shots"][0]["id"]]})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        project = test_state.film.get_project(job["project_id"])
        characters = [a for a in project.assets if a.kind == "character"]
        assert characters, "the analysis named no character"
        for asset in characters:
            assert asset.reference_images, asset.name
            assert test_state.film.store.resolve_media_path(project.id, asset.reference_images[0]).is_file()

    def test_a_picked_take_becomes_the_shots_current_version(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot_id = analysed["shots"][0]["id"]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 2, "rounds": 1, "shot_ids": [shot_id]})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        shot = job["shots"][0]
        current = test_state.film.get_project(job["project_id"]).find_shot(shot["film_shot_id"])[1].current_version  # type: ignore[index]
        other = next(c for c in shot["candidates"] if c["version_number"] != current)
        assert client.post(f"/api/video-reproduce/{analysed['id']}/shots/{shot_id}/pick/{other['id']}").status_code == 200
        film_shot = test_state.film.get_project(job["project_id"]).find_shot(shot["film_shot_id"])[1]  # type: ignore[index]
        assert film_shot.current_version == other["version_number"]


class TestTheStoryboardShowsWhatTheLoopChose:
    """Asked 2026-10-01: video reproduce should produce the storyboard and
    show which model and prompt made each take. Found: the film queue made
    every finished take the shot's current version, so the storyboard showed
    the last take rather than the best; and a take recorded the job's default
    model (LTX-2) while VACE 1.3B rendered it."""

    def test_the_best_take_is_the_storyboard_shots_current_version(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot_id = analysed["shots"][0]["id"]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 2, "rounds": 1, "shot_ids": [shot_id]})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        shot = job["shots"][0]
        chosen = next(c for c in shot["candidates"] if c["id"] == shot["picked_candidate_id"])
        assert len([c for c in shot["candidates"] if c["status"] == "complete"]) == 2
        film_shot = test_state.film.get_project(job["project_id"]).find_shot(shot["film_shot_id"])[1]  # type: ignore[index]
        assert film_shot.current_version == chosen["version_number"]

    def test_each_take_records_the_model_that_rendered_it(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions.append({"id": "vace_1.3B", "name": "Vace 1.3B", "installed": True})
        shot_id = analysed["shots"][0]["id"]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [shot_id]})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        take = job["shots"][0]["candidates"][0]
        assert take["status"] == "complete", take
        assert take["model"] == "vace_1.3B"
        film_shot = test_state.film.get_project(job["project_id"]).find_shot(job["shots"][0]["film_shot_id"])[1]  # type: ignore[index]
        assert film_shot.version(take["version_number"]).render_model == "vace_1.3B"  # type: ignore[union-attr]


class TestAnImageRunEndsComposed:
    """Asked 2026-10-01: "when reproducing images a composite should already
    be made". The composed storyboard shot existed only after Send to
    Composer; a finished loop now makes it itself."""

    def test_a_finished_loop_has_its_storyboard_shot_and_composition(self, client, create_fake_model_files, tmp_path, test_state):
        job = _image_job(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert done["candidates"], done["status"]
        assert done["storyboard_project_id"] and done["storyboard_shot_id"], "no storyboard shot without Send to Composer"
        _, shot = test_state.film.get_project(done["storyboard_project_id"]).find_shot(done["storyboard_shot_id"])  # type: ignore[misc]
        assert shot.composition is not None and shot.blockout_path
        assert shot.visual_prompt == done["prompt"]


    def test_a_composer_edit_survives_the_next_run(self, client, create_fake_model_files, tmp_path, test_state):
        """Every run now updates its storyboard shot; a run must not undo the user's composer work."""
        job = _image_job(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        project = test_state.film.get_project(done["storyboard_project_id"])
        shot = project.find_shot(done["storyboard_shot_id"])[1]  # type: ignore[index]
        shot.composition.duration_seconds = 7.75  # type: ignore[union-attr]
        test_state.film.store.save(project)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 2}})
        again = test_state.film.get_project(done["storyboard_project_id"]).find_shot(done["storyboard_shot_id"])[1]  # type: ignore[index]
        assert again.composition.duration_seconds == 7.75  # type: ignore[union-attr]


class TestTheComposedImageTakesThePhotosPose:
    """Asked 2026-10-01 (screenshot): the composer's mannequin stood at
    attention while the woman in the photo has her hands on her hips."""

    def test_the_storyboard_figure_is_posed_like_the_person(self, client, create_fake_model_files, tmp_path, test_state, fake_services):
        from services.vision.protocol import PosePerson
        from tests.test_pose import HANDS_ON_HIPS

        fake_services.vision.pose_override = [PosePerson(bbox=[0.2, 0.05, 0.62, 0.88], score=0.9, keypoints=HANDS_ON_HIPS)]
        fake_services.vision.regions_override = None
        job = _image_job(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert done["spec"]["poses"], "the analysis kept no pose"
        shot = test_state.film.get_project(done["storyboard_project_id"]).find_shot(done["storyboard_shot_id"])[1]  # type: ignore[index]
        figures = [o for o in shot.composition.objects if o.type == "figure"]  # type: ignore[union-attr]
        assert figures and figures[0].pose.get("l_elbow", (0, 0, 0))[2] < -60, figures[0].pose if figures else None


class TestOldImageShotsAreReseededWhenOpened:
    """Asked 2026-10-01 (screenshot, "the pose isnt 100% correct"): the
    composer showed a mannequin standing at rest beside a photo of a woman
    with her hands on her hips. That shot was seeded by an older version (v4),
    with no figure, and image shots were only ever seeded right after a
    reproduce run - opening the storyboard never refreshed them, as it does
    for video shots."""

    def _old_shot(self, client, create_fake_model_files, tmp_path, test_state, fake_services):
        from handlers.scene_handler import seed_fingerprint
        from services.vision.protocol import PosePerson
        from tests.test_pose import HANDS_ON_HIPS

        fake_services.vision.regions_override = None
        job = _image_job(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        # The job predates pose reading; the shot holds an untouched v4 seed without figures.
        stored = test_state.reproduce.get(job["id"])
        stored.spec.poses = []
        stored.spec.provenance.pop("poses", None)
        test_state.reproduce._save(stored)
        project = test_state.film.get_project(done["storyboard_project_id"])
        shot = project.find_shot(done["storyboard_shot_id"])[1]  # type: ignore[index]
        old = shot.composition.model_copy(update={"objects": []})  # type: ignore[union-attr]
        old.seed = f"v4:{seed_fingerprint(old)}"
        shot.composition = old
        test_state.film.store.save(project)
        fake_services.vision.pose_override = [PosePerson(bbox=[0.2, 0.05, 0.62, 0.88], score=0.9, keypoints=HANDS_ON_HIPS)]
        return done

    def test_opening_the_project_poses_the_figure_like_the_photo(self, client, create_fake_model_files, tmp_path, test_state, fake_services):
        done = self._old_shot(client, create_fake_model_files, tmp_path, test_state, fake_services)
        project = client.get(f"/api/film/projects/{done['storyboard_project_id']}").json()["project"]
        shot = next(s for sc in project["scenes"] for s in sc["shots"] if s["id"] == done["storyboard_shot_id"])
        composition = shot["composition"]
        from handlers.scene_handler import SEED_VERSION

        assert composition["seed"].startswith(f"v{SEED_VERSION}:"), composition["seed"]
        figures = [o for o in composition["objects"] if o["type"] == "figure"]
        assert figures, "still no figure for the person in the photo"
        assert figures[0]["pose"].get("l_elbow", [0, 0, 0])[2] < -60, figures[0]["pose"]

    def test_a_scene_the_user_edited_is_left_alone(self, client, create_fake_model_files, tmp_path, test_state, fake_services):
        done = self._old_shot(client, create_fake_model_files, tmp_path, test_state, fake_services)
        project = test_state.film.get_project(done["storyboard_project_id"])
        shot = project.find_shot(done["storyboard_shot_id"])[1]  # type: ignore[index]
        shot.composition.duration_seconds = 6.5  # type: ignore[union-attr]  (an edit: the seed no longer matches)
        test_state.film.store.save(project)
        again = client.get(f"/api/film/projects/{done['storyboard_project_id']}").json()["project"]
        kept = next(s for sc in again["scenes"] for s in sc["shots"] if s["id"] == done["storyboard_shot_id"])["composition"]
        assert kept["seed"].startswith("v4:") and kept["duration_seconds"] == 6.5 and kept["objects"] == []
