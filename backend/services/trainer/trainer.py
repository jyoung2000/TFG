"""The training service contract."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class TrainingRequest(BaseModel):
    """Everything a trainer needs, resolved by the handler (no UI state)."""

    run_id: str
    trainer_id: str
    #: Compile target the LoRA is for: z_image | qwen_image | wan22 | flux | ltx2.
    target: str
    #: Folder with images + `.txt` captions (one per image).
    dataset_dir: str
    output_dir: str
    output_name: str
    trigger: str = ""
    steps: int = 600
    rank: int = 16
    learning_rate: float = 1e-4
    batch_size: int = 1
    resolution: int = 768
    buckets: list[int] = Field(default_factory=lambda: [512, 768])
    blocks_to_swap: int = 0
    fp8: bool = True
    save_every: int = 100
    sample_every: int = 100
    sample_prompts: list[str] = Field(default_factory=list[str])
    seed: int = 42
    #: Resume from this checkpoint (safetensors) when set.
    resume_from: str = ""
    #: Weight files per trainer (dit/vae/text_encoder or name_or_path).
    weights: dict[str, str] = Field(default_factory=dict[str, str])


class TrainingProgress(BaseModel):
    step: int = 0
    total: int = 0
    loss: float | None = None
    eta_seconds: float | None = None
    phase: str = "training"
    #: New sample images written since the previous report (absolute paths).
    samples: list[str] = Field(default_factory=list[str])
    checkpoint: str = ""


class TrainingOutcome(BaseModel):
    status: str = "complete"  # complete | cancelled | failed
    lora_path: str = ""
    steps_done: int = 0
    final_loss: float | None = None
    samples: list[str] = Field(default_factory=list[str])
    log_tail: str = ""


class TrainerUnavailable(RuntimeError):
    """The trainer cannot run on this machine; the message says what to do."""


ProgressCallback = Callable[[TrainingProgress], None]
CancelledCallback = Callable[[], bool]


class LoraTrainer(Protocol):
    id: str

    def available(self) -> tuple[bool, str]:
        """(installed, reason-or-hint). Never raises."""
        ...

    def train(self, request: TrainingRequest, on_progress: ProgressCallback, is_cancelled: CancelledCallback) -> TrainingOutcome: ...


def existing_dir(path: str) -> Path | None:
    candidate = Path(path)
    return candidate if candidate.is_dir() else None
