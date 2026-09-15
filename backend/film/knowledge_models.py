"""Domain models for what TFG learns about the models it uses.

Three layers, deliberately separate:

* **Events** are what happened. A render finished, a version was approved, a
  prompt was edited. Facts, appended, never rewritten.
* **Observations** are what those events suggest. Each carries a kind, so a
  measured rate is never confused with a guess, and a confidence that reflects
  how much evidence stands behind it.
* **Profiles** are the rolled-up view of one model: its declared capabilities
  plus its observed behaviour here.

The separation is the point. "This model failed 4 of 5 renders" is arithmetic.
"This model overanimates static shots" is a hypothesis. Storing them the same
way would make the second look as solid as the first.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from film.film_models import now_ms

#: What happened. Extending this list is additive; old rows keep their kind.
EventKind = Literal[
    "generation_completed",
    "generation_failed",
    "generation_cancelled",
    "version_approved",
    "version_rejected",
    "version_promoted",
    "version_deleted",
    "prompt_edited",
    "negative_prompt_edited",
    "model_changed",
    "provider_changed",
    "continuity_corrected",
    "storyboard_corrected",
    "timeline_changed",
    "rating",
    "feedback",
]

#: Which switch in Settings governs an event. Learning can be turned off
#: wholesale or per category, and the recorder honours it at write time.
EventCategory = Literal["generation", "approval", "editing", "feedback"]

EVENT_CATEGORIES: dict[str, EventCategory] = {
    "generation_completed": "generation",
    "generation_failed": "generation",
    "generation_cancelled": "generation",
    "version_approved": "approval",
    "version_rejected": "approval",
    "version_promoted": "approval",
    "version_deleted": "approval",
    "prompt_edited": "editing",
    "negative_prompt_edited": "editing",
    "model_changed": "editing",
    "provider_changed": "editing",
    "continuity_corrected": "editing",
    "storyboard_corrected": "editing",
    "timeline_changed": "editing",
    "rating": "feedback",
    "feedback": "feedback",
}

#: How much weight a statement deserves. The order matters: the UI sorts by it
#: and the router only acts on the top three.
ObservationKind = Literal[
    "fact",
    "observed_pattern",
    "user_preference",
    "model_recommendation",
    "hypothesis",
]

OBSERVATION_KIND_RANK: dict[str, int] = {
    "fact": 0,
    "observed_pattern": 1,
    "user_preference": 2,
    "model_recommendation": 3,
    "hypothesis": 4,
}

Task = Literal["video", "image", "text", ""]


class KnowledgeEvent(BaseModel):
    """One thing that happened, with enough context to explain a conclusion."""

    id: str = ""
    created_at: int = Field(default_factory=now_ms)
    kind: EventKind = "generation_completed"
    category: EventCategory = "generation"

    project_id: str = ""
    scene_id: str = ""
    shot_id: str = ""
    version_number: int | None = None

    model: str = ""
    provider: str = ""
    task: Task = ""
    execution_mode: str = ""

    prompt: str = ""
    negative_prompt: str = ""

    #: "success" | "failure" | "cancelled" | "" for events with no outcome.
    outcome: str = ""
    duration_seconds: float | None = None
    error: str = ""
    #: 1..5 when the user rated the result.
    rating: int | None = None
    note: str = ""


class Observation(BaseModel):
    """Something the events suggest about a model, with its evidence."""

    id: str = ""
    model: str = ""
    provider: str = ""
    task: Task = ""
    kind: ObservationKind = "hypothesis"
    statement: str = ""
    #: 0..1. Grows with supporting evidence, falls with contradicting evidence.
    confidence: float = 0.0
    support_count: int = 0
    contradiction_count: int = 0
    sample_size: int = 0
    first_seen: int = 0
    last_seen: int = 0
    #: Event ids behind this, capped — enough to justify it, not a full log.
    evidence_event_ids: list[str] = Field(default_factory=list[str])


class PromptPattern(BaseModel):
    """How one piece of prompt vocabulary has fared with one model.

    Derived by counting, not by asking a model what it thinks works. The
    verdict stays `unclear` until the phrase has been used enough times to say
    anything, so an accident is never presented as a technique.
    """

    phrase: str = ""
    uses: int = 0
    successes: int = 0
    failures: int = 0
    approvals: int = 0
    rejections: int = 0
    confidence: float = 0.0
    #: "worked" when results were kept, "struggled" when they were not.
    verdict: Literal["worked", "struggled", "unclear"] = "unclear"


class ModelProfile(BaseModel):
    """What we know about one model: declared capabilities plus observed behaviour."""

    model: str = ""
    provider: str = ""
    task: Task = ""
    label: str = ""

    # Declared — from the provider or the local catalog, not from experience.
    supports_image_input: bool = False
    supports_negative_prompt: bool = True
    supports_camera_control: bool = False
    max_duration_seconds: float | None = None
    supported_aspect_ratios: list[str] = Field(default_factory=list[str])
    context_length: int | None = None
    prompt_convention: str = ""

    # Observed — measured here, from this user's own runs.
    runs: int = 0
    successes: int = 0
    failures: int = 0
    cancellations: int = 0
    approvals: int = 0
    rejections: int = 0
    average_seconds: float | None = None
    average_rating: float | None = None
    last_used_at: int = 0

    observations: list[Observation] = Field(default_factory=list[Observation])
    prompt_patterns: list[PromptPattern] = Field(default_factory=list[PromptPattern])

    @property
    def success_rate(self) -> float | None:
        attempts = self.successes + self.failures
        return self.successes / attempts if attempts else None

    @property
    def approval_rate(self) -> float | None:
        judged = self.approvals + self.rejections
        return self.approvals / judged if judged else None


class LearningSettings(BaseModel):
    """What the user allows TFG to remember. Off switches are honoured on write."""

    enabled: bool = True
    generation: bool = True
    approval: bool = True
    editing: bool = True
    feedback: bool = True

    def allows(self, category: str) -> bool:
        if not self.enabled:
            return False
        return bool(getattr(self, category, True))


class KnowledgeExport(BaseModel):
    """A portable dump, so knowledge can move between machines."""

    schema_version: int = 1
    exported_at: int = Field(default_factory=now_ms)
    events: list[KnowledgeEvent] = Field(default_factory=list[KnowledgeEvent])
    observations: list[Observation] = Field(default_factory=list[Observation])
