"""Video Reproduce v2 documents (phase 5).

One document per analysed video, stored beside the analysis as
`reproduce.json`. Mirrored in `frontend/types/video-reproduce.ts`
(snake_case, no mapping layer).
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.similarity.composite import ScoreBreakdown

VideoReproduceStatus = Literal["idle", "running", "complete", "failed", "cancelled"]
CandidateStatus = Literal["queued", "generating", "complete", "failed", "cancelled"]

#: How the composite is mixed with the flow-magnitude match, documented in docs/VIDEO_REPRODUCE.md.
VISUAL_WEIGHT = 0.8
MOTION_WEIGHT = 0.2


def now_ms() -> int:
    return int(time.time() * 1000)


class VideoCandidate(BaseModel):
    id: str
    #: Film shot version that rendered it, and the absolute output path.
    version_number: int
    path: str = ""
    #: Frame thumbnails inside the reproduce folder (relative), start/middle/end.
    frames: list[str] = Field(default_factory=list[str])
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    round: int = 1
    model: str = ""
    target: str = ""
    duration_seconds: float = 0.0
    status: CandidateStatus = "queued"
    error: str = ""
    scores: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    #: 0..1 flow-magnitude/direction agreement with the reference shot ("" component when unmeasured).
    motion_match: float | None = None
    job_id: str = ""
    created_at: int = Field(default_factory=now_ms)


class ReproduceShot(BaseModel):
    shot_id: str
    index: int = 0
    film_scene_id: str = ""
    film_shot_id: str = ""
    start: float = 0.0
    end: float = 0.0
    #: Snapped to the model's allowed durations.
    duration_seconds: float = 0.0
    #: Analysis-relative start frame used as the I2V conditioning image.
    start_frame: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    prompt_source: Literal["spec", "analysis", "user"] = "analysis"
    candidates: list[VideoCandidate] = Field(default_factory=list[VideoCandidate])
    best_candidate_id: str = ""
    picked_candidate_id: str = ""

    def candidate(self, candidate_id: str) -> VideoCandidate | None:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        return None

    def chosen(self) -> VideoCandidate | None:
        return self.candidate(self.picked_candidate_id) or self.candidate(self.best_candidate_id)


class VideoReproduceJob(BaseModel):
    version: int = 1
    analysis_id: str
    project_id: str = ""
    title: str = ""
    kind: Literal["preview", "final"] = "preview"
    target: str = ""
    model: str = ""
    resolution: str = ""
    fps: int = 24
    candidates_per_shot: int = 2
    rounds: int = 1
    seed: int | None = None
    status: VideoReproduceStatus = "idle"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    shots: list[ReproduceShot] = Field(default_factory=list[ReproduceShot])
    #: Reproduce-relative path of the last stitched result ("" until stitched).
    stitched_path: str = ""
    stitched_at: int | None = None
    job_id: str = ""
    peak_vram_mb: int | None = None
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)

    def shot(self, shot_id: str) -> ReproduceShot | None:
        for shot in self.shots:
            if shot.shot_id == shot_id:
                return shot
        return None

    @property
    def is_busy(self) -> bool:
        return self.status == "running"

    def to_summary(self) -> dict[str, Any]:
        return {"analysis_id": self.analysis_id, "status": self.status, "shots": len(self.shots)}
