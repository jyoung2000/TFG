"""Datasets, training runs and the LoRA registry (phase 7).

Persisted as JSON under `<app-data>/training/` and `<app-data>/loras/`;
mirrored in `frontend/types/training.ts` (snake_case, no mapping layer).
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

DatasetPreset = Literal["character", "style", "object"]
TrainingStatus = Literal["queued", "running", "complete", "failed", "cancelled"]
ItemSource = Literal["folder", "video", "history", "analysis", "candidate"]

#: Compile targets a LoRA can be trained for, with the WanGP lora folder each maps to.
LORA_TARGETS: dict[str, str] = {"z_image": "z_image", "qwen_image": "qwen", "flux": "flux2", "wan22": "wan", "ltx2": "ltx2"}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class DatasetItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("item"))
    #: File name inside the dataset folder.
    file: str
    caption: str = ""
    #: True once a person edited the caption (auto-captioning leaves it alone).
    edited: bool = False
    source: ItemSource = "folder"
    origin: str = ""
    width: int = 0
    height: int = 0


class Dataset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ds"))
    name: str = ""
    preset: DatasetPreset = "character"
    trigger: str = ""
    items: list[DatasetItem] = Field(default_factory=list[DatasetItem])
    #: Caption model used by auto-caption ("" until run).
    caption_model: str = ""
    #: Absolute folder holding the images and caption sidecars (set on save).
    folder: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def item(self, item_id: str) -> DatasetItem | None:
        return next((i for i in self.items if i.id == item_id), None)


class TrainingConfig(BaseModel):
    """Resolved per preset + target with 12 GB-safe defaults (`presets.py`)."""

    target: str = "z_image"
    trainer: str = "musubi"
    rank: int = 16
    steps: int = 600
    learning_rate: float = 1e-4
    batch_size: int = 1
    resolution: int = 768
    buckets: list[int] = Field(default_factory=lambda: [512, 768])
    blocks_to_swap: int = 0
    fp8: bool = True
    save_every: int = 100
    sample_every: int = 100
    seed: int = 42
    #: Estimated peak VRAM for this config (MB); refused when it exceeds the card.
    estimated_vram_mb: int = 11000


class TrainingSample(BaseModel):
    step: int
    path: str


class TrainingRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    name: str = ""
    dataset_id: str = ""
    preset: DatasetPreset = "character"
    trigger: str = ""
    config: TrainingConfig = Field(default_factory=TrainingConfig)
    status: TrainingStatus = "queued"
    phase: str = ""
    step: int = 0
    total_steps: int = 0
    loss_history: list[float] = Field(default_factory=list[float])
    eta_seconds: float | None = None
    samples: list[TrainingSample] = Field(default_factory=list[TrainingSample])
    checkpoints: list[str] = Field(default_factory=list[str])
    lora_id: str = ""
    lora_path: str = ""
    job_id: str = ""
    error: str = ""
    log_tail: str = ""
    peak_vram_mb: int | None = None
    started_at: int | None = None
    finished_at: int | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    @property
    def is_active(self) -> bool:
        return self.status in ("queued", "running")


class LoraEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lora"))
    name: str
    #: Absolute path of the safetensors inside `<app-data>/loras/<folder>/`.
    file: str
    target: str = "z_image"
    base_model: str = ""
    trigger: str = ""
    dataset_id: str = ""
    run_id: str = ""
    job_id: str = ""
    preset: DatasetPreset = "character"
    default_multiplier: float = 1.0
    size_bytes: int = 0
    #: True for files a person dropped into the folder (no run behind them).
    imported: bool = False
    created_at: int = Field(default_factory=now_ms)
