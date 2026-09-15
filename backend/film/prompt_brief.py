"""Building a `ShotBrief` from whatever the app already knows about a shot.

Two sources, one destination. A shot the user built in the storyboard and a
shot recovered from an imported video carry different structures, but a brief
is a brief: once either is in that shape, the compiler treats them identically
and a reconstructed shot gets exactly the same per-model prompts as an
authored one.

Nothing is invented here. A field the source does not have stays empty, and the
compiler omits empty sections rather than padding them.
"""

from __future__ import annotations

from film.film_models import FilmProject, FilmScene, FilmShot
from film.shot_vocabulary import (
    ANGLE_PHRASES,
    CAMERA_MOVE_PHRASES,
    COMPOSITION_PHRASES,
    ELEVATION_PHRASES,
    SHOT_SIZE_PHRASES,
)
from film.prompt_compiler import ShotBrief
from film.video_analysis_models import AnalyzedShot, VideoAnalysis


def _clauses(*parts: str) -> str:
    """Join written fragments with commas.

    Asset descriptions are prose and often end in a full stop; joining them
    raw produces "buried in snow., Cramped interior", which reads as a typo in
    the compiled prompt.
    """
    return ", ".join(part.strip().rstrip(".").strip() for part in parts if part.strip())


def brief_from_shot(project: FilmProject, scene: FilmScene, shot: FilmShot) -> ShotBrief:
    """The storyboard's structured fields, as a brief.

    Reuses the shared shot vocabulary rather than restating it, so the
    words a shot is described with do not drift between the prompt the host
    renders and the prompt compiled for another model.
    """
    framing = shot.framing

    subjects: list[str] = []
    for shot_character in shot.characters:
        asset = project.asset(shot_character.asset_id)
        if asset is None:
            continue
        details = _clauses(asset.description, asset.appearance, asset.wardrobe)
        emotion = shot_character.emotion or shot.emotion
        subject = asset.name
        if details:
            subject = f"{subject} ({details})"
        if emotion:
            subject = f"{subject}, looking {emotion}"
        if shot_character.pose_name:
            subject = f"{subject}, in a {shot_character.pose_name} pose"
        subjects.append(subject)
    for prop_id in shot.prop_ids:
        prop = project.asset(prop_id)
        if prop is not None:
            subjects.append(f"{prop.name}{f' ({prop.prop_details})' if prop.prop_details else ''}")

    location = ""
    location_id = shot.location_id or scene.location_id
    if location_id:
        asset = project.asset(location_id)
        if asset is not None:
            location = _clauses(asset.name, asset.description, asset.environment, asset.atmosphere)
    if not location and scene.description:
        location = scene.description

    camera = ", ".join(
        p
        for p in (
            ANGLE_PHRASES.get(framing.camera_angle, ""),
            ELEVATION_PHRASES.get(framing.camera_elevation, ""),
            COMPOSITION_PHRASES.get(framing.composition, ""),
        )
        if p
    )

    lighting_parts: list[str] = []
    if scene.lighting:
        lighting_parts.append(f"{scene.lighting} lighting")
    if scene.time_of_day:
        lighting_parts.append(scene.time_of_day)

    style_parts: list[str] = []
    if project.settings.style_prompt:
        style_parts.append(project.settings.style_prompt)
    style_parts.extend(a.style_prompt for a in project.assets if a.kind == "style" and a.style_prompt)
    if scene.mood:
        style_parts.append(f"{scene.mood} mood")

    audio = f'dialogue: "{shot.dialogue}"' if shot.dialogue else ""

    timeline = ""
    if shot.duration_seconds:
        timeline = f"{shot.duration_seconds:g} seconds at {shot.generation.fps}fps"

    # Continuity is constraint, not description: what must hold across the cut.
    continuity: list[str] = []
    if scene.continuity_notes:
        continuity.append(scene.continuity_notes)
    for shot_character in shot.characters:
        asset = project.asset(shot_character.asset_id)
        if asset is not None and asset.wardrobe:
            continuity.append(f"{asset.name} wearing {asset.wardrobe}")

    negative = [part.strip() for part in (shot.negative_prompt or project.settings.default_negative_prompt).split(",")]

    return ShotBrief(
        scene_intent=scene.description,
        subjects=subjects,
        action=shot.action or shot.description,
        location=location,
        shot_size=SHOT_SIZE_PHRASES.get(framing.shot_size, ""),
        camera=camera,
        lens="",  # the storyboard has no lens field; the composer's framing carries it
        movement=CAMERA_MOVE_PHRASES.get(shot.camera_move, ""),
        lighting=", ".join(lighting_parts),
        style=", ".join(style_parts),
        audio=audio,
        timeline=timeline,
        continuity=continuity,
        negative=[item for item in negative if item],
    )


def brief_from_analysis(analysis: VideoAnalysis, shot: AnalyzedShot) -> ShotBrief:
    """What was measured and inferred from an imported video, as a brief.

    Inferred fields carry a confidence on the analysis; that is the caller's to
    surface. This function only reshapes what is there — it does not filter by
    confidence, because deciding a description is too uncertain to use is a
    judgement for the screen showing it, not for the compiler.
    """
    visual, camera, narrative, editorial, audio = (
        shot.visual,
        shot.cinematography,
        shot.narrative,
        shot.editorial,
        shot.audio,
    )

    subjects = list(visual.subjects[:4])
    if visual.wardrobe:
        subjects.append(visual.wardrobe)

    camera_parts = [p for p in (visual.angle, visual.camera_height, camera.camera_position) if p]
    lighting_parts = [p for p in (visual.lighting, ", ".join(visual.palette[:3]), visual.contrast) if p]
    style_parts = [p for p in (visual.visual_style, visual.production_design, analysis.visual_style) if p]

    audio_parts: list[str] = []
    if audio.analyzed:
        audio_parts = [p for p in (audio.dialogue, audio.voiceover, audio.ambience, audio.music) if p]

    timeline_parts = [f"{shot.duration:.1f} seconds"]
    # Rhythm and pacing often carry the same word; saying it twice reads as a
    # stutter in the compiled prompt rather than as emphasis.
    tempo = editorial.rhythm or narrative.pacing
    if tempo:
        timeline_parts.append(f"{tempo} pacing")

    continuity = list(narrative.continuity_implications[:4])
    if camera.screen_direction:
        continuity.append(f"screen direction: {camera.screen_direction}")
    if camera.eyeline:
        continuity.append(f"eyeline: {camera.eyeline}")

    return ShotBrief(
        scene_intent=narrative.narrative_purpose or narrative.story_beat,
        subjects=subjects,
        action=narrative.what_happens or visual.description,
        location=" ".join(p for p in (visual.location, visual.environment) if p).strip(),
        shot_size=visual.shot_size,
        camera=", ".join(camera_parts),
        lens=", ".join(p for p in (visual.lens_estimate, visual.depth_of_field) if p),
        movement=camera.camera_movement or ("static camera" if camera.is_static else ""),
        lighting=", ".join(lighting_parts),
        style=", ".join(style_parts),
        audio="; ".join(audio_parts),
        timeline=", ".join(timeline_parts),
        continuity=continuity,
        negative=["text", "watermark", "logo", "distorted hands", "extra limbs"],
    )
