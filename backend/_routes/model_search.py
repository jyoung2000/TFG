"""Model manager API: search Hugging Face, list a repo's weights, download by link."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app_handler import AppHandler
from handlers.model_search_handler import ModelSearchHandler
from state import get_state_service

router = APIRouter(prefix="/api/model-manager", tags=["model-manager"])


def _service(handler: AppHandler) -> ModelSearchHandler:
    """`AppHandler.model_search` is wired in app_handler.py; read it by name so this module type-checks either way."""
    return handler.model_search


class HubModelResponse(BaseModel):
    repo_id: str
    downloads: int = 0
    likes: int = 0
    pipeline_tag: str = ""
    license: str = ""
    last_modified: str = ""


class HubFileResponse(BaseModel):
    path: str
    size_bytes: int = 0


class DownloadRequest(BaseModel):
    url: str = ""
    repo_id: str = ""
    path: str = ""
    destination: str


class DownloadResponse(BaseModel):
    job_id: str


class CancelResponse(BaseModel):
    ok: bool = True


@router.get("/search", response_model=list[HubModelResponse])
def route_search(
    q: str = "",
    limit: int = Query(default=20, ge=1, le=50),
    handler: AppHandler = Depends(get_state_service),
) -> list[HubModelResponse]:
    return [HubModelResponse(**vars(m)) for m in _service(handler).search(q, limit)]


@router.get("/files", response_model=list[HubFileResponse])
def route_files(repo: str = "", handler: AppHandler = Depends(get_state_service)) -> list[HubFileResponse]:
    return [HubFileResponse(**vars(f)) for f in _service(handler).files(repo)]


@router.post("/download", response_model=DownloadResponse)
def route_download(req: DownloadRequest, handler: AppHandler = Depends(get_state_service)) -> DownloadResponse:
    job_id = _service(handler).download(
        url=req.url, repo_id=req.repo_id, path=req.path, destination=req.destination
    )
    return DownloadResponse(job_id=job_id)


@router.post("/download/{job_id}/cancel", response_model=CancelResponse)
def route_cancel(job_id: str, handler: AppHandler = Depends(get_state_service)) -> CancelResponse:
    _service(handler).cancel(job_id)
    return CancelResponse()
