"""Routes for the model-specific prompt compiler."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app_handler import AppHandler
from film.prompt_api_types import (
    CompilePromptRequest,
    CompilePromptResponse,
    PromptTargetListResponse,
)
from state import get_state_service

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("/targets", response_model=PromptTargetListResponse)
def route_targets(handler: AppHandler = Depends(get_state_service)) -> PromptTargetListResponse:
    """Every prompt convention this app knows, and what identifies each one."""
    return handler.prompts.targets()


@router.post("/compile", response_model=CompilePromptResponse)
def route_compile(
    req: CompilePromptRequest,
    handler: AppHandler = Depends(get_state_service),
) -> CompilePromptResponse:
    """Compile one shot for a set of models, reporting what each cannot carry."""
    return handler.prompts.compile(req)
