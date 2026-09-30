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
