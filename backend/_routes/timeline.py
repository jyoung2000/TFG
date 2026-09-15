"""Routes for timeline editing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app_handler import AppHandler
from film.timeline_api_types import (
    TimelineActionRequest,
    TimelineActionResponse,
    TimelineHistoryResponse,
)
from film.timeline_models import TimelineView
from state import get_state_service

router = APIRouter(prefix="/api/film/projects/{project_id}/timeline", tags=["timeline"])


@router.get("", response_model=TimelineView)
def route_view(project_id: str, handler: AppHandler = Depends(get_state_service)) -> TimelineView:
    """The film as a running order with absolute times. Computed, never stored."""
    return handler.timeline.view(project_id)


@router.get("/history", response_model=TimelineHistoryResponse)
def route_history(
    project_id: str,
    limit: int = 50,
    handler: AppHandler = Depends(get_state_service),
) -> TimelineHistoryResponse:
    """Every timeline edit, newest last, with who made it."""
    history = handler.timeline.history(project_id, limit=limit)
    return TimelineHistoryResponse(
        # Snapshots stay on disk; they are the undo mechanism, not something a
        # caller needs, and each one is a copy of the whole project.
        actions=[action.model_copy(update={"before": None}) for action in history.actions],
        undoable=sum(1 for action in history.actions if not action.undone and action.before is not None),
    )


@router.post("/actions", response_model=TimelineActionResponse)
def route_apply(
    project_id: str,
    req: TimelineActionRequest,
    handler: AppHandler = Depends(get_state_service),
) -> TimelineActionResponse:
    """Apply one timeline edit. A refused edit changes nothing."""
    action = handler.timeline.apply(project_id, req.action, req.params, actor=req.actor)
    return TimelineActionResponse(action=action, timeline=handler.timeline.view(project_id))


@router.post("/undo", response_model=TimelineActionResponse)
def route_undo(
    project_id: str, handler: AppHandler = Depends(get_state_service)
) -> TimelineActionResponse:
    """Put the film back the way it was before the last undoable edit."""
    action = handler.timeline.undo(project_id)
    return TimelineActionResponse(action=action, timeline=handler.timeline.view(project_id))
