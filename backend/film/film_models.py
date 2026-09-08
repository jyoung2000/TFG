"""Film project domain models (schema v1).

The film project is a versioned facet of an LTX Desktop project (same id).
Scenes/shots/assets adapt BlueFish's chapter/storyboard/entity concepts; the
shot framing and composition schema adapts Open Media's shot-composer state
(see docs/INTEGRATED_UPSTREAMS.md). Everything here is plain data — behavior
lives in handlers and film_store.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

FILM_SCHEMA_VERSION = 1


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def now_ms() -> int:
    return int(time.time() * 1000)


# ============================================================
# Cinematography vocabulary (adapted from Open Media's shot axes,
# extended with xwide/xcu, POV/dutch, bird/worm per the film UX)
# ============================================================

ShotSize = Literal["xwide", "wide", "full", "medium", "mcu", "closeup", "xcu"]
CameraAngle = Literal[
    "front",
    "threeQuarterLeft",
    "threeQuarterRight",
    "profile",
    "back",
    "ots",
    "pov",
    "dutch",
]
CameraElevation = Literal["eye", "low", "high", "bird", "worm"]
CompositionId = Literal[
    "center",
    "leftThird",
    "rightThird",
    "upperThird",
    "lowerThird",
    "negativeSpace",
    "symmetrical",
    "leadingLines",
]
CameraMove = Literal[
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "dolly_left",
    "dolly_right",
    "orbit",
    "follow",
]

SHOT_SIZE_LABELS: dict[str, str] = {
    "xwide": "Extreme Wide",
    "wide": "Wide",
    "full": "Full",
    "medium": "Medium",
    "mcu": "Medium Close-Up",
    "closeup": "Close-Up",
    "xcu": "Extreme Close-Up",
}
CAMERA_ANGLE_LABELS: dict[str, str] = {
    "front": "Front",
    "threeQuarterLeft": "3/4 Left",
    "threeQuarterRight": "3/4 Right",
    "profile": "Profile",
    "back": "Back",
    "ots": "Over the Shoulder",
    "pov": "Point of View",
    "dutch": "Dutch",
}
CAMERA_ELEVATION_LABELS: dict[str, str] = {
    "eye": "Eye Level",
    "low": "Low",
    "high": "High",
    "bird": "Bird's Eye",
    "worm": "Worm's Eye",
}
COMPOSITION_LABELS: dict[str, str] = {
    "center": "Center",
    "leftThird": "Left Third",
    "rightThird": "Right Third",
    "upperThird": "Upper Third",
    "lowerThird": "Lower Third",
    "negativeSpace": "Negative Space",
    "symmetrical": "Symmetrical",
    "leadingLines": "Leading Lines",
}
CAMERA_MOVE_LABELS: dict[str, str] = {
    "static": "Static",
    "push_in": "Push In",
    "pull_out": "Pull Out",
    "pan_left": "Pan Left",
    "pan_right": "Pan Right",
    "tilt_up": "Tilt Up",
    "tilt_down": "Tilt Down",
    "dolly_left": "Truck Left",
    "dolly_right": "Truck Right",
    "orbit": "Orbit",
    "follow": "Follow",
}


# ============================================================
# Assets (adapted from BlueFish's unified entity model)
# ============================================================

FilmAssetKind = Literal["character", "location", "prop", "style"]


class FilmAsset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asset"))
    kind: FilmAssetKind
    name: str
    description: str = ""
    # Character fields
    appearance: str = ""
    wardrobe: str = ""
    accessories: str = ""
    # Location fields
    environment: str = ""
    lighting: str = ""
    atmosphere: str = ""
    time_of_day: str = ""
    # Prop fields
    prop_details: str = ""
    # Common
    style_prompt: str = ""
    continuity_notes: str = ""
    reference_images: list[str] = Field(default_factory=list[str])  # relative paths
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


# ============================================================
# Composition scene (persisted Shot Composer state; adapted from
# Open Media's composerStore SceneObject/Keyframe shape)
# ============================================================


class CompositionTransform(BaseModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # radians
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


CompositionObjectType = Literal[
    "figure",
    "cube",
    "plane",
    "cylinder",
    "sphere",
    "cone",
    "camera",
]


class CompositionKeyframe(BaseModel):
    id: str = Field(default_factory=lambda: new_id("kf"))
    time: float = 0.0
    transform: CompositionTransform = Field(default_factory=CompositionTransform)
    fov: float | None = None


class CompositionObject(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obj"))
    name: str = "Object"
    type: CompositionObjectType = "figure"
    # Link back to a film asset (character/prop) so composer objects and the
    # storyboard's cast stay one model, never two.
    asset_id: str | None = None
    visible: bool = True
    transform: CompositionTransform = Field(default_factory=CompositionTransform)
    # Named-joint pose: joint name -> [x, y, z] Euler degrees.
    pose: dict[str, tuple[float, float, float]] = Field(default_factory=dict)
    figure_variant: Literal["male", "female", "child"] = "male"
    color: str = "#8899aa"
    keyframes: list[CompositionKeyframe] = Field(default_factory=list[CompositionKeyframe])
    fov: float | None = None


class ShotFraming(BaseModel):
    shot_size: ShotSize = "medium"
    camera_angle: CameraAngle = "front"
    camera_elevation: CameraElevation = "eye"
    composition: CompositionId = "center"
    fov_deg: float = 40.0
    # OTS relationship: which composer object is foreground vs subject.
    ots_foreground_id: str | None = None
    ots_subject_id: str | None = None


class CompositionScene(BaseModel):
    objects: list[CompositionObject] = Field(default_factory=list[CompositionObject])
    camera: CompositionObject | None = None
    framing: ShotFraming = Field(default_factory=ShotFraming)
    camera_move: CameraMove = "static"
    duration_seconds: float = 3.0


class FilmPose(BaseModel):
    """A reusable named pose in the project pose library."""

    id: str = Field(default_factory=lambda: new_id("pose"))
    name: str
    category: str = "custom"
    joints: dict[str, tuple[float, float, float]] = Field(default_factory=dict)


# ============================================================
# Shots and versions
# ============================================================

ShotStatus = Literal[
    "draft",
    "composed",
    "ready",
    "queued",
    "generating",
    "review",
    "approved",
    "rejected",
]
VersionKind = Literal["preview", "final"]
VersionStatus = Literal["queued", "generating", "complete", "failed", "cancelled"]


class ShotCharacter(BaseModel):
    asset_id: str
    pose_name: str = ""
    emotion: str = ""
    position_hint: str = ""


class ShotGenerationSettings(BaseModel):
    model: str = ""  # empty = project default
    resolution: str = ""  # empty = project default
    fps: int = 24
    seed: int | None = None
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    use_capture_as_reference: bool = True
    continue_from_previous: bool = False
    # "project" inherits FilmProjectSettings.default_quality_preset; an explicit
    # model/resolution on the shot always wins (treated as custom).
    quality_preset: Literal["project", "fast_preview", "balanced", "quality", "custom"] = "project"


class ShotVersion(BaseModel):
    number: int
    kind: VersionKind
    status: VersionStatus = "queued"
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    resolution: str = ""
    fps: int = 24
    duration_seconds: float = 0.0
    seed: int | None = None
    capture_path: str = ""  # relative capture used as reference ('' = none)
    output_path: str = ""  # absolute path of the generated media
    error: str = ""
    # Wardrobe text per character asset at generation time, for continuity
    # comparisons against later edits.
    wardrobe_snapshot: dict[str, str] = Field(default_factory=dict)
    created_at: int = Field(default_factory=now_ms)


class FilmShot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("shot"))
    order: int = 0
    title: str = ""
    description: str = ""
    duration_seconds: float = 4.0

    framing: ShotFraming = Field(default_factory=ShotFraming)
    camera_move: CameraMove = "static"

    characters: list[ShotCharacter] = Field(default_factory=list[ShotCharacter])
    location_id: str | None = None
    prop_ids: list[str] = Field(default_factory=list[str])

    action: str = ""
    dialogue: str = ""
    emotion: str = ""

    visual_prompt: str = ""
    negative_prompt: str = ""
    prompt_locked: bool = False  # user edited the prompt; synthesis won't overwrite

    composition: CompositionScene | None = None
    capture_path: str = ""  # relative path of captured reference PNG ('' = none)

    generation: ShotGenerationSettings = Field(default_factory=ShotGenerationSettings)
    versions: list[ShotVersion] = Field(default_factory=list[ShotVersion])
    current_version: int | None = None

    status: ShotStatus = "draft"
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def version(self, number: int) -> ShotVersion | None:
        for candidate in self.versions:
            if candidate.number == number:
                return candidate
        return None


# ============================================================
# Scenes / script / project
# ============================================================


class FilmScene(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scene"))
    order: int = 0
    title: str = ""
    description: str = ""
    location_id: str | None = None
    character_ids: list[str] = Field(default_factory=list[str])
    prop_ids: list[str] = Field(default_factory=list[str])
    mood: str = ""
    lighting: str = ""
    time_of_day: str = ""
    continuity_notes: str = ""
    shots: list[FilmShot] = Field(default_factory=list[FilmShot])

    def shot(self, shot_id: str) -> FilmShot | None:
        for candidate in self.shots:
            if candidate.id == shot_id:
                return candidate
        return None

    @property
    def duration_seconds(self) -> float:
        return sum(shot.duration_seconds for shot in self.shots)


class FilmScript(BaseModel):
    content: str = ""
    updated_at: int = Field(default_factory=now_ms)


class FilmProjectSettings(BaseModel):
    default_model: str = ""
    default_resolution: str = ""
    style_prompt: str = ""
    default_negative_prompt: str = ""
    inter_shot_gap_seconds: float = 0.0
    strict_continuity: bool = False
    preview_resolution: str = "540p"
    preview_max_seconds: float = 4.0
    # Project-wide default for shots whose quality_preset is left on the
    # default ("balanced"); see FilmGenerationHandler.QUALITY_PROFILES.
    default_quality_preset: Literal["fast_preview", "balanced", "quality", "custom"] = "balanced"


class FilmProject(BaseModel):
    schema_version: int = FILM_SCHEMA_VERSION
    id: str
    name: str = ""
    script: FilmScript = Field(default_factory=FilmScript)
    settings: FilmProjectSettings = Field(default_factory=FilmProjectSettings)
    assets: list[FilmAsset] = Field(default_factory=list[FilmAsset])
    scenes: list[FilmScene] = Field(default_factory=list[FilmScene])
    pose_library: list[FilmPose] = Field(default_factory=list[FilmPose])
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def asset(self, asset_id: str) -> FilmAsset | None:
        for candidate in self.assets:
            if candidate.id == asset_id:
                return candidate
        return None

    def scene(self, scene_id: str) -> FilmScene | None:
        for candidate in self.scenes:
            if candidate.id == scene_id:
                return candidate
        return None

    def find_shot(self, shot_id: str) -> tuple[FilmScene, FilmShot] | None:
        for scene in self.scenes:
            shot = scene.shot(shot_id)
            if shot is not None:
                return scene, shot
        return None

    def previous_shot(self, shot_id: str) -> FilmShot | None:
        """The shot immediately before `shot_id` in scene+shot order."""
        ordered: list[FilmShot] = []
        for scene in sorted(self.scenes, key=lambda s: s.order):
            ordered.extend(sorted(scene.shots, key=lambda s: s.order))
        for index, shot in enumerate(ordered):
            if shot.id == shot_id:
                return ordered[index - 1] if index > 0 else None
        return None
