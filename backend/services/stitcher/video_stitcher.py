"""Stitch picked candidates in shot order.

The real implementation shells out to ffmpeg's concat demuxer: stream copy
first (same encoder, same settings → no generation loss), and a re-encode
only when the copy is refused (mixed parameters). The binary is resolved in
this order: `TFG_FFMPEG`, the `imageio-ffmpeg` wheel the backend already
depends on, then `ffmpeg` on PATH — nothing is added to the repository.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, Sequence

logger = logging.getLogger(__name__)


class StitchError(RuntimeError):
    pass


class VideoStitcher(Protocol):
    def concat(self, inputs: Sequence[Path], output: Path) -> Path: ...

    def encode_frames(self, frames: Sequence[Path], fps: int, output: Path) -> Path:
        """PNG frames (in order) → an H.264 mp4 at `fps`."""
        ...


def find_ffmpeg() -> str | None:
    override = os.environ.get("TFG_FFMPEG", "").strip()
    if override and Path(override).is_file():
        return override
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001 - the wheel may be absent in a slim install
        pass
    return shutil.which("ffmpeg")


class FfmpegStitcher:
    def __init__(self, ffmpeg: str | None = None) -> None:
        self._ffmpeg = ffmpeg

    def concat(self, inputs: Sequence[Path], output: Path) -> Path:
        paths = [Path(p) for p in inputs]
        if not paths:
            raise StitchError("Nothing to stitch: no candidate was picked.")
        for path in paths:
            if not path.is_file():
                raise StitchError(f"Missing clip: {path}")
        ffmpeg = self._ffmpeg or find_ffmpeg()
        if not ffmpeg:
            raise StitchError("ffmpeg was not found (set TFG_FFMPEG or install imageio-ffmpeg).")
        output.parent.mkdir(parents=True, exist_ok=True)
        if len(paths) == 1:
            shutil.copyfile(paths[0], output)
            return output
        listing = output.with_suffix(".concat.txt")
        listing.write_text("".join(f"file '{p.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for p in paths), encoding="utf-8")
        try:
            base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
            copy = subprocess.run([*base, "-c", "copy", "-movflags", "+faststart", str(output)], capture_output=True, text=True, check=False)
            if copy.returncode == 0 and output.is_file() and output.stat().st_size > 0:
                return output
            logger.info("Stream-copy concat refused (%s); re-encoding", copy.stderr.strip()[:200])
            encode = subprocess.run([*base, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18", "-an", "-movflags", "+faststart", str(output)], capture_output=True, text=True, check=False)
            if encode.returncode != 0 or not output.is_file():
                raise StitchError(f"ffmpeg could not stitch the clips: {encode.stderr.strip()[:400]}")
            return output
        finally:
            listing.unlink(missing_ok=True)


    def encode_frames(self, frames: Sequence[Path], fps: int, output: Path) -> Path:
        paths = [Path(p) for p in frames]
        if not paths:
            raise StitchError("No frames to encode.")
        ffmpeg = self._ffmpeg or find_ffmpeg()
        if not ffmpeg:
            raise StitchError("ffmpeg was not found (set TFG_FFMPEG or install imageio-ffmpeg).")
        output.parent.mkdir(parents=True, exist_ok=True)
        listing = output.with_suffix(".frames.txt")
        frame_time = 1.0 / max(1, fps)
        lines = "".join(f"file '{p.as_posix()}'\nduration {frame_time:.6f}\n" for p in paths) + f"file '{paths[-1].as_posix()}'\n"
        listing.write_text(lines, encoding="utf-8")
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-vsync", "vfr", "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18", "-movflags", "+faststart", str(output)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0 or not output.is_file():
                raise StitchError(f"ffmpeg could not encode the frames: {result.stderr.strip()[:400]}")
            return output
        finally:
            listing.unlink(missing_ok=True)


class FakeStitcher:
    """Writes the inputs' bytes back to back; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[Path], Path]] = []
        self.encoded: list[tuple[list[Path], int, Path]] = []
        self.fail_with: Exception | None = None

    def encode_frames(self, frames: Sequence[Path], fps: int, output: Path) -> Path:
        paths = [Path(p) for p in frames]
        self.encoded.append((paths, fps, Path(output)))
        if self.fail_with is not None:
            raise self.fail_with
        if not paths:
            raise StitchError("No frames to encode.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-frames-mp4:" + str(len(paths)).encode() + b"@" + str(fps).encode())
        return output

    def concat(self, inputs: Sequence[Path], output: Path) -> Path:
        paths = [Path(p) for p in inputs]
        self.calls.append((paths, Path(output)))
        if self.fail_with is not None:
            raise self.fail_with
        if not paths:
            raise StitchError("Nothing to stitch: no candidate was picked.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as handle:
            handle.write(b"fake-stitch\n")
            for path in paths:
                handle.write(path.read_bytes())
        return output
