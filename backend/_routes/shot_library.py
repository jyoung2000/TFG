"""Routes for the cross-project shot library."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from api_types import StatusResponse
from app_handler import AppHandler
from film.film_models import FilmShot
from film.shot_library_api_types import (
    ApplyLibraryItemRequest,
    LibraryListResponse,
    SaveToLibraryRequest,
    UpdateLibraryItemRequest,
)
from film.shot_library_models import LibraryShot
from state import get_state_service

router = APIRouter(prefix="/api/shot-library", tags=["shot-library"])


@router.get("", response_model=LibraryListResponse)
def route_list(
    q: str = "",
    tags: list[str] = Query(default=[]),
    favorite: bool | None = None,
    archived: bool = False,
    model: str = "",
    sort: str = "recent",
    handler: AppHandler = Depends(get_state_service),
) -> LibraryListResponse:
    """Search and filter. `archived` switches to the archived shelf, not adds to it."""
    items = handler.shot_library.search(
        query=q, tags=tags, favorite=favorite, archived=archived, model=model, sort=sort
    )
    return LibraryListResponse(
        items=items, tags=handler.shot_library.tag_counts(), total=len(items)
    )


@router.get("/{item_id}/preview")
def route_preview(item_id: str, handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    """Serve an item's copied preview. The path comes from the item, never the caller."""
    return FileResponse(handler.shot_library.preview_path(item_id))


@router.get("/{item_id}", response_model=LibraryShot)
def route_get(item_id: str, handler: AppHandler = Depends(get_state_service)) -> LibraryShot:
    return handler.shot_library.get(item_id)


@router.post("", response_model=LibraryShot)
def route_save(
    req: SaveToLibraryRequest, handler: AppHandler = Depends(get_state_service)
) -> LibraryShot:
    """Snapshot a shot into the library, copying its preview media."""
    return handler.shot_library.save_from_shot(
        req.project_id,
        req.shot_id,
        title=req.title,
        notes=req.notes,
        tags=req.tags,
        rating=req.rating,
        version_number=req.version_number,
    )


@router.put("/{item_id}", response_model=LibraryShot)
def route_update(
    item_id: str,
    req: UpdateLibraryItemRequest,
    handler: AppHandler = Depends(get_state_service),
) -> LibraryShot:
    return handler.shot_library.update(
        item_id,
        title=req.title,
        notes=req.notes,
        tags=req.tags,
        rating=req.rating,
        favorite=req.favorite,
    )


@router.post("/{item_id}/duplicate", response_model=LibraryShot)
def route_duplicate(item_id: str, handler: AppHandler = Depends(get_state_service)) -> LibraryShot:
    return handler.shot_library.duplicate(item_id)


@router.post("/{item_id}/apply", response_model=FilmShot)
def route_apply(
    item_id: str,
    req: ApplyLibraryItemRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmShot:
    """Write the item's settings onto a shot, or onto a new one in that scene."""
    return handler.shot_library.apply(
        item_id, req.project_id, req.scene_id, req.shot_id, overwrite_prompt=req.overwrite_prompt
    )


@router.post("/{item_id}/archive", response_model=LibraryShot)
def route_archive(item_id: str, handler: AppHandler = Depends(get_state_service)) -> LibraryShot:
    """Hide it. Reversible — see restore."""
    return handler.shot_library.archive(item_id, True)


@router.post("/{item_id}/restore", response_model=LibraryShot)
def route_restore(item_id: str, handler: AppHandler = Depends(get_state_service)) -> LibraryShot:
    return handler.shot_library.archive(item_id, False)


@router.delete("/{item_id}", response_model=StatusResponse)
def route_delete(item_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    """Permanent, and takes the copied preview with it. Archive is the reversible one."""
    title = handler.shot_library.delete(item_id)
    return StatusResponse(status=f"deleted {title}")
