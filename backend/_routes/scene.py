"""3D scene routes (phase 6): thin plumbing over `SceneHandler`."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app_handler import AppHandler
from film.scene_api_types import DescribeSceneRequest, DescribeSceneResponse, SceneBuildRequest, SceneBuildResponse
from state import get_state_service

router = APIRouter(prefix="/api/scene", tags=["scene"])


@router.post("/build", response_model=SceneBuildResponse)
def route_build(req: SceneBuildRequest, handler: AppHandler = Depends(get_state_service)) -> SceneBuildResponse:
    """ShotSpec → solved 3D layout + composer scene + camera words + blockout SVG."""
    return handler.scene.build(req)


@router.post("/describe", response_model=DescribeSceneResponse)
def route_describe(req: DescribeSceneRequest, handler: AppHandler = Depends(get_state_service)) -> DescribeSceneResponse:
    """Film vocabulary for a 3D layout (the composer calls this on every edit)."""
    return handler.scene.describe(req.layout3d)
