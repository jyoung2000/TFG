"""Timeline edits, as pure functions over a project.

Every operation here takes a `FilmProject` and mutates it in place, and does
nothing else — no locks, no IO, no clock beyond what the models supply. That
makes each one testable on its own and keeps the handler down to "snapshot,
apply, save", which is where the undo guarantee comes from.

Each raises `TimelineError` rather than returning a failure, so a partially
applied edit is impossible: the handler snapshots before calling in, and an
exception means nothing was written.
"""

from __future__ import annotations

from film.film_models import (
    FilmProject,
    FilmScene,
    FilmShot,
    ShotTransition,
    now_ms,
)

#: The shortest shot the timeline will produce. Below this a shot is not a
#: shot, and every renderer this app talks to refuses it anyway.
MIN_DURATION = 0.5
MAX_DURATION = 60.0


class TimelineError(Exception):
    """A timeline edit that cannot be made. Carries a message for the user."""


def _renumber(scene: FilmScene) -> None:
    for index, shot in enumerate(sorted(scene.shots, key=lambda s: s.order)):
        shot.order = index
    scene.shots.sort(key=lambda s: s.order)


def _clamp_duration(seconds: float) -> float:
    return round(max(MIN_DURATION, min(MAX_DURATION, seconds)), 2)


def locate(project: FilmProject, shot_id: str) -> tuple[FilmScene, FilmShot]:
    found = project.find_shot(shot_id)
    if found is None:
        raise TimelineError(f"Shot not found: {shot_id}")
    return found


def require_scene(project: FilmProject, scene_id: str) -> FilmScene:
    scene = project.scene(scene_id)
    if scene is None:
        raise TimelineError(f"Scene not found: {scene_id}")
    return scene


def ordered_shots(project: FilmProject) -> list[tuple[FilmScene, FilmShot]]:
    """Every shot in playing order, across scenes."""
    pairs: list[tuple[FilmScene, FilmShot]] = []
    for scene in sorted(project.scenes, key=lambda s: s.order):
        for shot in sorted(scene.shots, key=lambda s: s.order):
            pairs.append((scene, shot))
    return pairs


def _copy_shot(source: FilmShot, *, title: str, order: int) -> FilmShot:
    """A new shot with the same look, and none of the source's render history.

    Versions and captures are deliberately not carried over: the copy has not
    been rendered, and showing it the original's take would be a lie about what
    exists.
    """
    copy = source.model_copy(deep=True)
    copy.id = FilmShot().id
    copy.title = title
    copy.order = order
    copy.versions = []
    copy.current_version = None
    copy.capture_path = ""
    copy.status = "draft"
    copy.created_at = now_ms()
    copy.updated_at = now_ms()
    return copy


# ---- cutting ------------------------------------------------------------


def split_shot(project: FilmProject, shot_id: str, at_seconds: float | None = None) -> list[str]:
    """Cut one shot into two, dividing its duration.

    The second half keeps the look and the prompt but not the render: it is a
    different shot now and has not been made yet.
    """
    scene, shot = locate(project, shot_id)
    point = at_seconds if at_seconds is not None else shot.duration_seconds / 2
    if point <= 0 or point >= shot.duration_seconds:
        raise TimelineError(
            f"Split point must be inside the shot (0 to {shot.duration_seconds:g}s), got {point:g}s"
        )
    if min(point, shot.duration_seconds - point) < MIN_DURATION:
        raise TimelineError(f"Both halves must be at least {MIN_DURATION:g}s")

    second = _copy_shot(shot, title=f"{shot.title} (b)", order=shot.order + 1)
    second.duration_seconds = _clamp_duration(shot.duration_seconds - point)
    second.gap_before_seconds = 0.0
    # The cut between the halves is a cut, whatever bracketed the original.
    second.transition_in = ShotTransition()
    second.transition_out = shot.transition_out.model_copy(deep=True)

    shot.duration_seconds = _clamp_duration(point)
    shot.title = f"{shot.title} (a)"
    shot.transition_out = ShotTransition()
    shot.updated_at = now_ms()

    for other in scene.shots:
        if other.order > shot.order:
            other.order += 1
    scene.shots.append(second)
    _renumber(scene)
    return [shot.id, second.id]


def trim_shot(project: FilmProject, shot_id: str, seconds: float) -> float:
    """Change one shot's duration. Nothing else moves."""
    _, shot = locate(project, shot_id)
    shot.duration_seconds = _clamp_duration(seconds)
    shot.updated_at = now_ms()
    return shot.duration_seconds


def ripple_trim(project: FilmProject, shot_id: str, seconds: float) -> dict[str, float]:
    """Trim a shot and hold the film's total length.

    The difference is taken out of, or given to, the gaps that follow — so a
    ripple trim shortens one shot without shortening the film. When the gaps
    cannot absorb it, the film changes length and the result says by how much,
    rather than silently doing something else.
    """
    scene, shot = locate(project, shot_id)
    before = shot.duration_seconds
    after = _clamp_duration(seconds)
    delta = after - before
    shot.duration_seconds = after
    shot.updated_at = now_ms()

    remaining = delta
    if delta != 0:
        following = [s for s in sorted(scene.shots, key=lambda s: s.order) if s.order > shot.order]
        for candidate in following:
            if remaining == 0:
                break
            gap = candidate.gap_before_seconds if candidate.gap_before_seconds is not None else 0.0
            # Growing the shot eats gaps; shrinking it gives the time back to
            # the next gap so the running time holds.
            adjusted = max(0.0, gap - remaining)
            absorbed = gap - adjusted
            candidate.gap_before_seconds = round(adjusted, 2)
            remaining = round(remaining - absorbed, 2)
    return {"duration_seconds": after, "unabsorbed_seconds": round(remaining, 2)}


def set_duration(project: FilmProject, shot_id: str, seconds: float) -> float:
    return trim_shot(project, shot_id, seconds)


def set_gap(project: FilmProject, shot_id: str, seconds: float | None) -> float | None:
    """The pause before a shot. None hands it back to the scene's default."""
    _, shot = locate(project, shot_id)
    shot.gap_before_seconds = None if seconds is None else round(max(0.0, min(30.0, seconds)), 2)
    shot.updated_at = now_ms()
    return shot.gap_before_seconds


# ---- arranging ----------------------------------------------------------


def move_shot(project: FilmProject, shot_id: str, scene_id: str, position: int | None = None) -> int:
    """Move a shot within its scene, or into another one."""
    source_scene, shot = locate(project, shot_id)
    target = require_scene(project, scene_id)

    source_scene.shots = [s for s in source_scene.shots if s.id != shot_id]
    _renumber(source_scene)

    index = len(target.shots) if position is None else max(0, min(len(target.shots), position))
    for other in target.shots:
        if other.order >= index:
            other.order += 1
    shot.order = index
    shot.updated_at = now_ms()
    target.shots.append(shot)
    _renumber(target)
    return index


def reorder_shots(project: FilmProject, scene_id: str, ordered_ids: list[str]) -> list[str]:
    """Set a scene's running order.

    Ids not named keep their relative order at the end, so a partial list is a
    reorder of what it names rather than a silent deletion of what it omits.
    """
    scene = require_scene(project, scene_id)
    known = {shot.id for shot in scene.shots}
    unknown = [item for item in ordered_ids if item not in known]
    if unknown:
        raise TimelineError(f"Not in this scene: {', '.join(unknown)}")

    position = 0
    for shot_id in ordered_ids:
        shot = next(s for s in scene.shots if s.id == shot_id)
        shot.order = position
        position += 1
    for shot in sorted(scene.shots, key=lambda s: s.order):
        if shot.id not in ordered_ids:
            shot.order = position
            position += 1
    _renumber(scene)
    return [s.id for s in scene.shots]


def insert_shot(
    project: FilmProject, scene_id: str, position: int | None = None, *, title: str = "", duration: float = 4.0
) -> str:
    """Add an empty shot at a position in a scene."""
    scene = require_scene(project, scene_id)
    index = len(scene.shots) if position is None else max(0, min(len(scene.shots), position))
    for other in scene.shots:
        if other.order >= index:
            other.order += 1
    shot = FilmShot(
        order=index,
        title=title or f"Shot {index + 1}",
        duration_seconds=_clamp_duration(duration),
    )
    scene.shots.append(shot)
    _renumber(scene)
    return shot.id


def duplicate_shot(project: FilmProject, shot_id: str) -> str:
    """Copy a shot in place, without its renders."""
    scene, shot = locate(project, shot_id)
    copy = _copy_shot(shot, title=f"{shot.title} (copy)", order=shot.order + 1)
    for other in scene.shots:
        if other.order > shot.order:
            other.order += 1
    scene.shots.append(copy)
    _renumber(scene)
    return copy.id


def delete_shot(project: FilmProject, shot_id: str) -> str:
    scene, shot = locate(project, shot_id)
    scene.shots = [s for s in scene.shots if s.id != shot_id]
    _renumber(scene)
    return shot.title


# ---- replacing ----------------------------------------------------------


def replace_shot(project: FilmProject, shot_id: str, source_shot_id: str) -> str:
    """Take another shot's content, keeping this one's place in the film.

    Position, duration and gap stay; look, prompt and cast come from the
    source. Renders do not: the shot is different now, and its old take no
    longer shows what it is.
    """
    _, target = locate(project, shot_id)
    _, source = locate(project, source_shot_id)
    if target.id == source.id:
        raise TimelineError("A shot cannot replace itself")

    order, gap = target.order, target.gap_before_seconds
    transition_in = target.transition_in.model_copy(deep=True)
    transition_out = target.transition_out.model_copy(deep=True)

    target.visual_prompt = source.visual_prompt
    target.negative_prompt = source.negative_prompt
    target.prompt_locked = source.prompt_locked
    target.description = source.description
    target.action = source.action
    target.dialogue = source.dialogue
    target.emotion = source.emotion
    target.framing = source.framing.model_copy(deep=True)
    target.camera_move = source.camera_move
    target.characters = [c.model_copy(deep=True) for c in source.characters]
    target.prop_ids = list(source.prop_ids)
    target.location_id = source.location_id
    target.composition = source.composition.model_copy(deep=True) if source.composition else None
    target.generation = source.generation.model_copy(deep=True)

    target.versions = []
    target.current_version = None
    target.capture_path = ""
    target.status = "draft"
    target.order, target.gap_before_seconds = order, gap
    target.transition_in, target.transition_out = transition_in, transition_out
    target.updated_at = now_ms()
    return target.id


def replace_with_version(project: FilmProject, shot_id: str, number: int) -> int:
    """Put a different take on the timeline."""
    _, shot = locate(project, shot_id)
    version = shot.version(number)
    if version is None:
        raise TimelineError(f"Version not found: {number}")
    if version.status != "complete":
        raise TimelineError(f"Version {number} has no render to put on the timeline")
    shot.current_version = number
    if shot.status not in ("approved", "rejected"):
        shot.status = "review"
    shot.updated_at = now_ms()
    return number


# ---- transitions --------------------------------------------------------


def set_transition(
    project: FilmProject, shot_id: str, *, where: str, kind: str, duration: float = 0.5
) -> ShotTransition:
    """Set how a shot begins or ends."""
    _, shot = locate(project, shot_id)
    if where not in ("in", "out"):
        raise TimelineError("Transitions go 'in' or 'out'")
    try:
        transition = ShotTransition(kind=kind, duration_seconds=round(max(0.0, min(5.0, duration)), 2))  # type: ignore[arg-type]
    except ValueError as exc:
        raise TimelineError(f"Unknown transition: {kind}") from exc
    if where == "in":
        shot.transition_in = transition
    else:
        shot.transition_out = transition
    shot.updated_at = now_ms()
    return transition


# ---- shaping the whole thing --------------------------------------------


def build_montage(
    project: FilmProject, scene_id: str, shot_ids: list[str], *, shot_seconds: float = 1.2
) -> list[str]:
    """Make a run of shots into a montage: short, evenly cut, no gaps.

    Only touches rhythm — duration, gap and transition. What each shot *is*
    stays exactly as it was, because a montage is an editing decision, not a
    reason to rewrite anyone's prompts.
    """
    scene = require_scene(project, scene_id)
    known = {shot.id: shot for shot in scene.shots}
    missing = [item for item in shot_ids if item not in known]
    if missing:
        raise TimelineError(f"Not in this scene: {', '.join(missing)}")
    if len(shot_ids) < 2:
        raise TimelineError("A montage needs at least two shots")

    length = _clamp_duration(shot_seconds)
    for shot_id in shot_ids:
        shot = known[shot_id]
        shot.duration_seconds = length
        shot.gap_before_seconds = 0.0
        shot.transition_in = ShotTransition()
        shot.transition_out = ShotTransition()
        shot.updated_at = now_ms()
    return shot_ids


def add_opening(project: FilmProject, *, title: str = "Opening", duration: float = 3.0) -> str:
    """A shot at the very front of the film, fading in."""
    if not project.scenes:
        raise TimelineError("Add a scene before adding an opening shot")
    first = sorted(project.scenes, key=lambda s: s.order)[0]
    shot_id = insert_shot(project, first.id, 0, title=title, duration=duration)
    _, shot = locate(project, shot_id)
    shot.transition_in = ShotTransition(kind="fade_in", duration_seconds=1.0)
    return shot_id


def add_ending(project: FilmProject, *, title: str = "Ending", duration: float = 3.0) -> str:
    """A shot at the very end, fading out."""
    if not project.scenes:
        raise TimelineError("Add a scene before adding an ending shot")
    last = sorted(project.scenes, key=lambda s: s.order)[-1]
    shot_id = insert_shot(project, last.id, None, title=title, duration=duration)
    _, shot = locate(project, shot_id)
    shot.transition_out = ShotTransition(kind="fade_out", duration_seconds=1.0)
    return shot_id


def insert_broll(
    project: FilmProject, after_shot_id: str, *, title: str = "", duration: float = 2.0, prompt: str = ""
) -> str:
    """A cutaway after a shot: short, no gap, and marked as B-roll in its title."""
    scene, anchor = locate(project, after_shot_id)
    shot_id = insert_shot(
        project, scene.id, anchor.order + 1, title=title or f"B-roll after {anchor.title}", duration=duration
    )
    _, shot = locate(project, shot_id)
    shot.gap_before_seconds = 0.0
    if prompt:
        shot.visual_prompt = prompt
        shot.prompt_locked = True
    # Inherit the look, not the framing: a cutaway is a different angle on the
    # same world.
    shot.location_id = anchor.location_id
    shot.updated_at = now_ms()
    return shot_id


def align_durations(project: FilmProject, scene_id: str, seconds: float) -> int:
    """Give every shot in a scene the same length."""
    scene = require_scene(project, scene_id)
    if not scene.shots:
        raise TimelineError("That scene has no shots to align")
    length = _clamp_duration(seconds)
    for shot in scene.shots:
        shot.duration_seconds = length
        shot.updated_at = now_ms()
    return len(scene.shots)


def normalize_timeline(project: FilmProject, *, gap_seconds: float = 0.0) -> dict[str, object]:
    """Tidy the whole film: consistent gaps, no orphan orders, sane durations.

    Deliberately conservative — it fixes what is inconsistent rather than
    imposing a house style. Durations are only clamped into range, never
    reshaped, because how long a shot runs is a decision, not a defect.
    """
    touched: list[str] = []
    for scene in sorted(project.scenes, key=lambda s: s.order):
        _renumber(scene)
        for index, shot in enumerate(scene.shots):
            changed = False
            clamped = _clamp_duration(shot.duration_seconds)
            if clamped != shot.duration_seconds:
                shot.duration_seconds = clamped
                changed = True
            # The first shot of a scene takes the scene's gap, not its own.
            wanted = None if index == 0 else round(max(0.0, gap_seconds), 2)
            if shot.gap_before_seconds != wanted:
                shot.gap_before_seconds = wanted
                changed = True
            if changed:
                shot.updated_at = now_ms()
                touched.append(shot.id)
    for index, scene in enumerate(sorted(project.scenes, key=lambda s: s.order)):
        scene.order = index
    project.scenes.sort(key=lambda s: s.order)
    return {"scenes": len(project.scenes), "shots_changed": len(touched), "shot_ids": touched}
