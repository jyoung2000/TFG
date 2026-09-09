"""Routes for the Model Library: search, download, remember."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api_types import (
    LibraryDownloadRequest,
    LibraryDownloadStatus,
    ModelSearchResponse,
    ProviderTestResult,
    StatusResponse,
)
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api/models/library", tags=["model-library"])


@router.get("", response_model=ModelSearchResponse)
def route_search_models(
    query: str = "",
    task: str = Query(default="all", pattern="^(all|video|image|text)$"),
    source: str = Query(default="all", pattern="^(all|local|hosted)$"),
    only_compatible: bool = False,
    refresh: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    handler: AppHandler = Depends(get_state_service),
) -> ModelSearchResponse:
    """Every model this app can use, from local weights to hosted providers."""
    return handler.model_library.search(
        query=query,
        task=task,
        source=source,
        only_compatible=only_compatible,
        refresh=refresh,
        limit=limit,
    )


@router.post("/download", response_model=LibraryDownloadStatus)
def route_start_library_download(
    req: LibraryDownloadRequest,
    handler: AppHandler = Depends(get_state_service),
) -> LibraryDownloadStatus:
    return handler.model_library.start_download(req.provider, req.model_id)


@router.get("/download", response_model=LibraryDownloadStatus)
def route_library_download_status(
    handler: AppHandler = Depends(get_state_service),
) -> LibraryDownloadStatus:
    return handler.model_library.download_status()


@router.post("/download/cancel", response_model=LibraryDownloadStatus)
def route_cancel_library_download(
    handler: AppHandler = Depends(get_state_service),
) -> LibraryDownloadStatus:
    return handler.model_library.cancel_download()


@router.post("/providers/{provider}/test", response_model=ProviderTestResult)
def route_test_provider(
    provider: str,
    handler: AppHandler = Depends(get_state_service),
) -> ProviderTestResult:
    """Check a provider is really reachable with the key that is stored."""
    return handler.model_library.test_provider(provider)


@router.post("/remember", response_model=StatusResponse)
def route_remember_model(
    req: LibraryDownloadRequest,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    """Keep a model id the user typed so the library can offer it again."""
    handler.model_library.remember(req.provider, req.model_id)
    return StatusResponse(status="ok")
