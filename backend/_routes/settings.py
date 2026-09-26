"""Route handlers for GET/POST /api/settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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


class HardwarePresetsResponse(BaseModel):
    presets: list[dict[str, object]]
    gpu_name: str | None
    gpu_vram_gb: float | None
    applied: str


@router.get("/settings/presets", response_model=HardwarePresetsResponse)
def route_list_presets(handler: AppHandler = Depends(get_state_service)) -> HardwarePresetsResponse:
    gpu_name = handler.gpu_info.get_device_name()
    vram = handler.gpu_info.get_vram_total_gb()
    return HardwarePresetsResponse(
        presets=handler.settings.presets(gpu_name, float(vram) if vram is not None else None),
        gpu_name=gpu_name,
        gpu_vram_gb=float(vram) if vram is not None else None,
        applied=handler.settings.get_settings_snapshot().hardware_preset,
    )


@router.post("/settings/presets/{preset_id}/apply", response_model=SettingsResponse)
def route_apply_preset(preset_id: str, handler: AppHandler = Depends(get_state_service)) -> SettingsResponse:
    try:
        preset = handler.settings.apply_preset(preset_id)
    except KeyError as exc:
        raise HTTPError(404, f"Unknown hardware preset: {preset_id}") from exc
    logger.info("Applied hardware preset %s", preset.id)
    return to_settings_response(handler.settings.get_settings_snapshot())


@router.get("/settings/tiers")
def route_tiers(project: str = "", handler: AppHandler = Depends(get_state_service)) -> dict[str, list[dict[str, str]]]:
    """The resolved provider order per task (Settings shows why a tier is skipped)."""
    return handler.film_generation.tier_preview(project)


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
