"""Route handlers for /api/generate-image."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api_types import GenerateImageRequest, GenerateImageResponse
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api", tags=["image"])


@router.post("/generate-image", response_model=GenerateImageResponse)
def route_generate_image(
    req: GenerateImageRequest,
    handler: AppHandler = Depends(get_state_service),
) -> GenerateImageResponse:
    """POST /api/generate-image."""
    response = handler.image_generation.generate(req)
    if req.faceLock and req.loras and response.status == "complete" and response.image_paths:
        locked = handler.film_generation.sheet_lock(response.image_paths, req.loras, outfit=req.outfitLock)
        if locked is not None:
            response.face_scores, response.outfit_locked = locked
    return response

