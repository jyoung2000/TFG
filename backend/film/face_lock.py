"""Face lock: a render's face re-composed from the character's style-guide face.

Found 2026-10-03 (Raven): a character LoRA on Z-Image Turbo tops out near SFace
0.50 against the photo however it is trained (rank 32, LR 6e-4, a filtered
dataset, 16 render steps and strength 0.8-1.3 all scored 0.44-0.50), while the
style sheet's front face scores 0.85. The LoRA carries pose, body and outfit;
the face is then re-composed by FLUX.2 Klein from the head of the render (the
guide) and the style sheet's head (the person), aligned onto the render by the
five face landmarks, and blended over the face oval only. MEASURED on the same
six renders: 0.499 -> 0.576, every render up, worst 0.360 -> 0.458.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: A head square's side, in face-box sides: the head, the hair line and the neck.
HEAD_SCALE = 2.6
#: A face narrower than this has too few pixels to re-compose.
MIN_FACE_PX = 20

Box = tuple[float, float, float, float]
Points = list[tuple[float, float]]


def head_square(box: Box, width: int, height: int, *, scale: float = HEAD_SCALE) -> tuple[int, int, int] | None:
    """(left, top, side) of a square around a face box (x, y, w, h), centred a
    little below the face and kept inside the image; None for a face too small."""
    x, y, w, h = box
    if w < MIN_FACE_PX or h <= 0:
        return None
    side = int(min(scale * max(w, h), width, height))
    left = int(min(max(0.0, x + w / 2 - side / 2), width - side))
    top = int(min(max(0.0, y + 0.75 * h - side / 2), height - side))
    return left, top, side


def blend_face(image: np.ndarray, head: np.ndarray, head_at: tuple[int, int], head_points: Points, points: Points, box: Box) -> np.ndarray | None:
    """`head` (a re-composed head square placed at `head_at` in `image`) warped
    so its landmarks land on the image's `points`, blended over the face oval
    of `box` with a soft edge. None when the landmarks give no transform."""
    import cv2

    src = np.asarray(head_points, np.float32) + np.asarray(head_at, np.float32)
    dst = np.asarray(points, np.float32)
    found: Any = cv2.estimateAffinePartial2D(src, dst)
    matrix = found[0]
    if matrix is None:
        return None
    height, width = image.shape[:2]
    canvas = np.zeros_like(image)
    left, top = head_at
    side = head.shape[0]
    canvas[top:top + side, left:left + side] = head[: height - top, : width - left]
    warped: Any = cv2.warpAffine(canvas, matrix, (width, height), flags=cv2.INTER_LANCZOS4)
    x, y, w, h = box
    mask = np.zeros((height, width), np.float32)
    cv2.ellipse(mask, (int(x + w / 2), int(y + h * 0.55)), (max(1, int(w * 0.55)), max(1, int(h * 0.62))), 0, 0, 360, 1.0, -1)
    soft: Any = cv2.GaussianBlur(mask, (0, 0), max(2.0, w * 0.07))
    alpha = soft[..., None]
    return (warped * alpha + image.astype(np.float32) * (1 - alpha)).astype(np.uint8)
