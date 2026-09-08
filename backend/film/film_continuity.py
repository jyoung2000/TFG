"""Continuity checks: non-blocking warnings computed from shared project assets.

Every warning carries a severity and, where the app can repair it, a concrete
fix (a director command the UI/API can apply). A shot's overall level is the
worst severity among its warnings:

    GOOD < MINOR < SIGNIFICANT < BROKEN
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.film_models import FilmProject, FilmScene, FilmShot

ContinuityKind = Literal[
    "missing_asset",
    "location_mismatch",
    "character_not_in_scene",
    "prop_not_in_scene",
    "missing_capture",
    "missing_previous_output",
    "wardrobe_change",
    "duration_invalid",
    "screen_direction",
    "jump_cut",
    "framing_jump",
]

ContinuitySeverity = Literal["minor", "significant", "broken"]
ContinuityLevel = Literal["good", "minor", "significant", "broken"]

_SEVERITY: dict[str, ContinuitySeverity] = {
    "missing_asset": "broken",
    "duration_invalid": "broken",
    "location_mismatch": "significant",
    "missing_previous_output": "significant",
    "wardrobe_change": "significant",
    "character_not_in_scene": "minor",
    "prop_not_in_scene": "minor",
    "missing_capture": "minor",
    "screen_direction": "significant",
    "jump_cut": "minor",
    "framing_jump": "minor",
}

_SHOT_SIZE_ORDER = ["xwide", "wide", "full", "medium", "mcu", "closeup", "xcu"]

_LEVEL_RANK: dict[str, int] = {"good": 0, "minor": 1, "significant": 2, "broken": 3}


class ContinuityWarning(BaseModel):
    kind: ContinuityKind
    message: str
    severity: ContinuitySeverity = "minor"
    # Human-readable suggested fix.
    fix: str = ""
    # True when POST .../continuity/{shot_id}/fix can repair it automatically.
    auto_fixable: bool = False
    # Which asset/reference the warning is about (for targeted fixes).
    subject_id: str = ""


class ContinuityReport(BaseModel):
    level: ContinuityLevel
    warnings: list[ContinuityWarning] = Field(default_factory=list[ContinuityWarning])


def continuity_level(warnings: list[ContinuityWarning]) -> ContinuityLevel:
    worst: ContinuityLevel = "good"
    for warning in warnings:
        if _LEVEL_RANK[warning.severity] > _LEVEL_RANK[worst]:
            worst = warning.severity
    return worst


def _warn(kind: ContinuityKind, message: str, *, fix: str, auto_fixable: bool, subject_id: str = "") -> ContinuityWarning:
    return ContinuityWarning(
        kind=kind,
        message=message,
        severity=_SEVERITY[kind],
        fix=fix,
        auto_fixable=auto_fixable,
        subject_id=subject_id,
    )


def check_shot_continuity(
    project: FilmProject, scene: FilmScene, shot: FilmShot
) -> list[ContinuityWarning]:
    warnings: list[ContinuityWarning] = []

    for shot_character in shot.characters:
        asset = project.asset(shot_character.asset_id)
        if asset is None:
            warnings.append(
                _warn(
                    "missing_asset",
                    f"Shot references a character asset that no longer exists ({shot_character.asset_id}).",
                    fix="Remove the dangling character reference from the shot.",
                    auto_fixable=True,
                    subject_id=shot_character.asset_id,
                )
            )
        elif scene.character_ids and shot_character.asset_id not in scene.character_ids:
            warnings.append(
                _warn(
                    "character_not_in_scene",
                    f"{asset.name} is in this shot but not listed in the scene's characters.",
                    fix=f"Add {asset.name} to the scene's cast.",
                    auto_fixable=True,
                    subject_id=asset.id,
                )
            )

    if shot.location_id is not None:
        location = project.asset(shot.location_id)
        if location is None:
            warnings.append(
                _warn(
                    "missing_asset",
                    f"Shot references a location asset that no longer exists ({shot.location_id}).",
                    fix="Clear the shot's location.",
                    auto_fixable=True,
                    subject_id=shot.location_id,
                )
            )
        elif scene.location_id is not None and shot.location_id != scene.location_id:
            scene_location = project.asset(scene.location_id)
            scene_name = scene_location.name if scene_location else scene.location_id
            warnings.append(
                _warn(
                    "location_mismatch",
                    f"Shot location ({location.name}) differs from the scene's location ({scene_name}).",
                    fix=f"Use the scene's location ({scene_name}) for this shot.",
                    auto_fixable=True,
                    subject_id=shot.location_id,
                )
            )

    for prop_id in shot.prop_ids:
        prop = project.asset(prop_id)
        if prop is None:
            warnings.append(
                _warn(
                    "missing_asset",
                    f"Shot references a prop asset that no longer exists ({prop_id}).",
                    fix="Remove the dangling prop reference from the shot.",
                    auto_fixable=True,
                    subject_id=prop_id,
                )
            )
        elif scene.prop_ids and prop_id not in scene.prop_ids:
            warnings.append(
                _warn(
                    "prop_not_in_scene",
                    f"Prop {prop.name} is in this shot but not listed in the scene's props.",
                    fix=f"Add {prop.name} to the scene's props.",
                    auto_fixable=True,
                    subject_id=prop.id,
                )
            )

    # Only a *composed* shot without a capture is inconsistent; a fresh draft
    # simply generates from text, so it stays GOOD.
    if shot.generation.use_capture_as_reference and shot.composition is not None and not shot.capture_path:
        warnings.append(
            _warn(
                "missing_capture",
                "Generation is set to use the composition capture, but no capture exists yet.",
                fix="Open the Shot Composer and capture the frame, or generate from text only.",
                auto_fixable=True,
            )
        )

    if shot.generation.continue_from_previous:
        previous = project.previous_shot(shot.id)
        previous_output = ""
        if previous is not None and previous.current_version is not None:
            version = previous.version(previous.current_version)
            if version is not None:
                previous_output = version.output_path
        if not previous_output:
            warnings.append(
                _warn(
                    "missing_previous_output",
                    "Continue-from-previous is enabled, but the previous shot has no generated output yet.",
                    fix="Generate the previous shot first, or turn continue-from-previous off.",
                    auto_fixable=True,
                )
            )

    previous = project.previous_shot(shot.id)
    if previous is not None and previous.current_version is not None:
        previous_version = previous.version(previous.current_version)
        if previous_version is not None:
            for shot_character in shot.characters:
                asset = project.asset(shot_character.asset_id)
                if asset is None:
                    continue
                generated_with = previous_version.wardrobe_snapshot.get(shot_character.asset_id)
                if generated_with is not None and generated_with != asset.wardrobe:
                    warnings.append(
                        _warn(
                            "wardrobe_change",
                            (
                                f"{asset.name}'s wardrobe changed since the previous shot was "
                                f"generated (was: {generated_with or 'unset'})."
                            ),
                            fix=(
                                f"Regenerate the previous shot with the new wardrobe, or restore "
                                f"{asset.name}'s wardrobe to '{generated_with or 'unset'}'."
                            ),
                            auto_fixable=False,
                            subject_id=asset.id,
                        )
                    )

    if shot.duration_seconds <= 0:
        warnings.append(
            _warn(
                "duration_invalid",
                "Shot duration must be greater than zero.",
                fix="Set the duration to 4 seconds.",
                auto_fixable=True,
            )
        )

    if previous is not None and previous_in_same_scene(project, previous, shot):
        warnings.extend(camera_continuity_warnings(previous, shot))

    return warnings


def previous_in_same_scene(project: FilmProject, previous: FilmShot, shot: FilmShot) -> bool:
    found_prev = project.find_shot(previous.id)
    found_cur = project.find_shot(shot.id)
    return found_prev is not None and found_cur is not None and found_prev[0].id == found_cur[0].id


def _camera_side(shot: FilmShot, a_id: str, b_id: str) -> float | None:
    """Sign of the camera's side of the line through characters a→b on the
    ground plane (the 180° "axis of action"). None when not determinable."""
    composition = shot.composition
    if composition is None or composition.camera is None:
        return None
    a = next((o for o in composition.objects if o.asset_id == a_id), None)
    b = next((o for o in composition.objects if o.asset_id == b_id), None)
    if a is None or b is None:
        return None
    ax, _, az = a.transform.position
    bx, _, bz = b.transform.position
    cx, _, cz = composition.camera.transform.position
    dx, dz = bx - ax, bz - az
    if abs(dx) + abs(dz) < 1e-6:
        return None
    cross = dx * (cz - az) - dz * (cx - ax)
    if abs(cross) < 1e-3:
        return None
    return 1.0 if cross > 0 else -1.0


def camera_continuity_warnings(previous: FilmShot, shot: FilmShot) -> list[ContinuityWarning]:
    """Deterministic screen-direction / framing checks between consecutive
    shots of the same scene. Warnings, not rules: filmmakers break them on
    purpose, so nothing here is auto-fixable."""
    warnings: list[ContinuityWarning] = []
    shared = [c.asset_id for c in shot.characters if any(p.asset_id == c.asset_id for p in previous.characters)]
    if len(shared) >= 2:
        a_id, b_id = shared[0], shared[1]
        side_prev = _camera_side(previous, a_id, b_id)
        side_cur = _camera_side(shot, a_id, b_id)
        if side_prev is not None and side_cur is not None and side_prev != side_cur:
            warnings.append(
                _warn(
                    "screen_direction",
                    "The camera crosses the line of action between the two characters compared with the "
                    "previous shot (180° rule) — screen direction will flip.",
                    fix="Move the shot camera to the same side of the characters as the previous shot, or add a neutral/cutaway shot between them.",
                    auto_fixable=False,
                )
            )
    if shared or (len(shot.characters) == 1 and len(previous.characters) == 1 and shot.characters[0].asset_id == previous.characters[0].asset_id):
        prev_f, cur_f = previous.framing, shot.framing
        same_setup = (
            prev_f.shot_size == cur_f.shot_size
            and prev_f.camera_angle == cur_f.camera_angle
            and prev_f.camera_elevation == cur_f.camera_elevation
            and previous.camera_move == shot.camera_move
        )
        if same_setup:
            warnings.append(
                _warn(
                    "jump_cut",
                    "Same subject, same shot size, angle and elevation as the previous shot — this will read as a jump cut.",
                    fix="Change the shot size by at least two steps or the angle by ~30°, or merge the shots.",
                    auto_fixable=False,
                )
            )
        else:
            try:
                delta = abs(_SHOT_SIZE_ORDER.index(prev_f.shot_size) - _SHOT_SIZE_ORDER.index(cur_f.shot_size))
            except ValueError:
                delta = 0
            if delta >= 5 and prev_f.camera_angle == cur_f.camera_angle:
                warnings.append(
                    _warn(
                        "framing_jump",
                        "Severe framing jump on the same axis (e.g. extreme wide straight to extreme close-up).",
                        fix="Add an intermediate shot size, or change the angle so the cut reads as a new setup.",
                        auto_fixable=False,
                    )
                )
    return warnings


def shot_continuity_report(project: FilmProject, scene: FilmScene, shot: FilmShot) -> ContinuityReport:
    warnings = check_shot_continuity(project, scene, shot)
    return ContinuityReport(level=continuity_level(warnings), warnings=warnings)
