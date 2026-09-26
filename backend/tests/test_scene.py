"""Phase 6: image evidence → 3D layout → composer scene → back, the 3D
storyboard build, composer edits folded into the spec, and Deliver passes as
control signals."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from film.film_models import CompositionScene
from film.scene_solver import (
    TOLERANCE,
    aspect_of,
    composer_scene_from_layout,
    figure_variant_for,
    layout_from_composition,
    layout_from_spec,
    reproject_layout,
    reprojection_error,
)
from film.shot_spec import ShotSpec, SpecSource, SpecSubject
from services.wangp_bridge import WanGPBridge


def _spec(*subjects: tuple[str, list[float], float | None], hfov: float = 0.0, height: str = "") -> ShotSpec:
    spec = ShotSpec()
    spec.source = SpecSource(width=1920, height=1080, aspect="16:9")
    spec.subjects = [SpecSubject(label=label, bbox=box, depth_median=depth, count=1) for label, box, depth in subjects]
    if hfov:
        spec.camera.fov_deg = hfov
    if height:
        spec.camera.height = height
    return spec


class TestSolver:
    @pytest.mark.parametrize(
        "subjects",
        [
            [("person", [0.4, 0.2, 0.2, 0.7], 0.7)],
            [("person", [0.3, 0.25, 0.14, 0.6], 0.7), ("person", [0.6, 0.35, 0.08, 0.4], 0.4), ("chair", [0.1, 0.55, 0.12, 0.3], 0.6)],
            [("woman", [0.45, 0.1, 0.1, 0.35], 0.3), ("dog", [0.2, 0.7, 0.15, 0.2], 0.9)],
            [("person", [0.35, 0.0, 0.3, 1.0], 0.95)],  # clipped: depth-based distance
        ],
    )
    def test_layout_reprojects_within_tolerance(self, subjects):
        spec = _spec(*subjects)
        layout = layout_from_spec(spec)
        assert len(layout.objects) == len(subjects)
        assert all(o.pos[1] >= 0 for o in layout.objects), "nothing below the floor"
        assert reprojection_error(spec, layout) <= TOLERANCE
        # Depth ordering survives: nearer subjects sit closer to the camera (larger z).
        by_id = {o.id: o for o in layout.objects}
        boxes = reproject_layout(layout, aspect_of(spec))
        assert set(boxes) == set(by_id)

    def test_fov_and_height_hints_shape_the_camera(self):
        wide = layout_from_spec(_spec(("person", [0.45, 0.3, 0.1, 0.5], 0.6), hfov=90))
        long = layout_from_spec(_spec(("person", [0.45, 0.3, 0.1, 0.5], 0.6), hfov=30))
        assert wide.camera.fov > long.camera.fov
        # The same box through a long lens means a subject much farther away.
        assert abs(long.objects[0].pos[2]) > abs(wide.objects[0].pos[2]) * 1.5
        high = layout_from_spec(_spec(("person", [0.45, 0.3, 0.1, 0.5], 0.6), height="high"))
        assert high.camera.rot[0] < 0  # pitched down
        assert reprojection_error(_spec(("person", [0.45, 0.3, 0.1, 0.5], 0.6), height="high"), high) <= TOLERANCE

    def test_body_type_from_height(self):
        assert figure_variant_for(1.1) == "child"
        assert figure_variant_for(1.6) == "female"
        assert figure_variant_for(1.8) == "male"

    def test_composer_scene_round_trips_to_the_layout(self):
        spec = _spec(("person", [0.3, 0.25, 0.14, 0.6], 0.7), ("chair", [0.1, 0.55, 0.12, 0.3], 0.6))
        spec.camera.move = "push_in"
        layout = layout_from_spec(spec)
        scene = composer_scene_from_layout(layout, duration=4.0, move="push_in", motion=spec.motion)
        assert [o.type for o in scene.objects] == ["figure", "cube"]
        assert scene.camera is not None and len(scene.camera.keyframes) == 2
        assert scene.camera.keyframes[1].transform.position[2] < scene.camera.keyframes[0].transform.position[2]
        assert scene.framing.shot_size in {"xwide", "wide", "full", "medium", "mcu", "closeup", "xcu"}
        back = layout_from_composition(scene, base=layout)
        for original, restored in zip(layout.objects, back.objects):
            assert restored.kind == original.kind
            assert restored.pos == pytest.approx(original.pos, abs=1e-3)
            assert restored.scale[1] == pytest.approx(original.scale[1], abs=1e-3)
        assert back.camera.pos == pytest.approx(layout.camera.pos, abs=1e-3)
        assert back.camera.fov == pytest.approx(layout.camera.fov, abs=1e-3)
        assert reprojection_error(spec, back) <= TOLERANCE


def _import(client, video, **overrides) -> dict:
    response = client.post("/api/video-analysis/import", json={"path": video, "title": "Source", **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def _analysed(client, video, test_state, create_fake_model_files) -> dict:
    from tests.test_generation import _enable_local_text_encoding

    create_fake_model_files()
    _enable_local_text_encoding(test_state)
    analysis = _import(client, video)
    client.post(f"/api/video-analysis/{analysis['id']}/detect")
    return client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()


class TestSceneRoutes:
    def test_analysis_carries_a_layout_and_build_describes_it(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        spec = analysed["shots"][0]["spec"]
        assert spec["provenance"]["layout3d"] == "depth"
        assert spec["layout3d"]["objects"] and spec["layout3d"]["objects"][0]["kind"] == "figure"
        built = client.post("/api/scene/build", json={"spec": spec, "duration_seconds": 3.0})
        assert built.status_code == 200, built.text
        payload = built.json()
        assert payload["composition"]["objects"][0]["type"] == "figure"
        assert payload["camera_words"]["shot_size"]
        assert payload["camera_sentence"]
        assert payload["reprojection_error"] <= TOLERANCE
        assert payload["svg"].startswith("<svg")
        described = client.post("/api/scene/describe", json={"layout3d": payload["layout3d"]}).json()
        assert described["camera_words"] == payload["camera_words"]

    def test_storyboard3d_seeds_every_shot_with_a_scene_and_thumbnail(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        response = client.post(f"/api/video-analysis/{analysed['id']}/storyboard3d", json={})
        assert response.status_code == 200, response.text
        project = response.json()
        shots = [shot for scene in project["scenes"] for shot in scene["shots"]]
        assert len(shots) == len(analysed["shots"])
        for shot in shots:
            assert shot["composition"]["objects"], "figures from the layout"
            assert shot["composition"]["camera"]["keyframes"]
            assert shot["blockout_path"].endswith("-blockout.svg")
            media = client.get(f"/api/film/projects/{project['id']}/media", params={"path": shot["blockout_path"]})
            assert media.status_code == 200 and b"<svg" in media.content
            assert shot["status"] == "composed"
        jobs = client.get("/api/jobs", params={"kind": "scene_build"}).json()["jobs"]
        assert jobs and jobs[0]["status"] == "complete" and jobs[0]["metrics"]["shots_built"] == len(shots)
        assert len(jobs[0]["outputs"]) == len(shots)
        # Building again reuses the project instead of creating another.
        again = client.post(f"/api/video-analysis/{analysed['id']}/storyboard3d", json={}).json()
        assert again["id"] == project["id"]

    def test_composer_edits_fold_back_into_the_spec_and_prompt(self, client, video, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot = analysed["shots"][0]
        built = client.post("/api/scene/build", json={"spec": shot["spec"], "duration_seconds": 2.0}).json()
        composition = CompositionScene.model_validate(built["composition"])
        assert composition.camera is not None
        # Push the camera far back and up: the words must follow.
        pos = composition.camera.transform.position
        composition.camera.transform.position = (pos[0], pos[1] + 5.0, pos[2] + 14.0)
        composition.camera.transform.rotation = (-0.35, 0.0, 0.0)
        updated = client.put(
            f"/api/video-analysis/{analysed['id']}/shots/{shot['id']}/spec",
            json={"composition": composition.model_dump(mode="json"), "locks": {"layout3d": True}},
        )
        assert updated.status_code == 200, updated.text
        edited = next(s for s in updated.json()["shots"] if s["id"] == shot["id"])
        assert edited["spec"]["provenance"]["layout3d"] == "user"
        assert edited["spec"]["locks"]["layout3d"] is True
        assert edited["spec"]["camera"]["height"] in ("high", "bird")
        assert edited["spec"]["camera"]["shot_size"] in ("xwide", "wide")
        assert edited["provenance"] == "user"
        assert edited["spec"]["camera"]["shot_size"].replace("xwide", "extreme wide") in edited["prompts"]["storyboard"] or edited["visual"]["shot_size"] == edited["spec"]["camera"]["shot_size"]
        # A locked section is left alone by a re-analysis.
        reanalysed = client.post(f"/api/video-analysis/{analysed['id']}/analyze", json={}).json()
        kept = next(s for s in reanalysed["shots"] if s["id"] == shot["id"])
        assert kept["spec"]["layout3d"]["camera"]["pos"][1] == pytest.approx(pos[1] + 5.0, abs=1e-3)
        assert client.put(f"/api/video-analysis/{analysed['id']}/shots/nope/spec", json={"sections": {}}).status_code == 404


def _png(color=(10, 120, 200)) -> str:
    image = Image.new("RGB", (32, 18), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class TestDeliver:
    def test_deliver_writes_passes_and_wires_control_signals(self, client, fake_services, test_state):
        from tests.test_film_generation import PROJECT, _minimal_composition, _setup_shot

        scene_id, shot_id = _setup_shot(client)
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/deliver",
            json={"fps": 12, "width": 32, "height": 18, "clean": [_png(), _png((20, 20, 20))], "depth": [_png((200, 200, 200)), _png()], "stills": [_png()], "prompt": "a quiet moment", "metadata": {"marks": 2}, "composition": _minimal_composition()},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["control_video"].endswith("/reference.mp4")
        assert payload["depth_video"].endswith("/depth.mp4")
        assert payload["shot"]["generation"]["control_video"] == payload["control_video"]
        assert len(fake_services.stitcher.encoded) == 2
        assert fake_services.stitcher.encoded[0][1] == 12 and len(fake_services.stitcher.encoded[0][0]) == 2
        root = test_state.film.store.project_dir(PROJECT)
        for rel in payload["files"]:
            assert (root / rel).is_file(), rel
        assert (root / payload["package_dir"] / "prompt.txt").read_text().strip() == "a quiet moment"
        assert client.get(f"/api/film/projects/{PROJECT}/media", params={"path": payload["control_video"]}).status_code == 200
        assert client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/deliver", json={"fps": 24}).status_code == 400

    def test_render_request_carries_the_deliver_passes(self, client, fake_services, test_state, create_fake_model_files):
        from tests.test_film_generation import PROJECT, _enable_local, _setup_shot

        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True)
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/deliver", json={"fps": 24, "clean": [_png()], "depth": [_png()]})
        queued = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        assert queued.status_code == 200
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 5}).json()["jobs"][0]
        assert job["status"] == "complete"
        assert job["params"]["controlVideoPath"].endswith("reference.mp4") and Path(job["params"]["controlVideoPath"]).is_file()
        assert job["params"]["depthVideoPath"].endswith("depth.mp4")

    def test_wangp_settings_carry_the_guide_video(self, tmp_path: Path):
        class RecordingBridge(WanGPBridge):
            def __init__(self) -> None:
                super().__init__(enabled=True, root=tmp_path, python_executable=None, config_dir=tmp_path / "cfg", output_dir=tmp_path, video_model_type="ltx2_22B_distilled", image_model_type="z_image", camera_motion_prompts={}, extra_args=())
                self.manifests: list[list[dict[str, object]]] = []

            def _run_manifest(self, *, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[override]  # noqa: ANN001
                self.manifests.append(manifest)
                out = tmp_path / "out.mp4"
                out.write_bytes(b"x")
                return [str(out)]

        control = tmp_path / "reference.mp4"
        control.write_bytes(b"ref")
        bridge = RecordingBridge()
        bridge.generate_video(prompt="p", resolution_label="540p", aspect_ratio="16:9", duration_seconds=6, fps=24, steps=8, seed=1, camera_motion="none", negative_prompt="", image_path=None, audio_path=None, on_progress=lambda *a: None, is_cancelled=lambda: False, control_video_path=str(control), depth_video_path=None)
        params = bridge.manifests[0][0]["params"]
        assert isinstance(params, dict)
        assert params["video_guide"] == str(control.resolve()) and params["video_prompt_type"] == "V"
