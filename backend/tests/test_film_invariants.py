"""ONE SHOT STATE invariants and the director's composition tools.

The storyboard card, the Shot Composer and the AI Director all edit the same
``FilmShot`` (cast, framing, composition). These tests prove the sync in both
directions, that director tools mutate that single record, and that the
deterministic camera-continuity checks fire on real composer geometry.
"""

from __future__ import annotations

import math

from film.film_continuity import camera_continuity_warnings
from film.film_models import CompositionObject, CompositionScene, CompositionTransform, FilmShot, ShotCharacter

PROJECT = "invariant-project"


def _asset(client, kind: str, name: str) -> dict:
    response = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": kind, "name": name})
    assert response.status_code == 200, response.text
    return response.json()["asset"]


def _scene(client, **kwargs) -> dict:
    payload = {"title": "Scene", **kwargs}
    response = client.post(f"/api/film/projects/{PROJECT}/scenes", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _shot(client, scene_id: str, **kwargs) -> dict:
    payload = {"title": "Shot", "description": "a beat", **kwargs}
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _update(client, scene_id: str, shot_id: str, **kwargs) -> dict:
    response = client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def _get_shot(client, shot_id: str) -> dict:
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    for scene in project["scenes"]:
        for shot in scene["shots"]:
            if shot["id"] == shot_id:
                return shot
    raise AssertionError(f"shot {shot_id} missing")


def _command(client, name: str, **params) -> dict:
    response = client.post(f"/api/film/projects/{PROJECT}/director/command", json={"name": name, "params": params})
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def _figure(name: str, asset_id: str | None, position: tuple[float, float, float]) -> dict:
    return {
        "name": name,
        "type": "figure",
        "asset_id": asset_id,
        "transform": {"position": list(position), "rotation": [0, 0, 0], "scale": [1, 1, 1]},
    }


def _camera(position: tuple[float, float, float]) -> dict:
    return {
        "name": "Camera",
        "type": "camera",
        "transform": {"position": list(position), "rotation": [0, 0, 0], "scale": [1, 1, 1]},
        "fov": 40,
    }


class TestCastCompositionSync:
    def test_composer_figure_linked_to_character_joins_cast(self, client):
        mara = _asset(client, "character", "Mara")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        assert shot["characters"] == []
        updated = _update(
            client,
            scene["id"],
            shot["id"],
            composition={"objects": [_figure("Mara", mara["id"], (0, 0, 0))], "camera": _camera((0, 1.6, 4))},
        )
        assert [c["asset_id"] for c in updated["characters"]] == [mara["id"]]

    def test_assigning_character_adds_figure_and_unassigning_removes_it(self, client):
        mara = _asset(client, "character", "Mara")
        lamp = _asset(client, "prop", "Lamp")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        # Open the composer once (empty scene) so the shot carries a composition.
        _update(client, scene["id"], shot["id"], composition={"objects": [], "camera": _camera((0, 1.6, 4))})
        updated = _update(client, scene["id"], shot["id"], characters=[{"asset_id": mara["id"]}], prop_ids=[lamp["id"]])
        objects = updated["composition"]["objects"]
        by_asset = {o["asset_id"]: o for o in objects}
        assert by_asset[mara["id"]]["type"] == "figure"
        assert by_asset[lamp["id"]]["type"] == "cube"
        # Unassign both: the linked objects disappear, the composition stays.
        cleared = _update(client, scene["id"], shot["id"], characters=[], prop_ids=[])
        assert cleared["composition"]["objects"] == []

    def test_unlinked_objects_survive_cast_changes(self, client):
        mara = _asset(client, "character", "Mara")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        updated = _update(
            client,
            scene["id"],
            shot["id"],
            composition={
                "objects": [_figure("Extra", None, (2, 0, 0)), _figure("Mara", mara["id"], (0, 0, 0))],
                "camera": _camera((0, 1.6, 4)),
            },
        )
        assert len(updated["composition"]["objects"]) == 2
        cleared = _update(client, scene["id"], shot["id"], characters=[])
        assert [o["name"] for o in cleared["composition"]["objects"]] == ["Extra"]

    def test_framing_is_the_composition_framing(self, client):
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        updated = _update(
            client,
            scene["id"],
            shot["id"],
            composition={
                "objects": [],
                "camera": _camera((0, 1.6, 4)),
                "framing": {"shot_size": "closeup", "camera_angle": "threeQuarterLeft", "ots_shoulder": "right", "camera_mode": "manual"},
            },
        )
        assert updated["framing"]["shot_size"] == "closeup"
        assert updated["framing"]["ots_shoulder"] == "right"
        assert updated["framing"]["camera_mode"] == "manual"
        assert updated["framing"] == updated["composition"]["framing"]

    def test_stale_ots_ids_are_cleared_when_object_leaves(self, client):
        mara = _asset(client, "character", "Mara")
        theo = _asset(client, "character", "Theo")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        updated = _update(
            client,
            scene["id"],
            shot["id"],
            composition={
                "objects": [_figure("Mara", mara["id"], (-0.5, 0, 0)), _figure("Theo", theo["id"], (0.5, 0, 0))],
                "camera": _camera((0, 1.6, 4)),
            },
        )
        objects = {o["asset_id"]: o["id"] for o in updated["composition"]["objects"]}
        with_ots = _update(
            client,
            scene["id"],
            shot["id"],
            composition={
                **updated["composition"],
                "framing": {
                    **updated["composition"]["framing"],
                    "camera_angle": "ots",
                    "ots_foreground_id": objects[mara["id"]],
                    "ots_subject_id": objects[theo["id"]],
                },
            },
        )
        assert with_ots["framing"]["ots_foreground_id"] == objects[mara["id"]]
        # Drop Theo from the cast: the subject id must not dangle.
        dropped = _update(client, scene["id"], shot["id"], characters=[{"asset_id": mara["id"]}])
        assert dropped["framing"]["ots_subject_id"] is None
        assert dropped["framing"]["ots_foreground_id"] == objects[mara["id"]]


class TestDirectorCompositionTools:
    def _two_character_shot(self, client) -> tuple[str, str, str, str]:
        mara = _asset(client, "character", "Mara")
        theo = _asset(client, "character", "Theo")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        _update(client, scene["id"], shot["id"], characters=[{"asset_id": mara["id"]}, {"asset_id": theo["id"]}])
        return scene["id"], shot["id"], mara["id"], theo["id"]

    def test_position_rotate_scale_mutate_the_shot_composition(self, client):
        _, shot_id, mara_id, _ = self._two_character_shot(client)
        positioned = _command(client, "position_object", shot_id=shot_id, target="Mara", hint="foreground left")
        assert positioned["ok"], positioned["error"]
        assert positioned["result"]["position"] == [-0.9, 0.0, 1.2]
        rotated = _command(client, "rotate_object", shot_id=shot_id, target="mara", yaw_degrees=90)
        assert rotated["ok"]
        scaled = _command(client, "scale_object", shot_id=shot_id, target=mara_id, scale=1.1)
        assert scaled["ok"]
        shot = _get_shot(client, shot_id)
        obj = next(o for o in shot["composition"]["objects"] if o["asset_id"] == mara_id)
        assert obj["transform"]["position"] == [-0.9, 0.0, 1.2]
        assert math.isclose(obj["transform"]["rotation"][1], math.pi / 2)
        assert obj["transform"]["scale"] == [1.1, 1.1, 1.1]
        # The cast is unchanged: the composer seeded from it, not a copy.
        assert len(shot["characters"]) == 2
        assert len(shot["composition"]["objects"]) == 2

    def test_locked_object_refuses_director_moves(self, client):
        scene_id, shot_id, mara_id, _ = self._two_character_shot(client)
        seeded = _command(client, "get_composition", shot_id=shot_id)
        assert seeded["ok"] and seeded["result"] is None  # not saved until a tool writes
        _command(client, "position_object", shot_id=shot_id, target="Mara", x=1)
        shot = _get_shot(client, shot_id)
        composition = shot["composition"]
        for obj in composition["objects"]:
            if obj["asset_id"] == mara_id:
                obj["locked"] = True
        _update(client, scene_id, shot_id, composition=composition)
        refused = _command(client, "position_object", shot_id=shot_id, target="Mara", x=2)
        assert refused["ok"] is False
        assert "locked" in refused["error"]
        assert _get_shot(client, shot_id)["composition"]["objects"][0]["transform"]["position"][0] == 1

    def test_unknown_target_and_bad_hint(self, client):
        _, shot_id, _, _ = self._two_character_shot(client)
        missing = _command(client, "position_object", shot_id=shot_id, target="Nobody", x=1)
        assert missing["ok"] is False and "No composer object" in missing["error"]
        bad = _command(client, "position_object", shot_id=shot_id, target="Mara", hint="upstairs")
        assert bad["ok"] is False and "placement hint" in bad["error"]
        bad_scale = _command(client, "scale_object", shot_id=shot_id, target="Mara", scale=100)
        assert bad_scale["ok"] is False

    def test_set_ots_changes_framing_and_ensures_cast(self, client):
        mara = _asset(client, "character", "Mara")
        theo = _asset(client, "character", "Theo")
        scene = _scene(client)
        shot = _shot(client, scene["id"])
        result = _command(client, "set_ots", shot_id=shot["id"], foreground="Mara", subject="Theo", shoulder="right")
        assert result["ok"], result["error"]
        updated = _get_shot(client, shot["id"])
        assert {c["asset_id"] for c in updated["characters"]} == {mara["id"], theo["id"]}
        framing = updated["framing"]
        assert framing["camera_angle"] == "ots"
        assert framing["ots_shoulder"] == "right"
        objects = {o["asset_id"]: o["id"] for o in updated["composition"]["objects"]}
        assert framing["ots_foreground_id"] == objects[mara["id"]]
        assert framing["ots_subject_id"] == objects[theo["id"]]
        assert updated["composition"]["framing"] == framing
        bad = _command(client, "set_ots", shot_id=shot["id"], foreground="Mara", subject="Theo", shoulder="middle")
        assert bad["ok"] is False

    def test_set_camera_switches_to_manual_and_aims_at_target(self, client):
        _, shot_id, _, _ = self._two_character_shot(client)
        _command(client, "position_object", shot_id=shot_id, target="Theo", x=0, y=0, z=-3)
        result = _command(client, "set_camera", shot_id=shot_id, x=0, y=1.6, z=3, look_at="Theo", fov_deg=35)
        assert result["ok"], result["error"]
        shot = _get_shot(client, shot_id)
        camera = shot["composition"]["camera"]
        assert camera["transform"]["position"] == [0, 1.6, 3]
        assert camera["fov"] == 35
        assert shot["framing"]["camera_mode"] == "manual"
        assert shot["framing"]["fov_deg"] == 35
        # Looking down -z from +z: yaw lands on pi (atan2(0,-6) + pi = 2pi) and pitch is slightly down.
        pitch, yaw, _ = camera["transform"]["rotation"]
        assert pitch < 0
        assert math.isclose(yaw % (2 * math.pi), 0.0, abs_tol=1e-6)
        # A preset tool switches the camera back to preset mode.
        preset = _command(client, "set_ots", shot_id=shot_id, foreground="Mara", subject="Theo")
        assert preset["ok"]
        assert _get_shot(client, shot_id)["framing"]["camera_mode"] == "preset"

    def test_keyframes_for_camera_and_object(self, client):
        _, shot_id, mara_id, _ = self._two_character_shot(client)
        first = _command(client, "add_keyframe", shot_id=shot_id, target="camera", time=0, x=0, y=1.6, z=4)
        second = _command(client, "add_keyframe", shot_id=shot_id, target="camera", time=3, x=1, y=1.6, z=2, fov_deg=30)
        assert first["ok"] and second["ok"]
        assert second["result"]["count"] == 2
        walk = _command(client, "add_keyframe", shot_id=shot_id, target="Mara", time=2, x=2, yaw_degrees=45)
        assert walk["ok"], walk["error"]
        moved = _command(client, "update_keyframe", shot_id=shot_id, keyframe_id=second["result"]["keyframe_id"], time=1.5, z=1)
        assert moved["ok"] and moved["result"]["time"] == 1.5
        shot = _get_shot(client, shot_id)
        camera_keys = shot["composition"]["camera"]["keyframes"]
        assert [k["time"] for k in camera_keys] == [0, 1.5]
        assert camera_keys[1]["transform"]["position"] == [1, 1.6, 1]
        assert camera_keys[1]["fov"] == 30
        mara = next(o for o in shot["composition"]["objects"] if o["asset_id"] == mara_id)
        assert len(mara["keyframes"]) == 1
        assert math.isclose(mara["keyframes"][0]["transform"]["rotation"][1], math.pi / 4)
        deleted = _command(client, "delete_keyframe", shot_id=shot_id, keyframe_id=first["result"]["keyframe_id"])
        assert deleted["ok"] and deleted["result"]["count"] == 1
        gone = _command(client, "delete_keyframe", shot_id=shot_id, keyframe_id="nope")
        assert gone["ok"] is False
        negative = _command(client, "add_keyframe", shot_id=shot_id, target="camera", time=-1)
        assert negative["ok"] is False

    def test_update_pose_validates_joints(self, client):
        _, shot_id, mara_id, _ = self._two_character_shot(client)
        ok = _command(client, "update_pose", shot_id=shot_id, target="Mara", joints={"l_arm": [0, 0, 45], "head": [10, 0, 0]})
        assert ok["ok"], ok["error"]
        shot = _get_shot(client, shot_id)
        mara = next(o for o in shot["composition"]["objects"] if o["asset_id"] == mara_id)
        assert mara["pose"]["l_arm"] == [0, 0, 45]
        bad = _command(client, "update_pose", shot_id=shot_id, target="Mara", joints={"l_arm": [0, 0]})
        assert bad["ok"] is False
        bad_type = _command(client, "update_pose", shot_id=shot_id, target="Mara", joints={"l_arm": [0, "x", 0]})
        assert bad_type["ok"] is False
        # Not a figure: the camera has no joints.
        _command(client, "set_camera", shot_id=shot_id, x=0, y=1, z=3)
        not_figure = _command(client, "update_pose", shot_id=shot_id, target="shot-camera", joints={})
        assert not_figure["ok"] is False

    def test_shot_type_angle_elevation_and_duplicate(self, client):
        scene_id, shot_id, _, _ = self._two_character_shot(client)
        assert _command(client, "set_shot_type", shot_id=shot_id, shot_size="closeup")["ok"]
        assert _command(client, "set_camera_angle", shot_id=shot_id, camera_angle="profile")["ok"]
        assert _command(client, "set_camera_elevation", shot_id=shot_id, camera_elevation="low")["ok"]
        shot = _get_shot(client, shot_id)
        assert (shot["framing"]["shot_size"], shot["framing"]["camera_angle"], shot["framing"]["camera_elevation"]) == (
            "closeup",
            "profile",
            "low",
        )
        duplicated = _command(client, "duplicate_shot", shot_id=shot_id)
        assert duplicated["ok"], duplicated["error"]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        scene = next(s for s in project["scenes"] if s["id"] == scene_id)
        assert len(scene["shots"]) == 2
        copy = scene["shots"][1]
        assert copy["id"] != shot_id
        assert copy["framing"]["shot_size"] == "closeup"
        assert len(copy["characters"]) == 2
        assert copy["versions"] == []

    def test_capture_shot_reports_state_only(self, client):
        _, shot_id, _, _ = self._two_character_shot(client)
        result = _command(client, "capture_shot", shot_id=shot_id)
        assert result["ok"]
        assert result["result"]["has_capture"] is False
        assert "cannot render" in result["result"]["note"]

    def test_tools_are_advertised(self, client):
        tools = {t["name"] for t in client.get("/api/film/director/status").json()["tools"]}
        assert {
            "position_object",
            "rotate_object",
            "scale_object",
            "update_pose",
            "set_ots",
            "set_camera",
            "add_keyframe",
            "update_keyframe",
            "delete_keyframe",
            "capture_shot",
            "duplicate_shot",
            "assign_prop",
            "set_shot_type",
            "generate_preview",
            "generate_final",
        } <= tools


class TestCameraContinuity:
    def _shot_with(self, camera_x: float, framing: dict | None = None, camera_move: str = "static") -> FilmShot:
        shot = FilmShot(
            title="s",
            description="d",
            characters=[ShotCharacter(asset_id="a"), ShotCharacter(asset_id="b")],
            camera_move=camera_move,  # type: ignore[arg-type]
        )
        if framing:
            shot.framing = shot.framing.model_copy(update=framing)
        shot.composition = CompositionScene(
            objects=[
                CompositionObject(name="A", type="figure", asset_id="a", transform=CompositionTransform(position=(-1.0, 0.0, 0.0))),
                CompositionObject(name="B", type="figure", asset_id="b", transform=CompositionTransform(position=(1.0, 0.0, 0.0))),
            ],
            camera=CompositionObject(name="Cam", type="camera", transform=CompositionTransform(position=(camera_x, 1.6, 3.0))),
        )
        return shot

    def test_crossing_the_line_warns(self):
        previous = self._shot_with(0.0, {"shot_size": "wide"})
        current = self._shot_with(0.0, {"shot_size": "closeup"})
        assert current.composition is not None and current.composition.camera is not None
        current.composition.camera.transform = CompositionTransform(position=(0.0, 1.6, -3.0))
        kinds = [w.kind for w in camera_continuity_warnings(previous, current)]
        assert "screen_direction" in kinds
        assert all(not w.auto_fixable for w in camera_continuity_warnings(previous, current))

    def test_same_side_no_screen_direction_warning(self):
        previous = self._shot_with(0.0, {"shot_size": "wide"})
        current = self._shot_with(2.0, {"shot_size": "medium"})
        kinds = [w.kind for w in camera_continuity_warnings(previous, current)]
        assert "screen_direction" not in kinds
        assert "jump_cut" not in kinds

    def test_identical_setup_is_a_jump_cut(self):
        previous = self._shot_with(0.0, {"shot_size": "medium"})
        current = self._shot_with(0.0, {"shot_size": "medium"})
        kinds = [w.kind for w in camera_continuity_warnings(previous, current)]
        assert kinds == ["jump_cut"]

    def test_extreme_size_jump_on_same_axis(self):
        previous = self._shot_with(0.0, {"shot_size": "xwide"})
        current = self._shot_with(0.0, {"shot_size": "xcu"})
        kinds = [w.kind for w in camera_continuity_warnings(previous, current)]
        assert kinds == ["framing_jump"]

    def test_camera_continuity_runs_through_the_api(self, client):
        mara = _asset(client, "character", "Mara")
        theo = _asset(client, "character", "Theo")
        scene = _scene(client)
        first = _shot(client, scene["id"])
        second = _shot(client, scene["id"])
        cast_payload = {"characters": [{"asset_id": mara["id"]}, {"asset_id": theo["id"]}]}
        for shot_id, camera_z, size in ((first["id"], 3.0, "wide"), (second["id"], -3.0, "closeup")):
            _update(
                client,
                scene["id"],
                shot_id,
                **cast_payload,
                composition={
                    "objects": [_figure("Mara", mara["id"], (-1, 0, 0)), _figure("Theo", theo["id"], (1, 0, 0))],
                    "camera": _camera((0, 1.6, camera_z)),
                    "framing": {"shot_size": size},
                },
            )
        report = client.get(f"/api/film/projects/{PROJECT}/continuity/{second['id']}").json()
        kinds = {w["kind"] for w in report["warnings"]}
        assert "screen_direction" in kinds
        assert report["level"] == "significant"
        # First shot of the scene has no predecessor: nothing to compare.
        first_report = client.get(f"/api/film/projects/{PROJECT}/continuity/{first['id']}").json()
        assert "screen_direction" not in {w["kind"] for w in first_report["warnings"]}
