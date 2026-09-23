"""Local reference-image analysis and bounded recreation routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from _routes._errors import HTTPError
from app_handler import AppHandler
from film.image_recreation import ImageAnalysis
from server_utils.path_policy import PathPolicyError, resolve_within
from state import get_state_service

router = APIRouter(prefix="/api/image-analysis", tags=["image-analysis"])


class ImportRequest(BaseModel):
    path: str


class RenderRequest(BaseModel):
    candidates: int = Field(default=2, ge=1, le=3)
    rounds: int = Field(default=1, ge=1, le=2)


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


@router.post("/import", response_model=ImageAnalysis)
def import_image(req: ImportRequest, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    return handler.image_recreation.import_image(req.path)


@router.get("")
def list_analyses(handler: AppHandler = Depends(get_state_service)) -> dict[str, list[ImageAnalysis]]:
    return {"analyses": handler.image_recreation.list()}


@router.get("/{analysis_id}", response_model=ImageAnalysis)
def get_analysis(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    return handler.image_recreation.get(analysis_id)


@router.delete("/{analysis_id}")
def delete_analysis(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> dict[str, str]:
    handler.image_recreation.delete(analysis_id)
    return {"status": "ok"}


@router.post("/{analysis_id}/analyze", response_model=ImageAnalysis)
def analyze_image(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    return handler.image_recreation.analyze(analysis_id, handler.film_director.optional_provider("storyboard"))


@router.post("/{analysis_id}/render", response_model=ImageAnalysis)
def render_images(analysis_id: str, req: RenderRequest, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    provider = handler.film_director.optional_provider("storyboard") if req.rounds > 1 else None
    return handler.image_recreation.render(analysis_id, req.candidates, req.rounds, provider)


@router.put("/{analysis_id}/prompt", response_model=ImageAnalysis)
def edit_prompt(analysis_id: str, req: PromptRequest, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    return handler.image_recreation.edit_prompt(analysis_id, req.prompt)


@router.post("/{analysis_id}/refine", response_model=ImageAnalysis)
def refine_image(analysis_id: str, req: RenderRequest, handler: AppHandler = Depends(get_state_service)) -> ImageAnalysis:
    return handler.image_recreation.refine(analysis_id, req.candidates, handler.film_director.optional_provider("storyboard"))


@router.get("/{analysis_id}/media")
def image_media(analysis_id: str, path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    job = handler.image_recreation.get(analysis_id)
    allowed = {job.source_path, *(candidate.path for candidate in job.candidates)}
    if path not in allowed:
        raise HTTPError(400, "Image is not part of this analysis")
    try:
        image = resolve_within(handler.image_recreation.root / analysis_id, path, what="image")
    except PathPolicyError as exc:
        raise HTTPError(400, str(exc)) from exc
    if not image.is_file():
        raise HTTPError(404, "Image not found")
    return FileResponse(image)
