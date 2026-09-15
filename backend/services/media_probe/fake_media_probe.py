"""A `MediaProbe` that synthesises video instead of reading one.

Lets the whole analysis pipeline — detection, frame extraction, reconstruction —
run in tests with no video file and no decoder, while still exercising the real
detector against a real signal: the shot pattern is generated, so a test can
assert that the boundaries it planted are the ones that come back.
"""

from __future__ import annotations

from typing import Callable

from services.media_probe.media_probe import FrameSignature, VideoMetadataPayload


class FakeMediaProbe:
    """Configure `shot_seconds` to plant cuts the detector should find."""

    def __init__(
        self,
        *,
        duration: float = 12.0,
        fps: float = 24.0,
        width: int = 1920,
        height: int = 1080,
        has_audio: bool = True,
        shot_seconds: tuple[float, ...] = (2.0, 4.0, 6.0, 8.0, 10.0),
        sample_fps: float = 8.0,
    ) -> None:
        self.duration = duration
        self.fps = fps
        self.width = width
        self.height = height
        self.has_audio = has_audio
        self.shot_seconds = shot_seconds
        self.sample_fps = sample_fps
        self.readable = True
        #: Every path passed in, so a test can assert what was opened.
        self.probed: list[str] = []
        self.extracted: list[tuple[str, float]] = []

    def probe(self, path: str) -> VideoMetadataPayload:
        self.probed.append(path)
        if not self.readable:
            raise OSError("fake probe: unreadable file")
        return {
            "duration_seconds": self.duration,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "codec": "h264",
            "bit_rate": 2_500_000,
            "frame_count": int(self.duration * self.fps),
            "has_audio": self.has_audio,
            "audio_codec": "aac" if self.has_audio else "",
            "audio_channels": 2 if self.has_audio else 0,
            "audio_sample_rate": 48_000 if self.has_audio else 0,
            "rotation": 0,
            "pixel_format": "yuv420p",
        }

    def sample_signatures(
        self,
        path: str,
        *,
        sample_fps: float = 4.0,
        max_samples: int = 20000,
        on_progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[FrameSignature]:
        if not self.readable:
            raise OSError("fake probe: unreadable file")
        step = 1.0 / (sample_fps or self.sample_fps)
        signatures: list[FrameSignature] = []
        timestamp = 0.0
        index = 0
        while timestamp < self.duration and len(signatures) < max_samples:
            if is_cancelled is not None and is_cancelled():
                break
            shot_index = sum(1 for boundary in self.shot_seconds if timestamp >= boundary - 1e-9)
            # Each shot occupies its own histogram bin, so consecutive shots are
            # maximally different and a boundary is unambiguous.
            bins = max(2, len(self.shot_seconds) + 1)
            histogram = tuple(1.0 if b == shot_index % bins else 0.0 for b in range(bins))
            at_boundary = any(abs(timestamp - boundary) < step / 2 for boundary in self.shot_seconds)
            signatures.append(
                FrameSignature(
                    index=index,
                    timestamp=round(timestamp, 4),
                    histogram=histogram,
                    mean_luma=0.2 + 0.1 * (shot_index % 3),
                    delta=0.5 if at_boundary else 0.002,
                )
            )
            index += 1
            timestamp += step
            if on_progress is not None:
                on_progress(min(1.0, timestamp / self.duration))
        if on_progress is not None:
            on_progress(1.0)
        return signatures

    def extract_jpeg(self, path: str, timestamp: float, *, max_width: int = 640, quality: int = 82) -> bytes:
        if not self.readable:
            raise OSError("fake probe: unreadable file")
        self.extracted.append((path, round(timestamp, 3)))
        # A real 1x1 JPEG: callers that decode it get a valid image, and the
        # bytes are small enough to keep thousands of them in a test.
        return bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300"
            + "ff" * 64
            + "ffc00011080001000103012200021101031101"
            "ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
            "ffda0008010100003f00d2cf20ffd9"
        )
