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
    FilmShot,
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
    # "downloaded" | "not_downloaded" | "managed_by_wangp" | "cloud" |
    # "not_configured" (advisory row: a compatible path that needs setup)
    download_state: str
    execution: str  # "local" | "wangp" | "api"
    required: bool = True
    disk_size_gb: float | None = None
    estimated_min_vram_gb: float | None = None
    fits_gpu: bool | None = None
    supported_resolutions: list[str] = Field(default_factory=list[str])


class FilmCapabilitiesResponse(BaseModel):
    gpu_name: str | None
    gpu_vram_gb: float | None
    execution_mode: str  # "wangp" | "api" | "local"
    # One-sentence compatibility verdict for the detected GPU, plus a severity
    # for the UI: "ok" (a local path fits), "partial" (only some paths fit),
    # "none" (no local generation on this hardware).
    gpu_verdict: str
    gpu_verdict_level: str
    models: list[FilmModelCapability]
    # Total size of required-but-missing local model files ('' mode otherwise).
    total_required_download_gb: float | None
    # True when the text encoder can be skipped (cloud text encoding via API key).
    text_encoder_optional: bool
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


class DirectorChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class DirectorInstructRequest(BaseModel):
    instruction: str
    scene_id: str | None = None
    shot_id: str | None = None
    # Optional prior conversation turns (role: user|assistant, content) so the
    # director bar can behave like a chat without the backend keeping state.
    history: list[DirectorChatMessage] = Field(default_factory=list[DirectorChatMessage])


class DirectorContextDetails(BaseModel):
    """What was sent to the model — surfaced in the UI as 'context details'."""

    provider: str
    model: str
    role: str
    steps: int = 0
    tool_calls: int = 0
    prompt_chars: int = 0
    project_summary_chars: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    scope: str = ""


class DirectorInstructResponse(BaseModel):
    plan_summary: str
    results: list[DirectorCommandResult]
    reply: str = ""
    context: DirectorContextDetails | None = None


class DirectorChatRequest(BaseModel):
    """Project-less assistant chat (Quick Mode idea refinement, prompt help)."""

    messages: list[DirectorChatMessage]
    role: str = "prompt_refinement"
    # Optional generation context so suggestions respect the current setup.
    model_hint: str = ""
    duration_seconds: float | None = None


class DirectorChatResponse(BaseModel):
    reply: str
    suggested_prompt: str = ""
    suggested_negative_prompt: str = ""
    suggested_duration_seconds: float | None = None
    context: DirectorContextDetails


class DirectorRoleModel(BaseModel):
    role: str
    provider: str
    model: str


class DirectorToolInfo(BaseModel):
    name: str
    description: str


class DirectorStatusResponse(BaseModel):
    provider_setting: str
    active_provider: str  # "openrouter" | "gemini" | "none"
    gemini_configured: bool
    openrouter_configured: bool
    openrouter_key_source: str
    roles: list[DirectorRoleModel]
    tools: list[DirectorToolInfo]
    message: str = ""


class OpenRouterModelInfo(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    prompt_price: str = ""
    completion_price: str = ""
    supports_tools: bool = False
    supports_json: bool = False


class OpenRouterModelsResponse(BaseModel):
    models: list[OpenRouterModelInfo]
    fetched_at_ms: int
    cached: bool


class OpenRouterValidateResponse(BaseModel):
    valid: bool
    label: str = ""
    usage: float | None = None
    limit: float | None = None
    is_free_tier: bool | None = None
    message: str = ""


class RefinePromptRequest(BaseModel):
    guidance: str = ""


class RefinePromptResponse(BaseModel):
    shot: FilmShot
    previous_prompt: str
    context: DirectorContextDetails


class FilmBuildShot(BaseModel):
    title: str = ""
    description: str = ""
    action: str = ""
    dialogue: str = ""
    shot_size: str = "medium"
    camera_angle: str = "front"
    camera_elevation: str = "eye"
    composition: str = "center"
    camera_move: str = "static"
    duration_seconds: float = 4.0
    characters: list[str] = Field(default_factory=list[str])
    location: str = ""


class FilmBuildScene(BaseModel):
    title: str = ""
    description: str = ""
    location: str = ""
    time_of_day: str = ""
    mood: str = ""
    lighting: str = ""
    characters: list[str] = Field(default_factory=list[str])
    shots: list[FilmBuildShot] = Field(default_factory=list[FilmBuildShot])


class FilmBuildCharacter(BaseModel):
    name: str
    description: str = ""
    appearance: str = ""
    wardrobe: str = ""


class FilmBuildLocation(BaseModel):
    name: str
    description: str = ""
    environment: str = ""
    lighting: str = ""
    atmosphere: str = ""


class FilmBuildPlan(BaseModel):
    """Editable film plan produced by 'Build Film with AI'; nothing is
    persisted until the user applies it."""

    title: str = ""
    logline: str = ""
    style: str = ""
    script: str = ""
    characters: list[FilmBuildCharacter] = Field(default_factory=list[FilmBuildCharacter])
    locations: list[FilmBuildLocation] = Field(default_factory=list[FilmBuildLocation])
    scenes: list[FilmBuildScene] = Field(default_factory=list[FilmBuildScene])


class FilmBuildRequest(BaseModel):
    idea: str
    target_scenes: int = 3
    target_shots_per_scene: int = 3
    use_llm: bool = True
    style: str = ""


class FilmBuildResponse(BaseModel):
    plan: FilmBuildPlan
    used_llm: bool
    context: DirectorContextDetails | None = None


class FilmBuildApplyRequest(BaseModel):
    plan: FilmBuildPlan
    replace_existing: bool = False


class FilmBuildApplyResponse(BaseModel):
    status: str
    scenes_created: int
    shots_created: int
    characters_created: int
    locations_created: int
    project: FilmProject


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
