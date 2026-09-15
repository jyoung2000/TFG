"""PyAV-backed `MediaProbe`.

PyAV binds ffmpeg's libraries directly, so there is no subprocess to spawn and
no command line to escape — which also removes a whole class of injection risk
around user-supplied paths. Decoding is streamed: frames are converted to a
small greyscale thumbnail, reduced to a histogram, and dropped.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any, Callable, cast

from services.media_probe.media_probe import FrameSignature, VideoMetadataPayload

logger = logging.getLogger(__name__)

#: Frames are reduced to this before fingerprinting. Small enough to be cheap,
#: large enough that a cut still moves the histogram.
_THUMB_W = 64
_THUMB_H = 36
_HIST_BINS = 32


def _empty_metadata() -> VideoMetadataPayload:
    return {
        "duration_seconds": 0.0,
        "fps": 0.0,
        "width": 0,
        "height": 0,
        "codec": "",
        "bit_rate": 0,
        "frame_count": 0,
        "has_audio": False,
        "audio_codec": "",
        "audio_channels": 0,
        "audio_sample_rate": 0,
        "rotation": 0,
        "pixel_format": "",
    }


class MediaProbeImpl:
    """Real video reader. Every method raises OSError on an unreadable file."""

    def probe(self, path: str) -> VideoMetadataPayload:
        import av

        info = _empty_metadata()
        try:
            with av.open(path) as container:
                streams = cast(Any, container).streams
                video = streams.video[0] if streams.video else None
                audio = streams.audio[0] if streams.audio else None

                duration = getattr(cast(Any, container), "duration", None)
                if duration:
                    info["duration_seconds"] = float(duration) / 1_000_000.0
                info["bit_rate"] = int(getattr(cast(Any, container), "bit_rate", 0) or 0)

                if video is not None:
                    info["width"] = int(getattr(video, "width", 0) or 0)
                    info["height"] = int(getattr(video, "height", 0) or 0)
                    codec_ctx = getattr(video, "codec_context", None)
                    info["codec"] = str(getattr(getattr(codec_ctx, "codec", None), "name", "") or "")
                    info["pixel_format"] = str(getattr(codec_ctx, "pix_fmt", "") or "")
                    rate = getattr(video, "average_rate", None) or getattr(video, "guessed_rate", None)
                    if isinstance(rate, Fraction) and rate.denominator:
                        info["fps"] = float(rate)
                    info["frame_count"] = int(getattr(video, "frames", 0) or 0)
                    # A container without a duration still has a stream one.
                    if not info["duration_seconds"]:
                        stream_duration = getattr(video, "duration", None)
                        time_base = getattr(video, "time_base", None)
                        if stream_duration and time_base:
                            info["duration_seconds"] = float(stream_duration * time_base)
                    info["rotation"] = _rotation_of(video)

                if audio is not None:
                    info["has_audio"] = True
                    audio_ctx = getattr(audio, "codec_context", None)
                    info["audio_codec"] = str(getattr(getattr(audio_ctx, "codec", None), "name", "") or "")
                    info["audio_channels"] = int(getattr(audio_ctx, "channels", 0) or 0)
                    info["audio_sample_rate"] = int(getattr(audio_ctx, "sample_rate", 0) or 0)
        except Exception as exc:  # noqa: BLE001 - PyAV raises many container errors
            raise OSError(f"Could not read the video: {exc}") from exc

        # Derive what the container did not state, so callers get usable numbers.
        if not info["fps"] and info["frame_count"] and info["duration_seconds"]:
            info["fps"] = info["frame_count"] / info["duration_seconds"]
        if not info["frame_count"] and info["fps"] and info["duration_seconds"]:
            info["frame_count"] = int(info["fps"] * info["duration_seconds"])
        return info

    def sample_signatures(
        self,
        path: str,
        *,
        sample_fps: float = 4.0,
        max_samples: int = 20000,
        on_progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[FrameSignature]:
        import av
        import numpy as np

        step = 1.0 / sample_fps if sample_fps > 0 else 0.25
        signatures: list[FrameSignature] = []
        previous: Any = None
        next_at = 0.0
        duration = self.probe(path)["duration_seconds"]

        try:
            with av.open(path) as container:
                streams = cast(Any, container).streams
                if not streams.video:
                    return []
                stream = streams.video[0]
                # Decoding is the expensive part; skipping non-reference frames
                # is not safe for accurate timing, so decode all and sample.
                for frame in cast(Any, container).decode(stream):
                    if is_cancelled is not None and is_cancelled():
                        break
                    timestamp = float(frame.time or 0.0)
                    if timestamp + 1e-6 < next_at:
                        continue
                    next_at = timestamp + step

                    thumb = frame.reformat(width=_THUMB_W, height=_THUMB_H, format="gray")
                    plane = np.asarray(thumb.to_ndarray(), dtype=np.float32)
                    counts, _ = np.histogram(plane, bins=_HIST_BINS, range=(0.0, 255.0))
                    total = float(counts.sum()) or 1.0
                    histogram = tuple(float(value) / total for value in counts)
                    mean_luma = float(plane.mean()) / 255.0

                    delta = 0.0
                    if previous is not None:
                        delta = float(np.abs(plane - previous).mean()) / 255.0
                    previous = plane

                    signatures.append(
                        FrameSignature(
                            index=len(signatures),
                            timestamp=timestamp,
                            histogram=histogram,
                            mean_luma=mean_luma,
                            delta=delta,
                        )
                    )
                    if on_progress is not None and duration > 0:
                        on_progress(min(1.0, timestamp / duration))
                    if len(signatures) >= max_samples:
                        break
        except Exception as exc:  # noqa: BLE001 - a truncated file is normal input
            if not signatures:
                raise OSError(f"Could not decode the video: {exc}") from exc
            logger.warning("Decoding stopped early for %s: %s", path, exc)

        if on_progress is not None:
            on_progress(1.0)
        return signatures

    def extract_jpeg(self, path: str, timestamp: float, *, max_width: int = 640, quality: int = 82) -> bytes:
        import av

        try:
            with av.open(path) as container:
                streams = cast(Any, container).streams
                if not streams.video:
                    raise OSError("The file has no video stream")
                stream = streams.video[0]
                time_base = getattr(stream, "time_base", None)
                if timestamp > 0 and time_base:
                    offset = int(timestamp / float(time_base))
                    cast(Any, container).seek(offset, stream=stream, any_frame=False, backward=True)

                for frame in cast(Any, container).decode(stream):
                    if timestamp <= 0 or float(frame.time or 0.0) >= timestamp - 1e-3:
                        return _encode_jpeg(frame, max_width, quality)
                # Past the end: the last decoded frame is the best answer.
                raise OSError(f"No frame at {timestamp:.3f}s")
        except OSError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OSError(f"Could not extract a frame: {exc}") from exc


def _encode_jpeg(frame: Any, max_width: int, quality: int) -> bytes:
    import io

    image = frame.to_image()
    if image.width > max_width:
        height = max(1, round(image.height * max_width / image.width))
        image = image.resize((max_width, height))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _rotation_of(stream: Any) -> int:
    """Display rotation, which players apply but raw frames do not carry."""
    metadata = getattr(stream, "metadata", None)
    if isinstance(metadata, dict):
        raw = cast(dict[str, str], metadata).get("rotate", "")
        try:
            return int(float(raw)) % 360
        except (TypeError, ValueError):
            return 0
    return 0
