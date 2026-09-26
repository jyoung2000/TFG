"""Request/response models for the video-analysis routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.video_analysis_models import AnalysisDepth, VideoAnalysis


class ImportVideoRequest(BaseModel):
    """An absolute path to a video on this machine, plus how to analyse it."""

    path: str
    title: str = ""
    depth: AnalysisDepth = "standard"
    sensitivity: float = 0.5
    min_shot_seconds: float = 0.6
    max_shots: int = 400
    detect_fades: bool = True
    analyze_audio: bool = False
    analyze_text: bool = False
    #: '' lets the app choose the configured director provider.
    provider: str = ""
    model: str = ""


class AnalyzeRequest(BaseModel):
    #: Skip the model even when one is configured, for a fully local pass.
    offline_only: bool = False


class SplitRequest(BaseModel):
    at: float


class BoundaryRequest(BaseModel):
    start: float | None = None
    end: float | None = None


class PromptEditRequest(BaseModel):
    """Field-level prompt edits. Absent fields are left alone."""

    storyboard: str | None = None
    video: str | None = None
    cinematography: str | None = None
    environment: str | None = None
    character: str | None = None
    motion: str | None = None
    negative: str | None = None


class ReconstructRequest(BaseModel):
    project_id: str = ""
    name: str = ""


class VideoAnalysisListResponse(BaseModel):
    analyses: list[VideoAnalysis] = Field(default_factory=list[VideoAnalysis])


class VideoRecreationRequest(BaseModel):
    """Request to recreate a video from analyzed shots."""
    candidates: int = Field(default=2, ge=1, le=6)
    rounds: int = Field(default=1, ge=1, le=3)
    shot_ids: list[str] = Field(default_factory=list)  # Empty means all shots
    #: Fast Preview (540p, model "fast") or the project's final profile.
    kind: Literal["preview", "final"] = "preview"
    #: Base seed; candidate n of round r renders with seed + (r-1)*100 + n. None = random.
    seed: int | None = None


class VideoRecreationResponse(BaseModel):
    """Response containing generated video candidates."""
    status: str
    video_paths: list[str] | None = None
    shots_generated: int = 0
    analysis_id: str
