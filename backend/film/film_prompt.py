"""Prompt synthesis: structured shot state -> generation-ready visual prompt.

Adapts BlueFish's style-variable prompt assembly idea: every structured field
contributes a phrase; the shot's structured fields are never discarded — the
synthesized prompt is stored alongside them and only overwrites
`shot.visual_prompt` while `prompt_locked` is False.
"""

from __future__ import annotations

from film.film_models import (
    CAMERA_ANGLE_LABELS,
    CAMERA_ELEVATION_LABELS,
    CAMERA_MOVE_LABELS,
    COMPOSITION_LABELS,
    SHOT_SIZE_LABELS,
    FilmAsset,
    FilmProject,
    FilmScene,
    FilmShot,
)
from film.shot_vocabulary import (
    ANGLE_PHRASES,
    CAMERA_MOVE_PHRASES,
    COMPOSITION_PHRASES,
    ELEVATION_PHRASES,
    SHOT_SIZE_PHRASES,
)


def _describe_character(asset: FilmAsset, emotion: str, pose_name: str) -> str:
    parts = [asset.name]
    details = ", ".join(p for p in (asset.description, asset.appearance, asset.wardrobe) if p)
    if details:
        parts.append(f"({details})")
    if emotion:
        parts.append(f"looking {emotion}")
    if pose_name:
        parts.append(f"in a {pose_name} pose")
    return " ".join(parts)


def _describe_location(asset: FilmAsset, scene: FilmScene) -> str:
    parts = [p for p in (asset.name, asset.description, asset.environment, asset.atmosphere) if p]
    lighting = scene.lighting or asset.lighting
    if lighting:
        parts.append(f"{lighting} lighting")
    time_of_day = scene.time_of_day or asset.time_of_day
    if time_of_day:
        parts.append(time_of_day)
    return ", ".join(parts)


def synthesize_prompt(project: FilmProject, scene: FilmScene, shot: FilmShot) -> str:
    """Build a visual prompt from the shot's structured fields."""
    fragments: list[str] = []

    framing = shot.framing
    cinematography = ", ".join(
        p
        for p in (
            SHOT_SIZE_PHRASES.get(framing.shot_size, ""),
            ANGLE_PHRASES.get(framing.camera_angle, ""),
            ELEVATION_PHRASES.get(framing.camera_elevation, ""),
            COMPOSITION_PHRASES.get(framing.composition, ""),
        )
        if p
    )
    if cinematography:
        fragments.append(cinematography)

    subject_bits: list[str] = []
    for shot_character in shot.characters:
        asset = project.asset(shot_character.asset_id)
        if asset is not None:
            subject_bits.append(
                _describe_character(asset, shot_character.emotion or shot.emotion, shot_character.pose_name)
            )
    if subject_bits:
        fragments.append("; ".join(subject_bits))

    if shot.action:
        fragments.append(shot.action)
    elif shot.description:
        fragments.append(shot.description)

    if shot.dialogue:
        fragments.append(f'dialogue: "{shot.dialogue}"')

    location_id = shot.location_id or scene.location_id
    if location_id:
        location = project.asset(location_id)
        if location is not None:
            described = _describe_location(location, scene)
            if described:
                fragments.append(f"setting: {described}")
    elif scene.description:
        fragments.append(f"setting: {scene.description}")

    for prop_id in shot.prop_ids:
        prop = project.asset(prop_id)
        if prop is not None:
            detail = f" ({prop.prop_details})" if prop.prop_details else ""
            fragments.append(f"featuring {prop.name}{detail}")

    if scene.mood:
        fragments.append(f"{scene.mood} mood")

    move_phrase = CAMERA_MOVE_PHRASES.get(shot.camera_move, "")
    if move_phrase:
        fragments.append(move_phrase)

    style_bits = [p for p in (project.settings.style_prompt,) if p]
    for asset in project.assets:
        if asset.kind == "style" and asset.style_prompt:
            style_bits.append(asset.style_prompt)
    if style_bits:
        fragments.append(", ".join(style_bits))

    fragments.append("cinematic, professional cinematography, high detail")
    return ". ".join(fragment.strip().rstrip(".") for fragment in fragments if fragment.strip())


def synthesize_negative_prompt(project: FilmProject, shot: FilmShot) -> str:
    if shot.negative_prompt:
        return shot.negative_prompt
    return project.settings.default_negative_prompt


def framing_summary(shot: FilmShot) -> str:
    """Short human-readable framing line for cards and warnings."""
    framing = shot.framing
    parts = [
        SHOT_SIZE_LABELS.get(framing.shot_size, framing.shot_size),
        CAMERA_ANGLE_LABELS.get(framing.camera_angle, framing.camera_angle),
        CAMERA_ELEVATION_LABELS.get(framing.camera_elevation, framing.camera_elevation),
        COMPOSITION_LABELS.get(framing.composition, framing.composition),
    ]
    if shot.camera_move != "static":
        parts.append(CAMERA_MOVE_LABELS.get(shot.camera_move, shot.camera_move))
    return " · ".join(parts)
