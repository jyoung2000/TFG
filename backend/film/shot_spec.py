"""ShotSpec — the one contract between analysis and generation.

Every analyser (deterministic stats, Florence, CLIP, depth, optical flow, the
optional VLM, the user's edits) writes into this structure; every compiler
reads from it. `frontend/types/shotspec.ts` mirrors it field for field
(snake_case, no mapping layer).

Design borrowed from macchant/imex-next (MIT) — one canonical schema with a
confidence per field and the stages that produced it — and extended for
video and 3D: `motion`, `layout3d`, per-section `provenance` and `locks`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SPEC_VERSION = 1

SourceKind = Literal["image", "video_shot"]
Provenance = Literal["measured", "florence", "clip", "depth", "flow", "vlm", "user", ""]
SECTIONS: tuple[str, ...] = ("measured", "subjects", "scene", "camera", "lighting", "style", "motion", "layout3d", "narrative")

#: Precedence when two sources disagree on a *physical* property (lower wins).
#: Measured beats a detector, a detector beats a tagger, a tagger beats the VLM.
PROVENANCE_RANK: dict[str, int] = {"measured": 0, "depth": 0, "flow": 0, "florence": 1, "clip": 2, "vlm": 3, "user": -1, "": 9}


class SpecSource(BaseModel):
    kind: SourceKind = "image"
    #: Content hash of the file (or of the shot's representative frame).
    hash: str = ""
    path: str = ""
    width: int = 0
    height: int = 0
    aspect: str = ""
    fps: float | None = None
    start: float | None = None
    end: float | None = None


class PaletteEntry(BaseModel):
    hex: str
    share: float


class SpecMeasured(BaseModel):
    palette: list[PaletteEntry] = Field(default_factory=list[PaletteEntry])
    luminance: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    edge_density: float = 0.0
    sharpness: float = 0.0
    exif: dict[str, str] = Field(default_factory=dict[str, str])


class SpecSubject(BaseModel):
    label: str
    #: Normalised [x, y, w, h] in 0..1.
    bbox: list[float] = Field(default_factory=list[float])
    depth_median: float | None = None
    count: int = 1
    attributes: list[str] = Field(default_factory=list[str])


class SpecScene(BaseModel):
    location: str = ""
    environment: str = ""
    time_of_day: str = ""
    weather: str = ""
    fg: str = ""
    mg: str = ""
    bg: str = ""


class SpecCamera(BaseModel):
    shot_size: str = ""
    angle: str = ""
    height: str = ""
    fov_deg: float | None = None
    focal_mm: float | None = None
    lens_estimate: str = ""
    aperture: str = ""
    dof: str = ""
    focus: str = ""
    move: str = ""
    #: 0..1
    move_intensity: float = 0.0
    handheld: bool = False
    roll: float = 0.0


class SpecLighting(BaseModel):
    key_direction: str = ""
    quality: str = ""
    color_temp: str = ""
    mood: str = ""


class TagTerm(BaseModel):
    term: str
    score: float = 0.0


class SpecStyle(BaseModel):
    tags: list[TagTerm] = Field(default_factory=list[TagTerm])
    medium: str = ""
    artists: list[str] = Field(default_factory=list[str])
    negatives: list[str] = Field(default_factory=list[str])


class SpecMotionDominant(BaseModel):
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    roll: float = 0.0


class SpecMotion(BaseModel):
    dominant: SpecMotionDominant = Field(default_factory=SpecMotionDominant)
    magnitude: float = 0.0
    subject_motion: float = 0.0
    pacing: str = ""


class SpecLayoutCamera(BaseModel):
    pos: list[float] = Field(default_factory=lambda: [0.0, 1.6, 4.0])
    rot: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    fov: float = 40.0


class SpecLayoutObject(BaseModel):
    id: str
    kind: str = "figure"
    pos: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rot: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    pose: str = ""
    label: str = ""


class SpecLayout3D(BaseModel):
    camera: SpecLayoutCamera = Field(default_factory=SpecLayoutCamera)
    objects: list[SpecLayoutObject] = Field(default_factory=list[SpecLayoutObject])
    depth_map_path: str = ""


class SpecNarrative(BaseModel):
    what_happens: str = ""
    purpose: str = ""
    beat: str = ""


class ShotSpec(BaseModel):
    version: int = SPEC_VERSION
    source: SpecSource = Field(default_factory=SpecSource)
    measured: SpecMeasured = Field(default_factory=SpecMeasured)
    subjects: list[SpecSubject] = Field(default_factory=list[SpecSubject])
    scene: SpecScene = Field(default_factory=SpecScene)
    camera: SpecCamera = Field(default_factory=SpecCamera)
    lighting: SpecLighting = Field(default_factory=SpecLighting)
    style: SpecStyle = Field(default_factory=SpecStyle)
    motion: SpecMotion = Field(default_factory=SpecMotion)
    layout3d: SpecLayout3D = Field(default_factory=SpecLayout3D)
    narrative: SpecNarrative = Field(default_factory=SpecNarrative)
    #: Per section, 0..1.
    confidence: dict[str, float] = Field(default_factory=dict[str, float])
    #: Per section: which stage last wrote it.
    provenance: dict[str, str] = Field(default_factory=dict[str, str])
    #: Per section: True when the user pinned it — no stage may overwrite it.
    locks: dict[str, bool] = Field(default_factory=dict[str, bool])

    # ---- helpers ------------------------------------------------------------

    def is_locked(self, section: str) -> bool:
        return bool(self.locks.get(section, False))

    def set_section(self, section: str, provenance: Provenance, confidence: float) -> None:
        self.provenance[section] = provenance
        self.confidence[section] = round(max(0.0, min(1.0, confidence)), 3)

    def subject_labels(self) -> list[str]:
        return [f"{s.count} {s.label}" if s.count > 1 else s.label for s in self.subjects if s.label]

    def top_tags(self, limit: int = 8) -> list[str]:
        return [t.term for t in sorted(self.style.tags, key=lambda t: -t.score)[:limit]]

    def attribute_keys(self) -> list[str]:
        """Stable `section.field=value` keys the knowledge engine learns on.
        Only categorical, low-cardinality attributes — never free text."""
        keys: list[str] = []
        for field_name in ("shot_size", "angle", "height", "move", "dof", "lens_estimate"):
            value = getattr(self.camera, field_name)
            if value:
                keys.append(f"camera.{field_name}={_slug(str(value))}")
        for field_name in ("quality", "key_direction", "color_temp", "mood"):
            value = getattr(self.lighting, field_name)
            if value:
                keys.append(f"lighting.{field_name}={_slug(str(value))}")
        if self.style.medium:
            keys.append(f"style.medium={_slug(self.style.medium)}")
        for term in self.top_tags(4):
            keys.append(f"style.tag={_slug(term)}")
        if self.scene.time_of_day:
            keys.append(f"scene.time_of_day={_slug(self.scene.time_of_day)}")
        if self.source.aspect:
            keys.append(f"source.aspect={self.source.aspect}")
        if self.motion.pacing:
            keys.append(f"motion.pacing={_slug(self.motion.pacing)}")
        count = sum(s.count for s in self.subjects)
        if count:
            keys.append(f"subjects.count={min(count, 5)}")
        return sorted(set(keys))

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _slug(value: str) -> str:
    return "-".join(value.strip().lower().replace("_", " ").split())[:40]


def empty_spec(kind: SourceKind = "image") -> ShotSpec:
    spec = ShotSpec()
    spec.source.kind = kind
    return spec
