"""Optical-flow motion analysis: the fit on synthetic fields, the classifier,
and the real analyzer over the synthetic sample clip (no model, no GPU)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from services.motion import (
    FakeMotion,
    GlobalMotion,
    MotionSummary,
    OpticalFlowAnalyzer,
    describe_motion,
    estimate_global_motion,
    pacing_for,
    summarise_motions,
)
from services.motion.motion_analyzer import summary_from_motions

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _grid(h: int = 40, w: int = 60):
    ys, xs = np.mgrid[0:h, 0:w]
    return xs - (w - 1) / 2.0, ys - (h - 1) / 2.0


class TestFlowFit:
    def test_pure_translation_is_a_pan(self):
        flow = np.stack([np.full((40, 60), 3.0), np.zeros((40, 60))], axis=-1)
        fit = estimate_global_motion(flow)
        assert fit.pan == pytest.approx(3.0 / 60, abs=1e-6)
        assert abs(fit.tilt) < 1e-6 and abs(fit.zoom) < 1e-6 and abs(fit.roll) < 1e-6
        assert fit.residual < 1e-9

    def test_radial_field_is_a_zoom(self):
        px, py = _grid()
        flow = np.stack([0.05 * px, 0.05 * py], axis=-1)
        fit = estimate_global_motion(flow)
        assert fit.zoom == pytest.approx(0.05, abs=1e-6)
        assert abs(fit.pan) < 1e-6 and abs(fit.roll) < 1e-6

    def test_rotational_field_is_a_roll(self):
        px, py = _grid()
        flow = np.stack([-0.02 * py, 0.02 * px], axis=-1)
        fit = estimate_global_motion(flow)
        assert fit.roll == pytest.approx(0.02, abs=1e-6)
        assert abs(fit.zoom) < 1e-6

    def test_subject_motion_is_left_as_residual(self):
        flow = np.zeros((40, 60, 2))
        flow[10:20, 10:20, 0] = 6.0  # a moving patch on a static background
        fit = estimate_global_motion(flow)
        assert fit.residual > fit.magnitude * 0.5
        assert abs(fit.pan) < 0.01

    def test_degenerate_input_is_zero_not_an_exception(self):
        assert estimate_global_motion(np.zeros((1, 1, 2))) == GlobalMotion(0, 0, 0, 0, 0, 0)


class TestSummary:
    def test_reversing_pans_cancel_and_read_as_jitter(self):
        pairs = [GlobalMotion(pan=s * 0.01, tilt=0, zoom=0, roll=0, magnitude=0.01, residual=0) for s in (1, -1) * 6]
        agg = summarise_motions(pairs)
        assert abs(agg["pan"]) < 1e-9
        assert agg["jitter"] > 1.5
        summary = summary_from_motions(pairs, model="test", frames_sampled=13)
        assert summary.handheld is True
        assert "handheld" in describe_motion(summary)[1]

    def test_steady_pan_is_not_handheld_and_names_the_direction(self):
        pairs = [GlobalMotion(pan=0.01, tilt=0, zoom=0, roll=0, magnitude=0.01, residual=0.001)] * 10
        summary = summary_from_motions(pairs, model="test", frames_sampled=11)
        assert summary.handheld is False
        movement, types, is_static = describe_motion(summary)
        assert is_static is False
        assert types == ["pan left"]  # content drifts right → camera pans left
        assert "pan left" in movement

    def test_static_and_zoom_classification(self):
        static = summary_from_motions([GlobalMotion(0, 0, 0, 0, 0.0005, 0.0002)] * 6, model="t", frames_sampled=7)
        assert describe_motion(static) == ("static camera", [], True)
        push = summary_from_motions([GlobalMotion(0, 0, 0.01, 0, 0.01, 0.001)] * 6, model="t", frames_sampled=7)
        assert describe_motion(push)[1] == ["push in"]
        assert pacing_for(0.0, 0.0) == "still" and pacing_for(0.05, 0.0) == "fast"

    def test_summary_mirrors_the_spec_contract(self):
        keys = set(MotionSummary().model_dump())
        assert {"pan", "tilt", "zoom", "roll", "magnitude", "subject_motion", "pacing", "handheld"} <= keys


class TestRealAnalyzer:
    def test_synthetic_sample_clip_is_analysed(self):
        clip = SAMPLES / "clip-01.mp4"
        if not clip.is_file():
            pytest.skip("samples/clip-01.mp4 is not in this checkout")
        summary = OpticalFlowAnalyzer().analyze(str(clip), sample_fps=4.0, max_frames=12)
        assert summary.analyzed is True
        assert summary.frames_sampled >= 2
        assert summary.model == "opencv-farneback"
        assert 0.0 <= summary.confidence <= 1.0
        assert summary.pacing in {"still", "slow", "measured", "fast"}

    def test_a_missing_file_is_reported_not_raised(self):
        summary = OpticalFlowAnalyzer().analyze("/nonexistent/clip.mp4")
        assert summary.analyzed is False


def test_fake_motion_answers_by_path_prefix():
    fake = FakeMotion()
    fake.by_path["/videos/handheld"] = MotionSummary(analyzed=True, handheld=True, magnitude=0.02, pacing="fast")
    assert fake.analyze("/videos/handheld/take1.mp4").handheld is True
    assert fake.analyze("/videos/other.mp4").handheld is False
    assert fake.calls[0][0] == "/videos/handheld/take1.mp4"
