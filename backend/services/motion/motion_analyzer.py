"""The motion service: protocol, summary model and the OpenCV implementation."""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

import numpy as np
from pydantic import BaseModel

from services.motion.flow_math import GlobalMotion, estimate_global_motion, pacing_for, summarise_motions

logger = logging.getLogger(__name__)

#: Width the frames are downscaled to before flow; height follows the aspect.
_FLOW_WIDTH = 160
#: A shot whose per-pair jitter exceeds this reads as handheld.
_HANDHELD_JITTER = 0.9
#: Below this mean flow (fraction of the diagonal per sample) the camera is static.
_STATIC_MAGNITUDE = 0.002


class MotionSummary(BaseModel):
    """What optical flow measured for one clip or shot. Mirrors `spec.motion`."""

    analyzed: bool = False
    model: str = ""
    #: Dominant camera components, normalised per sampled pair (see flow_math).
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    roll: float = 0.0
    #: Mean flow length as a fraction of the frame diagonal per sampled pair.
    magnitude: float = 0.0
    #: Mean residual after removing the global camera model.
    subject_motion: float = 0.0
    #: High-frequency pan/tilt energy relative to the mean (0 = locked off).
    jitter: float = 0.0
    handheld: bool = False
    pacing: str = ""
    frames_sampled: int = 0
    #: 0..1 — how much of the flow the global model explains, times sample support.
    confidence: float = 0.0


class MotionAnalyzer(Protocol):
    def analyze(self, path: str, *, start: float | None = None, end: float | None = None, sample_fps: float = 6.0, max_frames: int = 48) -> MotionSummary: ...


def describe_motion(summary: MotionSummary) -> tuple[str, list[str], bool]:
    """Camera-move words for a summary: `(camera_movement, movement_types, is_static)`.

    Directions are the camera's, not the content's: content drifting right
    means the camera panned left.
    """
    if not summary.analyzed:
        return "", [], True
    types: list[str] = []
    horizontal = abs(summary.pan)
    vertical = abs(summary.tilt)
    if summary.magnitude < _STATIC_MAGNITUDE and abs(summary.zoom) < 0.002:
        camera = "handheld, nearly static" if summary.handheld else "static camera"
        return camera, (["handheld"] if summary.handheld else []), not summary.handheld
    if abs(summary.zoom) >= 0.003 and abs(summary.zoom) >= max(horizontal, vertical) * 0.5:
        types.append("push in" if summary.zoom > 0 else "pull out")
    if horizontal >= 0.0025 and horizontal >= vertical:
        types.append("pan left" if summary.pan > 0 else "pan right")
    elif vertical >= 0.0025:
        types.append("tilt up" if summary.tilt > 0 else "tilt down")
    if abs(summary.roll) >= 0.004:
        types.append("roll")
    if summary.handheld:
        types.append("handheld")
    if not types:
        types.append("slow drift")
    return ", ".join(types), types, False


class OpticalFlowAnalyzer:
    """Farneback dense flow over frames sampled with PyAV, downscaled for speed.

    RAFT is not wired: it needs weights this app cannot fetch offline and the
    Farneback fit is enough to classify the move and its magnitude.
    """

    model = "opencv-farneback"

    def analyze(self, path: str, *, start: float | None = None, end: float | None = None, sample_fps: float = 6.0, max_frames: int = 48) -> MotionSummary:
        frames = self._sample(path, start, end, sample_fps, max_frames)
        if len(frames) < 2:
            return MotionSummary(analyzed=False, model=self.model, frames_sampled=len(frames))
        import cv2

        motions: list[GlobalMotion] = []
        explained: list[float] = []
        for previous, current in zip(frames, frames[1:]):
            flow = cast(Any, cv2).calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            motion = estimate_global_motion(np.asarray(flow, dtype=np.float64))
            motions.append(motion)
            explained.append(1.0 - min(1.0, motion.residual / (motion.magnitude + 1e-6)) if motion.magnitude > 1e-6 else 1.0)
        return summary_from_motions(motions, explained, model=self.model, frames_sampled=len(frames))

    @staticmethod
    def _sample(path: str, start: float | None, end: float | None, sample_fps: float, max_frames: int) -> list[Any]:
        import av

        step = 1.0 / sample_fps if sample_fps > 0 else 0.2
        frames: list[Any] = []
        next_at = start or 0.0
        try:
            with av.open(path) as container:
                streams = cast(Any, container).streams
                if not streams.video:
                    return []
                stream = streams.video[0]
                if start:
                    cast(Any, container).seek(int(start / float(stream.time_base)) if stream.time_base else 0, stream=stream, backward=True)
                for frame in cast(Any, container).decode(stream):
                    timestamp = float(frame.time or 0.0)
                    if timestamp + 1e-6 < next_at:
                        continue
                    if end is not None and timestamp > end + 1e-6:
                        break
                    next_at = timestamp + step
                    height = max(2, int(round(_FLOW_WIDTH * frame.height / max(1, frame.width))))
                    gray = frame.reformat(width=_FLOW_WIDTH, height=height, format="gray")
                    frames.append(np.asarray(gray.to_ndarray(), dtype=np.uint8))
                    if len(frames) >= max_frames:
                        break
        except Exception as exc:  # noqa: BLE001 - a truncated file is normal input
            if not frames:
                logger.warning("Motion analysis could not decode %s: %s", path, exc)
                return []
            logger.warning("Motion decoding stopped early for %s: %s", path, exc)
        return frames


def summary_from_motions(motions: list[GlobalMotion], explained: list[float] | None = None, *, model: str, frames_sampled: int) -> MotionSummary:
    """Roll per-pair fits into a `MotionSummary` (shared by real and synthetic paths)."""
    agg = summarise_motions(motions)
    handheld = agg["jitter"] > _HANDHELD_JITTER and agg["magnitude"] >= _STATIC_MAGNITUDE / 2
    support = min(1.0, len(motions) / 8.0)
    fit = float(np.mean(explained)) if explained else 0.5
    return MotionSummary(
        analyzed=True,
        model=model,
        pan=round(agg["pan"], 5),
        tilt=round(agg["tilt"], 5),
        zoom=round(agg["zoom"], 5),
        roll=round(agg["roll"], 5),
        magnitude=round(agg["magnitude"], 5),
        subject_motion=round(agg["subject_motion"], 5),
        jitter=round(agg["jitter"], 4),
        handheld=handheld,
        pacing=pacing_for(agg["magnitude"], agg["subject_motion"]),
        frames_sampled=frames_sampled,
        confidence=round(max(0.0, min(1.0, 0.5 * support + 0.5 * fit)), 3),
    )
