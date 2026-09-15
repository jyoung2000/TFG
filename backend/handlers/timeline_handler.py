"""Editing the film's timeline, with an undo and a record of who did what.

Every edit follows the same three steps: snapshot the project, apply a pure
operation from `film/timeline_ops.py`, save. That shape is where the guarantees
come from —

* **Undo is exact.** The snapshot is the whole project as it was, so undo
  restores it rather than trying to invert an operation. A hand-written inverse
  can drift out of step with the operation it inverts; a snapshot cannot.
* **A failed edit changes nothing.** The operations raise rather than returning
  a failure, and nothing is written until one returns, so a refused edit leaves
  the project exactly as it was.
* **The history survives.** Actions are persisted beside the project, so "why
  does the film look like this?" is answerable after a restart — which matters
  more than usual when some of the edits were made by a model.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from threading import RLock
from typing import Callable, cast

from _routes._errors import HTTPError
from film.film_models import FilmProject, now_ms
from film.timeline_models import (
    DirectorAction,
    ShotTransition,
    TimelineEntry,
    TimelineHistory,
    TimelineView,
)
from film.timeline_ops import TimelineError, ordered_shots
from film import timeline_ops as ops
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

#: How many actions keep their undo snapshot. Older actions stay in the history
#: as a record but lose the snapshot, so the file cannot grow without bound.
_UNDOABLE = 25
#: How many actions are kept at all.
_RETAINED = 200


class TimelineHandler(StateHandlerBase):
    def __init__(self, state: AppState, lock: RLock, film_handler: FilmHandler) -> None:
        super().__init__(state, lock)
        self._film = film_handler

    # ---- history persistence --------------------------------------------

    def _history_file(self, project_id: str) -> Path:
        return self._film.store.project_dir(project_id) / "timeline_history.json"

    def history(self, project_id: str, *, limit: int = 50) -> TimelineHistory:
        path = self._history_file(project_id)
        if not path.is_file():
            return TimelineHistory(project_id=project_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stored = TimelineHistory.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # A damaged history must not make the film unusable: it is a
            # record, not the work.
            logger.warning("Could not read the timeline history for %s: %s", project_id, exc)
            return TimelineHistory(project_id=project_id)
        stored.actions = stored.actions[-limit:] if limit else stored.actions
        return stored

    def _write_history(self, project_id: str, history: TimelineHistory) -> None:
        history.project_id = project_id
        history.actions = history.actions[-_RETAINED:]
        # Only the most recent actions keep a snapshot. The rest stay readable
        # as a record without carrying a copy of the project each.
        for action in history.actions[:-_UNDOABLE]:
            action.before = None
        path = self._history_file(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        try:
            temporary.write_text(history.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            # Losing the record is bad; losing the edit would be worse. The
            # edit is already saved by the time this runs.
            logger.warning("Could not write the timeline history for %s: %s", project_id, exc)

    # ---- reading ---------------------------------------------------------

    def view(self, project_id: str) -> TimelineView:
        """The film as a running order, with absolute times. Computed, never stored."""
        project = self._film.get_project(project_id)
        default_gap = project.settings.inter_shot_gap_seconds
        entries: list[TimelineEntry] = []
        clock = 0.0
        rendered = 0
        for scene, shot in ordered_shots(project):
            scene_gap = scene.inter_shot_gap_seconds
            gap = shot.gap_before_seconds
            if gap is None:
                gap = scene_gap if scene_gap is not None else default_gap
            # The film does not open with a pause.
            gap = 0.0 if not entries else max(0.0, gap)
            clock += gap
            has_render = any(
                v.status == "complete" and v.number == shot.current_version for v in shot.versions
            )
            if has_render:
                rendered += 1
            entries.append(
                TimelineEntry(
                    scene_id=scene.id,
                    scene_title=scene.title,
                    shot_id=shot.id,
                    shot_title=shot.title,
                    order=len(entries),
                    start_seconds=round(clock, 2),
                    duration_seconds=shot.duration_seconds,
                    gap_before_seconds=round(gap, 2),
                    transition_in=shot.transition_in.model_copy(deep=True),
                    transition_out=shot.transition_out.model_copy(deep=True),
                    status=shot.status,
                    has_render=has_render,
                )
            )
            clock += shot.duration_seconds
        return TimelineView(
            entries=entries,
            total_seconds=round(clock, 2),
            shot_count=len(entries),
            rendered_count=rendered,
        )

    # ---- the one path every edit takes -----------------------------------

    def apply(
        self,
        project_id: str,
        action: str,
        params: dict[str, object],
        *,
        actor: str = "user",
    ) -> DirectorAction:
        """Snapshot, apply, save, record.

        The operation runs inside the lock against a freshly loaded project, so
        two edits cannot interleave and leave the film half-changed.
        """
        operation = _OPERATIONS.get(action)
        if operation is None:
            raise HTTPError(400, f"Unknown timeline action: {action}")

        with self.lock:
            project = self._film.store.load(project_id)
            before = project.model_dump()
            try:
                summary, affected = operation(project, params)
            except TimelineError as exc:
                raise HTTPError(400, str(exc)) from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPError(400, f"{action}: {exc}") from exc

            project.updated_at = now_ms()
            self._film.store.save(project)

            record = DirectorAction(
                id=f"act-{uuid.uuid4().hex[:12]}",
                action=action,
                actor="director" if actor == "director" else "user",
                summary=summary,
                params=params,
                affected_shot_ids=affected,
                before=before,
            )
            history = self.history(project_id, limit=0)
            history.actions.append(record)
            self._write_history(project_id, history)

        # The snapshot is not sent back with every edit — it is a copy of the
        # whole project and the caller already has the current one.
        return record.model_copy(update={"before": None})

    def undo(self, project_id: str) -> DirectorAction:
        """Put the film back the way it was before the last undoable action."""
        with self.lock:
            history = self.history(project_id, limit=0)
            target = next(
                (a for a in reversed(history.actions) if not a.undone and a.before is not None), None
            )
            if target is None:
                raise HTTPError(400, "Nothing to undo")
            try:
                restored = FilmProject.model_validate(target.before)
            except ValueError as exc:
                raise HTTPError(500, f"That snapshot cannot be restored: {exc}") from exc
            restored.updated_at = now_ms()
            self._film.store.save(restored)

            target.undone = True
            # The snapshot has served its purpose; keeping it would let a
            # second undo of the same action rewind work done since.
            target.before = None
            self._write_history(project_id, history)
        return target


# ---- the operations, as (project, params) -> (summary, affected ids) ------

_Operation = Callable[[FilmProject, dict[str, object]], tuple[str, list[str]]]


def _str(params: dict[str, object], key: str, *, required: bool = True, default: str = "") -> str:
    value = params.get(key, default)
    if not isinstance(value, str) or not value.strip():
        if required:
            raise TimelineError(f"{key} is required")
        return default
    return value.strip()


def _float(params: dict[str, object], key: str, default: float) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _optional_int(params: dict[str, object], key: str) -> int | None:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _id_list(params: dict[str, object], key: str) -> list[str]:
    value = params.get(key)
    if not isinstance(value, list):
        raise TimelineError(f"{key} must be a list of shot ids")
    return [str(item) for item in value if str(item).strip()]  # type: ignore[misc]


def _op_split(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    at = params.get("at_seconds")
    point = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None
    ids = ops.split_shot(project, shot_id, point)
    return (f"Split into two shots{f' at {point:g}s' if point is not None else ''}", ids)


def _op_trim(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    seconds = ops.trim_shot(project, shot_id, _float(params, "duration_seconds", 4.0))
    return (f"Trimmed to {seconds:g}s", [shot_id])


def _op_ripple(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    result = ops.ripple_trim(project, shot_id, _float(params, "duration_seconds", 4.0))
    unabsorbed = float(result["unabsorbed_seconds"])
    note = "" if unabsorbed == 0 else f", {abs(unabsorbed):g}s the gaps could not absorb"
    return (f"Ripple trimmed to {result['duration_seconds']:g}s{note}", [shot_id])


def _op_move(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    scene_id = _str(params, "scene_id")
    index = ops.move_shot(project, shot_id, scene_id, _optional_int(params, "position"))
    return (f"Moved to position {index + 1}", [shot_id])


def _op_reorder(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    scene_id = _str(params, "scene_id")
    order = ops.reorder_shots(project, scene_id, _id_list(params, "ordered_shot_ids"))
    return (f"Reordered {len(order)} shots", order)


def _op_insert(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    scene_id = _str(params, "scene_id")
    shot_id = ops.insert_shot(
        project,
        scene_id,
        _optional_int(params, "position"),
        title=_str(params, "title", required=False),
        duration=_float(params, "duration_seconds", 4.0),
    )
    return ("Inserted a shot", [shot_id])


def _op_replace(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    source = _str(params, "source_shot_id")
    ops.replace_shot(project, shot_id, source)
    return ("Replaced the shot's content, keeping its place", [shot_id, source])


def _op_replace_version(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    number = _optional_int(params, "version_number")
    if number is None:
        raise TimelineError("version_number is required")
    ops.replace_with_version(project, shot_id, number)
    return (f"Put take {number} on the timeline", [shot_id])


def _op_duplicate(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    copy_id = ops.duplicate_shot(project, shot_id)
    return ("Duplicated the shot", [shot_id, copy_id])


def _op_delete(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    title = ops.delete_shot(project, shot_id)
    return (f'Removed "{title}" from the timeline', [shot_id])


def _op_transition(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    where = _str(params, "where", required=False, default="out")
    kind = _str(params, "kind", required=False, default="cut")
    transition: ShotTransition = ops.set_transition(
        project, shot_id, where=where, kind=kind, duration=_float(params, "duration_seconds", 0.5)
    )
    length = "" if transition.kind == "cut" else f" over {transition.duration_seconds:g}s"
    return (f"Set the {where} transition to {transition.kind}{length}", [shot_id])


def _op_set_duration(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    seconds = ops.set_duration(project, shot_id, _float(params, "duration_seconds", 4.0))
    return (f"Set the duration to {seconds:g}s", [shot_id])


def _op_set_gap(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = _str(params, "shot_id")
    raw = params.get("gap_seconds")
    seconds = None if raw is None else _float(params, "gap_seconds", 0.0)
    result = ops.set_gap(project, shot_id, seconds)
    return (("Cleared the gap" if result is None else f"Set the gap before it to {result:g}s"), [shot_id])


def _op_montage(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    scene_id = _str(params, "scene_id")
    ids = _id_list(params, "shot_ids")
    length = _float(params, "shot_seconds", 1.2)
    ops.build_montage(project, scene_id, ids, shot_seconds=length)
    return (f"Cut {len(ids)} shots into a montage at {length:g}s each", ids)


def _op_opening(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = ops.add_opening(
        project,
        title=_str(params, "title", required=False, default="Opening"),
        duration=_float(params, "duration_seconds", 3.0),
    )
    return ("Added an opening shot that fades in", [shot_id])


def _op_ending(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    shot_id = ops.add_ending(
        project,
        title=_str(params, "title", required=False, default="Ending"),
        duration=_float(params, "duration_seconds", 3.0),
    )
    return ("Added an ending shot that fades out", [shot_id])


def _op_broll(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    after = _str(params, "after_shot_id")
    shot_id = ops.insert_broll(
        project,
        after,
        title=_str(params, "title", required=False),
        duration=_float(params, "duration_seconds", 2.0),
        prompt=_str(params, "prompt", required=False),
    )
    return ("Inserted a B-roll cutaway", [after, shot_id])


def _op_align(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    scene_id = _str(params, "scene_id")
    seconds = _float(params, "duration_seconds", 4.0)
    count = ops.align_durations(project, scene_id, seconds)
    scene = ops.require_scene(project, scene_id)
    return (f"Aligned {count} shots to {seconds:g}s each", [s.id for s in scene.shots])


def _op_normalize(project: FilmProject, params: dict[str, object]) -> tuple[str, list[str]]:
    result = ops.normalize_timeline(project, gap_seconds=_float(params, "gap_seconds", 0.0))
    changed = result["shot_ids"]
    ids = [str(item) for item in cast(list[object], changed)] if isinstance(changed, list) else []
    return (f"Normalised the timeline — {result['shots_changed']} shots changed", ids)


_OPERATIONS: dict[str, _Operation] = {
    "split_shot": _op_split,
    "trim_shot": _op_trim,
    "ripple_trim": _op_ripple,
    "move_shot": _op_move,
    "reorder_shots": _op_reorder,
    "insert_shot": _op_insert,
    "replace_shot": _op_replace,
    "replace_with_version": _op_replace_version,
    "duplicate_shot": _op_duplicate,
    "delete_shot": _op_delete,
    "set_transition": _op_transition,
    "set_duration": _op_set_duration,
    "set_gap": _op_set_gap,
    "build_montage": _op_montage,
    "add_opening": _op_opening,
    "add_ending": _op_ending,
    "insert_broll": _op_broll,
    "align_durations": _op_align,
    "normalize_timeline": _op_normalize,
}

#: Exposed so the director's tool registry and the UI both read one list.
TIMELINE_ACTIONS: tuple[str, ...] = tuple(sorted(_OPERATIONS))
