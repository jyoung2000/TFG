"""Pydantic request/response models and TypedDicts for ltx2_server."""

from __future__ import annotations

from typing import Literal, NamedTuple, TypeAlias, TypedDict
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

NonEmptyPrompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ImageConditioningInput(NamedTuple):
    """Image conditioning triplet used by all video pipelines."""

    path: str
    frame_idx: int
    strength: float


# ============================================================
# TypedDicts for module-level state globals
# ============================================================


class GenerationState(TypedDict):
    id: str | None
    cancelled: bool
    result: str | list[str] | None
    error: str | None
    status: str  # "idle" | "running" | "complete" | "cancelled" | "error"
    phase: str
    progress: int
    current_step: int
    total_steps: int


class ModelDownloadState(TypedDict):
    status: str  # "idle" | "downloading" | "complete" | "error"
    current_file: str
    current_file_progress: int
    total_progress: int
    downloaded_bytes: int
    total_bytes: int
    files_completed: int
    total_files: int
    error: str | None
    speed_mbps: int


JsonObject: TypeAlias = dict[str, object]
VideoCameraMotion = Literal[
    "none",
    "dolly_in",
    "dolly_out",
    "dolly_left",
    "dolly_right",
    "jib_up",
    "jib_down",
    "static",
    "focus_shift",
]


# ============================================================
# Response Models
# ============================================================


class ModelStatusItem(BaseModel):
    id: str
    name: str
    loaded: bool
    downloaded: bool


class GpuTelemetry(BaseModel):
    name: str
    vram: int
    vramUsed: int


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
    active_model: str | None
    gpu_info: GpuTelemetry
    sage_attention: bool
    models_status: list[ModelStatusItem]


class GpuInfoResponse(BaseModel):
    cuda_available: bool
    mps_available: bool = False
    gpu_available: bool = False
    gpu_name: str | None
    vram_gb: int | None
    gpu_info: GpuTelemetry


class RuntimePolicyResponse(BaseModel):
    force_api_generations: bool


class GenerationProgressResponse(BaseModel):
    status: str
    phase: str
    progress: int
    currentStep: int | None
    totalSteps: int | None


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str


class ModelFileStatus(BaseModel):
    name: str
    description: str
    downloaded: bool
    size: int
    expected_size: int
    required: bool = True
    is_folder: bool = False
    optional_reason: str | None = None


class TextEncoderStatus(BaseModel):
    downloaded: bool
    size_bytes: int
    size_gb: float
    expected_size_gb: float


class ModelsStatusResponse(BaseModel):
    models: list[ModelFileStatus]
    all_downloaded: bool
    total_size: int
    downloaded_size: int
    total_size_gb: float
    downloaded_size_gb: float
    models_path: str
    has_api_key: bool
    text_encoder_status: TextEncoderStatus
    use_local_text_encoder: bool


class DownloadProgressResponse(BaseModel):
    status: str
    currentFile: str
    currentFileProgress: int
    totalProgress: int
    downloadedBytes: int
    totalBytes: int
    filesCompleted: int
    totalFiles: int
    error: str | None
    speedMbps: int


class IcLoraModel(BaseModel):
    name: str
    path: str
    conditioning_type: str
    reference_downscale_factor: int


class IcLoraListResponse(BaseModel):
    models: list[IcLoraModel]
    directory: str


class SuggestGapPromptResponse(BaseModel):
    status: str = "success"
    suggested_prompt: str


class GenerateVideoResponse(BaseModel):
    status: str
    video_path: str | None = None
    # Seed actually used (None when the remote API picks its own), so callers
    # can reproduce or remake the clip.
    seed: int | None = None


class GenerateImageResponse(BaseModel):
    status: str
    image_paths: list[str] | None = None


class CancelResponse(BaseModel):
    status: str
    id: str | None = None


class RetakeResponse(BaseModel):
    status: str
    video_path: str | None = None
    result: JsonObject | None = None


class IcLoraExtractResponse(BaseModel):
    conditioning: str
    original: str
    conditioning_type: str
    frame_time: float


class IcLoraDownloadResponse(BaseModel):
    status: str
    path: str | None = None
    already_existed: bool | None = None
    already_exists: bool | None = None


class IcLoraGenerateResponse(BaseModel):
    status: str
    video_path: str | None = None


class ModelDownloadStartResponse(BaseModel):
    status: str
    message: str | None = None
    skippingTextEncoder: bool | None = None


class TextEncoderDownloadResponse(BaseModel):
    status: str
    message: str | None = None


class StatusResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    error: str
    message: str | None = None


# ============================================================
# Request Models
# ============================================================


class GenerateVideoRequest(BaseModel):
    prompt: NonEmptyPrompt
    resolution: str = "512p"
    model: str = "fast"
    cameraMotion: VideoCameraMotion = "none"
    negativePrompt: str = ""
    duration: str = "2"
    fps: str = "24"
    audio: str = "false"
    imagePath: str | None = None
    audioPath: str | None = None
    aspectRatio: Literal["16:9", "9:16"] = "16:9"


class GenerateImageRequest(BaseModel):
    prompt: NonEmptyPrompt
    width: int = 1024
    height: int = 1024
    numSteps: int = 4
    numImages: int = 1


class ModelDownloadRequest(BaseModel):
    skipTextEncoder: bool = False


# ---------------------------------------------------------------------------
# Model library: one searchable catalog over local weights and hosted models
# ---------------------------------------------------------------------------

LibraryTask = Literal["video", "image", "text"]
LibrarySource = Literal["local", "hosted"]


class LibraryModel(BaseModel):
    """One model the user can pick, download, or connect to."""

    id: str  # provider-scoped id, exactly what the provider expects
    name: str
    provider: str  # wangp | native | ollama | openai_compatible | openrouter | anthropic | xai | gemini | fal | wavespeed | replicate
    source: LibrarySource
    task: LibraryTask
    description: str = ""
    # installed | available | downloading | active | incompatible | needs_key | example
    state: str = "available"
    installed: bool = False
    downloadable: bool = False
    size_gb: float | None = None
    estimated_min_vram_gb: float | None = None
    fits_gpu: bool | None = None
    supports_image_input: bool = False
    context_length: int | None = None
    family: str = ""
    quantization: str = ""
    # True for the example ids this app ships for providers without a public
    # catalog API — check them against the provider's own model list.
    curated: bool = False
    url: str = ""


class LibrarySourceStatus(BaseModel):
    id: str
    label: str
    kind: LibrarySource
    configured: bool
    count: int = 0
    # Populated when this source could not be listed; the rest of the library
    # still works, so one unreachable provider never empties the page.
    error: str = ""
    catalog_url: str = ""


class ModelSearchResponse(BaseModel):
    models: list[LibraryModel]
    total: int
    sources: list[LibrarySourceStatus]
    gpu_name: str | None = None
    gpu_vram_gb: float | None = None
    models_path: str = ""
    # True when at least one local video/image model and one local text model
    # are installed — everything needed for a fully offline film.
    offline_ready: bool = False
    offline_note: str = ""


class ProviderTestResult(BaseModel):
    """Whether a provider is actually usable with the key that is stored."""

    provider: str
    label: str
    configured: bool
    # True only when a real request was made and it succeeded.
    ok: bool = False
    # False when this provider offers no way to check a key without starting a
    # paid generation — the UI says so instead of implying it verified anything.
    checked: bool = False
    message: str = ""
    # Models the check saw, when the check was a catalog listing.
    models_found: int = 0


class LibraryDownloadRequest(BaseModel):
    provider: str
    model_id: str


class LibraryDownloadStatus(BaseModel):
    active: bool = False
    provider: str = ""
    model_id: str = ""
    status: str = "idle"  # idle | running | complete | failed | cancelled
    files_total: int = 0
    files_done: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    progress: float = 0.0
    error: str = ""
    message: str = ""


class SuggestGapPromptRequest(BaseModel):
    beforePrompt: str = ""
    afterPrompt: str = ""
    beforeFrame: str | None = None
    afterFrame: str | None = None
    gapDuration: float = 5
    mode: str = "t2v"
    inputImage: str | None = None


class RetakeRequest(BaseModel):
    video_path: str
    start_time: float
    duration: float
    prompt: str = ""
    mode: str = "replace_audio_and_video"


class IcLoraDownloadRequest(BaseModel):
    model: str


class IcLoraExtractRequest(BaseModel):
    video_path: str
    conditioning_type: str = "canny"
    frame_time: float = 0


class IcLoraImageInput(BaseModel):
    path: str
    frame: int = 0
    strength: float = 1.0


def _default_ic_lora_images() -> list[IcLoraImageInput]:
    return []


class IcLoraGenerateRequest(BaseModel):
    video_path: str
    lora_path: str
    conditioning_type: str = "canny"
    prompt: NonEmptyPrompt
    conditioning_strength: float = 1.0
    seed: int = 42
    height: int = 512
    width: int = 768
    num_frames: int = 121
    frame_rate: float = 24
    num_inference_steps: int = 30
    cfg_guidance_scale: float = 1.0
    negative_prompt: str = ""
    images: list[IcLoraImageInput] = Field(default_factory=_default_ic_lora_images)
