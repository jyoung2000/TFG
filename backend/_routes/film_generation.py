"""Routes for film shot generation: queue, batch, capabilities, outputs."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from _routes._errors import HTTPError
from film.film_api_types import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    FilmCapabilitiesResponse,
    FilmQueueResponse,
    GenerateShotRequest,
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
    outputs_dir = handler.config.outputs_dir.resolve()
    candidate = Path(path).resolve()
    if outputs_dir != candidate and outputs_dir not in candidate.parents:
        raise HTTPError(400, "Path is outside the outputs directory")
    if not candidate.is_file():
        raise HTTPError(404, "Output not found")
    return FileResponse(candidate)
