"""Integration tests for /api/film project/asset/scene/shot routes."""

from __future__ import annotations

import base64
import io

from PIL import Image

PROJECT = "test-project"


def _png_base64(color: tuple[int, int, int] = (200, 30, 30)) -> str:
    image = Image.new("RGB", (32, 18), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _create_scene(client, title: str = "Scene 1") -> str:
    response = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": title})
    assert response.status_code == 200
    return response.json()["id"]


def _create_shot(client, scene_id: str, **overrides) -> str:
    payload = {"title": "Shot", "duration_seconds": 4.0}
    payload.update(overrides)
    response = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json=payload
    )
    assert response.status_code == 200
    return response.json()["id"]


def _composition(framing: dict | None = None) -> dict:
    return {
        "objects": [
            {
                "name": "Sarah",
                "type": "figure",
                "transform": {
                    "position": [0, 0, 0],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                },
                "pose": {"l_arm": [0, 0, 45]},
            }
        ],
        "camera": {
            "name": "Camera",
            "type": "camera",
            "transform": {"position": [0, 1.5, 3], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
            "fov": 40,
        },
        "framing": framing
        or {
            "shot_size": "medium",
            "camera_angle": "front",
            "camera_elevation": "eye",
            "composition": "center",
            "fov_deg": 40,
        },
        "camera_move": "push_in",
        "duration_seconds": 4.0,
    }


class TestFilmProject:
    def test_auto_creates_empty_project(self, client):
        response = client.get(f"/api/film/projects/{PROJECT}")
        assert response.status_code == 200
        project = response.json()["project"]
        assert project["id"] == PROJECT
        assert project["schema_version"] == 1
        assert project["scenes"] == []

    def test_script_update_persists(self, client):
        response = client.put(
            f"/api/film/projects/{PROJECT}/script", json={"content": "INT. LAB - NIGHT"}
        )
        assert response.status_code == 200
        reloaded = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert reloaded["script"]["content"] == "INT. LAB - NIGHT"

    def test_settings_update(self, client):
        response = client.put(
            f"/api/film/projects/{PROJECT}/settings",
            json={
                "settings": {
                    "default_model": "fast",
                    "default_resolution": "720p",
                    "style_prompt": "noir",
                    "default_negative_prompt": "blurry",
                    "inter_shot_gap_seconds": 0.5,
                    "strict_continuity": False,
                    "preview_resolution": "540p",
                    "preview_max_seconds": 3.0,
                }
            },
        )
        assert response.status_code == 200
        assert response.json()["project"]["settings"]["style_prompt"] == "noir"

    def test_invalid_project_id_400(self, client):
        response = client.get("/api/film/projects/..%2Fescape")
        assert response.status_code in (400, 404)


class TestAssets:
    def test_asset_crud(self, client):
        created = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "Sarah", "wardrobe": "red coat"},
        )
        assert created.status_code == 200
        asset_id = created.json()["asset"]["id"]

        updated = client.put(
            f"/api/film/projects/{PROJECT}/assets/{asset_id}", json={"wardrobe": "blue coat"}
        )
        assert updated.status_code == 200
        assert updated.json()["asset"]["wardrobe"] == "blue coat"

        deleted = client.delete(f"/api/film/projects/{PROJECT}/assets/{asset_id}")
        assert deleted.status_code == 200
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["assets"] == []

    def test_asset_requires_name(self, client):
        response = client.post(
            f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "  "}
        )
        assert response.status_code == 400

    def test_asset_reference_image_saved(self, client, test_state):
        asset_id = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "location", "name": "Cafe"},
        ).json()["asset"]["id"]
        response = client.post(
            f"/api/film/projects/{PROJECT}/assets/{asset_id}/references",
            json={"image_base64": _png_base64(), "name_hint": "cafe-ref"},
        )
        assert response.status_code == 200
        references = response.json()["asset"]["reference_images"]
        assert len(references) == 1
        media = client.get(
            f"/api/film/projects/{PROJECT}/media", params={"path": references[0]}
        )
        assert media.status_code == 200
        assert media.content.startswith(b"\x89PNG")

    def test_deleting_asset_scrubs_references(self, client):
        asset_id = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "Ghost"},
        ).json()["asset"]["id"]
        scene_id = _create_scene(client)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}",
            json={"character_ids": [asset_id]},
        )
        shot_id = _create_shot(client, scene_id)
        client.delete(f"/api/film/projects/{PROJECT}/assets/{asset_id}")
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        scene = project["scenes"][0]
        assert scene["character_ids"] == []
        shot = scene["shots"][0]
        assert all(c["asset_id"] != asset_id for c in shot["characters"])
        assert shot_id == shot["id"]


class TestScenesAndShots:
    def test_scene_and_shot_lifecycle(self, client):
        scene_id = _create_scene(client, "Opening")
        shot_id = _create_shot(client, scene_id, title="Establishing", duration_seconds=4.5)

        updated = client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}",
            json={"action": "Sunlight cuts across empty tables"},
        )
        assert updated.status_code == 200
        shot = updated.json()
        assert shot["action"] == "Sunlight cuts across empty tables"
        assert "Sunlight" in shot["visual_prompt"]  # prompt synthesized from fields

        deleted = client.delete(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}"
        )
        assert deleted.status_code == 200

    def test_shot_inherits_scene_cast(self, client):
        asset_id = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "Sarah"},
        ).json()["asset"]["id"]
        scene_id = _create_scene(client)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}",
            json={"character_ids": [asset_id]},
        )
        shot_id = _create_shot(client, scene_id)
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        shot = project["scenes"][0]["shots"][0]
        assert shot["id"] == shot_id
        assert shot["characters"][0]["asset_id"] == asset_id

    def test_shot_reorder(self, client):
        scene_id = _create_scene(client)
        first = _create_shot(client, scene_id, title="one")
        second = _create_shot(client, scene_id, title="two")
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/reorder",
            json={"ordered_ids": [second, first]},
        )
        assert response.status_code == 200
        titles = [s["title"] for s in response.json()["shots"]]
        assert titles == ["two", "one"]

    def test_shot_reorder_rejects_partial_permutation(self, client):
        scene_id = _create_scene(client)
        first = _create_shot(client, scene_id)
        _create_shot(client, scene_id)
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/reorder",
            json={"ordered_ids": [first]},
        )
        assert response.status_code == 400

    def test_scene_reorder(self, client):
        first = _create_scene(client, "A")
        second = _create_scene(client, "B")
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/reorder",
            json={"ordered_ids": [second, first]},
        )
        assert response.status_code == 200
        titles = [s["title"] for s in response.json()["project"]["scenes"]]
        assert titles == ["B", "A"]

    def test_duplicate_shot_resets_outputs(self, client):
        scene_id = _create_scene(client)
        shot_id = _create_shot(client, scene_id, title="Original")
        capture = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/capture",
            json={"image_base64": _png_base64(), "composition": _composition()},
        )
        assert capture.status_code == 200
        duplicated = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/duplicate"
        )
        assert duplicated.status_code == 200
        copy = duplicated.json()
        assert copy["title"] == "Original (copy)"
        assert copy["capture_path"] == ""
        assert copy["versions"] == []
        assert copy["composition"] is not None  # composition carried over
        assert copy["status"] == "composed"

    def test_missing_ids_404(self, client):
        assert client.put(
            f"/api/film/projects/{PROJECT}/scenes/nope", json={"title": "x"}
        ).status_code == 404
        scene_id = _create_scene(client)
        assert client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/nope", json={}
        ).status_code == 404


class TestCapture:
    def test_capture_persists_image_and_composition(self, client, test_state):
        scene_id = _create_scene(client)
        shot_id = _create_shot(client, scene_id)
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/capture",
            json={"image_base64": _png_base64(), "composition": _composition()},
        )
        assert response.status_code == 200
        shot = response.json()
        assert shot["capture_path"] == f"captures/{shot_id}.png"
        assert shot["status"] == "ready"
        # Framing/camera-move sync from composition.
        assert shot["camera_move"] == "push_in"

        media = client.get(
            f"/api/film/projects/{PROJECT}/media", params={"path": shot["capture_path"]}
        )
        assert media.status_code == 200
        assert media.content.startswith(b"\x89PNG")

        # Reload from disk: composition survives a full round trip.
        reloaded = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        composition = reloaded["scenes"][0]["shots"][0]["composition"]
        assert composition["objects"][0]["pose"]["l_arm"] == [0, 0, 45]

    def test_capture_rejects_non_png(self, client):
        scene_id = _create_scene(client)
        shot_id = _create_shot(client, scene_id)
        bogus = base64.b64encode(b"definitely not a png").decode()
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/capture",
            json={"image_base64": bogus, "composition": _composition()},
        )
        assert response.status_code == 400

    def test_media_path_traversal_400(self, client):
        client.get(f"/api/film/projects/{PROJECT}")  # ensure project exists
        response = client.get(
            f"/api/film/projects/{PROJECT}/media", params={"path": "../../etc/passwd"}
        )
        assert response.status_code == 400


class TestPoses:
    def test_pose_save_and_delete(self, client):
        response = client.post(
            f"/api/film/projects/{PROJECT}/poses",
            json={"name": "Hero Stance", "joints": {"l_arm": [0, 0, 80], "r_arm": [0, 0, -80]}},
        )
        assert response.status_code == 200
        pose = response.json()["pose"]
        assert pose["name"] == "Hero Stance"

        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert len(project["pose_library"]) == 1

        deleted = client.delete(f"/api/film/projects/{PROJECT}/poses/{pose['id']}")
        assert deleted.status_code == 200

    def test_pose_same_name_replaces(self, client):
        for arm in (10, 20):
            client.post(
                f"/api/film/projects/{PROJECT}/poses",
                json={"name": "Wave", "joints": {"l_arm": [0, 0, arm]}},
            )
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        waves = [p for p in project["pose_library"] if p["name"] == "Wave"]
        assert len(waves) == 1
        assert waves[0]["joints"]["l_arm"] == [0, 0, 20]


class TestContinuity:
    def test_warnings_for_missing_capture_and_scene_mismatch(self, client):
        sarah = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "Sarah"},
        ).json()["asset"]["id"]
        cafe = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "location", "name": "Cafe"},
        ).json()["asset"]["id"]
        street = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "location", "name": "Street"},
        ).json()["asset"]["id"]
        john = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "John"},
        ).json()["asset"]["id"]
        scene_id = _create_scene(client)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}",
            json={"location_id": cafe, "character_ids": [john]},
        )
        shot_id = _create_shot(client, scene_id)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}",
            json={
                "location_id": street,
                "characters": [{"asset_id": sarah, "pose_name": "", "emotion": "", "position_hint": ""}],
            },
        )
        response = client.get(f"/api/film/projects/{PROJECT}/continuity/{shot_id}")
        assert response.status_code == 200
        kinds = {w["kind"] for w in response.json()["warnings"]}
        assert "location_mismatch" in kinds
        assert "character_not_in_scene" in kinds
        assert "missing_capture" in kinds
