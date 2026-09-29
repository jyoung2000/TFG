"""Reproduce v2 document (`<outputs>/image_analyses/<id>/analysis.json`).

Same directory layout as v1 (`reference.<ext>`, `candidate-*.png`), a v2
document with the ShotSpec, per-candidate score breakdowns and rounds.
A v1 `ImageAnalysis` document is migrated on read.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from api_types import LoraUse
from pydantic import BaseModel, Field, field_validator

from film.film_models import now_ms
from film.prompt_compiler import PromptStyle
from film.shot_spec import ShotSpec
from services.similarity.composite import ScoreBreakdown

REPRODUCE_VERSION = 2
ReproduceStatus = Literal["idle", "analyzing", "rendering", "scoring", "complete", "failed", "cancelled", "plateau"]
CandidateSource = Literal["render", "fix", "patch", "inpaint", "legacy"]


#: The bar the brief asks for: composite >= 0.95, reported as 95 % identical.
DEFAULT_TARGET_SCORE = 0.95


class ReproduceBudget(BaseModel):
    candidates_per_round: int = Field(default=6, ge=1, le=12)
    max_rounds: int | None = Field(default=None)
    #: Stop once the best composite reaches this. 0.95 = 95 % identical.
    target_score: float = Field(default=DEFAULT_TARGET_SCORE, ge=0.0, le=1.0)

    @field_validator("target_score")
    @classmethod
    def _a_target_of_zero_is_not_a_target(cls, value: float) -> float:
        """A non-positive target means "no target", not "stop immediately".

        The loop ends on `best >= target`, so 0.0 is satisfied by the first
        candidate however bad it is: the run degenerates to a single round and
        still reports success. The UI's Target score field is `min={0}` with no
        validation and was observed reading 0.0, so this is reachable by
        typing rather than by malice. Anything <= 0 falls back to the real bar;
        a genuine target is left untouched.
        """
        return DEFAULT_TARGET_SCORE if value <= 0 else value


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
    strategy: str = ""  # prompt_refinement | seed_search | reference_conditioning | same_resolution
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
