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
