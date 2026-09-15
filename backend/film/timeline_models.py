"""The film's edit, and the record of how it got that way.

The timeline here is the film itself: scenes in order, shots in order within
them, each with a duration and a gap before it. There is no second data
structure — editing the timeline edits the storyboard, which is what makes an
edit survive into the render rather than living only in a preview.

Two things are added to that:

* **Transitions** on a shot, so a cut, a dissolve or a fade is part of the edit
  rather than something applied afterwards.
* **Director actions**, a persisted record of every timeline edit with the
  project state before it. That record is what makes undo possible, and it is
  also the answer to "why does the film look like this now?" — which matters
  more than usual when some of the edits were made by a model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.film_models import ShotTransition, now_ms

TRANSITION_LABELS: dict[str, str] = {
    "cut": "Cut",
    "dissolve": "Dissolve",
    "fade_in": "Fade in",
    "fade_out": "Fade out",
    "wipe": "Wipe",
    "dip_to_black": "Dip to black",
}

#: Every timeline edit the director (or the user) can make. The names are the
#: command names too, so a plan that says "ripple_trim" runs ripple_trim.
TimelineAction = Literal[
    "split_shot",
    "trim_shot",
    "ripple_trim",
    "move_shot",
    "reorder_shots",
    "insert_shot",
    "replace_shot",
    "replace_with_version",
    "duplicate_shot",
    "delete_shot",
    "set_transition",
    "set_duration",
    "set_gap",
    "build_montage",
    "add_opening",
    "add_ending",
    "insert_broll",
    "align_durations",
    "normalize_timeline",
]


class DirectorAction(BaseModel):
    """One timeline edit, with enough of the past to undo it.

    The snapshot is the whole project as it was immediately before. A film
    project is a small JSON document, and an exact snapshot cannot drift out of
    sync with the operation the way a hand-written inverse can. Correctness
    here is worth more than the bytes.
    """

    id: str = ""
    created_at: int = Field(default_factory=now_ms)
    action: str = ""
    #: "director" when a model made the edit, "user" when a person did. Worth
    #: keeping apart when reading back why the film looks like this.
    actor: Literal["director", "user"] = "user"
    #: One line, written for a person reading the history.
    summary: str = ""
    params: dict[str, object] = Field(default_factory=dict[str, object])
    affected_shot_ids: list[str] = Field(default_factory=list[str])
    #: The project immediately before this action. Absent once the action has
    #: been undone, or once it has aged out of the retained history.
    before: dict[str, object] | None = None
    undone: bool = False


class TimelineHistory(BaseModel):
    """The retained action log for one project."""

    schema_version: int = 1
    project_id: str = ""
    actions: list[DirectorAction] = Field(default_factory=list[DirectorAction])


class TimelineEntry(BaseModel):
    """One shot's place in the finished film, with absolute times."""

    scene_id: str = ""
    scene_title: str = ""
    shot_id: str = ""
    shot_title: str = ""
    order: int = 0
    start_seconds: float = 0.0
    duration_seconds: float = 0.0
    gap_before_seconds: float = 0.0
    transition_in: ShotTransition = Field(default_factory=ShotTransition)
    transition_out: ShotTransition = Field(default_factory=ShotTransition)
    status: str = ""
    has_render: bool = False


class TimelineView(BaseModel):
    """The film as a running order, computed rather than stored."""

    entries: list[TimelineEntry] = Field(default_factory=list[TimelineEntry])
    total_seconds: float = 0.0
    shot_count: int = 0
    rendered_count: int = 0
