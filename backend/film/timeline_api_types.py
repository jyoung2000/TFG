"""Request/response models for timeline editing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.timeline_models import DirectorAction, TimelineView


class TimelineActionRequest(BaseModel):
    #: One of TIMELINE_ACTIONS. An unknown name is a 400 rather than a no-op.
    action: str = ""
    params: dict[str, object] = Field(default_factory=dict[str, object])
    #: Who is making the edit. Kept so the history can tell a model's decisions
    #: from a person's when read back later.
    actor: Literal["user", "director"] = "user"


class TimelineActionResponse(BaseModel):
    action: DirectorAction = Field(default_factory=DirectorAction)
    #: The timeline after the edit, so the caller needs no second call.
    timeline: TimelineView = Field(default_factory=TimelineView)


class TimelineHistoryResponse(BaseModel):
    actions: list[DirectorAction] = Field(default_factory=list[DirectorAction])
    #: How many actions can still be undone.
    undoable: int = 0
