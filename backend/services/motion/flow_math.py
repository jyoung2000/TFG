"""Pure maths over dense optical-flow fields.

A flow field is an `(H, W, 2)` array of per-pixel displacements in pixels.
The global camera motion is the least-squares similarity transform that best
explains the field; whatever it leaves over is subject motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.floating]


@dataclass(frozen=True, slots=True)
class GlobalMotion:
    """One frame pair's camera motion, normalised to the frame size.

    `pan`/`tilt` are fractions of the frame width/height per pair (positive =
    content moves right/down, i.e. the camera pans left/tilts up in the
    conventional sense; callers describe it from the content's point of view).
    `zoom` is the divergence (positive = push in), `roll` the curl in radians.
    `magnitude` is the mean flow length as a fraction of the frame diagonal and
    `residual` the mean flow length left after removing the global model.
    """

    pan: float
    tilt: float
    zoom: float
    roll: float
    magnitude: float
    residual: float


def estimate_global_motion(flow: FloatArray) -> GlobalMotion:
    """Fit `v = t + (s-1)·p + ω·⊥p` by least squares over every pixel.

    The fit is a 4-parameter similarity (translation, uniform scale,
    rotation), which is what a camera pan/tilt/zoom/roll produces on a distant
    scene; the residual is everything else (parallax, subjects).
    """
    field = np.asarray(flow, dtype=np.float64)
    if field.ndim != 3 or field.shape[2] != 2 or field.shape[0] < 2 or field.shape[1] < 2:
        return GlobalMotion(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    height, width = int(field.shape[0]), int(field.shape[1])
    ys, xs = np.mgrid[0:height, 0:width]
    px = (xs - (width - 1) / 2.0).ravel()
    py = (ys - (height - 1) / 2.0).ravel()
    vx = field[:, :, 0].ravel()
    vy = field[:, :, 1].ravel()

    # Unknowns: tx, ty, s (scale-1), w (rotation). Rows: vx = tx + s·px − w·py ; vy = ty + s·py + w·px
    n = px.size
    a = np.zeros((2 * n, 4), dtype=np.float64)
    a[:n, 0] = 1.0
    a[:n, 2] = px
    a[:n, 3] = -py
    a[n:, 1] = 1.0
    a[n:, 2] = py
    a[n:, 3] = px
    b = np.concatenate([vx, vy])
    solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    tx, ty, scale, omega = (float(v) for v in solution)

    predicted = a @ solution
    residual_vec = b - predicted
    residual = float(np.hypot(residual_vec[:n], residual_vec[n:]).mean())
    diagonal = float(np.hypot(width, height)) or 1.0
    magnitude = float(np.hypot(vx, vy).mean()) / diagonal
    return GlobalMotion(
        pan=tx / width,
        tilt=ty / height,
        zoom=scale,
        roll=omega,
        magnitude=magnitude,
        residual=residual / diagonal,
    )


def pacing_for(magnitude: float, subject_motion: float) -> str:
    """Coarse pacing words the prompt vocabulary understands."""
    energy = magnitude + subject_motion
    if energy < 0.004:
        return "still"
    if energy < 0.015:
        return "slow"
    if energy < 0.04:
        return "measured"
    return "fast"


def summarise_motions(motions: Sequence[GlobalMotion]) -> dict[str, float]:
    """Aggregate per-pair fits into the shot-level numbers `MotionSummary` carries.

    Dominant components are the mean over pairs (so a pan that reverses cancels
    out, which is what "dominant" means); `jitter` is the high-frequency part —
    the mean absolute difference between consecutive pan/tilt values relative
    to their mean magnitude — so a steady dolly scores low and a handheld
    shake scores high even when the mean motion is small.
    """
    if not motions:
        return {"pan": 0.0, "tilt": 0.0, "zoom": 0.0, "roll": 0.0, "magnitude": 0.0, "subject_motion": 0.0, "jitter": 0.0}
    pans = np.array([m.pan for m in motions], dtype=np.float64)
    tilts = np.array([m.tilt for m in motions], dtype=np.float64)
    zooms = np.array([m.zoom for m in motions], dtype=np.float64)
    rolls = np.array([m.roll for m in motions], dtype=np.float64)
    magnitudes = np.array([m.magnitude for m in motions], dtype=np.float64)
    residuals = np.array([m.residual for m in motions], dtype=np.float64)
    jitter = 0.0
    if len(motions) > 1:
        steps = np.abs(np.diff(pans)) + np.abs(np.diff(tilts))
        level = float(np.abs(pans).mean() + np.abs(tilts).mean()) + 1e-4
        jitter = float(steps.mean()) / level
    return {
        "pan": float(pans.mean()),
        "tilt": float(tilts.mean()),
        "zoom": float(zooms.mean()),
        "roll": float(rolls.mean()),
        "magnitude": float(magnitudes.mean()),
        "subject_motion": float(residuals.mean()),
        "jitter": min(4.0, jitter),
    }
