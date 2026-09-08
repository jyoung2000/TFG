"""End-to-end acceptance film (docs/…: two scenes, five shots).

Runs the full workflow against the real FastAPI app with fake heavy services:
compose → capture → save → reload → preview → final → promote → the
send-to-timeline payload the frontend consumes. Generated outputs are real
files written by the fake pipeline through the host generation path.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

PROJECT = "acceptance-film"

SHOT_PLAN = [
    # (scene_index, title, shot_size, angle, duration)
    (0, "Wide establishing", "wide", "front", 4.0),
    (0, "Medium OTS", "medium", "ots", 5.0),
    (0, "Close-up reaction", "closeup", "front", 3.0),
    (1, "Medium moving shot", "medium", "threeQuarterLeft", 6.0),
    (1, "Close-up", "closeup", "profile", 3.0),
]


def _png_base64(seed: int) -> str:
    image = Image.new("RGB", (64, 36), ((seed * 37) % 255, (seed * 91) % 255, 120))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _composition(size: str, angle: str, duration: float, ots_ids: tuple[str, str] | None) -> dict:
    figure = {
        "id": "fig-a",
        "name": "Ava",
        "type": "figure",
        "visible": True,
        "transform": {"position": [0, 0, 0], "rotation": [0, 0.4, 0], "scale": [1, 1, 1]},
        "pose": {"l_arm": [0, 0, 35], "r_elbow": [40, 0, 0]},
        "figure_variant": "female",
        "color": "#7f9cc4",
        "keyframes": [],
    }
    second = {**figure, "id": "fig-b", "name": "Ben", "transform": {"position": [1.4, 0, 1.2], "rotation": [0, 3.3, 0], "scale": [1, 1, 1]}}
    return {
        "objects": [figure, second],
        "camera": {
            "id": "shot-camera",
            "name": "Shot Camera",
            "type": "camera",
            "visible": True,
            "transform": {"position": [0, 1.5, 3.2], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
            "pose": {},
            "figure_variant": "male",
            "color": "#ffffff",
            "keyframes": [
                {"id": "kf-1", "time": 0.0, "transform": {"position": [0, 1.5, 3.2], "rotation": [0, 0, 0], "scale": [1, 1, 1]}, "fov": 40},
                {"id": "kf-2", "time": duration, "transform": {"position": [0, 1.5, 2.4], "rotation": [0, 0, 0], "scale": [1, 1, 1]}, "fov": 40},
            ],
            "fov": 40,
        },
        "framing": {
            "shot_size": size,
            "camera_angle": angle,
            "camera_elevation": "eye",
            "composition": "center",
            "fov_deg": 40,
            "ots_foreground_id": ots_ids[0] if ots_ids else None,
            "ots_subject_id": ots_ids[1] if ots_ids else None,
        },
        "camera_move": "push_in",
        "duration_seconds": duration,
    }


def test_acceptance_film(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files()
    test_state.state.app_settings.use_local_text_encoder = True

    # 1. Assets: two characters and a location, reusable across shots.
    ava = client.post(
        f"/api/film/projects/{PROJECT}/assets",
        json={"kind": "character", "name": "Ava", "wardrobe": "green field jacket"},
    ).json()["asset"]["id"]
    ben = client.post(
        f"/api/film/projects/{PROJECT}/assets",
        json={"kind": "character", "name": "Ben", "wardrobe": "grey suit"},
    ).json()["asset"]["id"]
    rooftop = client.post(
        f"/api/film/projects/{PROJECT}/assets",
        json={"kind": "location", "name": "Rooftop", "environment": "city rooftop at dusk"},
    ).json()["asset"]["id"]

    # 2. Scenes.
    scene_ids: list[str] = []
    for title in ("Scene 1", "Scene 2"):
        scene = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": title}).json()
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene['id']}",
            json={"location_id": rooftop, "character_ids": [ava, ben]},
        )
        scene_ids.append(scene["id"])

    # 3. Shots per plan: create → compose (capture) → save.
    shot_refs: list[tuple[str, str]] = []  # (scene_id, shot_id)
    for index, (scene_index, title, size, angle, duration) in enumerate(SHOT_PLAN):
        scene_id = scene_ids[scene_index]
        shot = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots",
            json={"title": title, "duration_seconds": duration, "action": f"Beat {index + 1} on the rooftop"},
        ).json()
        ots = ("fig-a", "fig-b") if angle == "ots" else None
        captured = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot['id']}/capture",
            json={"image_base64": _png_base64(index), "composition": _composition(size, angle, duration, ots)},
        )
        assert captured.status_code == 200
        assert captured.json()["status"] == "ready"
        shot_refs.append((scene_id, shot["id"]))

    # 4. Reload from disk: everything persisted (fresh read of project.json).
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    assert [len(s["shots"]) for s in project["scenes"]] == [3, 2]
    ots_shot = project["scenes"][0]["shots"][1]
    assert ots_shot["framing"]["camera_angle"] == "ots"
    assert ots_shot["framing"]["ots_foreground_id"] == "fig-a"
    assert ots_shot["composition"]["camera"]["keyframes"][1]["time"] == 5.0
    total = sum(sh["duration_seconds"] for sc in project["scenes"] for sh in sc["shots"])
    assert total == 21.0

    # 5. Preview every shot (batch = whole storyboard), then final each.
    batch = client.post(f"/api/film/projects/{PROJECT}/generate/batch", json={"kind": "preview"})
    assert batch.status_code == 200
    assert len(batch.json()["queued"]) == 5

    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    for scene in project["scenes"]:
        for shot in scene["shots"]:
            assert shot["versions"][0]["kind"] == "preview"
            assert shot["versions"][0]["status"] == "complete"
            assert Path(shot["versions"][0]["output_path"]).exists()
            # Preview clamps duration to the configured maximum.
            assert shot["versions"][0]["duration_seconds"] <= 4.0

    for scene_id, shot_id in shot_refs:
        result = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate",
            json={"kind": "final"},
        )
        assert result.status_code == 200

    # 6. Review: finals complete, promoted as current, full duration preserved.
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    outputs: list[str] = []
    for scene in project["scenes"]:
        for shot in scene["shots"]:
            kinds = [v["kind"] for v in shot["versions"]]
            assert kinds == ["preview", "final"]
            final = shot["versions"][1]
            assert final["status"] == "complete"
            assert shot["current_version"] == 2
            assert final["duration_seconds"] == shot["duration_seconds"]
            assert final["wardrobe_snapshot"]  # continuity snapshot captured
            outputs.append(final["output_path"])
            # Approve the shot after review.
            approve = client.put(
                f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}",
                json={"status": "approved"},
            )
            assert approve.status_code == 200

    # 7. Timeline payload: every approved output is a real, served file the
    #    editor flow can register as an asset + clip.
    assert len(outputs) == 5
    for output in outputs:
        served = client.get("/api/film/output", params={"path": output})
        assert served.status_code == 200
        assert served.content == b"fake-video"

    # 8. Ten real pipeline runs total (5 previews + 5 finals), in queue order.
    assert len(fake_services.fast_video_pipeline.generate_calls) == 10
    prompts = [c["prompt"] for c in fake_services.fast_video_pipeline.generate_calls]
    assert "Beat 1" in prompts[0] and "Beat 5" in prompts[4]
