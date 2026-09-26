"""Describe an output file for History: dimensions, duration and a small JPEG.

Images go through PIL; videos through the media-probe service (metadata plus
a first-frame JPEG), so the only side effect that needs a fake in tests is
the one that already has one.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image

from services.job_store.job_models import JobOutput
from services.media_probe.media_probe import MediaProbe

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})
THUMB_MAX_EDGE = 320


def thumb_name(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"{digest}.jpg"


def describe_output(path: Path, thumbs_dir: Path, probe: MediaProbe) -> JobOutput:
    """Never raises: a file whose preview cannot be made is still an output."""
    suffix = path.suffix.lower()
    output = JobOutput(path=str(path), kind="file")
    if not path.is_file():
        return output
    try:
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumbs_dir / thumb_name(path)
        if suffix in IMAGE_SUFFIXES:
            output.kind = "image"
            with Image.open(path) as image:
                output.width, output.height = image.size
                preview = image.convert("RGB")
                preview.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
                preview.save(thumb_path, format="JPEG", quality=82)
            output.thumb = str(thumb_path)
        elif suffix in VIDEO_SUFFIXES:
            output.kind = "video"
            metadata = probe.probe(str(path))
            output.width = int(metadata.get("width") or 0)
            output.height = int(metadata.get("height") or 0)
            output.duration = float(metadata.get("duration_seconds") or 0.0)
            timestamp = min(0.1, output.duration / 2) if output.duration > 0 else 0.0
            thumb_path.write_bytes(probe.extract_jpeg(str(path), timestamp, max_width=THUMB_MAX_EDGE))
            output.thumb = str(thumb_path)
    except Exception as exc:  # noqa: BLE001 - a missing preview must not fail the job
        logger.warning("Could not describe output %s: %s", path, exc)
    return output
