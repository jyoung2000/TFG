"""Continuity checks: non-blocking warnings computed from shared project assets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
]


class ContinuityWarning(BaseModel):
    kind: ContinuityKind
    message: str


def check_shot_continuity(
    project: FilmProject, scene: FilmScene, shot: FilmShot
) -> list[ContinuityWarning]:
    warnings: list[ContinuityWarning] = []

    for shot_character in shot.characters:
        asset = project.asset(shot_character.asset_id)
        if asset is None:
            warnings.append(
                ContinuityWarning(
                    kind="missing_asset",
                    message=f"Shot references a character asset that no longer exists ({shot_character.asset_id}).",
                )
            )
        elif scene.character_ids and shot_character.asset_id not in scene.character_ids:
            warnings.append(
                ContinuityWarning(
                    kind="character_not_in_scene",
                    message=f"{asset.name} is in this shot but not listed in the scene's characters.",
                )
            )

    if shot.location_id is not None:
        location = project.asset(shot.location_id)
        if location is None:
            warnings.append(
                ContinuityWarning(
                    kind="missing_asset",
                    message=f"Shot references a location asset that no longer exists ({shot.location_id}).",
                )
            )
        elif scene.location_id is not None and shot.location_id != scene.location_id:
            scene_location = project.asset(scene.location_id)
            scene_name = scene_location.name if scene_location else scene.location_id
            warnings.append(
                ContinuityWarning(
                    kind="location_mismatch",
                    message=f"Shot location ({location.name}) differs from the scene's location ({scene_name}).",
                )
            )

    for prop_id in shot.prop_ids:
        prop = project.asset(prop_id)
        if prop is None:
            warnings.append(
                ContinuityWarning(
                    kind="missing_asset",
                    message=f"Shot references a prop asset that no longer exists ({prop_id}).",
                )
            )
        elif scene.prop_ids and prop_id not in scene.prop_ids:
            warnings.append(
                ContinuityWarning(
                    kind="prop_not_in_scene",
                    message=f"Prop {prop.name} is in this shot but not listed in the scene's props.",
                )
            )

    if shot.generation.use_capture_as_reference and not shot.capture_path:
        warnings.append(
            ContinuityWarning(
                kind="missing_capture",
                message="Generation is set to use the composition capture, but no capture exists yet.",
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
                ContinuityWarning(
                    kind="missing_previous_output",
                    message="Continue-from-previous is enabled, but the previous shot has no generated output yet.",
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
                        ContinuityWarning(
                            kind="wardrobe_change",
                            message=(
                                f"{asset.name}'s wardrobe changed since the previous shot was "
                                f"generated (was: {generated_with or 'unset'})."
                            ),
                        )
                    )

    if shot.duration_seconds <= 0:
        warnings.append(
            ContinuityWarning(
                kind="duration_invalid",
                message="Shot duration must be greater than zero.",
            )
        )

    return warnings
