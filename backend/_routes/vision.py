"""Vision routes: status, one-off analysis, VRAM control. Thin."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app_handler import AppHandler
from handlers.vision_handler import VisionAnalysis, VramStatus
from services.vision.protocol import VisionStatus
from state import get_state_service

router = APIRouter(prefix="/api/vision", tags=["vision"])


class VisionStatusResponse(BaseModel):
    vision: VisionStatus
    vram: VramStatus
    cache: dict[str, int]
    vlm: str


class AnalyzeImageRequest(BaseModel):
    path: str
    caption: bool = True
    regions: bool = True
    tags: bool = True
    depth: bool = True
    use_cache: bool = True


class PrepareRenderRequest(BaseModel):
    model_type: str


class UnloadResponse(BaseModel):
    unloaded: list[str]


@router.get("/status", response_model=VisionStatusResponse)
def route_vision_status(handler: AppHandler = Depends(get_state_service)) -> VisionStatusResponse:
    vlm = handler.vision.optional_vlm(handler.film_director.optional_provider("storyboard"))
    return VisionStatusResponse(
        vision=handler.vision.status(),
        vram=handler.vision.vram_status(),
        cache=handler.vision.cache_summary(),
        vlm=f"{vlm.name}:{vlm.model}" if vlm is not None else "",
    )


@router.post("/analyze", response_model=VisionAnalysis)
def route_vision_analyze(req: AnalyzeImageRequest, handler: AppHandler = Depends(get_state_service)) -> VisionAnalysis:
    return handler.vision.analyze(
        req.path, want_caption=req.caption, want_regions=req.regions, want_tags=req.tags, want_depth=req.depth, use_cache=req.use_cache
    )


@router.post("/unload", response_model=UnloadResponse)
def route_vision_unload(handler: AppHandler = Depends(get_state_service)) -> UnloadResponse:
    return UnloadResponse(unloaded=handler.vision.unload())


@router.post("/prepare-render", response_model=VramStatus)
def route_prepare_render(req: PrepareRenderRequest, handler: AppHandler = Depends(get_state_service)) -> VramStatus:
    handler.vision.prepare_for_render(req.model_type)
    return handler.vision.vram_status()


@router.delete("/cache")
def route_clear_cache(handler: AppHandler = Depends(get_state_service)) -> dict[str, int]:
    return {"removed": handler.vision.clear_cache()}
