"""Job records.

One row per unit of work the app does on the user's behalf. The shape is the
contract between every handler that does work and the History tab that shows
it; `frontend/types/jobs.ts` mirrors it field for field (snake_case, no
mapping layer).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

JobKind = Literal[
    "image_gen",
    "video_gen",
    "image_reproduce",
    "video_reproduce",
    "analysis",
    "scene_build",
    "training",
    "download",
]
JobStatus = Literal["queued", "running", "complete", "failed", "cancelled"]

JOB_KINDS: tuple[JobKind, ...] = (
    "image_gen",
    "video_gen",
    "image_reproduce",
    "video_reproduce",
    "analysis",
    "scene_build",
    "training",
    "download",
)
JOB_STATUSES: tuple[JobStatus, ...] = ("queued", "running", "complete", "failed", "cancelled")
TERMINAL_STATUSES: frozenset[str] = frozenset({"complete", "failed", "cancelled"})

OutputKind = Literal["image", "video", "file"]


def now_ms() -> int:
    return int(time.time() * 1000)


def new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


class JobOutput(BaseModel):
    """One produced file plus what History needs to show it without opening it."""

    path: str
    kind: OutputKind = "file"
    width: int = 0
    height: int = 0
    duration: float = 0.0
    #: Absolute path of a small JPEG preview inside the outputs directory ("" when none).
    thumb: str = ""


class Job(BaseModel):
    id: str = Field(default_factory=new_job_id)
    kind: JobKind
    status: JobStatus = "queued"
    #: 0..100
    progress: float = 0.0
    phase: str = ""
    #: A short human label: shot title, model name, file name.
    title: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)
    started_at: int | None = None
    finished_at: int | None = None
    model: str = ""
    provider: str = "local"
    seed: int | None = None
    prompt: str = ""
    negative_prompt: str = ""
    #: The ShotSpec (phase 3) or any structured description the job ran from.
    spec: dict[str, Any] = Field(default_factory=dict)
    #: Request parameters, enough to re-run the job.
    params: dict[str, Any] = Field(default_factory=dict)
    #: Source material: reference paths, analysis ids, dataset ids.
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: list[JobOutput] = Field(default_factory=list[JobOutput])
    #: scores, peak_vram_mb, seconds, …
    metrics: dict[str, Any] = Field(default_factory=dict)
    parent_job_id: str = ""
    project_id: str = ""
    shot_id: str = ""
    error: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
