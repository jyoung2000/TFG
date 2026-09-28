"""The vision model fills every ShotSpec block it is asked for, for images and
video shots, including subjects when object detection is unavailable.

Round 5 on the RTX 4070: the installed app's runtime had no Florence-2, so
detection produced no subjects, and qwen2.5vl:7b put the person in the
foreground ("woman in black leather outfit"). The Subjects block stayed empty
because the image prompt never asked for subjects and apply_vlm only accepted
a `subjects` list or a `subject` string. On video, the shot mapping passed
`fg`/`mg`/`bg`/`height`/`dof`, keys apply_vlm never read, and no subjects.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from film.llm_providers import LLMReply
from film.shot_spec import ShotSpec
from film.shot_spec_fusion import apply_vlm
from film.video_analysis_models import AnalyzedShot, NarrativeAnalysis, VisualAnalysis
from handlers.video_analysis_handler import VideoAnalysisHandler

# What qwen2.5vl:7b returned for the leather-outfit reference in the report.
QWEN_READ: dict[str, object] = {
    "location": "studio",
    "environment": "plain white backdrop",
    "foreground": "woman in black leather outfit",
    "midground": "white backdrop",
    "background": "none",
    "shot_size": "full",
    "angle": "straight on",
    "camera_height": "standard",
    "lighting_quality": "bright and even light",
    "mood": "professional",
    "what_happens": "posed for photo",
    "confidence": 0.95,
}


class TestSubjectsFromTheVisionModel:
    def test_a_person_only_named_in_the_foreground_becomes_a_subject(self) -> None:
        spec = ShotSpec()
        apply_vlm(spec, dict(QWEN_READ), 0.95)
        assert spec.subjects, "the Subjects block stayed empty"
        assert "woman" in spec.subjects[0].label
        assert spec.provenance.get("subjects") == "vlm"
        assert spec.confidence["subjects"] < 0.95, "a derived subject is not as sure as a named one"

    def test_subjects_as_objects_keep_count_and_attributes(self) -> None:
        spec = ShotSpec()
        fields = dict(QWEN_READ)
        fields["subjects"] = [
            {"label": "Woman", "count": 1, "attributes": ["black leather catsuit", "hands on hips"]},
            {"name": "dog", "count": 2},
        ]
        apply_vlm(spec, fields, 0.9)
        assert [s.label for s in spec.subjects] == ["woman", "dog"]
        assert spec.subjects[0].attributes == ["black leather catsuit", "hands on hips"]
        assert spec.subjects[1].count == 2

    def test_detected_subjects_are_never_replaced(self) -> None:
        from film.shot_spec import SpecSubject

        spec = ShotSpec(subjects=[SpecSubject(label="person", count=1)])
        spec.set_section("subjects", "florence", 0.9)
        apply_vlm(spec, dict(QWEN_READ, subjects=["cat"]), 0.95)
        assert [s.label for s in spec.subjects] == ["person"]


class TestVideoShotMapping:
    def test_every_visual_field_reaches_the_spec(self) -> None:
        shot = AnalyzedShot(
            visual=VisualAnalysis(
                subjects=["woman", "motorbike"],
                location="city street",
                foreground="woman in a red coat",
                midground="parked cars",
                background="neon shop fronts",
                shot_size="medium",
                angle="low",
                camera_height="knee",
                depth_of_field="shallow",
                focus="woman",
                lighting="soft",
                confidence=0.8,
            ),
            narrative=NarrativeAnalysis(what_happens="she walks to the bike", story_beat="departure"),
        )
        VideoAnalysisHandler._apply_vlm_to_spec(shot)  # noqa: SLF001 - the mapping under test
        spec = shot.spec
        assert (spec.scene.fg, spec.scene.mg, spec.scene.bg) == ("woman in a red coat", "parked cars", "neon shop fronts")
        assert spec.camera.height == "knee"
        assert spec.camera.dof == "shallow"
        assert [s.label for s in spec.subjects] == ["woman", "motorbike"]
        assert spec.narrative.beat == "departure"


def _png(path: Path) -> Path:
    Image.new("RGB", (96, 160), (240, 240, 240)).save(path)
    return path


class TestImageReproduceEndToEnd:
    def test_without_detection_the_vlm_fills_subjects_and_is_asked_for_them(self, client, test_state, fake_services, create_fake_model_files, tmp_path, monkeypatch) -> None:
        create_fake_model_files(include_zit=True)
        fake_services.vision.disabled.add("florence")  # the installed runtime has no Florence-2
        asked: list[str] = []

        class _Qwen:
            name = "openai_compatible"
            model = "qwen2.5vl:7b"

            def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
                asked.append(messages[0].content)
                return LLMReply(text=json.dumps(QWEN_READ), tool_calls=[], model=self.model)

        monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _Qwen())
        client.post("/api/settings", json={"vision": {"vlmProvider": "director"}})
        imported = client.post("/api/reproduce/import", json={"path": str(_png(tmp_path / "reference.png"))}).json()
        job = client.post(f"/api/reproduce/{imported['id']}/analyze").json()

        assert "subjects" in asked[0], "the image prompt never asks the model for subjects"
        assert job["vision_model"] == "openai_compatible:qwen2.5vl:7b"
        assert job["spec"]["subjects"], "Subjects stayed empty with detection down"
        assert "woman" in job["spec"]["subjects"][0]["label"]
        for block in ("scene", "camera", "lighting", "narrative"):
            assert job["spec"]["provenance"].get(block) == "vlm", block


class TestFlexibleLists:
    def test_list_fields_keep_their_items(self) -> None:
        # Pydantic runs BeforeValidators last-listed first, so the string
        # flattener joined every multi-item list into one "a; b" entry.
        visual = VisualAnalysis(subjects=["woman", "motorbike"], props=["helmet", "keys", "map"])
        assert visual.subjects == ["woman", "motorbike"]
        assert visual.props == ["helmet", "keys", "map"]

    def test_the_shapes_small_models_emit_are_still_accepted(self) -> None:
        assert VisualAnalysis(subjects="astronaut").subjects == ["astronaut"]  # type: ignore[arg-type]
        assert VisualAnalysis(subjects=None).subjects == []  # type: ignore[arg-type]
        assert VisualAnalysis(subjects="").subjects == []
        assert VisualAnalysis(subjects=["astronaut", " ", 3]).subjects == ["astronaut"]  # type: ignore[list-item]
        assert VisualAnalysis(background=["dark space"]).background == "dark space"  # type: ignore[arg-type]
