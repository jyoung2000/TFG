"""Request/response models for the video-analysis routes."""

from __future__ import annotations

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
