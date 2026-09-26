"""Reproduce v2 document (`<outputs>/image_analyses/<id>/analysis.json`).

Same directory layout as v1 (`reference.<ext>`, `candidate-*.png`), a v2
document with the ShotSpec, per-candidate score breakdowns and rounds.
A v1 `ImageAnalysis` document is migrated on read.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from api_types import LoraUse
from pydantic import BaseModel, Field

from film.film_models import now_ms
from film.prompt_compiler import PromptStyle
from film.shot_spec import ShotSpec
from services.similarity.composite import ScoreBreakdown

REPRODUCE_VERSION = 2
ReproduceStatus = Literal["idle", "analyzing", "rendering", "scoring", "complete", "failed", "cancelled"]
CandidateSource = Literal["render", "fix", "patch", "inpaint", "legacy"]


class ReproduceBudget(BaseModel):
    candidates_per_round: int = Field(default=6, ge=1, le=12)
    max_rounds: int = Field(default=3, ge=1, le=8)
    #: Stop early once the best composite reaches this.
    target_score: float = Field(default=0.9, ge=0.0, le=1.0)


class ReproduceCandidate(BaseModel):
    id: str
    path: str
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    params: dict[str, Any] = Field(default_factory=dict[str, Any])
    round: int = 1
    model: str = ""
    target: str = ""
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    job_id: str = ""
    source: CandidateSource = "render"
    #: The candidate this one was fixed/patched from ("" for renders).
    parent_id: str = ""
    created_at: int = Field(default_factory=now_ms)


class ReproducePatch(BaseModel):
    """One metric-guided or VLM-guided change to the next round's prompt."""

    reason: str
    phrase: str
    metric: str = ""
    value: float = 0.0


class ReproduceRound(BaseModel):
    index: int
    prompt: str
    negative_prompt: str = ""
    target: str = ""
    style: str = ""
    hints_applied: list[str] = Field(default_factory=list[str])
    patches: list[ReproducePatch] = Field(default_factory=list[ReproducePatch])
    seeds: list[int] = Field(default_factory=list[int])
    best_candidate_id: str = ""
    best_score: float = 0.0
    started_at: int = Field(default_factory=now_ms)
    finished_at: int | None = None
    note: str = ""


class ReproduceJob(BaseModel):
    version: int = REPRODUCE_VERSION
    id: str
    title: str
    source_path: str
    width: int
    height: int
    spec: ShotSpec = Field(default_factory=ShotSpec)
    #: Compile target + style the loop renders with.
    target: str = "z_image"
    style: PromptStyle | None = None
    #: A user-written prompt overrides the compiled one when set.
    prompt_override: str = ""
    #: The prompt last compiled/used (shown in the UI).
    prompt: str = ""
    negative_prompt: str = ""
    image_model: str = ""
    vision_model: str = ""
    budget: ReproduceBudget = Field(default_factory=ReproduceBudget)
    #: LoRAs (absolute safetensors path + multiplier) applied to every candidate render.
    loras: list[LoraUse] = Field(default_factory=list[LoraUse])
    status: ReproduceStatus = "idle"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    candidates: list[ReproduceCandidate] = Field(default_factory=list[ReproduceCandidate])
    rounds: list[ReproduceRound] = Field(default_factory=list[ReproduceRound])
    best_candidate_id: str = ""
    #: The candidate used as the scoring reference ("" = the imported image).
    reference_candidate_id: str = ""
    picked_candidate_id: str = ""
    #: Evidence per spec section: what was measured/detected and by which stage.
    why: dict[str, Any] = Field(default_factory=dict[str, Any])
    depth_path: str = ""
    job_id: str = ""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def candidate(self, candidate_id: str) -> ReproduceCandidate | None:
        return next((c for c in self.candidates if c.id == candidate_id), None)

    def best(self) -> ReproduceCandidate | None:
        return self.candidate(self.best_candidate_id)

    @property
    def is_busy(self) -> bool:
        return self.status in ("analyzing", "rendering", "scoring")


def migrate_document(payload: dict[str, Any]) -> ReproduceJob:
    """v2 as-is; a v1 `ImageAnalysis` document becomes a v2 job with the old
    prompt, candidates (score → composite) and best pick carried over."""
    if int(payload.get("version", 1)) >= REPRODUCE_VERSION:
        return ReproduceJob.model_validate(payload)
    candidates: list[ReproduceCandidate] = []
    for raw in cast(list[dict[str, Any]], payload.get("candidates", [])):
        score = float(raw.get("score", 0.0))
        candidates.append(
            ReproduceCandidate(
                id=str(raw.get("id", "")),
                path=str(raw.get("path", "")),
                prompt=str(raw.get("prompt", "")),
                round=int(raw.get("round", 1)),
                model=str(raw.get("model", "")),
                scores=ScoreBreakdown(composite=score, components={"legacy_mae": score}, weights_used={"legacy_mae": 1.0}),
                source="legacy",
            )
        )
    spec = ShotSpec()
    spec.source.width = int(payload.get("width", 0))
    spec.source.height = int(payload.get("height", 0))
    spec.source.path = str(payload.get("source_path", ""))
    if payload.get("caption"):
        spec.narrative.what_happens = str(payload["caption"])
    job = ReproduceJob(
        id=str(payload["id"]),
        title=str(payload.get("title", "")),
        source_path=str(payload.get("source_path", "")),
        width=int(payload.get("width", 0)),
        height=int(payload.get("height", 0)),
        spec=spec,
        prompt=str(payload.get("prompt", "")),
        prompt_override=str(payload.get("prompt", "")),
        image_model=str(payload.get("image_model", "")),
        vision_model=str(payload.get("vision_model", "")),
        candidates=candidates,
        best_candidate_id=str(payload.get("best_candidate_id", "")),
        status="complete" if candidates else "idle",
        depth_path=str(payload.get("depth_path", "")),
        why={"legacy": "migrated from a v1 analysis; scores were pixel MAE"},
    )
    return job
