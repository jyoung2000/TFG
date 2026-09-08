"""Disk persistence for film projects.

Layout (under RuntimeConfig.outputs_dir):

    film_projects/<project-id>/
      project.json     # FilmProject, schema-versioned
      captures/        # captured composition reference PNGs + JSON snapshots
      references/      # uploaded asset reference images
      outputs/         # reserved for copies of generated media

Writes are atomic (tmp file + rename). Loads run migrate() before parsing so
older schema versions upgrade in place. A corrupted project.json is renamed
aside (never silently destroyed) and replaced with a fresh empty facet.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import cast

from film.film_models import FILM_SCHEMA_VERSION, FilmProject

logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class FilmStoreError(Exception):
    """Raised for invalid project ids or unreadable project data."""


def validate_project_id(project_id: str) -> str:
    if not _PROJECT_ID_RE.match(project_id):
        raise FilmStoreError(f"Invalid film project id: {project_id!r}")
    return project_id


def migrate(payload: dict[str, object]) -> dict[str, object]:
    """Upgrade an older film project payload to the current schema, in steps.

    v0 (pre-release experiments) stored shots directly under "shots" with no
    scenes; wrap them into a single scene. Each future bump adds one step here.
    """
    version = payload.get("schema_version")
    if not isinstance(version, int) or version < 1:
        shots = payload.pop("shots", None)
        scenes = payload.get("scenes")
        if isinstance(shots, list) and not scenes:
            payload["scenes"] = [
                {"title": "Scene 1", "order": 0, "shots": shots},
            ]
        payload["schema_version"] = 1
    return payload


class FilmStore:
    """Loads and saves film projects under a root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def project_dir(self, project_id: str) -> Path:
        return self._root / validate_project_id(project_id)

    def captures_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "captures"

    def references_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "references"

    def outputs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "outputs"

    def _project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def list_project_ids(self) -> list[str]:
        """Ids of every persisted film project (directories with a project.json)."""
        if not self._root.exists():
            return []
        ids: list[str] = []
        for entry in sorted(self._root.iterdir()):
            if entry.is_dir() and (entry / "project.json").is_file():
                ids.append(entry.name)
        return ids

    def exists(self, project_id: str) -> bool:
        return self._project_file(project_id).exists()

    def load(self, project_id: str) -> FilmProject:
        """Load a project, creating an empty facet if none exists yet."""
        path = self._project_file(project_id)
        if not path.exists():
            project = FilmProject(id=validate_project_id(project_id))
            self.save(project)
            return project
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise FilmStoreError("project.json is not a JSON object")
            migrated = migrate(cast(dict[str, object], raw))
            return FilmProject.model_validate(migrated)
        except FilmStoreError:
            raise
        except Exception as exc:
            backup = path.with_name(f"project.corrupt-{int(time.time())}.json")
            try:
                path.rename(backup)
                logger.error(
                    "Film project %s was unreadable (%s); preserved as %s",
                    project_id,
                    exc,
                    backup.name,
                )
            except OSError:
                logger.error("Film project %s was unreadable and could not be preserved", project_id)
            project = FilmProject(id=validate_project_id(project_id))
            self.save(project)
            return project

    def save(self, project: FilmProject) -> None:
        directory = self.project_dir(project.id)
        directory.mkdir(parents=True, exist_ok=True)
        path = self._project_file(project.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def resolve_media_path(self, project_id: str, relative: str) -> Path:
        """Resolve a project-relative media path, refusing traversal outside it."""
        base = self.project_dir(project_id).resolve()
        candidate = (base / relative).resolve()
        if base != candidate and base not in candidate.parents:
            raise FilmStoreError(f"Path escapes the film project directory: {relative!r}")
        return candidate

    def save_capture(
        self,
        project_id: str,
        shot_id: str,
        image_bytes: bytes,
        composition_json: str,
    ) -> str:
        """Persist a capture PNG + composition snapshot; returns the relative PNG path."""
        captures = self.captures_dir(project_id)
        captures.mkdir(parents=True, exist_ok=True)
        png_rel = f"captures/{shot_id}.png"
        (captures / f"{shot_id}.png").write_bytes(image_bytes)
        (captures / f"{shot_id}.json").write_text(composition_json, encoding="utf-8")
        return png_rel

    def save_reference_image(self, project_id: str, name_hint: str, image_bytes: bytes) -> str:
        """Persist an asset reference image; returns the relative path."""
        references = self.references_dir(project_id)
        references.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", name_hint) or "reference"
        filename = f"{int(time.time() * 1000)}-{safe}"
        if not filename.lower().endswith(".png"):
            filename += ".png"
        (references / filename).write_bytes(image_bytes)
        return f"references/{filename}"


assert FILM_SCHEMA_VERSION == 1, "bump migrate() alongside FILM_SCHEMA_VERSION"
