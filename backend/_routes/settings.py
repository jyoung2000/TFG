"""Route handlers for GET/POST /api/settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from _routes._errors import HTTPError
from state.app_settings import SettingsResponse, UpdateSettingsRequest, to_settings_response
from api_types import StatusResponse
from state import get_state_service
from app_handler import AppHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsResponse)
def route_get_settings(handler: AppHandler = Depends(get_state_service)) -> SettingsResponse:
    return to_settings_response(handler.settings.get_settings_snapshot())


@router.post("/settings", response_model=StatusResponse)
def route_post_settings(
    req: UpdateSettingsRequest,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    _, _after, changed_paths = handler.settings.update_settings(req)
    changed_roots = {path.split(".", 1)[0] for path in changed_paths}

    logger.info(
        "Applied settings patch (changed=%s)",
        ", ".join(sorted(changed_roots)) if changed_roots else "none",
    )

    return StatusResponse(status="ok")


_KEY_FIELDS = {
    "ltx": "ltx_api_key",
    "fal": "fal_api_key",
    "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key",
    "openai-compatible": "openai_compatible_api_key",
    "anthropic": "anthropic_api_key",
    "xai": "xai_api_key",
    "wavespeed": "wavespeed_api_key",
    "replicate": "replicate_api_key",
}


@router.delete("/settings/api-keys/{provider}", response_model=StatusResponse)
def route_clear_api_key(
    provider: str,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    field = _KEY_FIELDS.get(provider)
    if field is None:
        raise HTTPError(404, f"Unknown API key provider: {provider}")
    handler.settings.clear_api_key(field)
    logger.info("Cleared stored %s API key", provider)
    return StatusResponse(status="ok")
