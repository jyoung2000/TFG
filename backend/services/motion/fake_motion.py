"""Deterministic motion service for tests: no decoding, configurable answers."""

from __future__ import annotations

from services.motion.motion_analyzer import MotionSummary


class FakeMotion:
    model = "fake-flow"

    def __init__(self, default: MotionSummary | None = None) -> None:
        self.default = default or MotionSummary(
            analyzed=True, model=self.model, pan=0.006, tilt=0.0, zoom=0.0, roll=0.0,
            magnitude=0.012, subject_motion=0.004, jitter=0.1, handheld=False, pacing="slow",
            frames_sampled=12, confidence=0.8,
        )
        #: Answers by path (or path prefix); anything else gets `default`.
        self.by_path: dict[str, MotionSummary] = {}
        self.calls: list[tuple[str, float | None, float | None]] = []
        self.fail_with: Exception | None = None

    def analyze(self, path: str, *, start: float | None = None, end: float | None = None, sample_fps: float = 6.0, max_frames: int = 48) -> MotionSummary:  # noqa: ARG002
        self.calls.append((path, start, end))
        if self.fail_with is not None:
            raise self.fail_with
        for key, summary in self.by_path.items():
            if path == key or path.startswith(key):
                return summary.model_copy()
        return self.default.model_copy()
