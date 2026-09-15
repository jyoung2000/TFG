"""Reading a video file: metadata, sampled frame signatures, single frames.

Kept behind a Protocol like every other heavy side effect in this codebase, so
the analysis pipeline can be tested end to end without a real video file.

The real implementation streams with PyAV rather than shelling out to ffmpeg:
no subprocess, no argument quoting to get wrong, and no need for a binary on
PATH. Frames are decoded and discarded as they go, so a long video never lands
in memory whole.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, TypedDict


class VideoMetadataPayload(TypedDict):
    """What a container can tell us before any decoding happens."""

    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    bit_rate: int
    frame_count: int
    has_audio: bool
    audio_codec: str
    audio_channels: int
    audio_sample_rate: int
    rotation: int
    pixel_format: str


@dataclass(slots=True)
class FrameSignature:
    """A cheap fingerprint of one sampled frame.

    Shot detection works on these rather than on pixels, which keeps the
    detector a pure function over small numbers — testable without a decoder,
    and cheap enough to hold for a whole feature-length video.
    """

    index: int
    timestamp: float
    #: Normalised luma histogram; sums to 1.0.
    histogram: tuple[float, ...] = field(default_factory=tuple)
    mean_luma: float = 0.0
    #: Mean absolute difference from the previous sampled frame (0..1).
    delta: float = 0.0


class MediaProbe(Protocol):
    """Read-only access to a video file on disk."""

    def probe(self, path: str) -> VideoMetadataPayload:
        """Container/stream metadata. Raises OSError when unreadable."""
        ...

    def sample_signatures(
        self,
        path: str,
        *,
        sample_fps: float = 4.0,
        max_samples: int = 20000,
        on_progress: Callable[[float], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[FrameSignature]:
        """Walk the video once, returning a fingerprint per sampled frame."""
        ...

    def extract_jpeg(self, path: str, timestamp: float, *, max_width: int = 640, quality: int = 82) -> bytes:
        """One frame at (or just after) `timestamp`, as JPEG bytes."""
        ...
