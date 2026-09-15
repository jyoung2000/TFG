"""Shot-boundary detection.

Deliberately a pure function over frame fingerprints rather than something that
owns a decoder: the hard part is the decision rule, and keeping it separable
means it can be tested against synthetic signal without a video file, and
re-run instantly when the user changes sensitivity without decoding again.

The score behind every decision is kept on the boundary, so the UI can show why
a cut was placed and the user can argue with it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal, Sequence

from services.media_probe.media_probe import FrameSignature

DetectionMethod = Literal["cut", "fade", "uniform", "whole"]


@dataclass(slots=True)
class DetectionSettings:
    """How eager to be about calling something a cut."""

    #: 0..1. Higher finds more cuts. 0.5 is the balanced default.
    sensitivity: float = 0.5
    min_shot_seconds: float = 0.6
    max_shots: int = 400
    detect_fades: bool = True
    #: When nothing is found, split evenly rather than returning one long shot.
    uniform_fallback_seconds: float = 6.0


@dataclass(slots=True)
class ShotBoundary:
    """One detected shot, in seconds."""

    index: int
    start: float
    end: float
    #: 0..1, how strongly the evidence supported this boundary.
    confidence: float
    method: DetectionMethod

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _histogram_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """L1 distance over two normalised histograms, scaled to 0..1."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return min(1.0, sum(abs(x - y) for x, y in zip(a, b)) / 2.0)


def change_scores(signatures: Sequence[FrameSignature]) -> list[float]:
    """Per-sample change score. Index i is the change *arriving at* sample i."""
    scores = [0.0] * len(signatures)
    for i in range(1, len(signatures)):
        hist = _histogram_distance(signatures[i - 1].histogram, signatures[i].histogram)
        # The histogram catches a change of content; the pixel delta catches a
        # change of composition that happens to keep the same tonal spread.
        scores[i] = 0.7 * hist + 0.3 * min(1.0, signatures[i].delta * 4.0)
    return scores


def _threshold(scores: Sequence[float], sensitivity: float) -> float:
    """Adaptive cut threshold.

    A fixed number cannot serve both a flat interview and a music video, so the
    threshold floats with the material: the median plus a multiple of the median
    absolute deviation. Sensitivity moves the multiple, not the floor.
    """
    usable = [s for s in scores[1:] if s > 0]
    if not usable:
        return 1.0
    median = statistics.median(usable)
    deviation = statistics.median([abs(s - median) for s in usable]) or 0.01
    # sensitivity 0 -> ~8 MADs (only the most obvious cuts), 1 -> ~2 MADs.
    multiple = 8.0 - 6.0 * max(0.0, min(1.0, sensitivity))
    # The floor stops a completely static video from reporting noise as cuts.
    return max(median + multiple * deviation, 0.08)


def _fade_ranges(signatures: Sequence[FrameSignature]) -> list[int]:
    """Indices where the picture passes through near-black.

    A dissolve through black reads as low change on either side with a luma
    trough between, which the cut rule alone would miss.
    """
    marks: list[int] = []
    for i in range(1, len(signatures) - 1):
        previous, current, following = signatures[i - 1], signatures[i], signatures[i + 1]
        if current.mean_luma < 0.06 and previous.mean_luma > current.mean_luma < following.mean_luma:
            marks.append(i)
    return marks


def detect_shots(
    signatures: Sequence[FrameSignature],
    duration: float,
    settings: DetectionSettings | None = None,
) -> list[ShotBoundary]:
    """Split a video into shots. Always returns at least one shot."""
    config = settings or DetectionSettings()
    if duration <= 0:
        duration = signatures[-1].timestamp if signatures else 0.0
    if duration <= 0:
        return []
    if len(signatures) < 3:
        return [ShotBoundary(index=0, start=0.0, end=duration, confidence=0.0, method="whole")]

    scores = change_scores(signatures)
    threshold = _threshold(scores, config.sensitivity)

    candidates: list[tuple[int, float, DetectionMethod]] = []
    for i in range(1, len(signatures)):
        if scores[i] >= threshold:
            # Confidence grows with how far past the threshold the score sits.
            confidence = min(1.0, (scores[i] - threshold) / max(threshold, 1e-6) + 0.5)
            candidates.append((i, confidence, "cut"))

    if config.detect_fades:
        marked = {index for index, _, _ in candidates}
        for index in _fade_ranges(signatures):
            if index not in marked:
                candidates.append((index, 0.45, "fade"))

    candidates.sort(key=lambda item: item[0])

    # Enforce the minimum shot length, keeping the stronger of two close cuts.
    kept: list[tuple[int, float, DetectionMethod]] = []
    for candidate in candidates:
        if not kept:
            if signatures[candidate[0]].timestamp >= config.min_shot_seconds:
                kept.append(candidate)
            continue
        gap = signatures[candidate[0]].timestamp - signatures[kept[-1][0]].timestamp
        if gap >= config.min_shot_seconds:
            kept.append(candidate)
        elif candidate[1] > kept[-1][1]:
            kept[-1] = candidate

    # Too many cuts is worse than too few: keep the most confident.
    if config.max_shots > 0 and len(kept) > config.max_shots - 1:
        strongest = sorted(kept, key=lambda item: item[1], reverse=True)[: config.max_shots - 1]
        kept = sorted(strongest, key=lambda item: item[0])

    if not kept:
        return _uniform_split(duration, config)

    shots: list[ShotBoundary] = []
    start = 0.0
    for index, confidence, method in kept:
        end = signatures[index].timestamp
        if end - start < config.min_shot_seconds:
            continue
        shots.append(
            ShotBoundary(index=len(shots), start=round(start, 3), end=round(end, 3), confidence=round(confidence, 3), method=method)
        )
        start = end
    if duration - start >= 0.05:
        shots.append(
            ShotBoundary(index=len(shots), start=round(start, 3), end=round(duration, 3), confidence=0.5, method="cut")
        )
    return shots or _uniform_split(duration, config)


def _uniform_split(duration: float, config: DetectionSettings) -> list[ShotBoundary]:
    """No cuts found — a single long take, or a detector that was too strict.

    Splitting evenly is reported as its own method with zero confidence, so the
    UI never presents an arbitrary split as a detected cut.
    """
    window = max(config.min_shot_seconds, config.uniform_fallback_seconds)
    if duration <= window:
        return [ShotBoundary(index=0, start=0.0, end=round(duration, 3), confidence=0.0, method="whole")]
    shots: list[ShotBoundary] = []
    start = 0.0
    while start < duration - 0.05:
        end = min(duration, start + window)
        if duration - end < config.min_shot_seconds:
            end = duration
        shots.append(ShotBoundary(index=len(shots), start=round(start, 3), end=round(end, 3), confidence=0.0, method="uniform"))
        start = end
        if config.max_shots > 0 and len(shots) >= config.max_shots:
            break
    return shots


def split_shot(shots: Sequence[ShotBoundary], index: int, at: float) -> list[ShotBoundary]:
    """Split one shot in two at `at` seconds. Manual edits carry no confidence."""
    if index < 0 or index >= len(shots):
        raise ValueError(f"No shot at index {index}")
    target = shots[index]
    if not (target.start < at < target.end):
        raise ValueError(f"{at}s is outside shot {index} ({target.start}-{target.end})")
    replacement = [
        ShotBoundary(index=0, start=target.start, end=round(at, 3), confidence=1.0, method="cut"),
        ShotBoundary(index=0, start=round(at, 3), end=target.end, confidence=1.0, method="cut"),
    ]
    return _renumber([*shots[:index], *replacement, *shots[index + 1 :]])


def merge_shots(shots: Sequence[ShotBoundary], index: int) -> list[ShotBoundary]:
    """Merge the shot at `index` with the one after it."""
    if index < 0 or index + 1 >= len(shots):
        raise ValueError(f"No shot after index {index} to merge with")
    first, second = shots[index], shots[index + 1]
    merged = ShotBoundary(
        index=0,
        start=first.start,
        end=second.end,
        confidence=min(first.confidence, second.confidence),
        method=first.method,
    )
    return _renumber([*shots[:index], merged, *shots[index + 2 :]])


def set_boundary(shots: Sequence[ShotBoundary], index: int, *, start: float | None = None, end: float | None = None) -> list[ShotBoundary]:
    """Move one shot's edge, dragging its neighbour's edge with it."""
    if index < 0 or index >= len(shots):
        raise ValueError(f"No shot at index {index}")
    updated = [ShotBoundary(s.index, s.start, s.end, s.confidence, s.method) for s in shots]
    if start is not None:
        if index == 0:
            raise ValueError("The first shot starts at zero")
        if not (updated[index - 1].start < start < updated[index].end):
            raise ValueError("The new start must sit inside the neighbouring shots")
        updated[index].start = round(start, 3)
        updated[index - 1].end = round(start, 3)
    if end is not None:
        if index == len(updated) - 1:
            raise ValueError("The last shot ends with the video")
        if not (updated[index].start < end < updated[index + 1].end):
            raise ValueError("The new end must sit inside the neighbouring shots")
        updated[index].end = round(end, 3)
        updated[index + 1].start = round(end, 3)
    return _renumber(updated)


def _renumber(shots: Sequence[ShotBoundary]) -> list[ShotBoundary]:
    return [ShotBoundary(i, s.start, s.end, s.confidence, s.method) for i, s in enumerate(shots)]
