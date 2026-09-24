"""Route handlers for /api/generate, /api/generate/cancel, /api/generation/progress."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api_types import (
    CancelResponse,
    GenerateVideoRequest,
    GenerateVideoResponse,
    GenerationProgressResponse,
    GenerationQueueItem,
    GenerationQueueResponse,
)
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api", tags=["generation"])


@router.post("/generate", response_model=GenerateVideoResponse)
def route_generate(
    req: GenerateVideoRequest,
    handler: AppHandler = Depends(get_state_service),
) -> GenerateVideoResponse:
    """POST /api/generate — video generation from JSON body."""
    return handler.video_generation.generate(req)


@router.post("/generate/cancel", response_model=CancelResponse)
def route_generate_cancel(handler: AppHandler = Depends(get_state_service)) -> CancelResponse:
    """POST /api/generate/cancel."""
    return handler.generation.cancel_generation()


@router.get("/generation/progress", response_model=GenerationProgressResponse)
def route_generation_progress(handler: AppHandler = Depends(get_state_service)) -> GenerationProgressResponse:
    """GET /api/generation/progress."""
    return handler.generation.get_generation_progress()


@router.get("/generation/queue", response_model=GenerationQueueResponse)
def route_generation_queue(handler: AppHandler = Depends(get_state_service)) -> GenerationQueueResponse:
    """Active generation plus the latest five image/video outputs."""
    progress = handler.generation.get_generation_progress()
    active: dict[str, object] | None = {
        "status": progress.status,
        "phase": progress.phase,
        "progress": progress.progress,
        "currentStep": progress.currentStep,
        "totalSteps": progress.totalSteps,
    }
    # Film Maker jobs use a separate serialized queue but the same generation
    # backend. Surface that job when no direct Generate tab job is running.
    if progress.status != "running":
        queue = handler.film_generation.get_queue()
        if queue.active is not None:
            active_project = handler.film.get_project(queue.active.project_id)
            active = {
                "status": queue.active.status,
                "phase": queue.phase,
                "progress": queue.progress or 0,
                "prompt": f"{active_project.name} · {queue.active.shot_title}",
                "id": queue.active.shot_id,
            }
        elif queue.pending:
            pending_project = handler.film.get_project(queue.pending[0].project_id)
            active = {
                "status": "queued",
                "phase": f"{len(queue.pending)} shots waiting",
                "progress": 0,
                "prompt": f"{pending_project.name} · {queue.pending[0].shot_title}",
                "id": queue.pending[0].shot_id,
            }

    suffixes = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".png", ".jpg", ".jpeg", ".webp"}
    roots = [handler.config.outputs_dir, handler.config.outputs_dir / "image_analyses"]
    film_projects = handler.config.outputs_dir / "film_projects"
    if film_projects.is_dir():
        for project_dir in film_projects.iterdir():
            for relative in ("outputs", "references"):
                candidate_dir = project_dir / relative
                if candidate_dir.is_dir():
                    roots.append(candidate_dir)
    paths: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in suffixes:
                paths.append(path)
            elif root.name == "image_analyses" and path.is_dir():
                paths.extend(child for child in path.iterdir() if child.is_file() and child.suffix.lower() in suffixes)
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    recent = [
        GenerationQueueItem(
            path=str(path),
            prompt=path.stem,
            completed_at=int(path.stat().st_mtime * 1000),
            type="video" if path.suffix.lower() in {".mp4", ".webm", ".mov", ".m4v", ".mkv"} else "image",
            size_mb=round(path.stat().st_size / (1024 * 1024), 4),
        )
        for path in paths[:5]
    ]
    return GenerationQueueResponse(active=active, recent=recent)
