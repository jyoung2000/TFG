"""A picture for every storyboard beat.

Asked 2026-10-01: the storyboard should have an image of the scene it is
describing next to each line or bit, in every area. Found: a shot only had a
picture once it was rendered, captured in the composer or built from a
video (a 3D blockout); a storyboard written from a script was text only.
Each shot can now get a storyboard frame - its own still, kept apart from
the composer capture that feeds the video model - composed with the cast's
reference images when FLUX.2 can, so the characters stay the same.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_asset_angles import FLUX2, _png
from tests.test_training import PROJECT


def _shot(client, title: str = "Shot", action: str = "Sarah tears the letter open", characters: list[str] | None = None) -> tuple[str, str]:
    scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Coffee shop"}).json()["id"]
    if characters:
        client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}", json={"character_ids": characters})
    shot_id = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json={"title": title, "duration_seconds": 4.0, "action": action}).json()["id"]
    return scene_id, shot_id


def _project(client) -> dict:
    return client.get(f"/api/film/projects/{PROJECT}").json()["project"]


def _find_shot(project: dict, shot_id: str) -> dict:
    return next(s for scene in project["scenes"] for s in scene["shots"] if s["id"] == shot_id)


class TestStoryboardFrames:
    def test_a_shot_gets_a_frame_of_what_it_describes(self, client, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        scene_id, shot_id = _shot(client)
        response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
        assert response.status_code == 200, response.text
        frame = _find_shot(_project(client), shot_id)["frame_path"]
        assert frame
        assert client.get(f"/api/film/projects/{PROJECT}/media", params={"path": frame}).status_code == 200
        assert _find_shot(_project(client), shot_id)["capture_path"] == "", "the composer capture (the video's start frame) is untouched"

    def test_the_whole_storyboard_gets_frames_where_it_has_none(self, client, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        _, first = _shot(client, "One")
        scene_id, second = _shot(client, "Two", "John walks through the rain")
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{second}/frame", json={})
        kept = _find_shot(_project(client), second)["frame_path"]
        response = client.post(f"/api/film/projects/{PROJECT}/frames", json={"missing_only": True})
        assert response.status_code == 200, response.text
        assert response.json()["generated"] >= 1
        project = _project(client)
        assert _find_shot(project, first)["frame_path"]
        assert _find_shot(project, second)["frame_path"] == kept, "a shot that had a frame keeps it"

    def test_the_cast_stays_the_same_person_in_every_frame(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions.append(FLUX2)
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Sarah"}).json()["asset"]
        asset = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": _png((10, 120, 200)), "name_hint": "front"}).json()["asset"]
        scene_id, shot_id = _shot(client, characters=[asset["id"]])
        client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}", json={"characters": [{"asset_id": asset["id"]}]})
        assert client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={}).status_code == 200
        params = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" in m[0]["params"]][-1]
        assert params["model_type"] == "flux2_klein_4b" and params["video_prompt_type"] == "I"
        assert [Path(p).name for p in params["image_refs"]] == [Path(asset["reference_images"][0]).name]
