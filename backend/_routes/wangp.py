"""Remote WanGP server routes: the container side of `RemoteWanGPBridge`. Thin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app_handler import AppHandler
from state import get_state_service

router = APIRouter(prefix="/api/wangp", tags=["wangp"])


class UploadRequest(BaseModel):
    name: str
    data_base64: str


class ManifestRequest(BaseModel):
    manifest: list[dict[str, Any]]
    media_suffixes: list[str] = Field(default_factory=list[str])


class ManifestJobResponse(BaseModel):
    id: str
    status: str
    phase: str
    progress: float | None
    outputs: list[str]
    error: str


def _job_response(job: Any) -> ManifestJobResponse:
    return ManifestJobResponse(id=job.id, status=job.status, phase=job.phase, progress=job.progress, outputs=list(job.outputs), error=job.error)


@router.get("/status")
def route_status(handler: AppHandler = Depends(get_state_service)) -> dict[str, object]:
    return handler.wangp_server.status()


@router.get("/definitions")
def route_definitions(handler: AppHandler = Depends(get_state_service)) -> dict[str, object]:
    return {"definitions": handler.wangp_server.definitions()}


@router.post("/upload")
def route_upload(req: UploadRequest, handler: AppHandler = Depends(get_state_service)) -> dict[str, str]:
    return {"path": handler.wangp_server.upload(req.name, req.data_base64)}


@router.post("/manifest", response_model=ManifestJobResponse)
def route_manifest(req: ManifestRequest, handler: AppHandler = Depends(get_state_service)) -> ManifestJobResponse:
    return _job_response(handler.wangp_server.submit(req.manifest, req.media_suffixes))


@router.get("/jobs/{job_id}", response_model=ManifestJobResponse)
def route_job(job_id: str, handler: AppHandler = Depends(get_state_service)) -> ManifestJobResponse:
    return _job_response(handler.wangp_server.get(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=ManifestJobResponse)
def route_cancel(job_id: str, handler: AppHandler = Depends(get_state_service)) -> ManifestJobResponse:
    return _job_response(handler.wangp_server.cancel(job_id))


@router.get("/output")
def route_output(path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    return FileResponse(handler.wangp_server.output_path(path))
