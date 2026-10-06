"""Jobs API: the History tab's only data source. Thin plumbing."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api_types import ImportJobsRequest, ImportJobsResponse
from app_handler import AppHandler
from services.job_store.job_models import Job
from state import get_state_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobListResponse(BaseModel):
    jobs: list[Job]
    next_cursor: str = ""


class JobDetailResponse(BaseModel):
    job: Job
    lineage: list[Job]
    children: list[Job]


class JobDeleteResponse(BaseModel):
    deleted: bool
    removed_files: list[str]


@router.get("", response_model=JobListResponse)
def route_list_jobs(
    kind: str = "",
    status: str = "",
    project: str = "",
    q: str = "",
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str = "",
    handler: AppHandler = Depends(get_state_service),
) -> JobListResponse:
    jobs, next_cursor = handler.jobs.list(kind=kind, status=status, project_id=project, search=q, limit=limit, cursor=cursor)
    return JobListResponse(jobs=jobs, next_cursor=next_cursor)


@router.get("/events")
def route_job_events(
    since: int = 0,
    handler: AppHandler = Depends(get_state_service),
) -> StreamingResponse:
    """Server-sent events: one `job` event per changed job, `reset` when the
    client fell too far behind, a comment every 15 s to keep the socket open."""

    def stream() -> Iterator[str]:
        seq = since
        yield "retry: 2000\n\n"
        while True:
            seq, changed = handler.jobs.wait_for_changes(seq, timeout=15.0)
            if not changed:
                yield ": keepalive\n\n"
                continue
            if "*" in changed:
                yield f"id: {seq}\nevent: reset\ndata: {{}}\n\n"
                continue
            for job in handler.jobs.snapshot(changed):
                yield f"id: {seq}\nevent: job\ndata: {job.model_dump_json()}\n\n"
            for job_id in changed:
                if handler.jobs.store.get(job_id) is None:
                    yield f"id: {seq}\nevent: deleted\ndata: {json.dumps({'id': job_id})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/import", response_model=ImportJobsResponse)
def route_import_jobs(req: ImportJobsRequest, handler: AppHandler = Depends(get_state_service)) -> ImportJobsResponse:
    return handler.jobs.import_quick_history(req)


@router.get("/{job_id}", response_model=JobDetailResponse)
def route_get_job(job_id: str, handler: AppHandler = Depends(get_state_service)) -> JobDetailResponse:
    job = handler.jobs.get(job_id)
    return JobDetailResponse(job=job, lineage=handler.jobs.lineage(job_id), children=handler.jobs.children(job_id))


@router.delete("/{job_id}", response_model=JobDeleteResponse)
def route_delete_job(
    job_id: str, files: bool = False, handler: AppHandler = Depends(get_state_service)
) -> JobDeleteResponse:
    removed = handler.jobs.delete(job_id, files=files)
    return JobDeleteResponse(deleted=True, removed_files=removed)


@router.post("/{job_id}/cancel", response_model=Job)
def route_cancel_job(job_id: str, handler: AppHandler = Depends(get_state_service)) -> Job:
    return handler.jobs.cancel(job_id)


@router.post("/{job_id}/rerun", response_model=Job)
def route_rerun_job(job_id: str, handler: AppHandler = Depends(get_state_service)) -> Job:
    return handler.jobs.rerun(
        job_id,
        lambda target: handler.task_runner.run_background(target, task_name=f"rerun-{job_id}"),
    )
