"""Film project package export/import (.ltxfilm zip).

Package layout (format "ltx-film-package", version 1):

    manifest.json        {"format", "format_version", "exported_at_ms",
                          "schema_version", "project_id", "project_name",
                          "includes_outputs", "media": [...]}
    project.json         FilmProject (schema-versioned, same as on disk)
    captures/…           capture PNGs + composition JSON snapshots
    references/…         asset reference images
    outputs/…            generated media (optional): <shot-id>-v<n>.<ext>

Inside the package every media path is relative; version.output_path is
rewritten to "outputs/<file>" on export and back to an absolute path under
the destination project on import. Import validates the manifest, the
project schema (through migrate()), every member path (no absolute paths, no
"..", only the three media folders, extension allowlist) and enforces size
limits before anything touches the store.
"""

from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import ValidationError

from film.film_models import FILM_SCHEMA_VERSION, FilmProject
from film.film_store import FilmStore, FilmStoreError, migrate

PACKAGE_FORMAT = "ltx-film-package"
PACKAGE_FORMAT_VERSION = 1
PACKAGE_EXTENSION = ".ltxfilm"

_MEDIA_DIRS = ("captures", "references", "outputs")
_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".json", ".mp4", ".webm", ".mov", ".m4v"}
_MAX_MEMBERS = 5000
_MAX_MEMBER_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB per member
_MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024  # 64 GB per package
_MAX_PROJECT_JSON_BYTES = 50 * 1024 * 1024


class FilmPackageError(Exception):
    """Invalid package or unsafe content; message is safe to show the user."""


@dataclass(slots=True)
class PackageSummary:
    project_id: str
    project_name: str
    schema_version: int
    scenes: int
    shots: int
    assets: int
    media_files: int
    includes_outputs: bool
    total_bytes: int
    warnings: list[str] = field(default_factory=list[str])


def _safe_member_path(name: str) -> PurePosixPath:
    """Validate a zip member path and return it as a relative POSIX path."""
    if not name or name.endswith("/"):
        raise FilmPackageError(f"Directory entries are not allowed in the package: {name!r}")
    if "\\" in name:
        raise FilmPackageError(f"Backslashes are not allowed in package paths: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise FilmPackageError(f"Unsafe path in package: {name!r}")
    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise FilmPackageError(f"File type not allowed in package: {name!r}")
    return path


def _rewrite_outputs_for_export(project: FilmProject) -> dict[str, Path]:
    """Point every version output at a package-relative path; return the
    mapping package_path -> source file for members that exist on disk."""
    media: dict[str, Path] = {}
    for scene in project.scenes:
        for shot in scene.shots:
            for version in shot.versions:
                if not version.output_path:
                    continue
                source = Path(version.output_path)
                if not source.is_file():
                    version.output_path = ""
                    if version.status == "complete":
                        version.error = "Output file was missing at export time"
                    continue
                member = f"outputs/{shot.id}-v{version.number}{source.suffix.lower() or '.mp4'}"
                media[member] = source
                version.output_path = member
    return media


def export_package(
    store: FilmStore,
    project_id: str,
    destination: Path,
    *,
    include_outputs: bool = True,
) -> PackageSummary:
    """Write a package for ``project_id`` to ``destination`` (.ltxfilm)."""
    project = store.load(project_id).model_copy(deep=True)
    project_dir = store.project_dir(project_id)
    media: dict[str, Path] = {}
    warnings: list[str] = []

    for folder in ("captures", "references"):
        directory = project_dir / folder
        if directory.is_dir():
            for file in sorted(directory.rglob("*")):
                if file.is_file() and file.suffix.lower() in _ALLOWED_EXTENSIONS:
                    media[f"{folder}/{file.relative_to(directory).as_posix()}"] = file

    if include_outputs:
        media.update(_rewrite_outputs_for_export(project))
    else:
        for scene in project.scenes:
            for shot in scene.shots:
                for version in shot.versions:
                    if version.output_path:
                        version.output_path = ""
                        warnings.append(f"Output for {shot.title or shot.id} v{version.number} not included")

    total_bytes = sum(path.stat().st_size for path in media.values())
    manifest = {
        "format": PACKAGE_FORMAT,
        "format_version": PACKAGE_FORMAT_VERSION,
        "exported_at_ms": int(time.time() * 1000),
        "schema_version": project.schema_version,
        "project_id": project.id,
        "project_name": project.name,
        "includes_outputs": include_outputs,
        "media": sorted(media),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("project.json", project.model_dump_json(indent=2))
        for member, source in media.items():
            archive.write(source, arcname=member, compress_type=zipfile.ZIP_STORED if source.suffix.lower() in (".mp4", ".webm", ".mov", ".m4v") else zipfile.ZIP_DEFLATED)
    tmp.replace(destination)
    return PackageSummary(
        project_id=project.id,
        project_name=project.name,
        schema_version=project.schema_version,
        scenes=len(project.scenes),
        shots=sum(len(s.shots) for s in project.scenes),
        assets=len(project.assets),
        media_files=len(media),
        includes_outputs=include_outputs,
        total_bytes=total_bytes,
        warnings=warnings,
    )


@dataclass(slots=True)
class _ValidatedPackage:
    project: FilmProject
    members: list[tuple[PurePosixPath, zipfile.ZipInfo]]
    manifest: dict[str, object]
    total_bytes: int


def _validate_package(path: Path) -> tuple[zipfile.ZipFile, _ValidatedPackage]:
    if not path.is_file():
        raise FilmPackageError(f"Package not found: {path}")
    if not zipfile.is_zipfile(path):
        raise FilmPackageError("Not a film package (expected a zip archive)")
    archive = zipfile.ZipFile(path)
    try:
        infos = archive.infolist()
        if len(infos) > _MAX_MEMBERS:
            raise FilmPackageError(f"Package has too many files ({len(infos)} > {_MAX_MEMBERS})")
        names = {info.filename for info in infos}
        if "manifest.json" not in names or "project.json" not in names:
            raise FilmPackageError("Package is missing manifest.json or project.json")
        try:
            manifest_raw: object = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise FilmPackageError("manifest.json is not valid JSON") from exc
        if not isinstance(manifest_raw, dict):
            raise FilmPackageError("manifest.json must be a JSON object")
        manifest = cast(dict[str, object], manifest_raw)
        if manifest.get("format") != PACKAGE_FORMAT:
            raise FilmPackageError("This file is not an LTX film package")
        version = manifest.get("format_version")
        if not isinstance(version, int) or version < 1 or version > PACKAGE_FORMAT_VERSION:
            raise FilmPackageError(
                f"Unsupported package format version {version!r} (this app reads up to {PACKAGE_FORMAT_VERSION})"
            )
        project_info = archive.getinfo("project.json")
        if project_info.file_size > _MAX_PROJECT_JSON_BYTES:
            raise FilmPackageError("project.json is unreasonably large")
        try:
            project_raw: object = json.loads(archive.read("project.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise FilmPackageError("project.json is not valid JSON") from exc
        if not isinstance(project_raw, dict):
            raise FilmPackageError("project.json must be a JSON object")
        try:
            project = FilmProject.model_validate(migrate(cast(dict[str, object], project_raw)))
        except ValidationError as exc:
            errors = exc.errors()
            location = ".".join(str(part) for part in errors[0]["loc"]) if errors else "project"
            reason = errors[0]["msg"] if errors else "invalid"
            raise FilmPackageError(f"project.json failed schema validation at {location or 'project'}: {reason}") from exc
        if project.schema_version > FILM_SCHEMA_VERSION:
            raise FilmPackageError(
                f"Project schema {project.schema_version} is newer than this app supports ({FILM_SCHEMA_VERSION})"
            )

        members: list[tuple[PurePosixPath, zipfile.ZipInfo]] = []
        total = 0
        for info in infos:
            if info.filename in ("manifest.json", "project.json"):
                continue
            rel = _safe_member_path(info.filename)
            if rel.parts[0] not in _MEDIA_DIRS:
                raise FilmPackageError(f"Unexpected file outside the media folders: {info.filename!r}")
            if info.file_size > _MAX_MEMBER_BYTES:
                raise FilmPackageError(f"{info.filename!r} exceeds the per-file size limit")
            total += info.file_size
            if total > _MAX_TOTAL_BYTES:
                raise FilmPackageError("Package exceeds the total size limit")
            members.append((rel, info))
        member_names = {rel.as_posix() for rel, _ in members}
        for scene in project.scenes:
            for shot in scene.shots:
                if shot.capture_path and shot.capture_path not in member_names:
                    shot.capture_path = ""
                for version in shot.versions:
                    if version.output_path and version.output_path not in member_names:
                        version.output_path = ""
                        if version.status == "complete":
                            version.error = "Output was not included in the imported package"
        for asset in project.assets:
            asset.reference_images = [p for p in asset.reference_images if p in member_names]
        return archive, _ValidatedPackage(project=project, members=members, manifest=manifest, total_bytes=total)
    except Exception:
        archive.close()
        raise


def inspect_package(path: Path) -> PackageSummary:
    archive, validated = _validate_package(path)
    archive.close()
    project = validated.project
    return PackageSummary(
        project_id=project.id,
        project_name=project.name,
        schema_version=project.schema_version,
        scenes=len(project.scenes),
        shots=sum(len(s.shots) for s in project.scenes),
        assets=len(project.assets),
        media_files=len(validated.members),
        includes_outputs=bool(validated.manifest.get("includes_outputs", False)),
        total_bytes=validated.total_bytes,
    )


def import_package(store: FilmStore, path: Path, target_project_id: str) -> tuple[FilmProject, PackageSummary]:
    """Validate ``path`` and install it as ``target_project_id``, replacing
    that project's facet and media. Nothing is written until validation passed."""
    archive, validated = _validate_package(path)
    try:
        project = validated.project
        project.id = target_project_id
        project_dir = store.project_dir(target_project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        base = project_dir.resolve()
        # Clear previous media so stale files never leak into the new facet.
        for folder in _MEDIA_DIRS:
            directory = project_dir / folder
            if directory.is_dir():
                for file in directory.rglob("*"):
                    if file.is_file():
                        file.unlink()
        for rel, info in validated.members:
            target = (project_dir / Path(*rel.parts)).resolve()
            if base != target and base not in target.parents:
                raise FilmPackageError(f"Unsafe path in package: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as sink:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    sink.write(chunk)
        for scene in project.scenes:
            for shot in scene.shots:
                for version in shot.versions:
                    if version.output_path:
                        version.output_path = str((project_dir / Path(*PurePosixPath(version.output_path).parts)).resolve())
        try:
            store.save(project)
        except FilmStoreError as exc:
            raise FilmPackageError(str(exc)) from exc
    finally:
        archive.close()
    summary = PackageSummary(
        project_id=project.id,
        project_name=project.name,
        schema_version=project.schema_version,
        scenes=len(project.scenes),
        shots=sum(len(s.shots) for s in project.scenes),
        assets=len(project.assets),
        media_files=len(validated.members),
        includes_outputs=bool(validated.manifest.get("includes_outputs", False)),
        total_bytes=validated.total_bytes,
    )
    return project, summary
