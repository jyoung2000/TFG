"""The cross-project shot library.

A shot that worked is worth more than the film it was made for. The library is
where one gets kept so it can be used again somewhere else — which means it
cannot be a reference into a project, because that project will be renamed,
archived, or have the very take deleted.

So a library item is a **copy**. The settings are snapshotted and the preview
media is copied into the library's own directory. Deleting the source shot,
the source take, or the whole source project leaves the library entry intact
and usable. The lineage is kept alongside as a record of where it came from,
not as a dependency on it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.film_models import ShotFraming, now_ms

#: What the preview is, so a caller knows which element to render.
PreviewKind = Literal["video", "image", "none"]


class LibraryLineage(BaseModel):
    """Where this came from. A record, never a dependency.

    Every field can point at something that no longer exists, and the entry
    keeps working anyway — that is the point of copying rather than linking.
    """

    project_id: str = ""
    project_name: str = ""
    scene_id: str = ""
    scene_title: str = ""
    shot_id: str = ""
    shot_title: str = ""
    version_number: int | None = None
    captured_at: int = Field(default_factory=now_ms)


class LibraryShot(BaseModel):
    """One reusable shot."""

    id: str = ""
    title: str = ""
    notes: str = ""

    # What gets applied to a shot that uses this.
    visual_prompt: str = ""
    negative_prompt: str = ""
    framing: ShotFraming = Field(default_factory=ShotFraming)
    camera_move: str = "static"
    duration_seconds: float = 5.0
    model: str = ""
    resolution: str = ""
    fps: int = 24
    seed: int | None = None
    aspect_ratio: str = "16:9"
    style: str = ""

    # A copy, relative to the library's previews directory — so the entry
    # survives the take it came from being deleted.
    preview_path: str = ""
    preview_kind: PreviewKind = "none"

    lineage: LibraryLineage = Field(default_factory=LibraryLineage)

    tags: list[str] = Field(default_factory=list[str])
    #: 0 means unrated, which is not the same as rated zero.
    rating: int = 0
    favorite: bool = False
    #: Archived items are hidden from the default listing and restorable.
    #: Deletion is separate, permanent, and confirmed.
    archived: bool = False
    archived_at: int | None = None

    used_count: int = 0
    last_used_at: int = 0
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class LibraryIndex(BaseModel):
    """The whole library as it sits on disk."""

    schema_version: int = 1
    items: list[LibraryShot] = Field(default_factory=list[LibraryShot])
