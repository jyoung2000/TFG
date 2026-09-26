"""Request/response models for the knowledge routes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from film.knowledge_models import KnowledgeExport, LearningSettings, ModelProfile


class KnowledgeSummaryResponse(BaseModel):
    learning: LearningSettings = Field(default_factory=LearningSettings)
    event_count: int = 0
    model_count: int = 0
    observation_count: int = 0
    #: Where the knowledge lives, so the user can find or delete it.
    database: str = ""
    updated_at: int = 0


class ModelProfileListResponse(BaseModel):
    models: list[ModelProfile] = Field(default_factory=list[ModelProfile])


class RecordFeedbackRequest(BaseModel):
    model: str = ""
    provider: str = ""
    project_id: str = ""
    shot_id: str = ""
    #: 1..5, or omitted for a note without a score.
    rating: int | None = None
    note: str = ""


class RecommendRequest(BaseModel):
    task: str = "video"
    #: Models the caller has already filtered by capability.
    candidates: list[str] = Field(default_factory=list[str])


class RecommendResponse(BaseModel):
    model: str = ""
    #: Cites the evidence, so the user can disagree with it.
    reason: str = ""


class KnowledgeImportRequest(BaseModel):
    payload: KnowledgeExport
    replace: bool = False


class KnowledgeResetRequest(BaseModel):
    #: Empty for both means "forget everything".
    model: str = ""
    project_id: str = ""


class PromptHintsRequest(BaseModel):
    """Ask what has worked for shots like this one on this target."""

    spec_keys: list[str] = Field(default_factory=list[str])
    target: str = ""
    model: str = ""
    limit: int = 8


class RecordCandidateRequest(BaseModel):
    """A Reproduce candidate was scored (or picked by the user)."""

    picked: bool = False
    model: str = ""
    provider: str = "local"
    target: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    spec_keys: list[str] = Field(default_factory=list[str])
    metrics: dict[str, float] = Field(default_factory=dict[str, float])
    project_id: str = ""
    shot_id: str = ""
    note: str = ""
