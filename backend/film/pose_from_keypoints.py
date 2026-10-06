"""2D body keypoints → the composer figure's joint rotations.

A pose detector (DWPose) gives each person's body keypoints in the image.
The composer's mannequin (`frontend/views/film/composer/figure.ts`) is a
joint hierarchy whose limbs hang along -Y from their pivots, faces +Z, and has
its left side on +X. Seen from a camera in front of it, a rotation about a
joint's Z axis swings that limb in the image plane - so the angle each limb
makes in the photo becomes that joint's Z rotation, relative to its parent:

    torso → neck → head, torso → shoulder → elbow, pelvis → hip → knee

which reproduces the silhouette the camera sees (arms out, hands on hips,
legs apart, a leaning torso, a tilted head). Depth - a knee bent toward the
camera - is not in a single image and is left at rest.

Keypoints are normalised [x, y, score] in COCO-WholeBody order (17 body
points, then 6 foot points).
"""

from __future__ import annotations

import math

NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 11, 12, 13, 14, 15, 16

#: Keypoints below this detector score are treated as not visible.
MIN_SCORE = 0.3
#: How far the spine and the neck may lean before it is read as a detector slip.
MAX_TORSO_DEG = 45.0
MAX_NECK_DEG = 35.0
MAX_HEAD_YAW_DEG = 70.0


def _wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def _seen(points: list[list[float]], index: int) -> bool:
    return index < len(points) and len(points[index]) >= 3 and points[index][2] >= MIN_SCORE


def facing_camera(points: list[list[float]]) -> bool | None:
    """True when the person faces the camera (their left shoulder on the image
    right), False when seen from behind, None when the shoulders are missing."""
    if not (_seen(points, L_SHOULDER) and _seen(points, R_SHOULDER)):
        return None
    return points[L_SHOULDER][0] >= points[R_SHOULDER][0]


def joints_from_keypoints(points: list[list[float]], aspect: float) -> dict[str, list[float]]:
    """Joint name → [x, y, z] Euler degrees for the composer figure.

    `aspect` is the image's width / height, so x and y distances compare in
    the same units. A person seen from behind gets their pose mirrored the way
    a figure turned 180° needs it (the caller turns the figure)."""
    front = facing_camera(points)
    # Image vector → the figure's frontal plane: up is -y; the figure's +x is
    # the image right when it faces the camera, the image left from behind.
    side = 1.0 if front is not False else -1.0

    def vector(a: int, b: int) -> tuple[float, float] | None:
        if not (_seen(points, a) and _seen(points, b)):
            return None
        return (side * (points[b][0] - points[a][0]) * aspect, -(points[b][1] - points[a][1]))

    def midpoint_vector(a: tuple[int, int], b: tuple[int, int]) -> tuple[float, float] | None:
        if not all(_seen(points, i) for i in (*a, *b)):
            return None
        ax, ay = (points[a[0]][0] + points[a[1]][0]) / 2, (points[a[0]][1] + points[a[1]][1]) / 2
        bx, by = (points[b[0]][0] + points[b[1]][0]) / 2, (points[b[0]][1] + points[b[1]][1]) / 2
        return (side * (bx - ax) * aspect, -(by - ay))

    def hanging(v: tuple[float, float]) -> float:
        """Z rotation that swings a limb hanging along -Y onto `v`."""
        return math.degrees(math.atan2(v[0], -v[1]))

    def rising(v: tuple[float, float]) -> float:
        """Z rotation that swings a segment pointing along +Y onto `v`."""
        return math.degrees(math.atan2(-v[0], v[1]))

    joints: dict[str, list[float]] = {}

    def put(name: str, z: float, y: float = 0.0) -> None:
        if abs(z) >= 0.5 or abs(y) >= 0.5:
            joints[name] = [0.0, round(y, 1), round(_wrap(z), 1)]

    torso = 0.0
    spine = midpoint_vector((L_HIP, R_HIP), (L_SHOULDER, R_SHOULDER))
    if spine is not None:
        torso = max(-MAX_TORSO_DEG, min(MAX_TORSO_DEG, rising(spine)))
        put("torso", torso)

    for prefix, shoulder, elbow, wrist in (("l", L_SHOULDER, L_ELBOW, L_WRIST), ("r", R_SHOULDER, R_ELBOW, R_WRIST)):
        upper = vector(shoulder, elbow)
        if upper is None:
            continue
        arm = hanging(upper)
        put(f"{prefix}_arm", arm - torso)
        forearm = vector(elbow, wrist)
        if forearm is not None:
            put(f"{prefix}_elbow", hanging(forearm) - arm)

    for prefix, hip, knee, ankle in (("l", L_HIP, L_KNEE, L_ANKLE), ("r", R_HIP, R_KNEE, R_ANKLE)):
        thigh = vector(hip, knee)
        if thigh is None:
            continue
        leg = hanging(thigh)
        put(f"{prefix}_leg", leg)
        shin = vector(knee, ankle)
        if shin is not None:
            put(f"{prefix}_knee", hanging(shin) - leg)

    neck_angle = 0.0
    if _seen(points, NOSE) and _seen(points, L_SHOULDER) and _seen(points, R_SHOULDER):
        mid_x = (points[L_SHOULDER][0] + points[R_SHOULDER][0]) / 2
        mid_y = (points[L_SHOULDER][1] + points[R_SHOULDER][1]) / 2
        neck = (side * (points[NOSE][0] - mid_x) * aspect, -(points[NOSE][1] - mid_y))
        neck_angle = max(-MAX_NECK_DEG, min(MAX_NECK_DEG, rising(neck) - torso))
        put("neck", neck_angle)

    # Head: roll from the eye line, yaw from where the nose sits between the ears.
    roll = 0.0
    eyes = vector(R_EYE, L_EYE)
    if eyes is not None and abs(eyes[0]) > 1e-6:
        roll = math.degrees(math.atan2(eyes[1], eyes[0]))
        roll = max(-MAX_NECK_DEG, min(MAX_NECK_DEG, roll - torso - neck_angle))
    yaw = 0.0
    if _seen(points, NOSE) and _seen(points, L_EAR) and _seen(points, R_EAR):
        span = (points[L_EAR][0] - points[R_EAR][0]) * side
        if abs(span) > 1e-4:
            centre = (points[L_EAR][0] + points[R_EAR][0]) / 2
            offset = side * (points[NOSE][0] - centre) / (abs(span) / 2)
            yaw = math.degrees(math.asin(max(-1.0, min(1.0, offset))))
            yaw = max(-MAX_HEAD_YAW_DEG, min(MAX_HEAD_YAW_DEG, yaw))
    put("head", roll, yaw)
    return joints


def share_inside(points: list[list[float]], box: list[float], margin: float = 0.08) -> float:
    """Fraction of a person's visible keypoints inside `box` (grown by `margin`)."""
    x, y, w, h = box
    seen = [p for p in points[:23] if len(p) >= 3 and p[2] >= MIN_SCORE]
    if not seen:
        return 0.0
    inside = [p for p in seen if x - margin <= p[0] <= x + w + margin and y - margin <= p[1] <= y + h + margin]
    return len(inside) / len(seen)
