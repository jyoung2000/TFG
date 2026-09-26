"""Video Reproduce v2 routes: thin plumbing over `VideoReproduceHandler`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app_handler import AppHandler
from film.video_analysis_api_types import VideoRecreationRequest, VideoRecreationResponse
from film.video_reproduce_models import VideoReproduceJob
from state import get_state_service

router = APIRouter(prefix="/api/video-reproduce", tags=["video-reproduce"])


@router.get("/{analysis_id}", response_model=VideoReproduceJob)
def route_get(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoReproduceJob:
    return handler.video_reproduce.get(analysis_id)


@router.post("/{analysis_id}/start", response_model=VideoRecreationResponse)
def route_start(analysis_id: str, req: VideoRecreationRequest, handler: AppHandler = Depends(get_state_service)) -> VideoRecreationResponse:
    return handler.video_reproduce.start(analysis_id, req)


@router.post("/{analysis_id}/cancel", response_model=VideoReproduceJob)
def route_cancel(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoReproduceJob:
    return handler.video_reproduce.cancel(analysis_id)


@router.post("/{analysis_id}/shots/{shot_id}/pick/{candidate_id}", response_model=VideoReproduceJob)
def route_pick(analysis_id: str, shot_id: str, candidate_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoReproduceJob:
    return handler.video_reproduce.pick(analysis_id, shot_id, candidate_id)


@router.post("/{analysis_id}/shots/{shot_id}/redo", response_model=VideoReproduceJob)
def route_redo(analysis_id: str, shot_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoReproduceJob:
    return handler.video_reproduce.redo(analysis_id, shot_id)


@router.post("/{analysis_id}/stitch", response_model=VideoReproduceJob)
def route_stitch(analysis_id: str, handler: AppHandler = Depends(get_state_service)) -> VideoReproduceJob:
    return handler.video_reproduce.stitch(analysis_id)


@router.get("/{analysis_id}/media")
def route_media(analysis_id: str, path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    """A candidate clip, a frame thumbnail or the stitched result — only files this job recorded."""
    resolved = handler.video_reproduce.media_path(analysis_id, path)
    media_type = "video/mp4" if resolved.suffix.lower() in (".mp4", ".m4v", ".mov") else "image/jpeg"
    return FileResponse(resolved, media_type=media_type)
