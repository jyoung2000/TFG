"""Face lock: a render's face re-composed from the character's style-guide face.

Found 2026-10-03 (Raven): a character LoRA on Z-Image Turbo tops out near SFace
0.50 against the photo however it is trained (rank 32, LR 6e-4, a filtered
dataset, 16 render steps and strength 0.8-1.3 all scored 0.44-0.50), while the
style sheet's front face scores 0.85. The LoRA carries pose, body and outfit;
the face is then re-composed by FLUX.2 Klein from the head of the render (the
guide) and the style sheet's head (the person), aligned onto the render by the
five face landmarks, and blended over the face oval only. MEASURED on the same
six renders: 0.499 -> 0.576, every render up, worst 0.360 -> 0.458.

The style sheet only has a front face (its "profile" view faces the camera),
and FLUX.2 pulls a turned head toward it: in-app a profile preview came back
facing the camera on a side-on body. So the head's pose is measured from the
landmarks (`yaw`): profiles are left alone, turned heads get a prompt that
keeps the angle, and a re-composed head that turned is dropped. MEASURED
(yaw, Raven's views): front ~0, three-quarter +-0.17-0.26, profile +-0.45-0.68;
the identity prompt moved -0.28 -> -0.10, the angle prompt -0.28 -> -0.26.

The outfit (2026-10-04: "The womans outfit and face aren't consistent in the
latest LoRA"): the LoRA alone gave a different jacket and neckline per render.
Before the face pass, FLUX.2 re-composes the whole character from the style
sheet's front view with the render as the scene. MEASURED on six renders: the
sheet's jacket, corset and leggings in all six; medium and full shots (face
0.10-0.17 of the frame) kept face size (x0.96-1.03), place (<= 0.12 face
widths) and head turn (<= 0.02), close-ups (0.40-0.61) were zoomed out to
medium shots (x0.24-0.38). So close-ups and profiles skip the outfit pass, and
a pass that moves the face is dropped. Face match is unchanged by it (0.496 vs
0.500): the face pass that follows is what locks the face.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: A head square's side, in face-box sides: the head, the hair line and the neck.
HEAD_SCALE = 2.6
#: A face narrower than this has too few pixels to re-compose.
MIN_FACE_PX = 20
#: |yaw| above this is a profile: no front face to lock it to.
PROFILE_YAW = 0.4
#: |yaw| up to this is a front view; beyond it the head is turned.
FRONT_YAW = 0.12
#: A re-composed head whose yaw moved more than this changed the pose.
MAX_YAW_SHIFT = 0.12

#: A face this much of the frame's width is a close-up: the outfit pass zooms it out.
CLOSE_UP_FACE = 0.28
#: The outfit pass kept the framing when the face's size stayed within these
#: ratios and its centre within this many face widths.
FRAMING_SIZE = (0.8, 1.25)
FRAMING_SHIFT = 0.35
#: The outfit pass renders near the image's own size: about a megapixel at most,
#: and never under this long edge.
OUTFIT_MAX_PIXELS = 1024 * 1024 * 1.1
OUTFIT_MIN_EDGE = 768

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


def is_close_up(box: Box, width: int) -> bool:
    """Whether the face fills enough of the frame to be a close-up."""
    return width > 0 and box[2] / width >= CLOSE_UP_FACE


def framing_kept(before: Box, after: Box) -> bool:
    """Whether a re-composed image kept the shot: the face about as large, about where it was."""
    if before[2] <= 0 or after[2] <= 0:
        return False
    ratio = after[2] / before[2]
    shift = math.hypot((after[0] + after[2] / 2) - (before[0] + before[2] / 2), (after[1] + after[3] / 2) - (before[1] + before[3] / 2)) / before[2]
    return FRAMING_SIZE[0] <= ratio <= FRAMING_SIZE[1] and shift <= FRAMING_SHIFT


def fit_size(width: int, height: int) -> tuple[int, int]:
    """The size the outfit pass renders at for an image: its own size where the
    model can (multiples of 16, about a megapixel at most), so nothing is
    resized back up and blurred; small images are rendered larger."""
    scale = OUTFIT_MIN_EDGE / max(width, height) if max(width, height) < OUTFIT_MIN_EDGE else 1.0
    area = width * height * scale * scale
    if area > OUTFIT_MAX_PIXELS:
        scale *= math.sqrt(OUTFIT_MAX_PIXELS / area)
    return max(256, int(width * scale) // 16 * 16), max(256, int(height * scale) // 16 * 16)


def yaw(points: Points) -> float:
    """How far the head is turned: the nose tip's offset from the midpoint of
    the eyes, in eye distances (0 = facing the camera; sign = direction)."""
    (rx, ry), (lx, ly), (nx, _) = points[0], points[1], points[2]
    distance = float(np.hypot(lx - rx, ly - ry))
    return (nx - (rx + lx) / 2) / distance if distance > 0 else 0.0


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
    # Only where the re-composed head has pixels: in a close-up the face oval
    # reaches past the head square (QA 2026-10-03: a hard band in the hair).
    covered = np.zeros((height, width), np.float32)
    covered[top:top + side, left:left + side] = 1.0
    valid: Any = cv2.warpAffine(covered, matrix, (width, height), flags=cv2.INTER_NEAREST)
    x, y, w, h = box
    inset = max(1, int(w * 0.08))
    inside: Any = cv2.erode(valid, np.ones((2 * inset + 1, 2 * inset + 1), np.uint8))
    mask = np.zeros((height, width), np.float32)
    cv2.ellipse(mask, (int(x + w / 2), int(y + h * 0.55)), (max(1, int(w * 0.55)), max(1, int(h * 0.62))), 0, 0, 360, 1.0, -1)
    soft: Any = cv2.GaussianBlur(np.asarray(mask * inside, np.float32), (0, 0), max(2.0, w * 0.07))
    alpha = np.asarray(soft, np.float32)[..., None]
    blended = np.asarray(warped, np.float32) * alpha + image.astype(np.float32) * (1 - alpha)
    return blended.astype(np.uint8)
