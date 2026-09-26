"""Routes for the model-specific prompt compiler."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app_handler import AppHandler
from film.prompt_api_types import (
    CompilePromptRequest,
    CompilePromptResponse,
    CompileSpecAllResponse,
    CompileSpecRequest,
    CompileSpecResponse,
    PromptTargetListResponse,
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplateUpdateRequest,
)
from film.prompt_compiler import PromptStyle
from film.prompt_templates import PromptTemplate
from film.shot_spec import ShotSpec
from pydantic import BaseModel, Field
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


class CompileSpecAllRequest(BaseModel):
    spec: ShotSpec
    targets: list[str] = Field(default_factory=list[str])
    styles: list[PromptStyle] = Field(default_factory=list[PromptStyle])
    seed: int | None = None
    use_hints: bool = True


@router.post("/compile-spec", response_model=CompileSpecResponse)
def route_compile_spec(req: CompileSpecRequest, handler: AppHandler = Depends(get_state_service)) -> CompileSpecResponse:
    """Compile a ShotSpec for one target (+ knowledge hints)."""
    return handler.prompts.compile_spec(req)


@router.post("/compile-spec/all", response_model=CompileSpecAllResponse)
def route_compile_spec_all(req: CompileSpecAllRequest, handler: AppHandler = Depends(get_state_service)) -> CompileSpecAllResponse:
    """Every target × style at once, for the Reproduce editor."""
    return handler.prompts.compile_spec_all(req.spec, req.targets, req.styles, seed=req.seed, use_hints=req.use_hints)


@router.get("/templates", response_model=PromptTemplateListResponse)
def route_templates(handler: AppHandler = Depends(get_state_service)) -> PromptTemplateListResponse:
    return handler.prompts.templates()


@router.post("/templates", response_model=PromptTemplate)
def route_create_template(req: PromptTemplateCreateRequest, handler: AppHandler = Depends(get_state_service)) -> PromptTemplate:
    return handler.prompts.create_template(req)


@router.put("/templates/{template_id}", response_model=PromptTemplate)
def route_update_template(template_id: str, req: PromptTemplateUpdateRequest, handler: AppHandler = Depends(get_state_service)) -> PromptTemplate:
    return handler.prompts.update_template(template_id, req)


@router.delete("/templates/{template_id}")
def route_delete_template(template_id: str, handler: AppHandler = Depends(get_state_service)) -> dict[str, bool]:
    return {"deleted": handler.prompts.delete_template(template_id)}


@router.post("/templates/{template_id}/reset", response_model=PromptTemplate)
def route_reset_template(template_id: str, handler: AppHandler = Depends(get_state_service)) -> PromptTemplate:
    return handler.prompts.reset_template(template_id)
