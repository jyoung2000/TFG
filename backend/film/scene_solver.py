"""Image evidence → 3D layout → composer scene, and back (phase 6).

Pure geometry, no three.js, no models. Conventions match the composer:
metres, +Y up, the camera looks down −Z from `camera.pos`, figures stand on
y = 0 and face +Z (toward a front camera) when their yaw is 0. Camera FOV in
`SpecLayout3D.camera.fov` is the *vertical* FOV in degrees (three.js), while
`SpecCamera.fov_deg` is the horizontal lens FOV; `vertical_fov()` converts.

Depth medians from Depth-Anything are relative (1 = near, 0 = far), so a
person's metric distance comes from their box height when the box is not
clipped by the frame; depth only orders the others. Every placement is done
along the pixel ray of the box, so reprojecting the layout returns the box
within tolerance — that round trip is the test.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from film.film_models import (
    CameraMove,
    CompositionKeyframe,
    CompositionObject,
    CompositionScene,
    CompositionTransform,
    ShotFraming,
)
from film.shot_spec import ShotSpec, SpecLayout3D, SpecLayoutCamera, SpecLayoutObject, SpecMotion, SpecSubject
from film.shot_vocabulary import describe_camera

#: Relative depth → metres when nothing metric is known (documented heuristic).
NEAR_M = 1.2
FAR_M = 14.0
#: Reference heights per label (metres); anything else is a metre-tall prop.
LABEL_HEIGHTS: dict[str, float] = {
    "person": 1.7, "man": 1.75, "woman": 1.65, "child": 1.2, "boy": 1.3, "girl": 1.3, "people": 1.7,
    "dog": 0.6, "cat": 0.3, "horse": 1.6, "bird": 0.25,
    "car": 1.5, "truck": 2.5, "bus": 3.2, "motorcycle": 1.2, "bicycle": 1.1, "boat": 1.5,
    "chair": 0.9, "table": 0.75, "couch": 0.85, "bed": 0.6, "door": 2.0, "window": 1.2, "tree": 4.0, "building": 8.0,
}
PERSON_LABELS = frozenset({"person", "man", "woman", "child", "boy", "girl", "people", "figure", "human"})
#: Figure body type from real height (body type from bbox height, per the plan).
CHILD_MAX_M = 1.35
FEMALE_MAX_M = 1.72
FIGURE_WIDTH_M = 0.5
FIGURE_REF_HEIGHT_M = 1.7
DEFAULT_VFOV_DEG = 40.0
#: Reprojection tolerance the round-trip tests assert (fraction of the frame).
TOLERANCE = 0.05


def vertical_fov(hfov_deg: float, aspect: float) -> float:
    """Horizontal lens FOV → vertical camera FOV, both in degrees."""
    if hfov_deg <= 0 or hfov_deg >= 179 or aspect <= 0:
        return DEFAULT_VFOV_DEG
    return math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) / aspect))


def horizontal_fov(vfov_deg: float, aspect: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(vfov_deg) / 2) * aspect))


def aspect_of(spec: ShotSpec) -> float:
    if spec.source.width and spec.source.height:
        return spec.source.width / spec.source.height
    text = spec.source.aspect
    if ":" in text:
        try:
            a, b = text.split(":")
            return float(a) / float(b)
        except ValueError:
            pass
    return 16 / 9


@dataclass(frozen=True)
class Camera:
    """Camera at `pos`, pitched by `pitch` radians (positive looks up), no yaw/roll."""

    pos: tuple[float, float, float]
    pitch: float
    vfov_deg: float
    aspect: float

    @property
    def tan_v(self) -> float:
        return math.tan(math.radians(self.vfov_deg) / 2)

    @property
    def tan_h(self) -> float:
        return self.tan_v * self.aspect

    def ray(self, nx: float, ny: float) -> tuple[float, float, float]:
        """World-space unit direction through normalised image coords (0..1, y down)."""
        cx = (nx - 0.5) * 2 * self.tan_h
        cy = (0.5 - ny) * 2 * self.tan_v
        cz = -1.0
        # Pitch about X: positive pitch looks up.
        c, s = math.cos(self.pitch), math.sin(self.pitch)
        wx, wy, wz = cx, cy * c - cz * s, cy * s + cz * c
        norm = math.sqrt(wx * wx + wy * wy + wz * wz) or 1.0
        return wx / norm, wy / norm, wz / norm

    def project(self, point: tuple[float, float, float]) -> tuple[float, float] | None:
        """World point → normalised image coords; None when behind the camera."""
        dx, dy, dz = point[0] - self.pos[0], point[1] - self.pos[1], point[2] - self.pos[2]
        c, s = math.cos(-self.pitch), math.sin(-self.pitch)
        cx, cy, cz = dx, dy * c - dz * s, dy * s + dz * c
        if cz >= -1e-6:
            return None
        depth = -cz
        return 0.5 + (cx / depth) / (2 * self.tan_h), 0.5 - (cy / depth) / (2 * self.tan_v)

    def depth_along_axis(self, point: tuple[float, float, float]) -> float:
        dy, dz = point[1] - self.pos[1], point[2] - self.pos[2]
        c, s = math.cos(-self.pitch), math.sin(-self.pitch)
        return -(dy * s + dz * c)


def reference_height(label: str) -> float:
    key = label.strip().lower()
    for name, height in LABEL_HEIGHTS.items():
        if key == name or key.endswith(" " + name) or key.startswith(name + " "):
            return height
    return 1.0


def is_person(label: str) -> bool:
    key = label.strip().lower()
    return any(key == p or key.endswith(" " + p) for p in PERSON_LABELS)


def figure_variant_for(height_m: float) -> str:
    if height_m < CHILD_MAX_M:
        return "child"
    if height_m < FEMALE_MAX_M:
        return "female"
    return "male"


def _distance_for(subject: SpecSubject, camera: Camera) -> float:
    """Metres along the camera axis. Height-based when the box is whole,
    else relative depth; clamped to the usable range."""
    _, y, _, h = subject.bbox
    clipped = y < 0.02 or y + h > 0.98 or h <= 0.02
    if not clipped:
        distance = reference_height(subject.label) / (2 * h * camera.tan_v)
    elif subject.depth_median is not None:
        distance = NEAR_M + (1.0 - max(0.0, min(1.0, subject.depth_median))) * (FAR_M - NEAR_M)
    else:
        distance = reference_height(subject.label) / (2 * max(h, 0.05) * camera.tan_v)
    return max(0.6, min(60.0, distance))


def _solve_camera(subjects: list[SpecSubject], vfov_deg: float, aspect: float, hint_height: str = "") -> Camera:
    """Camera height + pitch so that every whole figure's feet land on y = 0.

    A person's feet ray must reach the ground at that person's distance; with
    the pitch fixed that gives one camera height per figure, so the pitch is
    searched (±30°) for the least disagreement, regularised toward level. A
    single figure is therefore level unless the spec says high/low angle.
    """
    figures = [s for s in subjects if len(s.bbox) == 4 and is_person(s.label) and not (s.bbox[1] + s.bbox[3] > 0.98)]
    preferred = {"high": -0.2, "bird": -0.6, "low": 0.15, "worm": 0.3}.get(hint_height, 0.0)
    if not figures:
        pitch = preferred
        height = 1.6 if hint_height in ("", "eye") else {"high": 3.0, "bird": 8.0, "low": 0.6, "worm": 0.2}.get(hint_height, 1.6)
        return Camera(pos=(0.0, height, 0.0), pitch=pitch, vfov_deg=vfov_deg, aspect=aspect)

    def implied_heights(pitch: float) -> list[float]:
        probe = Camera(pos=(0.0, 0.0, 0.0), pitch=pitch, vfov_deg=vfov_deg, aspect=aspect)
        out: list[float] = []
        for s in figures:
            x, y, w, h = s.bbox
            distance = _distance_for(s, probe)
            rx, ry, rz = probe.ray(x + w / 2, y + h)
            # Point along the feet ray at axis depth `distance`: scale so the axis depth matches.
            axis = probe.depth_along_axis((rx, ry, rz))
            scale = distance / max(axis, 1e-4)
            out.append(-ry * scale)
        return out

    best_pitch, best_cost = preferred, float("inf")
    steps = 121
    for i in range(steps):
        pitch = math.radians(-30 + 60 * i / (steps - 1))
        heights = implied_heights(pitch)
        mean = sum(heights) / len(heights)
        spread = sum((h - mean) ** 2 for h in heights) / len(heights)
        # A camera below the floor is impossible: feet above the horizon mean
        # the camera looks down, so an implausibly low height is penalised
        # hard enough to tilt the search instead of clamping later.
        cost = spread + 0.02 * (pitch - preferred) ** 2 + 50.0 * max(0.0, 0.3 - mean) ** 2
        if cost < best_cost:
            best_cost, best_pitch = cost, pitch
    heights = implied_heights(best_pitch)
    cam_y = max(0.2, sum(heights) / len(heights))
    return Camera(pos=(0.0, cam_y, 0.0), pitch=best_pitch, vfov_deg=vfov_deg, aspect=aspect)


def layout_from_spec(spec: ShotSpec, *, vfov_deg: float | None = None) -> SpecLayout3D:
    """Subjects × depth × FOV → world positions, a solved camera, figure sizes."""
    aspect = aspect_of(spec)
    if vfov_deg is None:
        if spec.camera.fov_deg:
            vfov_deg = vertical_fov(spec.camera.fov_deg, aspect)
        elif spec.camera.focal_mm:
            vfov_deg = vertical_fov(math.degrees(2 * math.atan(36.0 / (2 * spec.camera.focal_mm))), aspect)
        else:
            vfov_deg = DEFAULT_VFOV_DEG
    subjects = [s for s in spec.subjects if len(s.bbox) == 4 and s.bbox[2] > 0 and s.bbox[3] > 0]
    camera = _solve_camera(subjects, vfov_deg, aspect, spec.camera.height)
    objects: list[SpecLayoutObject] = []
    for index, subject in enumerate(subjects):
        x, y, w, h = subject.bbox
        person = is_person(subject.label)
        # Grounded when the box's bottom ray reaches the floor in front of the
        # camera: the object then stands exactly where that ray lands, so its
        # reprojection is exact by construction. Otherwise (a window, a bird,
        # a box cut by the frame edge) it floats at the depth-derived distance.
        bx, by, bz = camera.ray(x + w / 2, y + h)
        grounded = by < -1e-4 and (y + h) <= 0.98
        ax, ay, az, distance = 0.0, 0.0, 0.0, 0.0
        if grounded:
            along = camera.pos[1] / -by
            ax, ay, az = camera.pos[0] + bx * along, 0.0, camera.pos[2] + bz * along
            distance = camera.depth_along_axis((ax, ay, az))
            if distance < 0.4:
                grounded = False
        if not grounded:
            distance = _distance_for(subject, camera)
            rx, ry, rz = camera.ray(x + w / 2, y + h / 2)
            axis = camera.depth_along_axis((camera.pos[0] + rx, camera.pos[1] + ry, camera.pos[2] + rz))
            scale = distance / max(axis, 1e-4)
            ax, ay, az = camera.pos[0] + rx * scale, camera.pos[1] + ry * scale, camera.pos[2] + rz * scale
        frame_height_m = 2 * distance * camera.tan_v
        frame_width_m = frame_height_m * aspect
        height_m = max(0.1, h * frame_height_m)
        width_m = max(0.1, w * frame_width_m)
        if not grounded:
            ay = max(0.0, ay - height_m / 2)
        if person:
            unit = height_m / FIGURE_REF_HEIGHT_M
            objects.append(
                SpecLayoutObject(
                    id=f"fig-{index + 1}",
                    kind="figure",
                    pos=[round(ax, 3), round(ay, 3), round(az, 3)],
                    rot=[0.0, 0.0, 0.0],
                    scale=[round(unit, 4)] * 3,
                    pose="stand",
                    label=subject.label,
                )
            )
        else:
            objects.append(
                SpecLayoutObject(
                    id=f"prop-{index + 1}",
                    kind="prop",
                    pos=[round(ax, 3), round(ay, 3), round(az, 3)],
                    rot=[0.0, 0.0, 0.0],
                    scale=[round(width_m, 3), round(height_m, 3), round(min(width_m, height_m), 3)],
                    pose="",
                    label=subject.label,
                )
            )
    layout = SpecLayout3D(
        camera=SpecLayoutCamera(pos=[0.0, round(camera.pos[1], 3), 0.0], rot=[round(camera.pitch, 4), 0.0, 0.0], fov=round(vfov_deg, 2)),
        objects=objects,
        depth_map_path=spec.layout3d.depth_map_path,
    )
    return layout


def camera_from_layout(layout: SpecLayout3D, aspect: float) -> Camera:
    pos = list(layout.camera.pos) + [0.0] * (3 - len(layout.camera.pos))
    rot = list(layout.camera.rot) + [0.0] * (3 - len(layout.camera.rot))
    return Camera(pos=(pos[0], pos[1], pos[2]), pitch=rot[0], vfov_deg=layout.camera.fov or DEFAULT_VFOV_DEG, aspect=aspect)


def reproject_layout(layout: SpecLayout3D, aspect: float) -> dict[str, list[float]]:
    """Every object's box as the camera would see it: `{id: [x, y, w, h]}`.

    Figures are FIGURE_WIDTH_M × 1.7 m at their scale; props use their scale as
    metres. Objects behind the camera are omitted.
    """
    camera = camera_from_layout(layout, aspect)
    boxes: dict[str, list[float]] = {}
    for obj in layout.objects:
        pos = list(obj.pos) + [0.0] * (3 - len(obj.pos))
        scale = list(obj.scale) + [1.0] * (3 - len(obj.scale))
        if obj.kind == "figure":
            height_m, width_m = FIGURE_REF_HEIGHT_M * scale[1], FIGURE_WIDTH_M * scale[0]
            bottom, top = pos[1], pos[1] + height_m
        else:
            height_m, width_m = scale[1], scale[0]
            bottom, top = pos[1], pos[1] + height_m
        foot = camera.project((pos[0], bottom, pos[2]))
        head = camera.project((pos[0], top, pos[2]))
        if foot is None or head is None:
            continue
        depth = camera.depth_along_axis((pos[0], (top + bottom) / 2, pos[2]))
        w = width_m / (2 * depth * camera.tan_h) if depth > 0 else 0.0
        cx = (foot[0] + head[0]) / 2
        boxes[obj.id] = [round(cx - w / 2, 4), round(head[1], 4), round(w, 4), round(foot[1] - head[1], 4)]
    return boxes


def reprojection_error(spec: ShotSpec, layout: SpecLayout3D) -> float:
    """Largest centre/top/bottom deviation between the spec's boxes and the
    layout's reprojection (fraction of the frame)."""
    boxes = reproject_layout(layout, aspect_of(spec))
    subjects = [s for s in spec.subjects if len(s.bbox) == 4 and s.bbox[2] > 0 and s.bbox[3] > 0]
    worst = 0.0
    for index, subject in enumerate(subjects):
        key = f"fig-{index + 1}" if is_person(subject.label) else f"prop-{index + 1}"
        box = boxes.get(key)
        if box is None:
            return 1.0
        x, y, w, h = subject.bbox
        bx, by, bw, bh = box
        worst = max(worst, abs((x + w / 2) - (bx + bw / 2)), abs(y - by), abs((y + h) - (by + bh)))
    return round(worst, 4)


# ---- composer scene ---------------------------------------------------------------

_MOVE_FROM_WORDS: dict[str, CameraMove] = {
    "push_in": "push_in", "pull_out": "pull_out", "pan_left": "pan_left", "pan_right": "pan_right",
    "tilt_up": "tilt_up", "tilt_down": "tilt_down", "dolly_left": "dolly_left", "dolly_right": "dolly_right",
    "orbit": "orbit", "follow": "follow", "static": "static", "handheld": "static",
}


def camera_move_for(spec: ShotSpec) -> CameraMove:
    move = (spec.camera.move or "").strip().lower().replace(" ", "_")
    return _MOVE_FROM_WORDS.get(move, "static")


def _euler_for(pitch: float, yaw: float, roll: float) -> tuple[float, float, float]:
    return (round(pitch, 5), round(yaw, 5), round(roll, 5))


def camera_keyframes(layout: SpecLayout3D, move: CameraMove, duration: float, intensity: float = 1.0) -> list[CompositionKeyframe]:
    """Start/end keyframes for a camera move, sized by the camera–subject distance
    (twin of `sceneFromAnalysis.ts`)."""
    pos = list(layout.camera.pos) + [0.0] * (3 - len(layout.camera.pos))
    rot = list(layout.camera.rot) + [0.0] * (3 - len(layout.camera.rot))
    subject = next((o for o in layout.objects if o.kind == "figure"), layout.objects[0] if layout.objects else None)
    distance = 4.0
    if subject is not None:
        spos = list(subject.pos) + [0.0] * (3 - len(subject.pos))
        distance = max(0.5, math.sqrt((spos[0] - pos[0]) ** 2 + (spos[2] - pos[2]) ** 2))
    travel = distance * 0.25 * max(0.1, min(3.0, intensity))
    angle = math.radians(12) * max(0.1, min(3.0, intensity))
    start = CompositionKeyframe(id="kf-start", time=0.0, transform=CompositionTransform(position=(pos[0], pos[1], pos[2]), rotation=_euler_for(rot[0], rot[1], rot[2])), fov=layout.camera.fov)
    if move == "static":
        return [start]
    end_pos = [pos[0], pos[1], pos[2]]
    end_rot = [rot[0], rot[1], rot[2]]
    if move == "push_in" or move == "follow":
        end_pos[2] -= travel
    elif move == "pull_out":
        end_pos[2] += travel
    elif move == "pan_left":
        end_rot[1] += angle
    elif move == "pan_right":
        end_rot[1] -= angle
    elif move == "tilt_up":
        end_rot[0] += angle
    elif move == "tilt_down":
        end_rot[0] -= angle
    elif move == "dolly_left":
        end_pos[0] -= travel
    elif move == "dolly_right":
        end_pos[0] += travel
    elif move == "orbit":
        spos = list(subject.pos) + [0.0] * (3 - len(subject.pos)) if subject is not None else [0.0, 0.0, pos[2] - distance]
        theta = math.radians(30) * max(0.1, min(3.0, intensity))
        dx, dz = pos[0] - spos[0], pos[2] - spos[2]
        end_pos[0] = spos[0] + dx * math.cos(theta) - dz * math.sin(theta)
        end_pos[2] = spos[2] + dx * math.sin(theta) + dz * math.cos(theta)
        end_rot[1] = rot[1] + theta
    end = CompositionKeyframe(
        id="kf-end",
        time=max(0.1, duration),
        transform=CompositionTransform(position=(round(end_pos[0], 4), round(end_pos[1], 4), round(end_pos[2], 4)), rotation=_euler_for(end_rot[0], end_rot[1], end_rot[2])),
        fov=layout.camera.fov,
    )
    return [start, end]


def composer_scene_from_layout(layout: SpecLayout3D, *, duration: float, move: CameraMove = "static", motion: SpecMotion | None = None, framing: ShotFraming | None = None) -> CompositionScene:
    """A `CompositionScene` the Shot Composer opens pre-seeded from the layout."""
    objects: list[CompositionObject] = []
    for obj in layout.objects:
        pos = list(obj.pos) + [0.0] * (3 - len(obj.pos))
        rot = list(obj.rot) + [0.0] * (3 - len(obj.rot))
        scale = list(obj.scale) + [1.0] * (3 - len(obj.scale))
        if obj.kind == "figure":
            height_m = FIGURE_REF_HEIGHT_M * scale[1]
            objects.append(
                CompositionObject(
                    id=obj.id,
                    name=(obj.label or "Figure").title(),
                    type="figure",
                    transform=CompositionTransform(position=(pos[0], pos[1], pos[2]), rotation=(rot[0], rot[1], rot[2]), scale=(scale[1], scale[1], scale[1])),
                    figure_variant=figure_variant_for(height_m),  # type: ignore[arg-type]
                )
            )
        else:
            objects.append(
                CompositionObject(
                    id=obj.id,
                    name=(obj.label or "Prop").title(),
                    type="cube",
                    transform=CompositionTransform(position=(pos[0], pos[1], pos[2]), rotation=(rot[0], rot[1], rot[2]), scale=(scale[0], scale[1], scale[2])),
                    color="#8a93a6",
                )
            )
    intensity = 1.0
    if motion is not None and motion.magnitude:
        intensity = max(0.3, min(2.0, motion.magnitude / 0.012))
    keyframes = camera_keyframes(layout, move, duration, intensity)
    pos = list(layout.camera.pos) + [0.0] * (3 - len(layout.camera.pos))
    rot = list(layout.camera.rot) + [0.0] * (3 - len(layout.camera.rot))
    camera = CompositionObject(
        id="shot-camera",
        name="Shot Camera",
        type="camera",
        transform=CompositionTransform(position=(pos[0], pos[1], pos[2]), rotation=(rot[0], rot[1], rot[2])),
        color="#ffffff",
        keyframes=keyframes,
        fov=layout.camera.fov,
    )
    words = describe_camera(layout)
    frame = framing.model_copy() if framing is not None else ShotFraming()
    if words.get("shot_size"):
        frame.shot_size = words["shot_size"]  # type: ignore[assignment]
    if words.get("angle"):
        frame.camera_angle = words["angle"]  # type: ignore[assignment]
    if words.get("height"):
        frame.camera_elevation = words["height"]  # type: ignore[assignment]
    frame.fov_deg = layout.camera.fov
    frame.camera_mode = "manual"
    return CompositionScene(objects=objects, camera=camera, framing=frame, camera_move=move, duration_seconds=max(0.5, duration))


def layout_from_composition(composition: CompositionScene, base: SpecLayout3D | None = None) -> SpecLayout3D:
    """The composer's scene back into `spec.layout3d` (round trip)."""
    objects: list[SpecLayoutObject] = []
    for obj in composition.objects:
        if obj.type == "camera" or not obj.visible:
            continue
        t = obj.transform
        if obj.type == "figure":
            objects.append(SpecLayoutObject(id=obj.id, kind="figure", pos=[round(v, 4) for v in t.position], rot=[round(v, 5) for v in t.rotation], scale=[round(t.scale[1], 4)] * 3, pose="stand", label=obj.name.lower()))
        else:
            objects.append(SpecLayoutObject(id=obj.id, kind="prop", pos=[round(v, 4) for v in t.position], rot=[round(v, 5) for v in t.rotation], scale=[round(v, 4) for v in t.scale], label=obj.name.lower()))
    camera = SpecLayoutCamera()
    if composition.camera is not None:
        camera = SpecLayoutCamera(pos=[round(v, 4) for v in composition.camera.transform.position], rot=[round(v, 5) for v in composition.camera.transform.rotation], fov=composition.camera.fov or composition.framing.fov_deg or DEFAULT_VFOV_DEG)
    return SpecLayout3D(camera=camera, objects=objects, depth_map_path=base.depth_map_path if base is not None else "")


# ---- thumbnail ------------------------------------------------------------------------

def blockout_svg(layout: SpecLayout3D, *, width: int = 320, height: int = 180, title: str = "") -> str:
    """A deterministic isometric blockout of the layout: grid, figures, props,
    the camera wedge. Used as the storyboard card thumbnail before any render."""
    cos30, sin30 = math.cos(math.radians(30)), 0.5
    points: list[tuple[float, float]] = []

    def iso(x: float, y: float, z: float) -> tuple[float, float]:
        return (x - z) * cos30, (x + z) * sin30 - y

    cam = list(layout.camera.pos) + [0.0] * (3 - len(layout.camera.pos))
    items: list[tuple[float, float, float, float, float, str, str]] = []  # x,y,z,h,w,kind,label
    for obj in layout.objects:
        pos = list(obj.pos) + [0.0] * (3 - len(obj.pos))
        scale = list(obj.scale) + [1.0] * (3 - len(obj.scale))
        if obj.kind == "figure":
            items.append((pos[0], pos[1], pos[2], FIGURE_REF_HEIGHT_M * scale[1], FIGURE_WIDTH_M * scale[0], "figure", obj.label))
        else:
            items.append((pos[0], pos[1], pos[2], scale[1], scale[0], "prop", obj.label))
    for x, y, z, h, w, _, _ in items:
        points.append(iso(x, y, z))
        points.append(iso(x, y + h, z))
    points.append(iso(cam[0], cam[1], cam[2]))
    points.append(iso(cam[0], 0.0, cam[2]))
    for gx in (-4, 4):
        for gz in (-8, 4):
            points.append(iso(gx, 0.0, gz))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max(max_x - min_x, 1e-3), max(max_y - min_y, 1e-3)
    scale = min((width - 24) / span_x, (height - 24) / span_y)
    ox, oy = 12 - min_x * scale + ((width - 24) - span_x * scale) / 2, 12 - min_y * scale + ((height - 24) - span_y * scale) / 2

    def px(p: tuple[float, float]) -> tuple[float, float]:
        return round(ox + p[0] * scale, 1), round(oy + p[1] * scale, 1)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="3D blockout{(": " + title) if title else ""}">',
             f'<rect width="{width}" height="{height}" fill="#16181d"/>']
    for gx in range(-4, 5, 2):
        a, b = px(iso(gx, 0, -8)), px(iso(gx, 0, 4))
        parts.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#2a2e38" stroke-width="1"/>')
    for gz in range(-8, 5, 2):
        a, b = px(iso(-4, 0, gz)), px(iso(4, 0, gz))
        parts.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#2a2e38" stroke-width="1"/>')
    # Camera wedge: from the camera toward −Z.
    c0 = px(iso(cam[0], cam[1], cam[2]))
    half = math.tan(math.radians((layout.camera.fov or DEFAULT_VFOV_DEG) / 2)) * 3 * 1.6
    l, r = px(iso(cam[0] - half, cam[1], cam[2] - 3)), px(iso(cam[0] + half, cam[1], cam[2] - 3))
    parts.append(f'<polygon points="{c0[0]},{c0[1]} {l[0]},{l[1]} {r[0]},{r[1]}" fill="#8b5cf6" fill-opacity="0.18" stroke="#8b5cf6" stroke-width="1"/>')
    parts.append(f'<circle cx="{c0[0]}" cy="{c0[1]}" r="3" fill="#8b5cf6"/>')
    for x, y, z, h, w, kind, label in sorted(items, key=lambda i: -(i[0] + i[2])):
        foot, head = px(iso(x, y, z)), px(iso(x, y + h, z))
        width_px = max(3.0, w * scale * cos30)
        if kind == "figure":
            body_h = max(4.0, (foot[1] - head[1]) * 0.72)
            parts.append(f'<rect x="{round(foot[0] - width_px / 2, 1)}" y="{round(foot[1] - body_h, 1)}" width="{round(width_px, 1)}" height="{round(body_h, 1)}" rx="{round(width_px / 2, 1)}" fill="#c9a97a"/>')
            parts.append(f'<circle cx="{head[0]}" cy="{round(head[1] + (foot[1] - head[1]) * 0.12, 1)}" r="{round(max(2.0, (foot[1] - head[1]) * 0.11), 1)}" fill="#e6c9a0"/>')
        else:
            parts.append(f'<rect x="{round(foot[0] - width_px / 2, 1)}" y="{head[1]}" width="{round(width_px, 1)}" height="{round(max(3.0, foot[1] - head[1]), 1)}" fill="#8a93a6" fill-opacity="0.85"/>')
        if label:
            parts.append(f'<text x="{foot[0]}" y="{round(foot[1] + 11, 1)}" font-size="9" fill="#9ca3af" text-anchor="middle" font-family="sans-serif">{_escape(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
