"""Request/response models for the cross-project shot library."""

from __future__ import annotations

from pydantic import BaseModel, Field

from film.shot_library_models import LibraryShot


class SaveToLibraryRequest(BaseModel):
    project_id: str = ""
    shot_id: str = ""
    title: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list[str])
    rating: int = 0
    #: The take to use for the preview; the shot's current one when omitted.
    version_number: int | None = None


class UpdateLibraryItemRequest(BaseModel):
    """Only the fields present are changed, so a rating edit cannot blank the notes."""

    title: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    rating: int | None = None
    favorite: bool | None = None


class ApplyLibraryItemRequest(BaseModel):
    project_id: str = ""
    scene_id: str = ""
    #: Empty means "add a new shot to this scene".
    shot_id: str = ""
    overwrite_prompt: bool = True


class LibraryListResponse(BaseModel):
    items: list[LibraryShot] = Field(default_factory=list[LibraryShot])
    #: Every tag in use with its count, so the filter UI needs no second call.
    tags: dict[str, int] = Field(default_factory=dict[str, int])
    total: int = 0
