"""Every spec field the VLM can answer gets asked for.

MEASURED in the installed app (job ia-7806a69e0a03, 2026-09-30): after the
analysis the spec still had scene.time_of_day / scene.bg and camera.fov_deg /
focal_mm / aperture / move empty. The follow-up question fired only for a
block with *no* field filled, and a partial answer could not be merged: the
scene/lighting/narrative sections were replaced wholesale. Now the empty
fields are listed by name, asked for once, and filled field by field without
overwriting anything already there.
"""

from __future__ import annotations

from film.shot_spec import ShotSpec
from film.shot_spec_fusion import empty_fields, fill_empty_fields


def test_empty_fields_are_listed_by_name():
    spec = ShotSpec()
    spec.scene.location = "photo studio"
    spec.camera.shot_size = "full"
    missing = empty_fields(spec)
    assert "scene.location" not in missing and "camera.shot_size" not in missing
    for name in ("scene.time_of_day", "scene.bg", "camera.focal_mm", "camera.aperture", "lighting.mood", "narrative.what_happens"):
        assert name in missing, name


def test_a_partial_answer_fills_only_the_empty_fields():
    spec = ShotSpec()
    spec.scene.location = "photo studio"
    spec.set_section("scene", "vlm", 0.8)
    wrote = fill_empty_fields(spec, {
        "scene.location": "a beach",          # already set: must not overwrite
        "scene.time_of_day": "day",
        "scene.bg": "seamless white paper backdrop",
        "camera.focal_mm": "50mm",
        "camera.fov_deg": 46,
        "camera.aperture": "f/8",
        "camera.move": "static",
        "lighting.mood": "unknown",           # placeholder: ignored
    }, 0.6)
    assert spec.scene.location == "photo studio"
    assert spec.scene.time_of_day == "day" and spec.scene.bg == "seamless white paper backdrop"
    assert spec.camera.focal_mm == 50.0 and spec.camera.fov_deg == 46.0
    assert spec.camera.aperture == "f/8" and spec.camera.move == "static"
    assert spec.lighting.mood == ""
    assert "scene.time_of_day" in wrote and "scene.location" not in wrote


def test_locked_sections_are_left_alone():
    spec = ShotSpec()
    spec.locks["camera"] = True
    fill_empty_fields(spec, {"camera.aperture": "f/2"}, 0.6)
    assert spec.camera.aperture == ""


class TestAFailedComponentIsRetriedNotCached:
    """MEASURED in the installed app (2026-09-30): after Florence-2 was fixed
    (transformers 4.54 -> 4.57.6), a re-analysis of the same image still said
    "cannot import name 'Florence2ForConditionalGeneration'": the vision cache
    treated the recorded *failure* as a final answer. A disabled component
    stays cached; a failed one is retried."""

    def _png(self, tmp_path):
        from PIL import Image

        path = tmp_path / "ref.png"
        Image.new("RGB", (64, 48), (200, 30, 30)).save(path)
        return str(path)

    def test_a_component_that_failed_is_run_again(self, test_state, fake_services, tmp_path):
        image = self._png(tmp_path)
        original = fake_services.vision.caption

        def broken(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("cannot import name 'Florence2ForConditionalGeneration' from 'transformers'")

        fake_services.vision.caption = broken
        first = test_state.vision.analyze(image)
        assert first.caption is None and "caption" in first.notes
        fake_services.vision.caption = original
        second = test_state.vision.analyze(image)
        assert second.caption is not None, "the cached failure was served instead of retrying"

    def test_a_disabled_component_stays_cached(self, test_state, fake_services, tmp_path):
        image = self._png(tmp_path)
        fake_services.vision.disabled.add("florence")
        test_state.vision.analyze(image)
        calls: list[int] = []
        original = fake_services.vision.caption
        fake_services.vision.caption = lambda *a, **k: calls.append(1) or original(*a, **k)
        test_state.vision.analyze(image)
        assert calls == [], "a component the user switched off was retried"


def test_the_prompt_does_not_repeat_scene_terms():
    """MEASURED (ia-da9ab2af6672): location, environment, time of day and
    weather all answered "studio" and the prompt read "studio, studio,
    studio, studio"."""
    from film.prompt_compiler import compile_from_spec

    spec = ShotSpec()
    spec.scene.location = "studio"
    spec.scene.environment = "Studio"
    spec.scene.time_of_day = "studio"
    spec.scene.weather = "studio"
    spec.scene.bg = "white"
    prompt = compile_from_spec(spec, "z_image").prompt.lower()
    assert "studio, studio" not in prompt and prompt.count("studio") == 1, prompt
