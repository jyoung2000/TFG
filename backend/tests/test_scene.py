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


class TestCloseUpsAndGroups:
    """MEASURED in the installed app (r21, the reference clip's 10 s kiss,
    a close-up): the composer opened on a *full* shot with one standing
    figure 6 m away and a 2 x 3 m box labelled "Human Face". The solver read
    every person box as a whole standing body, a "person" box with count 2
    as one person, and a face as a prop. These are that shot's subjects."""

    @staticmethod
    def _kiss() -> ShotSpec:
        spec = _spec(("human face", [0.4156, 0.1824, 0.2266, 0.6791], None), ("person", [0.0813, 0.0169, 0.5625, 0.9662], None), hfov=45)
        spec.subjects[1].count = 2
        spec.camera.shot_size = "closeup"
        return spec

    def test_a_group_box_becomes_one_figure_per_person(self):
        layout = layout_from_spec(self._kiss())
        assert len([o for o in layout.objects if o.kind == "figure"]) == 2

    def test_a_face_is_part_of_a_person_not_a_prop(self):
        layout = layout_from_spec(self._kiss())
        assert not [o for o in layout.objects if o.kind == "prop"], [o.label for o in layout.objects]

    def test_a_close_up_reads_as_a_close_up(self):
        from film.shot_vocabulary import describe_camera

        layout = layout_from_spec(self._kiss())
        assert describe_camera(layout)["shot_size"] == "closeup"
        scene = composer_scene_from_layout(layout, duration=10.0)
        assert scene.framing.shot_size == "closeup"

    def test_a_close_up_figure_fills_the_frame_with_its_head_and_shoulders(self):
        spec = self._kiss()
        layout = layout_from_spec(spec)
        boxes = reproject_layout(layout, aspect_of(spec))
        figures = [boxes[o.id] for o in layout.objects if o.kind == "figure"]
        # The heads sit near the top of the frame, the bodies run out of it.
        assert all(box[1] < 0.2 and box[1] + box[3] > 1.0 for box in figures), figures

    def test_what_a_person_wears_is_part_of_them_not_a_prop(self):
        """MEASURED (r22, the clip's second shot): a "tie" box became a cube 7 m behind the man."""
        spec = _spec(("person", [0.1, 0.05, 0.6, 0.95], None), ("tie", [0.3, 0.6, 0.05, 0.3], None), hfov=45)
        spec.camera.shot_size = "closeup"
        layout = layout_from_spec(spec)
        assert [o.kind for o in layout.objects] == ["figure"]
        # Without a person a worn item is just an object.
        alone = layout_from_spec(_spec(("hat", [0.4, 0.4, 0.2, 0.2], None)))
        assert [o.kind for o in alone.objects] == ["prop"]

    def test_more_faces_than_people_means_more_people(self):
        """MEASURED (r22, the clip's second shot): two faces, one person box -
        the man and the woman leaning in - seeded one figure."""
        spec = _spec(("human face", [0.36, 0.16, 0.17, 0.55], None), ("person", [0.37, 0.16, 0.54, 0.82], None), ("tie", [0.4, 0.77, 0.07, 0.14], None), hfov=45)
        spec.subjects[0].count = 2
        spec.camera.shot_size = "closeup"
        layout = layout_from_spec(spec)
        assert [o.kind for o in layout.objects] == ["figure", "figure"]

    def test_a_head_to_toe_person_is_not_a_tight_shot_whatever_the_words_say(self):
        """MEASURED (r23, the clothed reference image, 1125 x 2000): the vision
        model called a head-to-toe portrait a "medium shot"; seeding then put a
        Medium figure in the composer, and "trousers" became a cube."""
        from film.shot_spec import SpecSource
        from film.shot_vocabulary import describe_camera

        spec = _spec(
            ("human face", [0.443, 0.065, 0.151, 0.102], None), ("jacket", [0.116, 0.162, 0.766, 0.297], None),
            ("human head", [0.366, 0.009, 0.295, 0.16], None), ("trousers", [0.262, 0.428, 0.529, 0.493], None),
            ("woman", [0.13, 0.006, 0.747, 0.976], None),
        )
        spec.source = SpecSource(width=1125, height=2000, aspect="9:16")
        spec.camera.shot_size = "medium"
        layout = layout_from_spec(spec)
        assert [(o.kind, o.label) for o in layout.objects] == [("figure", "woman")]
        assert describe_camera(layout)["shot_size"] == "full"

    def test_a_figure_standing_for_a_face_is_named_as_a_person(self):
        spec = _spec(("human face", [0.3, 0.1, 0.4, 0.85], None), hfov=45)
        spec.camera.shot_size = "closeup"
        assert [o.label for o in layout_from_spec(spec).objects] == ["person"]

    def test_a_face_alone_is_still_a_person(self):
        spec = _spec(("face", [0.3, 0.1, 0.4, 0.85], None), hfov=45)
        spec.camera.shot_size = "close-up"
        layout = layout_from_spec(spec)
        assert [o.kind for o in layout.objects] == ["figure"]


class TestSeedingFollowsTheSolver:
    """MEASURED (r21): an analysis keeps the layout the solver gave at
    analysis time, and seeding reused it - so a fixed solver never reached a
    reproduced shot, and a stale seed stayed in the composer for good."""

    def test_a_shot_is_seeded_from_a_fresh_solve_not_the_stored_layout(self, test_state):
        from film.film_models import FilmProject, FilmScene, FilmShot
        from film.shot_spec import SpecLayout3D, SpecLayoutObject

        spec = TestCloseUpsAndGroups._kiss()
        # What the old solver stored: a face prop and one standing figure.
        spec.layout3d = SpecLayout3D(objects=[SpecLayoutObject(id="prop-1", kind="prop", pos=[0.3, 0.0, -6.0], scale=[2.2, 3.0, 2.2], label="human face")])
        spec.set_section("layout3d", "depth", 0.6)
        shot = FilmShot(id="shot-1", order=1, title="kiss")
        project = FilmProject(id="film-seed", name="seed", scenes=[FilmScene(id="scene-1", order=1, title="s", shots=[shot])])
        test_state.film.store.save(project)
        test_state.scene.seed_shot(project, shot, spec, 10.0)
        assert shot.composition is not None
        assert [o.type for o in shot.composition.objects] == ["figure", "figure"]
        assert shot.composition.framing.shot_size == "closeup"

    def test_a_layout_the_user_set_is_kept(self, test_state):
        from film.film_models import FilmProject, FilmScene, FilmShot
        from film.shot_spec import SpecLayout3D, SpecLayoutObject

        spec = TestCloseUpsAndGroups._kiss()
        spec.layout3d = SpecLayout3D(objects=[SpecLayoutObject(id="fig-9", kind="figure", pos=[0.0, 0.0, -3.0], label="hero")])
        spec.set_section("layout3d", "user", 1.0)
        shot = FilmShot(id="shot-2", order=1, title="kept")
        project = FilmProject(id="film-kept", name="kept", scenes=[FilmScene(id="scene-1", order=1, title="s", shots=[shot])])
        test_state.film.store.save(project)
        test_state.scene.seed_shot(project, shot, spec, 4.0)
        assert [o.id for o in shot.composition.objects] == ["fig-9"]  # type: ignore[union-attr]

    def test_an_untouched_older_seed_is_replaced_and_an_edited_one_is_not(self, client, video, test_state, create_fake_model_files):
        from tests.test_video_reproduce import _analysed as analysed_for_reproduce

        analysed = analysed_for_reproduce(client, video, test_state, create_fake_model_files)
        ids = [s["id"] for s in analysed["shots"][:2]]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": ids})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        project = test_state.film.get_project(job["project_id"])
        untouched = project.find_shot(job["shots"][0]["film_shot_id"])[1]  # type: ignore[index]
        edited = project.find_shot(job["shots"][1]["film_shot_id"])[1]  # type: ignore[index]
        assert untouched.composition.seed and edited.composition.seed  # type: ignore[union-attr]
        version, fingerprint = untouched.composition.seed.split(":", 1)  # type: ignore[union-attr]
        # Both as an older seed version left them; the second one then edited.
        untouched.composition.seed = f"v0:{fingerprint}"  # type: ignore[union-attr]
        edited.composition.seed = "v0:" + edited.composition.seed.split(":", 1)[1]  # type: ignore[union-attr]
        edited.composition.duration_seconds = 9.25  # type: ignore[union-attr]
        test_state.film.store.save(project)
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": ids})
        after = test_state.film.get_project(job["project_id"])
        assert after.find_shot(untouched.id)[1].composition.seed.startswith(version + ":")  # type: ignore[index,union-attr]
        kept = after.find_shot(edited.id)[1].composition  # type: ignore[index]
        assert kept.duration_seconds == 9.25 and kept.seed.startswith("v0:")  # type: ignore[union-attr]
