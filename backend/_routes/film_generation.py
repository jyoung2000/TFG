"""Routes for film shot generation: queue, batch, capabilities, outputs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from _routes._errors import HTTPError
from server_utils.path_policy import PathPolicyError, require_within_any
from film.film_api_types import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    FilmCapabilitiesResponse,
    FilmQueueResponse,
    GenerateShotRequest,
    QueueControlResponse,
    QueueMoveRequest,
    QueueShotResponse,
)
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api/film", tags=["film-generation"])


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/generate",
    response_model=QueueShotResponse,
)
def route_generate_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    req: GenerateShotRequest,
    handler: AppHandler = Depends(get_state_service),
) -> QueueShotResponse:
    return handler.film_generation.queue_shot(project_id, scene_id, shot_id, req)


@router.post("/projects/{project_id}/generate/batch", response_model=BatchGenerateResponse)
def route_generate_batch(
    project_id: str,
    req: BatchGenerateRequest,
    handler: AppHandler = Depends(get_state_service),
) -> BatchGenerateResponse:
    return handler.film_generation.queue_batch(project_id, req)


@router.get("/queue", response_model=FilmQueueResponse)
def route_film_queue(handler: AppHandler = Depends(get_state_service)) -> FilmQueueResponse:
    return handler.film_generation.get_queue()


@router.post("/queue/cancel", response_model=FilmQueueResponse)
def route_film_queue_cancel(
    handler: AppHandler = Depends(get_state_service),
) -> FilmQueueResponse:
    return handler.film_generation.cancel_all()


@router.post("/queue/pause", response_model=QueueControlResponse)
def route_film_queue_pause(handler: AppHandler = Depends(get_state_service)) -> QueueControlResponse:
    return QueueControlResponse(status="paused", queue=handler.film_generation.pause())


@router.post("/queue/resume", response_model=QueueControlResponse)
def route_film_queue_resume(handler: AppHandler = Depends(get_state_service)) -> QueueControlResponse:
    return QueueControlResponse(status="resumed", queue=handler.film_generation.resume())


@router.post("/queue/{shot_id}/cancel", response_model=QueueControlResponse)
def route_film_queue_cancel_job(
    shot_id: str, handler: AppHandler = Depends(get_state_service)
) -> QueueControlResponse:
    return QueueControlResponse(status="cancelled", queue=handler.film_generation.cancel_job(shot_id))


@router.post("/queue/{shot_id}/move", response_model=QueueControlResponse)
def route_film_queue_move(
    shot_id: str, req: QueueMoveRequest, handler: AppHandler = Depends(get_state_service)
) -> QueueControlResponse:
    return QueueControlResponse(status="moved", queue=handler.film_generation.move(shot_id, req.index))


@router.post("/queue/{shot_id}/prioritize", response_model=QueueControlResponse)
def route_film_queue_prioritize(
    shot_id: str, handler: AppHandler = Depends(get_state_service)
) -> QueueControlResponse:
    return QueueControlResponse(status="prioritized", queue=handler.film_generation.prioritize(shot_id))


@router.get("/capabilities", response_model=FilmCapabilitiesResponse)
def route_film_capabilities(
    handler: AppHandler = Depends(get_state_service),
) -> FilmCapabilitiesResponse:
    return handler.film_generation.capabilities()


@router.get("/output")
def route_film_output(
    path: str = Query(min_length=1),
    handler: AppHandler = Depends(get_state_service),
) -> FileResponse:
    """Serve a generated output strictly from within the outputs directory."""
    try:
        candidate = require_within_any(path, [handler.config.outputs_dir], what="output path")
    except PathPolicyError as exc:
        raise HTTPError(400, str(exc)) from exc
    if not candidate.is_file():
        raise HTTPError(404, "Output not found")
    return FileResponse(candidate)
