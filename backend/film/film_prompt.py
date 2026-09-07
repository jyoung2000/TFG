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

_SHOT_SIZE_PHRASES: dict[str, str] = {
    "xwide": "extreme wide shot",
    "wide": "wide shot",
    "full": "full shot",
    "medium": "medium shot",
    "mcu": "medium close-up",
    "closeup": "close-up",
    "xcu": "extreme close-up",
}
_ANGLE_PHRASES: dict[str, str] = {
    "front": "front angle",
    "threeQuarterLeft": "three-quarter left angle",
    "threeQuarterRight": "three-quarter right angle",
    "profile": "profile angle",
    "back": "shot from behind",
    "ots": "over-the-shoulder shot",
    "pov": "point-of-view shot",
    "dutch": "dutch angle, tilted horizon",
}
_ELEVATION_PHRASES: dict[str, str] = {
    "eye": "eye-level camera",
    "low": "low-angle camera looking up",
    "high": "high-angle camera looking down",
    "bird": "bird's-eye view from above",
    "worm": "worm's-eye view from ground level",
}
_COMPOSITION_PHRASES: dict[str, str] = {
    "center": "subject centered in frame",
    "leftThird": "subject on the left third of the frame",
    "rightThird": "subject on the right third of the frame",
    "upperThird": "subject in the upper third of the frame",
    "lowerThird": "subject in the lower third of the frame",
    "negativeSpace": "strong negative space, subject far off-center",
    "symmetrical": "symmetrical composition",
    "leadingLines": "leading lines drawing the eye to the subject",
}
_CAMERA_MOVE_PHRASES: dict[str, str] = {
    "static": "static camera, locked-off shot",
    "push_in": "slow push in, camera moving toward the subject",
    "pull_out": "slow pull out, camera moving away from the subject",
    "pan_left": "camera panning left",
    "pan_right": "camera panning right",
    "tilt_up": "camera tilting up",
    "tilt_down": "camera tilting down",
    "dolly_left": "camera trucking left, lateral movement",
    "dolly_right": "camera trucking right, lateral movement",
    "orbit": "camera orbiting around the subject",
    "follow": "camera following the subject",
}


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
            _SHOT_SIZE_PHRASES.get(framing.shot_size, ""),
            _ANGLE_PHRASES.get(framing.camera_angle, ""),
            _ELEVATION_PHRASES.get(framing.camera_elevation, ""),
            _COMPOSITION_PHRASES.get(framing.composition, ""),
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

    move_phrase = _CAMERA_MOVE_PHRASES.get(shot.camera_move, "")
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
