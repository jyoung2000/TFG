"""The cross-project shot library: save a shot that worked, use it elsewhere.

Everything here operates on copies. Saving snapshots a shot's settings and
copies its preview media into the library's own directory; applying writes
those settings onto a different shot in a different project. Neither leaves a
link between the two, so deleting one never breaks the other.

Two ways to remove an item, and they are not the same:

* **Archive** hides it from the default listing and is undone by **restore**.
  This is the safe one, and the one the UI offers first.
* **Delete** is permanent and takes the copied preview with it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import RLock

from _routes._errors import HTTPError
from film.film_models import FilmShot, now_ms
from film.shot_library_models import LibraryIndex, LibraryLineage, LibraryShot
from film.shot_library_store import ShotLibraryError, ShotLibraryStore
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

#: Tags are lowercased and trimmed so "Night" and "night " are one tag.
_MAX_TAGS = 24
_MAX_TAG_LENGTH = 40


def normalise_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        cleaned = tag.strip().lower()[:_MAX_TAG_LENGTH]
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:_MAX_TAGS]


class ShotLibraryHandler(StateHandlerBase):
    def __init__(self, state: AppState, lock: RLock, root: Path, film_handler: FilmHandler) -> None:
        super().__init__(state, lock)
        self._store = ShotLibraryStore(root)
        self._film = film_handler

    @property
    def store(self) -> ShotLibraryStore:
        return self._store

    # ---- reading ---------------------------------------------------------

    def _index(self) -> LibraryIndex:
        try:
            return self._store.load()
        except ShotLibraryError as exc:
            raise HTTPError(500, str(exc)) from exc

    def _write(self, index: LibraryIndex) -> None:
        try:
            self._store.save(index)
        except ShotLibraryError as exc:
            raise HTTPError(500, str(exc)) from exc

    def _require(self, index: LibraryIndex, item_id: str) -> LibraryShot:
        for item in index.items:
            if item.id == item_id:
                return item
        raise HTTPError(404, f"Library item not found: {item_id}")

    def search(
        self,
        *,
        query: str = "",
        tags: list[str] | None = None,
        favorite: bool | None = None,
        archived: bool = False,
        model: str = "",
        sort: str = "recent",
    ) -> list[LibraryShot]:
        """Filter the library.

        `archived` is a switch rather than a filter value: archived items are
        out of the way by default, and asking for them gets only them.
        """
        wanted = normalise_tags(tags or [])
        needle = query.strip().lower()
        results: list[LibraryShot] = []
        for item in self._index().items:
            if item.archived != archived:
                continue
            if favorite is not None and item.favorite != favorite:
                continue
            if model and model.lower() not in item.model.lower():
                continue
            if wanted and not all(tag in item.tags for tag in wanted):
                continue
            if needle and needle not in " ".join(
                (item.title, item.notes, item.visual_prompt, item.model, " ".join(item.tags))
            ).lower():
                continue
            results.append(item)

        if sort == "rating":
            results.sort(key=lambda i: (i.rating, i.updated_at), reverse=True)
        elif sort == "used":
            results.sort(key=lambda i: (i.used_count, i.last_used_at), reverse=True)
        elif sort == "title":
            results.sort(key=lambda i: i.title.lower())
        else:
            results.sort(key=lambda i: i.updated_at, reverse=True)
        # Favourites first within the chosen order, because that is what
        # favouriting is for.
        results.sort(key=lambda i: not i.favorite)
        return results

    def get(self, item_id: str) -> LibraryShot:
        return self._require(self._index(), item_id)

    def tag_counts(self) -> dict[str, int]:
        """Every tag in use, with how many items carry it — for the filter UI."""
        counts: dict[str, int] = {}
        for item in self._index().items:
            if item.archived:
                continue
            for tag in item.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))

    def preview_path(self, item_id: str) -> Path:
        """The file to serve for one item's preview.

        Resolved from the item's own stored name rather than from anything the
        caller sends, so there is no path for a request to walk out of the
        previews directory.
        """
        item = self.get(item_id)
        if not item.preview_path:
            raise HTTPError(404, "That library item has no preview")
        try:
            path = self._store.preview_path(item.preview_path)
        except ShotLibraryError as exc:
            # `library.json` is a file the user can edit. An entry naming
            # something outside the previews directory is bad input, not a
            # server fault, and it is refused rather than followed.
            raise HTTPError(400, str(exc)) from exc
        if not path.is_file():
            raise HTTPError(404, "That preview is missing from disk")
        return path

    # ---- saving ----------------------------------------------------------

    def save_from_shot(
        self,
        project_id: str,
        shot_id: str,
        *,
        title: str = "",
        notes: str = "",
        tags: list[str] | None = None,
        rating: int = 0,
        version_number: int | None = None,
    ) -> LibraryShot:
        """Snapshot a shot into the library, copying its preview.

        The take used for the preview is the one named, or the shot's current
        one. A shot with no rendered take can still be saved — its settings are
        the reusable part — and the entry simply has no preview.
        """
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        scene, shot = found

        number = version_number if version_number is not None else shot.current_version
        version = shot.version(number) if number is not None else None
        if version is not None and version.status != "complete":
            version = None

        item_id = self._store.new_id()
        preview_name = ""
        preview_kind = "none"
        if version is not None and version.output_path:
            source = Path(version.output_path)
            if source.is_file():
                try:
                    preview_name = self._store.copy_preview(item_id, source)
                    preview_kind = "video"
                except ShotLibraryError as exc:
                    # A missing preview is a worse entry, not a failed save.
                    logger.warning("Saving %s without a preview: %s", shot_id, exc)
        if not preview_name and shot.capture_path:
            capture = self._film.store.captures_dir(project_id) / shot.capture_path
            if capture.is_file():
                try:
                    preview_name = self._store.copy_preview(item_id, capture)
                    preview_kind = "image"
                except ShotLibraryError as exc:
                    logger.warning("Saving %s without a capture preview: %s", shot_id, exc)

        item = LibraryShot(
            id=item_id,
            title=(title.strip() or shot.title or "Untitled shot")[:200],
            notes=notes.strip()[:2000],
            visual_prompt=shot.visual_prompt,
            negative_prompt=shot.negative_prompt,
            framing=shot.framing.model_copy(deep=True),
            camera_move=shot.camera_move,
            duration_seconds=shot.duration_seconds,
            model=(version.model if version else shot.generation.model),
            resolution=(version.resolution if version else shot.generation.resolution),
            fps=(version.fps if version else shot.generation.fps),
            seed=(version.seed if version else shot.generation.seed),
            aspect_ratio=shot.generation.aspect_ratio,
            style=project.settings.style_prompt,
            preview_path=preview_name,
            preview_kind=preview_kind,  # type: ignore[arg-type]
            lineage=LibraryLineage(
                project_id=project_id,
                project_name=project.name,
                scene_id=scene.id,
                scene_title=scene.title,
                shot_id=shot.id,
                shot_title=shot.title,
                version_number=(version.number if version else None),
            ),
            tags=normalise_tags(tags or []),
            rating=max(0, min(5, rating)),
        )

        index = self._index()
        index.items.append(item)
        self._write(index)
        return item

    # ---- using -----------------------------------------------------------

    def apply(
        self, item_id: str, project_id: str, scene_id: str, shot_id: str = "", *, overwrite_prompt: bool = True
    ) -> FilmShot:
        """Write a library item's settings onto a shot, or onto a new one.

        A copy, not a link: nothing afterwards ties the shot to the library
        entry, so editing one never changes the other.
        """
        item = self.get(item_id)

        with self.lock:
            project = self._film.store.load(project_id)
            scene = next((s for s in project.scenes if s.id == scene_id), None)
            if scene is None:
                raise HTTPError(404, f"Scene not found: {scene_id}")

            if shot_id:
                shot = next((s for s in scene.shots if s.id == shot_id), None)
                if shot is None:
                    raise HTTPError(404, f"Shot not found: {shot_id}")
            else:
                shot = FilmShot(
                    order=len(scene.shots),
                    title=item.title,
                )
                scene.shots.append(shot)

            shot.framing = item.framing.model_copy(deep=True)
            shot.camera_move = item.camera_move  # type: ignore[assignment]
            shot.duration_seconds = item.duration_seconds
            shot.generation.model = item.model
            shot.generation.resolution = item.resolution
            shot.generation.fps = item.fps
            shot.generation.seed = item.seed
            shot.generation.aspect_ratio = item.aspect_ratio  # type: ignore[assignment]
            if overwrite_prompt and item.visual_prompt:
                shot.visual_prompt = item.visual_prompt
                # An applied prompt is an explicit choice, so synthesis must
                # not quietly replace it on the next edit.
                shot.prompt_locked = True
            if item.negative_prompt:
                shot.negative_prompt = item.negative_prompt
            shot.updated_at = now_ms()
            project.updated_at = now_ms()
            self._film.store.save(project)

        index = self._index()
        stored = self._require(index, item_id)
        stored.used_count += 1
        stored.last_used_at = now_ms()
        self._write(index)
        return shot

    # ---- curating --------------------------------------------------------

    def update(
        self,
        item_id: str,
        *,
        title: str | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
        rating: int | None = None,
        favorite: bool | None = None,
    ) -> LibraryShot:
        index = self._index()
        item = self._require(index, item_id)
        if title is not None:
            cleaned = title.strip()[:200]
            if not cleaned:
                raise HTTPError(400, "A library item needs a title")
            item.title = cleaned
        if notes is not None:
            item.notes = notes.strip()[:2000]
        if tags is not None:
            item.tags = normalise_tags(tags)
        if rating is not None:
            item.rating = max(0, min(5, rating))
        if favorite is not None:
            item.favorite = favorite
        item.updated_at = now_ms()
        self._write(index)
        return item

    def duplicate(self, item_id: str) -> LibraryShot:
        """Copy an entry, preview and all, so one can be varied without losing the other."""
        index = self._index()
        source = self._require(index, item_id)
        copy = source.model_copy(deep=True)
        copy.id = self._store.new_id()
        copy.title = f"{source.title} (copy)"[:200]
        copy.preview_path = self._store.duplicate_preview(source.preview_path, copy.id)
        if not copy.preview_path:
            copy.preview_kind = "none"
        copy.used_count = 0
        copy.last_used_at = 0
        copy.favorite = False
        copy.archived = False
        copy.archived_at = None
        copy.created_at = now_ms()
        copy.updated_at = now_ms()
        index.items.append(copy)
        self._write(index)
        return copy

    def archive(self, item_id: str, archived: bool) -> LibraryShot:
        """Hide an item, or bring it back. Reversible, unlike delete."""
        index = self._index()
        item = self._require(index, item_id)
        item.archived = archived
        item.archived_at = now_ms() if archived else None
        item.updated_at = now_ms()
        self._write(index)
        return item

    def delete(self, item_id: str) -> str:
        """Permanent, and takes the copied preview with it.

        Archive is the reversible one; this is not. The UI confirms it and
        offers archiving instead.
        """
        index = self._index()
        item = self._require(index, item_id)
        # Best effort, and deliberately not fatal: a crafted or missing preview
        # name must not leave the entry stuck in the library forever.
        self._store.remove_preview(item.preview_path)
        index.items = [candidate for candidate in index.items if candidate.id != item_id]
        self._write(index)
        return item.title
