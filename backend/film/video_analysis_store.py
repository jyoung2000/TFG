"""Persistence for video analyses.

Same shape as `FilmStore`: one directory per analysis holding a JSON document
plus the frames extracted from the source. Frames live beside the document so
an analysis is self-describing and can be deleted in one move.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import cast

from film.video_analysis_models import VideoAnalysis

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class VideoAnalysisStoreError(Exception):
    """Invalid analysis id, or unreadable analysis data."""


def validate_analysis_id(analysis_id: str) -> str:
    if not _ID_RE.match(analysis_id):
        raise VideoAnalysisStoreError(f"Invalid analysis id: {analysis_id!r}")
    return analysis_id


def migrate(payload: dict[str, object]) -> dict[str, object]:
    """Upgrade an older analysis document. Each schema bump adds a step here."""
    version = payload.get("schema_version")
    if not isinstance(version, int) or version < 1:
        payload["schema_version"] = 1
    return payload


class VideoAnalysisStore:
    """Loads and saves analyses under a root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def directory(self, analysis_id: str) -> Path:
        return self._root / validate_analysis_id(analysis_id)

    def frames_directory(self, analysis_id: str) -> Path:
        return self.directory(analysis_id) / "frames"

    def _document(self, analysis_id: str) -> Path:
        return self.directory(analysis_id) / "analysis.json"

    def exists(self, analysis_id: str) -> bool:
        return self._document(analysis_id).is_file()

    def load(self, analysis_id: str) -> VideoAnalysis:
        path = self._document(analysis_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise VideoAnalysisStoreError(f"No analysis named {analysis_id}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise VideoAnalysisStoreError(f"Analysis {analysis_id} is unreadable: {exc}") from exc
        if not isinstance(payload, dict):
            raise VideoAnalysisStoreError(f"Analysis {analysis_id} is not an object")
        return VideoAnalysis.model_validate(migrate(cast(dict[str, object], payload)))

    def save(self, analysis: VideoAnalysis) -> None:
        directory = self.directory(analysis.id)
        directory.mkdir(parents=True, exist_ok=True)
        document = self._document(analysis.id)
        # Write beside the target and move, so a crash mid-write cannot leave a
        # half-written analysis that fails to parse on the next open.
        temporary = document.with_suffix(".json.tmp")
        temporary.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(document)

    def list_ids(self) -> list[str]:
        if not self._root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self._root.iterdir()
            if entry.is_dir() and (entry / "analysis.json").is_file()
        )

    def delete(self, analysis_id: str) -> None:
        import shutil

        directory = self.directory(analysis_id)
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
