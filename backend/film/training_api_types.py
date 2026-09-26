"""Request/response models for the training routes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from film.training_models import Dataset, DatasetPreset, LoraEntry, TrainingConfig, TrainingRun


class CreateDatasetRequest(BaseModel):
    name: str = ""
    preset: DatasetPreset = "character"
    trigger: str = ""


class ImportDatasetItemsRequest(BaseModel):
    """Any mix of sources; each becomes one or more items."""

    folder: str = ""
    image_paths: list[str] = Field(default_factory=list[str])
    #: Absolute video path + frames per second to sample.
    video_path: str = ""
    video_fps: float = 1.0
    video_max_frames: int = 24
    #: History job ids whose image outputs become items.
    job_ids: list[str] = Field(default_factory=list[str])
    #: Video-analysis id (all extracted frames) or image-reproduce id (its candidates).
    analysis_id: str = ""
    reproduce_id: str = ""


class UpdateDatasetRequest(BaseModel):
    name: str | None = None
    preset: DatasetPreset | None = None
    trigger: str | None = None


class CaptionRequest(BaseModel):
    #: Re-caption items a person already edited too.
    overwrite_edited: bool = False


class UpdateItemRequest(BaseModel):
    caption: str


class DatasetListResponse(BaseModel):
    datasets: list[Dataset] = Field(default_factory=list[Dataset])


class TrainerStatus(BaseModel):
    id: str
    name: str
    upstream: str
    license: str
    targets: list[str]
    installed: bool
    fits_12gb: bool
    reason: str
    notes: str


class TrainingStatusResponse(BaseModel):
    trainers: list[TrainerStatus] = Field(default_factory=list[TrainerStatus])
    #: Weight files per target the subprocess trainers need, and whether each exists.
    weights: dict[str, dict[str, str]] = Field(default_factory=dict[str, dict[str, str]])
    machine_vram_mb: int = 12288
    active_run_id: str = ""


class SuggestConfigRequest(BaseModel):
    dataset_id: str
    target: str = "z_image"


class StartTrainingRequest(BaseModel):
    dataset_id: str
    name: str = ""
    config: TrainingConfig | None = None
    #: Resume this run's last checkpoint instead of starting fresh.
    resume_run_id: str = ""


class RunListResponse(BaseModel):
    runs: list[TrainingRun] = Field(default_factory=list[TrainingRun])


class LoraListResponse(BaseModel):
    loras: list[LoraEntry] = Field(default_factory=list[LoraEntry])


class ImportLoraRequest(BaseModel):
    path: str
    name: str = ""
    target: str = "z_image"
    trigger: str = ""


class UpdateLoraRequest(BaseModel):
    name: str | None = None
    trigger: str | None = None
    default_multiplier: float | None = None
