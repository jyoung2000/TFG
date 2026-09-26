"""Routes for analysing an existing video into an editable project."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from _routes._errors import HTTPError
from api_types import StatusResponse
from app_handler import AppHandler
from film.video_analysis_api_types import (
    AnalyzeRequest,
    BoundaryRequest,
    ImportVideoRequest,
    PromptEditRequest,
    ReconstructRequest,
    SplitRequest,
    VideoAnalysisListResponse,
    VideoRecreationRequest,
    VideoRecreationResponse,
)
from film.film_models import FilmProject
from film.scene_api_types import ShotSpecUpdateRequest, Storyboard3DRequest
from film.video_analysis_models import VideoAnalysis
from server_utils.path_policy import PathPolicyError, resolve_within
from state import get_state_service

router = APIRouter(prefix="/api/video-analysis", tags=["video-analysis"])


@router.post("/import", response_model=VideoAnalysis)
def route_import_video(
    req: ImportVideoRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    """Register a video and read its metadata."""
    return handler.video_analysis.import_video(
        req.path,
        title=req.title,
        depth=req.depth,
        sensitivity=req.sensitivity,
        min_shot_seconds=req.min_shot_seconds,
        max_shots=req.max_shots,
        detect_fades=req.detect_fades,
        analyze_audio=req.analyze_audio,
        analyze_text=req.analyze_text,
        provider=req.provider,
        model=req.model,
    )


@router.get("", response_model=VideoAnalysisListResponse)
def route_list_analyses(handler: AppHandler = Depends(get_state_service)) -> VideoAnalysisListResponse:
    return VideoAnalysisListResponse(analyses=handler.video_analysis.list_analyses())


@router.get("/{analysis_id}", response_model=VideoAnalysis)
def route_get_analysis(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoAnalysis:
    return handler.video_analysis.get(analysis_id)


@router.delete("/{analysis_id}", response_model=StatusResponse)
def route_delete_analysis(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    handler.video_analysis.delete(analysis_id)
    return StatusResponse(status="ok")


@router.post("/{analysis_id}/detect", response_model=VideoAnalysis)
def route_detect(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoAnalysis:
    """Find shot boundaries. Deterministic: needs no provider and no network."""
    return handler.video_analysis.detect(analysis_id)


@router.post("/{analysis_id}/analyze", response_model=VideoAnalysis)
def route_analyze(
    analysis_id: str,
    req: AnalyzeRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    """Describe each shot, with a model when one is configured."""
    provider = None if req.offline_only else handler.film_director.optional_provider("storyboard")
    return handler.video_analysis.analyze(analysis_id, provider)


@router.post("/{analysis_id}/cancel", response_model=VideoAnalysis)
def route_cancel(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoAnalysis:
    return handler.video_analysis.cancel(analysis_id)


@router.post("/{analysis_id}/shots/{shot_id}/split", response_model=VideoAnalysis)
def route_split_shot(
    analysis_id: str,
    shot_id: str,
    req: SplitRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    return handler.video_analysis.split(analysis_id, shot_id, req.at)


@router.post("/{analysis_id}/shots/{shot_id}/merge", response_model=VideoAnalysis)
def route_merge_shot(
    analysis_id: str,
    shot_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    return handler.video_analysis.merge(analysis_id, shot_id)


@router.put("/{analysis_id}/shots/{shot_id}/boundary", response_model=VideoAnalysis)
def route_move_boundary(
    analysis_id: str,
    shot_id: str,
    req: BoundaryRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    return handler.video_analysis.move_boundary(analysis_id, shot_id, start=req.start, end=req.end)


@router.put("/{analysis_id}/shots/{shot_id}/prompts", response_model=VideoAnalysis)
def route_edit_prompts(
    analysis_id: str,
    shot_id: str,
    req: PromptEditRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    """Edit a reconstructed prompt. Marks it so regeneration will not overwrite."""
    return handler.video_analysis.edit_prompts(analysis_id, shot_id, req)


@router.post("/{analysis_id}/reconstruct", response_model=FilmProject)
def route_reconstruct(
    analysis_id: str,
    req: ReconstructRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProject:
    """Build an editable film project from the analysis."""
    return handler.video_analysis.reconstruct(analysis_id, project_id=req.project_id, name=req.name)


@router.post("/{analysis_id}/storyboard3d", response_model=FilmProject)
def route_storyboard3d(
    analysis_id: str,
    req: Storyboard3DRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProject:
    """A film project whose shots open the composer pre-seeded from their 3D layouts."""
    return handler.scene.storyboard3d(analysis_id, project_id=req.project_id, name=req.name)


@router.put("/{analysis_id}/shots/{shot_id}/spec", response_model=VideoAnalysis)
def route_update_shot_spec(
    analysis_id: str,
    shot_id: str,
    req: ShotSpecUpdateRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoAnalysis:
    """Edit a shot's ShotSpec sections (or fold a composer scene back into it)."""
    return handler.scene.update_shot_spec(analysis_id, shot_id, req)


@router.post("/{analysis_id}/recreate", response_model=VideoRecreationResponse)
def route_recreate_video(
    analysis_id: str,
    req: VideoRecreationRequest,
    handler: AppHandler = Depends(get_state_service),
) -> VideoRecreationResponse:
    """Recreate the analysed shots as generated candidates (one job per shot)."""
    return handler.video_analysis.recreate_video(analysis_id, req)


@router.get("/{analysis_id}/frame")
def route_frame(
    analysis_id: str,
    path: str,
    handler: AppHandler = Depends(get_state_service),
) -> FileResponse:
    """Serve one extracted still. The path is confined to the analysis folder."""
    directory = handler.video_analysis.store.directory(analysis_id)
    try:
        resolved = resolve_within(directory, path, what="frame")
    except PathPolicyError as exc:
        raise HTTPError(400, str(exc)) from exc
    if not resolved.is_file():
        raise HTTPError(404, "No such frame")
    return FileResponse(resolved, media_type="image/jpeg")
