"""Persistence for the cross-project shot library.

One JSON index plus a directory of copied previews, outside any project:

    <outputs>/shot_library/library.json
    <outputs>/shot_library/previews/<item-id>.<ext>

JSON rather than SQLite, unlike the knowledge engine, because the access
pattern is the opposite: a curated list a person reads and edits by hand, not
an append-only log read by aggregation. It is small, it wants to be readable,
and rewriting it whole on every change costs nothing at this size.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from film.shot_library_models import LibraryIndex

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class ShotLibraryError(Exception):
    """Raised when the library cannot be read or written."""


def migrate(payload: dict[str, object]) -> dict[str, object]:
    """Upgrade an older library payload. Each future bump adds a step here."""
    version = payload.get("schema_version")
    if not isinstance(version, int) or version < 1:
        payload["schema_version"] = 1
    return payload


def _safe_name(relative: str) -> str:
    """A stored preview filename, or an error.

    Nothing legitimate ever contains a separator or a parent reference: the
    store mints these names itself as `<item-id><suffix>`.
    """
    name = relative.strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or Path(name).name != name:
        raise ShotLibraryError(f"Not a stored preview name: {relative!r}")
    return name


class ShotLibraryStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._index_file = root / "library.json"
        self._previews = root / "previews"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def previews_dir(self) -> Path:
        return self._previews

    def load(self) -> LibraryIndex:
        if not self._index_file.is_file():
            return LibraryIndex()
        try:
            payload = json.loads(self._index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ShotLibraryError(f"Could not read the shot library: {exc}") from exc
        if not isinstance(payload, dict):
            raise ShotLibraryError("The shot library file is not an object")
        try:
            return LibraryIndex.model_validate(migrate(payload))  # type: ignore[arg-type]
        except ValueError as exc:
            raise ShotLibraryError(f"The shot library file is not valid: {exc}") from exc

    def save(self, index: LibraryIndex) -> None:
        """Write via a temp file, so a crash mid-write cannot lose the library."""
        index.schema_version = _SCHEMA_VERSION
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._index_file.with_suffix(".json.tmp")
        try:
            temporary.write_text(index.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(self._index_file)
        except OSError as exc:
            raise ShotLibraryError(f"Could not write the shot library: {exc}") from exc

    def new_id(self) -> str:
        return f"lib-{uuid.uuid4().hex[:12]}"

    def copy_preview(self, item_id: str, source: Path) -> str:
        """Copy a take's media into the library.

        A copy rather than a link: the whole point of the library is that it
        keeps working after the take, the shot or the project it came from is
        gone. Returns the stored filename, relative to the previews directory.
        """
        self._previews.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower() or ".bin"
        target = self._previews / f"{item_id}{suffix}"
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise ShotLibraryError(f"Could not copy the preview: {exc}") from exc
        return target.name

    def preview_path(self, relative: str) -> Path:
        """Resolve a stored preview name, refusing anything that is not one.

        The name is written by `copy_preview` and is always a bare filename.
        But `library.json` is a file on the user's disk that they can edit, and
        an entry saying "../../../something" must not become a read or a
        delete outside the previews directory.
        """
        return self._previews / _safe_name(relative)

    def remove_preview(self, relative: str) -> None:
        """Best effort: a library entry going away must not fail on a stray file."""
        if not relative:
            return
        try:
            self._previews.joinpath(_safe_name(relative)).unlink(missing_ok=True)
        except (OSError, ShotLibraryError) as exc:
            logger.warning("Could not remove library preview %s: %s", relative, exc)

    def duplicate_preview(self, source_relative: str, item_id: str) -> str:
        if not source_relative:
            return ""
        source = self.preview_path(source_relative)
        if not source.is_file():
            return ""
        return self.copy_preview(item_id, source)
