"""Image Reproduce v2 routes. Thin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app_handler import AppHandler
from film.prompt_compiler import PromptStyle
from film.reproduce_models import ReproduceBudget, ReproduceJob
from services.image_ops import Adjustments
from state import get_state_service

router = APIRouter(prefix="/api/reproduce", tags=["reproduce"])


class ImportRequest(BaseModel):
    path: str


class ReproduceListResponse(BaseModel):
    jobs: list[ReproduceJob]


class SpecPatchRequest(BaseModel):
    sections: dict[str, Any] = Field(default_factory=dict[str, Any])
    locks: dict[str, bool] | None = None


class PromptRequest(BaseModel):
    prompt: str = Field(default="", max_length=4000)
    target: str | None = None
    style: PromptStyle | None = None


class StartRequest(BaseModel):
    budget: ReproduceBudget | None = None
    seed: int | None = None
    #: Ask the VLM to compare on plateaus (needs a vision-capable model).
    use_vlm: bool = False


class FixRequest(BaseModel):
    exposure: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    hue: float = 0.0
    black_point: float = 0.0
    white_point: float = 1.0
    gamma: float = 1.0
    temperature: float = 0.0
    mask_png_base64: str = ""
    patch_from_reference: bool = False
    inpaint_prompt: str = ""


def _vlm(handler: AppHandler):
    return handler.vision.optional_vlm(handler.film_director.optional_provider("storyboard"))


@router.post("/import", response_model=ReproduceJob)
def route_import(req: ImportRequest, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.import_image(req.path)


@router.get("", response_model=ReproduceListResponse)
def route_list(handler: AppHandler = Depends(get_state_service)) -> ReproduceListResponse:
    return ReproduceListResponse(jobs=handler.reproduce.list())


@router.get("/{job_id}", response_model=ReproduceJob)
def route_get(job_id: str, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.get(job_id)


@router.delete("/{job_id}")
def route_delete(job_id: str, handler: AppHandler = Depends(get_state_service)) -> dict[str, str]:
    handler.reproduce.delete(job_id)
    return {"status": "ok"}


@router.post("/{job_id}/analyze", response_model=ReproduceJob)
def route_analyze(job_id: str, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.analyze(job_id, _vlm(handler))


@router.put("/{job_id}/spec", response_model=ReproduceJob)
def route_spec(job_id: str, req: SpecPatchRequest, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.update_spec(job_id, req.sections, locks=req.locks)


@router.put("/{job_id}/prompt", response_model=ReproduceJob)
def route_prompt(job_id: str, req: PromptRequest, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.set_prompt(job_id, req.prompt, target=req.target, style=req.style)


@router.post("/{job_id}/start", response_model=ReproduceJob)
def route_start(job_id: str, req: StartRequest, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.start(job_id, req.budget, seed=req.seed, provider=_vlm(handler) if req.use_vlm else None)


@router.post("/{job_id}/cancel", response_model=ReproduceJob)
def route_cancel(job_id: str, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.cancel(job_id)


@router.post("/{job_id}/pin/{candidate_id}", response_model=ReproduceJob)
def route_pin(job_id: str, candidate_id: str, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.pin(job_id, "" if candidate_id == "source" else candidate_id)


@router.post("/{job_id}/pick/{candidate_id}", response_model=ReproduceJob)
def route_pick(job_id: str, candidate_id: str, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    return handler.reproduce.pick(job_id, candidate_id)


@router.post("/{job_id}/candidates/{candidate_id}/fix", response_model=ReproduceJob)
def route_fix(job_id: str, candidate_id: str, req: FixRequest, handler: AppHandler = Depends(get_state_service)) -> ReproduceJob:
    adjustments = Adjustments(
        exposure=req.exposure, contrast=req.contrast, saturation=req.saturation, hue=req.hue,
        black_point=req.black_point, white_point=req.white_point, gamma=req.gamma, temperature=req.temperature,
    )
    return handler.reproduce.commit_fix(
        job_id, candidate_id, adjustments=adjustments, mask_png_base64=req.mask_png_base64,
        patch_from_reference=req.patch_from_reference, inpaint_prompt=req.inpaint_prompt,
    )


@router.get("/{job_id}/media")
def route_media(job_id: str, path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    return FileResponse(handler.reproduce.media_path(job_id, path))
