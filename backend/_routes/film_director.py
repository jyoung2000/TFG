"""Routes for the AI Director, providers, and film building."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from film.film_api_types import (
    DirectorChatRequest,
    DirectorChatResponse,
    DirectorCommandRequest,
    DirectorCommandResponse,
    DirectorInstructRequest,
    DirectorInstructResponse,
    DirectorStatusResponse,
    FilmBuildApplyRequest,
    FilmBuildApplyResponse,
    FilmBuildRequest,
    FilmBuildResponse,
    GenerateStoryboardRequest,
    GenerateStoryboardResponse,
    OpenRouterModelsResponse,
    OpenRouterValidateResponse,
    RefinePromptRequest,
    RefinePromptResponse,
    VisualReviewResponse,
)
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api/film", tags=["film-director"])


@router.get("/director/status", response_model=DirectorStatusResponse)
def route_director_status(handler: AppHandler = Depends(get_state_service)) -> DirectorStatusResponse:
    return handler.film_director.status()


@router.get("/director/openrouter/models", response_model=OpenRouterModelsResponse)
def route_openrouter_models(
    refresh: bool = False,
    handler: AppHandler = Depends(get_state_service),
) -> OpenRouterModelsResponse:
    return handler.film_director.openrouter_models(refresh=refresh)


@router.post("/projects/{project_id}/continuity/{shot_id}/visual-review", response_model=VisualReviewResponse)
def route_visual_review(
    project_id: str,
    shot_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> VisualReviewResponse:
    """Optional multimodal review of two rendered shots (never blocks; deterministic checks stay authoritative)."""
    return handler.film_director.visual_review(project_id, shot_id)


@router.get("/director/models/{provider}", response_model=OpenRouterModelsResponse)
def route_director_provider_models(
    provider: str,
    refresh: bool = False,
    handler: AppHandler = Depends(get_state_service),
) -> OpenRouterModelsResponse:
    """The chat models a text provider offers for the configured key/endpoint."""
    return handler.film_director.chat_models(provider, refresh=refresh)


@router.get("/director/openai-compatible/models", response_model=OpenRouterModelsResponse)
def route_openai_compatible_models(handler: AppHandler = Depends(get_state_service)) -> OpenRouterModelsResponse:
    return handler.film_director.openai_compatible_models()


@router.post("/director/openrouter/validate", response_model=OpenRouterValidateResponse)
def route_openrouter_validate(handler: AppHandler = Depends(get_state_service)) -> OpenRouterValidateResponse:
    return handler.film_director.validate_openrouter_key()


@router.post("/director/chat", response_model=DirectorChatResponse)
def route_director_chat(
    req: DirectorChatRequest,
    handler: AppHandler = Depends(get_state_service),
) -> DirectorChatResponse:
    return handler.film_director.chat(req)


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
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/refine-prompt",
    response_model=RefinePromptResponse,
)
def route_refine_prompt(
    project_id: str,
    scene_id: str,
    shot_id: str,
    req: RefinePromptRequest,
    handler: AppHandler = Depends(get_state_service),
) -> RefinePromptResponse:
    return handler.film_director.refine_prompt(project_id, scene_id, shot_id, req)


@router.post(
    "/projects/{project_id}/storyboard/generate", response_model=GenerateStoryboardResponse
)
def route_generate_storyboard(
    project_id: str,
    req: GenerateStoryboardRequest,
    handler: AppHandler = Depends(get_state_service),
) -> GenerateStoryboardResponse:
    return handler.film_director.generate_storyboard(project_id, req)


@router.post("/projects/{project_id}/build", response_model=FilmBuildResponse)
def route_build_film(
    project_id: str,
    req: FilmBuildRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmBuildResponse:
    return handler.film_director.build_film(project_id, req)


@router.post("/projects/{project_id}/build/apply", response_model=FilmBuildApplyResponse)
def route_apply_build(
    project_id: str,
    req: FilmBuildApplyRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmBuildApplyResponse:
    return handler.film_director.apply_build(project_id, req)
