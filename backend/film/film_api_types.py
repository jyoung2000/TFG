"""Request/response models for the /api/film routes.

Kept beside the film domain (rather than in the app-wide api_types.py) per the
backend's many-small-files convention; these are the typed API contract for
the film feature only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from film.film_continuity import ContinuityWarning
from film.film_models import (
    CameraMove,
    CompositionScene,
    FilmAsset,
    FilmAssetKind,
    FilmPose,
    FilmProject,
    FilmProjectSettings,
    ShotCharacter,
    ShotFraming,
    ShotGenerationSettings,
    VersionKind,
)


class FilmProjectResponse(BaseModel):
    project: FilmProject


class UpdateScriptRequest(BaseModel):
    content: str


class UpdateFilmSettingsRequest(BaseModel):
    settings: FilmProjectSettings


class CreateAssetRequest(BaseModel):
    kind: FilmAssetKind
    name: str
    description: str = ""
    appearance: str = ""
    wardrobe: str = ""
    accessories: str = ""
    environment: str = ""
    lighting: str = ""
    atmosphere: str = ""
    time_of_day: str = ""
    prop_details: str = ""
    style_prompt: str = ""
    continuity_notes: str = ""


class UpdateAssetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    appearance: str | None = None
    wardrobe: str | None = None
    accessories: str | None = None
    environment: str | None = None
    lighting: str | None = None
    atmosphere: str | None = None
    time_of_day: str | None = None
    prop_details: str | None = None
    style_prompt: str | None = None
    continuity_notes: str | None = None


class AssetResponse(BaseModel):
    asset: FilmAsset


class AddAssetReferenceRequest(BaseModel):
    image_base64: str
    name_hint: str = "reference"


class CreateSceneRequest(BaseModel):
    title: str = ""
    description: str = ""
    location_id: str | None = None
    character_ids: list[str] = Field(default_factory=list[str])
    prop_ids: list[str] = Field(default_factory=list[str])
    mood: str = ""
    lighting: str = ""
    time_of_day: str = ""


class UpdateSceneRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    location_id: str | None = None
    clear_location: bool = False
    character_ids: list[str] | None = None
    prop_ids: list[str] | None = None
    mood: str | None = None
    lighting: str | None = None
    time_of_day: str | None = None
    continuity_notes: str | None = None


class ReorderRequest(BaseModel):
    ordered_ids: list[str]


class CreateShotRequest(BaseModel):
    title: str = ""
    description: str = ""
    duration_seconds: float = 4.0
    action: str = ""
    dialogue: str = ""


class UpdateShotRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_seconds: float | None = None
    framing: ShotFraming | None = None
    camera_move: CameraMove | None = None
    characters: list[ShotCharacter] | None = None
    location_id: str | None = None
    clear_location: bool = False
    prop_ids: list[str] | None = None
    action: str | None = None
    dialogue: str | None = None
    emotion: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    prompt_locked: bool | None = None
    composition: CompositionScene | None = None
    generation: ShotGenerationSettings | None = None
    status: str | None = None


class ShotCaptureRequest(BaseModel):
    image_base64: str
    composition: CompositionScene


class SavePoseRequest(BaseModel):
    name: str
    category: str = "custom"
    joints: dict[str, tuple[float, float, float]]


class PoseResponse(BaseModel):
    pose: FilmPose


class GenerateShotRequest(BaseModel):
    kind: VersionKind = "preview"


class BatchGenerateRequest(BaseModel):
    kind: VersionKind = "preview"
    scene_id: str | None = None
    shot_ids: list[str] = Field(default_factory=list[str])  # empty + no scene = whole storyboard


class QueuedJob(BaseModel):
    project_id: str
    scene_id: str
    shot_id: str
    shot_title: str
    kind: VersionKind
    version_number: int
    status: str


class FilmQueueResponse(BaseModel):
    active: QueuedJob | None
    pending: list[QueuedJob]


class QueueShotResponse(BaseModel):
    status: str
    version_number: int
    warnings: list[ContinuityWarning] = Field(default_factory=list[ContinuityWarning])


class BatchGenerateResponse(BaseModel):
    status: str
    queued: list[QueuedJob]


class PromoteVersionResponse(BaseModel):
    status: str
    current_version: int


class ContinuityResponse(BaseModel):
    warnings: list[ContinuityWarning]


class FilmModelCapability(BaseModel):
    id: str
    label: str
    modes: list[str]
    supports_image_to_video: bool
    supports_text_to_video: bool
    supports_reference_images: bool
    supports_audio: bool
    downloaded: bool
    download_state: str  # "downloaded" | "not_downloaded" | "managed_by_wangp" | "cloud"
    execution: str  # "local" | "wangp" | "api"
    disk_size_gb: float | None = None
    estimated_min_vram_gb: float | None = None
    fits_gpu: bool | None = None
    supported_resolutions: list[str] = Field(default_factory=list[str])


class FilmCapabilitiesResponse(BaseModel):
    gpu_name: str | None
    gpu_vram_gb: float | None
    execution_mode: str  # "wangp" | "api" | "local"
    models: list[FilmModelCapability]
    vram_note: str


class DirectorCommandRequest(BaseModel):
    name: str
    params: dict[str, object] = Field(default_factory=dict)


class DirectorCommandResult(BaseModel):
    name: str
    ok: bool
    result: object | None = None
    error: str = ""


class DirectorCommandResponse(BaseModel):
    results: list[DirectorCommandResult]


class DirectorInstructRequest(BaseModel):
    instruction: str
    scene_id: str | None = None
    shot_id: str | None = None


class DirectorInstructResponse(BaseModel):
    plan_summary: str
    results: list[DirectorCommandResult]


class GenerateStoryboardRequest(BaseModel):
    use_llm: bool = False
    target_shots_per_scene: int = 4
    replace_existing: bool = False


class GenerateStoryboardResponse(BaseModel):
    status: str
    scenes_created: int
    shots_created: int
    characters_created: int
    used_llm: bool
