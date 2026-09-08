"""One filesystem path policy for every film/media endpoint.

Every route that takes a path from the renderer (media, outputs, package
paths, imported generations) funnels through these helpers, so the rules are
in one place:

* paths are resolved canonically (symlinks followed) before comparison;
* a path must live under an explicitly allowed base directory;
* ``..`` segments, absolute escapes and symlinks that point outside the base
  are all rejected the same way;
* user-supplied destinations are required to be absolute and to carry an
  allowed extension.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class PathPolicyError(ValueError):
    """Raised for a path outside the allowed area; message is user-safe."""


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:  # pragma: no cover - exotic filesystems
        raise PathPolicyError(f"Cannot resolve path: {path}") from exc


def is_within(base: Path, candidate: Path) -> bool:
    base_c = _canonical(base)
    cand_c = _canonical(candidate)
    return cand_c == base_c or base_c in cand_c.parents


def resolve_within(base: Path, relative: str, *, what: str = "path") -> Path:
    """Join ``relative`` onto ``base`` and prove the result stays inside it."""
    if not relative or relative.strip() != relative:
        raise PathPolicyError(f"Invalid {what}")
    if "\x00" in relative:
        raise PathPolicyError(f"Invalid {what}")
    candidate = Path(base) / relative
    if Path(relative).is_absolute() or not is_within(base, candidate):
        raise PathPolicyError(f"{what} escapes the allowed directory: {relative!r}")
    return _canonical(candidate)


def require_within_any(candidate: str | Path, bases: Iterable[Path], *, what: str = "path") -> Path:
    """An absolute path that must resolve under one of ``bases``."""
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        raise PathPolicyError(f"{what} must be an absolute path")
    for base in bases:
        if is_within(base, path):
            return _canonical(path)
    raise PathPolicyError(f"{what} is outside the allowed directories")


def require_absolute_file(candidate: str, *, what: str = "file", allowed_suffixes: Iterable[str] | None = None) -> Path:
    """A user-picked absolute file path (from a native dialog) that exists."""
    raw = candidate.strip()
    if not raw or "\x00" in raw:
        raise PathPolicyError(f"{what} is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PathPolicyError(f"{what} must be an absolute path")
    if allowed_suffixes is not None and path.suffix.lower() not in {s.lower() for s in allowed_suffixes}:
        raise PathPolicyError(f"{what} has an unsupported file type: {path.suffix or 'none'}")
    if not path.is_file():
        raise PathPolicyError(f"{what} not found: {raw}")
    return _canonical(path)


def require_destination(candidate: str, *, suffix: str, what: str = "destination") -> Path:
    """A user-picked absolute destination; the suffix is enforced so an export
    can never overwrite an arbitrary file type."""
    raw = candidate.strip()
    if not raw or "\x00" in raw:
        raise PathPolicyError(f"{what} is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PathPolicyError(f"{what} must be an absolute path")
    if path.is_dir():
        raise PathPolicyError(f"{what} points at a directory")
    if path.suffix.lower() != suffix.lower():
        path = path.with_name(path.name + suffix)
    if path.is_dir():
        raise PathPolicyError(f"{what} points at a directory")
    return path
