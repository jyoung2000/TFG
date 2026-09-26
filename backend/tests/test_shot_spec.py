"""ShotSpec: fusion precedence, compile determinism, target/style coverage,
4070-valid parameters, camera vocabulary from 3D, templates, and the
knowledge loop that must change a prompt after enough wins."""

from __future__ import annotations

import itertools
from pathlib import Path

from PIL import Image

from film.prompt_compiler import PromptHints, TARGETS, compile_from_spec, resolve_target
from film.prompt_templates import BUILTIN_TEMPLATES, TemplateStore
from film.shot_spec import ShotSpec, SpecLayout3D, SpecLayoutObject, SpecSubject, TagTerm
from film.shot_spec_fusion import apply_flow, apply_user, apply_vlm, merge_specs, spec_from_vision
from film.shot_vocabulary import describe_camera, focal_from_fov
from handlers.vision_handler import VisionAnalysis
from services.vision.depth import depth_median_in_box, read_depth_png
from services.vision.fake_vision import FakeVision
from services.vision.protocol import VisionRegion

SPEC_TARGETS = ("ltx2", "wan22", "z_image", "qwen_image_edit", "flux", "sdxl", "cloud_generic")
STYLES = ("narrative", "structured", "tagged", "weighted", "json", "negative_only")


def _analysis(tmp_path: Path, color: tuple[int, int, int] = (200, 40, 40)) -> VisionAnalysis:
    image = tmp_path / "ref.png"
    Image.new("RGB", (640, 360), color).save(image)
    vision = FakeVision()
    depth = vision.depth(str(image), str(tmp_path / "depth.png"))
    regions = vision.detect(str(image)).regions
    depth01 = read_depth_png(Path(depth.depth_png))
    for region in regions:
        region.depth_median = depth_median_in_box(depth01, region.bbox)
    return VisionAnalysis(
        image_path=str(image),
        content_hash="hash-" + "".join(f"{c:02x}" for c in color),
        measured=vision.stats(str(image)),
        caption=vision.caption(str(image)),
        regions=regions,
        tags=vision.tags(str(image)),
        depth=depth,
    )


def _rich_spec(tmp_path: Path) -> ShotSpec:
    spec = spec_from_vision(_analysis(tmp_path))
    apply_vlm(spec, {"location": "relay station", "time_of_day": "night", "lighting_quality": "soft", "mood": "calm", "what_happens": "an engineer studies a dead console"}, 0.7)
    return spec


class TestFusion:
    def test_measured_and_detection_beat_the_vlm(self, tmp_path: Path):
        spec = spec_from_vision(_analysis(tmp_path))
        assert spec.source.aspect == "16:9"
        assert spec.provenance["measured"] == "measured"
        assert [s.label for s in spec.subjects] == ["person"]
        assert spec.provenance["subjects"] == "florence"
        assert spec.camera.shot_size == "full"  # a 0.7-high box
        assert spec.style.tags and spec.provenance["style"] == "clip"
        assert spec.style.medium == "photograph" or spec.style.medium == "photo"
        assert spec.layout3d.depth_map_path.endswith("depth.png")
        assert spec.subjects[0].depth_median is not None
        apply_vlm(spec, {"subjects": ["a dragon"], "shot_size": "xcu", "medium": "anime", "location": "cave"}, 0.9)
        assert [s.label for s in spec.subjects] == ["person"], "a detector's count outranks the VLM"
        assert spec.camera.shot_size != "xcu", "measured framing survives"
        assert spec.scene.location == "cave" and spec.provenance["scene"] == "vlm"
        assert spec.style.medium != "anime", "CLIP's medium stays"

    def test_locks_are_absolute(self, tmp_path: Path):
        spec = spec_from_vision(_analysis(tmp_path))
        apply_user(spec, {"camera": {**spec.camera.model_dump(), "shot_size": "closeup"}})
        assert spec.locks["camera"] and spec.provenance["camera"] == "user"
        apply_flow(spec, pan=0.3, tilt=0.0, zoom=0.0, roll=0.0, magnitude=0.3, subject_motion=0.1, handheld=True, pacing="fast")
        assert spec.camera.shot_size == "closeup" and spec.camera.move == "", "flow may not touch a locked camera"
        assert spec.motion.dominant.pan == 0.3 and spec.provenance["motion"] == "flow"
        fresh = spec_from_vision(_analysis(tmp_path, (20, 20, 200)))
        merged = merge_specs(spec, fresh)
        assert merged.camera.shot_size == "closeup"
        assert merged.source.hash == fresh.source.hash

    def test_flow_owns_the_camera_move(self, tmp_path: Path):
        spec = spec_from_vision(_analysis(tmp_path))
        apply_flow(spec, pan=0.0, tilt=0.0, zoom=0.4, roll=0.0, magnitude=0.4, subject_motion=0.0, handheld=False, pacing="slow", fps=24.0)
        assert spec.camera.move == "push_in"
        assert spec.camera.move_intensity == 1.0
        assert spec.source.fps == 24.0


class TestCompile:
    def test_every_target_and_style_yields_a_prompt_and_4070_valid_params(self, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        for target, style in itertools.product(SPEC_TARGETS, STYLES):
            result = compile_from_spec(spec, target, style, seed=7)  # type: ignore[arg-type]
            assert result.matched, target
            if style == "negative_only":
                assert result.prompt == "" and result.negative_prompt
            else:
                assert len(result.prompt) > 20, (target, style)
            assert result.params.seed == 7
            if result.target_id in ("z_image", "qwen_image_edit", "flux", "sdxl"):
                assert result.params.width % 16 == 0 and result.params.height % 16 == 0
                assert max(result.params.width, result.params.height) <= 1024
                assert result.params.duration == 0
            else:
                assert result.params.duration in (4.0, 5.0, 6.0, 8.0, 10.0)
                assert result.params.resolution in ("480p", "540p", "720p")
                assert result.params.fps in (16, 24)
            if result.target_id == "z_image":
                assert result.params.steps >= 8
            assert result.params.steps <= 30

    def test_compile_is_deterministic(self, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        hints = PromptHints(phrases=["anamorphic flare"], params={"steps": 12})
        first = compile_from_spec(spec, "ltx2", "narrative", hints, seed=3)
        second = compile_from_spec(spec, "ltx2", "narrative", hints, seed=3)
        assert first == second
        assert "anamorphic flare" in first.prompt and first.params.steps == 12
        assert "anamorphic flare" in first.hints_applied

    def test_still_targets_drop_motion_and_video_targets_keep_the_start_frame(self, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        apply_flow(spec, pan=0.0, tilt=0.0, zoom=0.3, magnitude=0.3, roll=0.0, subject_motion=0.0, handheld=False, pacing="slow")
        still = compile_from_spec(spec, "z_image")
        assert "push in" not in still.prompt and any("still frame" in d for d in still.dropped)
        video = compile_from_spec(spec, "ltx2")
        assert "push in" in video.prompt
        assert video.conditioning.start_frame == spec.source.path
        edit = compile_from_spec(spec, "qwen_image_edit")
        assert edit.conditioning.refs == [spec.source.path]

    def test_tags_are_ordered_by_clip_score(self, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        spec.style.tags = [TagTerm(term="low score", score=0.1), TagTerm(term="high score", score=0.9)]
        prompt = compile_from_spec(spec, "sdxl", "tagged").prompt
        assert prompt.index("high score") < prompt.index("low score")

    def test_target_ids_resolve_exactly_and_by_model_id(self):
        assert resolve_target("ltx2")[0].id == "ltx2"
        assert resolve_target("ltx2_22B_distilled")[0].id == "ltx2"
        assert resolve_target("wan2_2_ti2v_5B")[0].id == "wan22"
        assert resolve_target("z_image")[0].id == "z_image"
        assert resolve_target("qwen_image_edit_20B")[0].id == "qwen_image_edit"
        assert resolve_target("cloud_generic")[0].id == "cloud_generic"
        assert {t.id for t in TARGETS} >= set(SPEC_TARGETS)


class TestCameraVocabulary:
    def test_describe_camera_from_layout(self):
        layout = SpecLayout3D(objects=[SpecLayoutObject(id="mara", kind="figure", pos=[0, 0, 0], rot=[0, 0, 0])])
        layout.camera.pos = [0.0, 1.5, 2.2]
        layout.camera.fov = 40.0
        described = describe_camera(layout)
        assert described["shot_size"] in ("full", "medium")
        assert described["height"] == "eye"
        assert described["angle"] == "front"
        assert described["lens_estimate"]
        layout.camera.pos = [0.0, 6.0, 2.2]
        assert describe_camera(layout)["height"] in ("high", "bird")
        layout.camera.pos = [0.0, 1.5, 12.0]
        assert describe_camera(layout)["shot_size"] in ("wide", "xwide")
        layout.camera.pos = [0.0, 1.5, -2.2]
        assert describe_camera(layout)["angle"] == "back"
        assert 40 < focal_from_fov(40.0) < 55


class TestTemplates:
    def test_builtins_and_overrides(self, tmp_path: Path):
        store = TemplateStore(tmp_path / "templates.json")
        assert [t.id for t in store.list()][:4] == [t.id for t in BUILTIN_TEMPLATES]
        store.set_instruction("natural", "Write one calm paragraph.")
        assert store.get("natural").instruction == "Write one calm paragraph."
        again = TemplateStore(tmp_path / "templates.json")
        assert again.get("natural").instruction == "Write one calm paragraph."
        custom = again.create("Mine", "Do the thing.", "desc")
        assert again.get(custom.id).name == "Mine" and not again.get(custom.id).built_in
        again.reset("natural")
        assert again.get("natural").instruction == BUILTIN_TEMPLATES[1].instruction
        assert again.delete(custom.id) and not again.delete(custom.id)


class TestKnowledgeLoop:
    def test_hints_change_the_prompt_after_three_winning_events(self, client, test_state, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        keys = spec.attribute_keys()
        assert keys, "the spec carries learnable attributes"
        baseline = client.post("/api/prompts/compile-spec", json={"spec": spec.to_json(), "target": "ltx2", "style": "narrative", "seed": 1}).json()
        assert baseline["hints"]["sample"] == 0 and baseline["hints"]["phrases"] == []
        winning = "medium shot, person, soft light, volumetric haze, anamorphic bokeh, 35mm lens"
        for index in range(3):
            r = client.post(
                "/api/knowledge/candidate",
                json={"picked": index == 0, "model": "ltx2_22B_distilled", "target": "ltx2", "prompt": winning, "seed": 100 + index,
                      "spec_keys": keys, "metrics": {"composite": 0.8 + index * 0.02, "steps": 12, "guidance": 1.0}},
            )
            assert r.status_code == 200, r.text
        hints = client.post("/api/knowledge/hints", json={"spec_keys": keys, "target": "ltx2"}).json()
        assert hints["sample"] == 3
        assert "volumetric haze" in hints["phrases"] and "anamorphic bokeh" in hints["phrases"]
        assert hints["params"]["steps"] == 12
        hinted = client.post("/api/prompts/compile-spec", json={"spec": spec.to_json(), "target": "ltx2", "style": "narrative", "seed": 1}).json()
        assert hinted["result"]["prompt"] != baseline["result"]["prompt"]
        assert "volumetric haze" in hinted["result"]["prompt"]
        assert hinted["result"]["params"]["steps"] == 12
        # Unrelated shots get no advice from these wins.
        other = client.post("/api/knowledge/hints", json={"spec_keys": ["camera.shot_size=xcu", "style.medium=anime", "scene.time_of_day=dawn"], "target": "ltx2"}).json()
        assert other["phrases"] == []
        # Learning switched off → nothing recorded.
        client.put("/api/knowledge/settings", json={"enabled": False, "generation": True, "approval": True, "editing": True, "feedback": True})
        r = client.post("/api/knowledge/candidate", json={"picked": True, "model": "x", "target": "ltx2", "prompt": "secret", "spec_keys": keys, "metrics": {}})
        assert r.status_code == 200
        assert not any(e["prompt"] == "secret" for e in client.get("/api/knowledge/events").json())

    def test_compile_all_and_templates_routes(self, client, tmp_path: Path):
        spec = _rich_spec(tmp_path)
        r = client.post("/api/prompts/compile-spec/all", json={"spec": spec.to_json(), "targets": ["ltx2", "z_image"], "styles": ["narrative", "tagged"]})
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert set(results) == {"ltx2:narrative", "ltx2:tagged", "z_image:narrative", "z_image:tagged"}
        assert all(v["prompt"] for v in results.values())
        templates = client.get("/api/prompts/templates").json()["templates"]
        assert [t["id"] for t in templates][:4] == ["detailed", "natural", "tags", "concise"]
        updated = client.put("/api/prompts/templates/tags", json={"instruction": "Tags only, please."})
        assert updated.status_code == 200 and updated.json()["instruction"] == "Tags only, please."
        assert client.put("/api/prompts/templates/nope", json={"instruction": "x"}).status_code == 404
        created = client.post("/api/prompts/templates", json={"name": "House", "instruction": "Our house style."}).json()
        assert created["id"].startswith("custom-")
        assert client.delete(f"/api/prompts/templates/{created['id']}").json()["deleted"] is True


class TestCatalog:
    def test_capability_catalog_answers_task_flags(self):
        from film.media_providers import capabilities_for, catalog_models

        assert len(catalog_models()) > 400
        assert len(catalog_models("i2v")) > 50
        banana = capabilities_for("nano-banana")
        assert banana is not None and "EDIT" in banana.tasks and "1:1" in banana.aspect_ratios
        assert capabilities_for("definitely-not-a-model") is None


def test_subject_helpers():
    spec = ShotSpec()
    spec.subjects = [SpecSubject(label="person", count=2), SpecSubject(label="dog")]
    assert spec.subject_labels() == ["2 person", "dog"]
    assert "subjects.count=3" in spec.attribute_keys()
    assert VisionRegion(label="x").bbox == []
