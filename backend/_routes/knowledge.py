"""Routes for the knowledge engine: what TFG has learned about its models."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api_types import StatusResponse
from app_handler import AppHandler
from film.knowledge_api_types import (
    KnowledgeImportRequest,
    KnowledgeResetRequest,
    KnowledgeSummaryResponse,
    ModelProfileListResponse,
    RecommendRequest,
    RecommendResponse,
    RecordFeedbackRequest,
    PromptHintsRequest,
    RecordCandidateRequest,
)
from film.knowledge_models import KnowledgeEvent, KnowledgeExport, LearningSettings
from film.prompt_compiler import PromptHints
from state import get_state_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("", response_model=KnowledgeSummaryResponse)
def route_summary(handler: AppHandler = Depends(get_state_service)) -> KnowledgeSummaryResponse:
    return KnowledgeSummaryResponse(**handler.knowledge.summary())  # type: ignore[arg-type]


@router.get("/models", response_model=ModelProfileListResponse)
def route_profiles(handler: AppHandler = Depends(get_state_service)) -> ModelProfileListResponse:
    """Every model that has been used here, with what was observed about it."""
    return ModelProfileListResponse(models=handler.knowledge.profiles())


@router.get("/events", response_model=list[KnowledgeEvent])
def route_events(
    project_id: str = "",
    limit: int = 100,
    handler: AppHandler = Depends(get_state_service),
) -> list[KnowledgeEvent]:
    return handler.knowledge.recent_events(project_id=project_id, limit=limit)


@router.put("/settings", response_model=LearningSettings)
def route_update_learning(
    settings: LearningSettings,
    handler: AppHandler = Depends(get_state_service),
) -> LearningSettings:
    """Turn learning off wholesale or by category."""
    return handler.knowledge.update_settings(settings)


@router.post("/feedback", response_model=StatusResponse)
def route_feedback(
    req: RecordFeedbackRequest,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    """Record a rating or a note against a model."""
    recorded = handler.knowledge.record(
        KnowledgeEvent(
            kind="rating" if req.rating is not None else "feedback",
            model=req.model,
            provider=req.provider,
            project_id=req.project_id,
            shot_id=req.shot_id,
            rating=req.rating,
            note=req.note,
        )
    )
    # "declined" is not an error: the user switched this category off.
    return StatusResponse(status="ok" if recorded else "declined")


@router.post("/recommend", response_model=RecommendResponse)
def route_recommend(
    req: RecommendRequest,
    handler: AppHandler = Depends(get_state_service),
) -> RecommendResponse:
    """Rank models the caller has already filtered by capability."""
    model, reason = handler.knowledge.recommend(req.task, req.candidates)
    return RecommendResponse(model=model, reason=reason)


@router.get("/export", response_model=KnowledgeExport)
def route_export(handler: AppHandler = Depends(get_state_service)) -> KnowledgeExport:
    return handler.knowledge.export()


@router.post("/import", response_model=StatusResponse)
def route_import(
    req: KnowledgeImportRequest,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    count = handler.knowledge.import_knowledge(req.payload, replace=req.replace)
    return StatusResponse(status=f"imported {count}")


@router.post("/reset", response_model=StatusResponse)
def route_reset(
    req: KnowledgeResetRequest,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    removed = handler.knowledge.reset(model=req.model, project_id=req.project_id)
    return StatusResponse(status=f"removed {removed}")


@router.post("/hints", response_model=PromptHints)
def route_hints(req: PromptHintsRequest, handler: AppHandler = Depends(get_state_service)) -> PromptHints:
    """What has worked for shots like this one on this target."""
    return handler.knowledge.hints_for(req.spec_keys, req.target, model=req.model, limit=req.limit)


@router.post("/candidate", response_model=StatusResponse)
def route_candidate(req: RecordCandidateRequest, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    """Record a scored or picked Reproduce candidate."""
    handler.knowledge.record_candidate(
        picked=req.picked,
        model=req.model,
        provider=req.provider,
        target=req.target,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        seed=req.seed,
        spec_keys=req.spec_keys,
        metrics=req.metrics,
        project_id=req.project_id,
        shot_id=req.shot_id,
        note=req.note,
    )
    return StatusResponse(status="ok")
