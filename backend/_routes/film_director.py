"""Routes for the AI Director and storyboard generation."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from film.film_api_types import (
    DirectorCommandRequest,
    DirectorCommandResponse,
    DirectorInstructRequest,
    DirectorInstructResponse,
    GenerateStoryboardRequest,
    GenerateStoryboardResponse,
)
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api/film", tags=["film-director"])


@router.post("/projects/{project_id}/director/command", response_model=DirectorCommandResponse)
def route_director_command(
    project_id: str,
    req: DirectorCommandRequest,
    handler: AppHandler = Depends(get_state_service),
) -> DirectorCommandResponse:
    return handler.film_director.run_command(project_id, req)


@router.post("/projects/{project_id}/director/instruct", response_model=DirectorInstructResponse)
def route_director_instruct(
    project_id: str,
    req: DirectorInstructRequest,
    handler: AppHandler = Depends(get_state_service),
) -> DirectorInstructResponse:
    return handler.film_director.instruct(project_id, req)


@router.post(
    "/projects/{project_id}/storyboard/generate", response_model=GenerateStoryboardResponse
)
def route_generate_storyboard(
    project_id: str,
    req: GenerateStoryboardRequest,
    handler: AppHandler = Depends(get_state_service),
) -> GenerateStoryboardResponse:
    return handler.film_director.generate_storyboard(project_id, req)
