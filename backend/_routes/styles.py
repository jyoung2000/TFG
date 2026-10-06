"""Route handlers for /api/styles: the app-wide style library
(handlers/style_library_handler.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api_types import StatusResponse
from app_handler import AppHandler
from handlers.style_library_handler import SavedStyle
from state import get_state_service

router = APIRouter(prefix="/api/styles", tags=["styles"])


class StylesResponse(BaseModel):
    styles: list[SavedStyle]


class CreateStyleRequest(BaseModel):
    name: str
    #: The style's pictures, base64 (data URLs are fine); the vision model reads three.
    images_base64: list[str] = Field(default_factory=list[str])


@router.get("", response_model=StylesResponse)
def route_list_styles(handler: AppHandler = Depends(get_state_service)) -> StylesResponse:
    return StylesResponse(styles=handler.styles.list())


@router.post("", response_model=SavedStyle)
def route_create_style(req: CreateStyleRequest, handler: AppHandler = Depends(get_state_service)) -> SavedStyle:
    """Save a style from pictures; the configured vision AI reverse-engineers it (none: pictures only)."""
    provider = handler.film_director.optional_provider("storyboard")
    return handler.styles.create(req.name, req.images_base64, provider)


@router.delete("/{style_id}", response_model=StatusResponse)
def route_delete_style(style_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    handler.styles.delete(style_id)
    return StatusResponse(status="ok")


@router.get("/{style_id}/images/{index}")
def route_style_image(style_id: str, index: int, handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    return FileResponse(handler.styles.image_file(style_id, index))
