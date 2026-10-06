"""Optical-flow motion analysis (phase 5).

`MotionAnalyzer` is the service boundary: `OpticalFlowAnalyzer` decodes with
PyAV and runs OpenCV Farneback; `FakeMotion` returns configured summaries.
The maths that turns flow fields into a camera-move summary is pure and
lives in `flow_math`, so it is tested on synthetic fields, not stubbed.
"""

from services.motion.fake_motion import FakeMotion
from services.motion.flow_math import (
    GlobalMotion,
    estimate_global_motion,
    pacing_for,
    summarise_motions,
)
from services.motion.motion_analyzer import (
    MotionAnalyzer,
    MotionSummary,
    OpticalFlowAnalyzer,
    describe_motion,
)

__all__ = [
    "FakeMotion",
    "GlobalMotion",
    "MotionAnalyzer",
    "MotionSummary",
    "OpticalFlowAnalyzer",
    "describe_motion",
    "estimate_global_motion",
    "pacing_for",
    "summarise_motions",
]
