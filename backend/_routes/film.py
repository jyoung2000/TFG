"""Routes for the film project CRUD surface (/api/film/projects/...)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from _routes._errors import HTTPError
from api_types import StatusResponse
from film.film_api_types import (
    AddAssetReferenceRequest,
    AssetResponse,
    ContinuityResponse,
    CreateAssetRequest,
    CreateSceneRequest,
    CreateShotRequest,
    DeleteVersionResponse,
    ExportPackageRequest,
    FilmProjectResponse,
    FixContinuityRequest,
    FixContinuityResponse,
    GenerateAssetReferenceRequest,
    GenerateAssetReferenceResponse,
    ImportGenerationRequest,
    ImportGenerationResponse,
    ImportPackageRequest,
    ImportPackageResponse,
    PackageSummaryResponse,
    PoseResponse,
    ProjectContinuityResponse,
    PromoteVersionResponse,
    ReorderRequest,
    ReplaceProjectRequest,
    SavePoseRequest,
    ShotCaptureRequest,
    UpdateAssetRequest,
    UpdateFilmSettingsRequest,
    UpdateSceneRequest,
    UpdateScriptRequest,
    UpdateShotRequest,
    DeliverRequest,
    DeliverResponse,
    ReferenceSheetRequest,
    ReferenceSheetResponse,
)
from film.film_models import FilmScene, FilmShot
from state import get_state_service
from app_handler import AppHandler

router = APIRouter(prefix="/api/film", tags=["film"])


class SceneResponse(FilmScene):
    pass


class ShotResponse(FilmShot):
    pass


@router.get("/projects/{project_id}", response_model=FilmProjectResponse)
def route_get_film_project(
    project_id: str, handler: AppHandler = Depends(get_state_service)
) -> FilmProjectResponse:
    return FilmProjectResponse(project=handler.film.get_project(project_id))


@router.put("/projects/{project_id}", response_model=FilmProjectResponse)
def route_replace_film_project(
    project_id: str,
    req: ReplaceProjectRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProjectResponse:
    """Whole-project replacement for undo/redo snapshots."""
    return FilmProjectResponse(project=handler.film_generation.replace_project(project_id, req))


@router.put("/projects/{project_id}/script", response_model=FilmProjectResponse)
def route_update_script(
    project_id: str,
    req: UpdateScriptRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProjectResponse:
    return FilmProjectResponse(project=handler.film.update_script(project_id, req))


@router.put("/projects/{project_id}/settings", response_model=FilmProjectResponse)
def route_update_film_settings(
    project_id: str,
    req: UpdateFilmSettingsRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProjectResponse:
    return FilmProjectResponse(project=handler.film.update_settings(project_id, req))


@router.post("/projects/{project_id}/export", response_model=PackageSummaryResponse)
def route_export_package(
    project_id: str,
    req: ExportPackageRequest,
    handler: AppHandler = Depends(get_state_service),
) -> PackageSummaryResponse:
    return handler.film.export_package(project_id, req)


@router.post("/projects/{project_id}/import", response_model=ImportPackageResponse)
def route_import_package(
    project_id: str,
    req: ImportPackageRequest,
    handler: AppHandler = Depends(get_state_service),
) -> ImportPackageResponse:
    return handler.film.import_package(project_id, req)


@router.get("/packages/inspect", response_model=PackageSummaryResponse)
def route_inspect_package(
    package_path: str = Query(min_length=1),
    handler: AppHandler = Depends(get_state_service),
) -> PackageSummaryResponse:
    return handler.film.inspect_package(package_path)


@router.post("/projects/{project_id}/import-generation", response_model=ImportGenerationResponse)
def route_import_generation(
    project_id: str,
    req: ImportGenerationRequest,
    handler: AppHandler = Depends(get_state_service),
) -> ImportGenerationResponse:
    return handler.film.import_generation(project_id, req)


# ---- Assets ------------------------------------------------------------


@router.post("/projects/{project_id}/assets", response_model=AssetResponse)
def route_create_asset(
    project_id: str,
    req: CreateAssetRequest,
    handler: AppHandler = Depends(get_state_service),
) -> AssetResponse:
    return AssetResponse(asset=handler.film.create_asset(project_id, req))


@router.post(
    "/projects/{project_id}/assets/{asset_id}/generate-reference",
    response_model=GenerateAssetReferenceResponse,
)
def route_generate_asset_reference(
    project_id: str,
    asset_id: str,
    req: GenerateAssetReferenceRequest,
    handler: AppHandler = Depends(get_state_service),
) -> GenerateAssetReferenceResponse:
    """Render a reference image for this asset with the project's image model."""
    return handler.film_generation.generate_asset_reference(project_id, asset_id, req)


@router.post(
    "/projects/{project_id}/assets/{asset_id}/reference-sheet",
    response_model=ReferenceSheetResponse,
)
def route_reference_sheet(
    project_id: str,
    asset_id: str,
    req: ReferenceSheetRequest,
    handler: AppHandler = Depends(get_state_service),
) -> ReferenceSheetResponse:
    """Consistency Kit: multi-angle references with one seed and the asset's LoRA."""
    return handler.film_generation.generate_reference_sheet(project_id, asset_id, req)


@router.put("/projects/{project_id}/assets/{asset_id}", response_model=AssetResponse)
def route_update_asset(
    project_id: str,
    asset_id: str,
    req: UpdateAssetRequest,
    handler: AppHandler = Depends(get_state_service),
) -> AssetResponse:
    return AssetResponse(asset=handler.film.update_asset(project_id, asset_id, req))


@router.delete("/projects/{project_id}/assets/{asset_id}", response_model=StatusResponse)
def route_delete_asset(
    project_id: str,
    asset_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    handler.film.delete_asset(project_id, asset_id)
    return StatusResponse(status="deleted")


@router.post("/projects/{project_id}/assets/{asset_id}/references", response_model=AssetResponse)
def route_add_asset_reference(
    project_id: str,
    asset_id: str,
    req: AddAssetReferenceRequest,
    handler: AppHandler = Depends(get_state_service),
) -> AssetResponse:
    return AssetResponse(asset=handler.film.add_asset_reference(project_id, asset_id, req))


@router.delete("/projects/{project_id}/assets/{asset_id}/references", response_model=AssetResponse)
def route_delete_asset_reference(
    project_id: str,
    asset_id: str,
    path: str,
    handler: AppHandler = Depends(get_state_service),
) -> AssetResponse:
    """Remove one reference image (by its relative path) and delete the file."""
    return AssetResponse(asset=handler.film.delete_asset_reference(project_id, asset_id, path))


# ---- Scenes ------------------------------------------------------------


@router.post("/projects/{project_id}/scenes", response_model=SceneResponse)
def route_create_scene(
    project_id: str,
    req: CreateSceneRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmScene:
    return handler.film.create_scene(project_id, req)


@router.put("/projects/{project_id}/scenes/{scene_id}", response_model=SceneResponse)
def route_update_scene(
    project_id: str,
    scene_id: str,
    req: UpdateSceneRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmScene:
    return handler.film.update_scene(project_id, scene_id, req)


@router.delete("/projects/{project_id}/scenes/{scene_id}", response_model=StatusResponse)
def route_delete_scene(
    project_id: str,
    scene_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    handler.film.delete_scene(project_id, scene_id)
    return StatusResponse(status="deleted")


@router.post("/projects/{project_id}/scenes/reorder", response_model=FilmProjectResponse)
def route_reorder_scenes(
    project_id: str,
    req: ReorderRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmProjectResponse:
    return FilmProjectResponse(project=handler.film.reorder_scenes(project_id, req))


# ---- Shots -------------------------------------------------------------


@router.post("/projects/{project_id}/scenes/{scene_id}/shots", response_model=ShotResponse)
def route_create_shot(
    project_id: str,
    scene_id: str,
    req: CreateShotRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmShot:
    return handler.film.create_shot(project_id, scene_id, req)


@router.put(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}", response_model=ShotResponse
)
def route_update_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    req: UpdateShotRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmShot:
    return handler.film.update_shot(project_id, scene_id, shot_id, req)


@router.delete(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}", response_model=StatusResponse
)
def route_delete_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    handler.film.delete_shot(project_id, scene_id, shot_id)
    return StatusResponse(status="deleted")


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/reorder", response_model=SceneResponse
)
def route_reorder_shots(
    project_id: str,
    scene_id: str,
    req: ReorderRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmScene:
    return handler.film.reorder_shots(project_id, scene_id, req)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/duplicate",
    response_model=ShotResponse,
)
def route_duplicate_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> FilmShot:
    return handler.film.duplicate_shot(project_id, scene_id, shot_id)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/deliver",
    response_model=DeliverResponse,
)
def route_deliver_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    req: DeliverRequest,
    handler: AppHandler = Depends(get_state_service),
) -> DeliverResponse:
    """Deliver package: rendered passes → mp4s in the project, wired as control signals."""
    return handler.film.deliver(project_id, scene_id, shot_id, req, handler.stitcher)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/capture",
    response_model=ShotResponse,
)
def route_capture_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    req: ShotCaptureRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FilmShot:
    return handler.film.capture_shot(project_id, scene_id, shot_id, req)


@router.post(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/versions/{number}/promote",
    response_model=PromoteVersionResponse,
)
def route_promote_version(
    project_id: str,
    scene_id: str,
    shot_id: str,
    number: int,
    handler: AppHandler = Depends(get_state_service),
) -> PromoteVersionResponse:
    shot = handler.film.promote_version(project_id, scene_id, shot_id, number)
    return PromoteVersionResponse(status="promoted", current_version=shot.current_version or number)


@router.delete(
    "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/versions/{number}",
    response_model=DeleteVersionResponse,
)
def route_delete_version(
    project_id: str,
    scene_id: str,
    shot_id: str,
    number: int,
    force: bool = False,
    handler: AppHandler = Depends(get_state_service),
) -> DeleteVersionResponse:
    """Delete one take's media, keeping its record.

    `force` is needed to delete the take the shot is currently on; the take on
    an approved shot is refused outright.
    """
    return handler.film.delete_version(project_id, scene_id, shot_id, number, force=force)


# ---- Poses -------------------------------------------------------------


@router.post("/projects/{project_id}/poses", response_model=PoseResponse)
def route_save_pose(
    project_id: str,
    req: SavePoseRequest,
    handler: AppHandler = Depends(get_state_service),
) -> PoseResponse:
    return PoseResponse(pose=handler.film.save_pose(project_id, req))


@router.delete("/projects/{project_id}/poses/{pose_id}", response_model=StatusResponse)
def route_delete_pose(
    project_id: str,
    pose_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> StatusResponse:
    handler.film.delete_pose(project_id, pose_id)
    return StatusResponse(status="deleted")


# ---- Continuity / media ------------------------------------------------


@router.get("/projects/{project_id}/continuity/{shot_id}", response_model=ContinuityResponse)
def route_shot_continuity(
    project_id: str,
    shot_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> ContinuityResponse:
    report = handler.film.continuity_report(project_id, shot_id)
    return ContinuityResponse(level=report.level, warnings=report.warnings)


@router.get("/projects/{project_id}/continuity", response_model=ProjectContinuityResponse)
def route_project_continuity(
    project_id: str, handler: AppHandler = Depends(get_state_service)
) -> ProjectContinuityResponse:
    return handler.film.project_continuity(project_id)


@router.post("/projects/{project_id}/continuity/{shot_id}/fix", response_model=FixContinuityResponse)
def route_fix_continuity(
    project_id: str,
    shot_id: str,
    req: FixContinuityRequest,
    handler: AppHandler = Depends(get_state_service),
) -> FixContinuityResponse:
    return handler.film.fix_continuity(project_id, shot_id, req)


@router.get("/projects/{project_id}/media")
def route_film_media(
    project_id: str,
    path: str = Query(min_length=1),
    handler: AppHandler = Depends(get_state_service),
) -> FileResponse:
    return FileResponse(handler.film.media_path(project_id, path))


# ---- Style guide ---------------------------------------------------------


@router.post(
    "/projects/{project_id}/assets/{asset_id}/style-guide",
    response_model=AssetResponse,
)
def route_generate_style_guide(
    project_id: str,
    asset_id: str,
    handler: AppHandler = Depends(get_state_service),
) -> AssetResponse:
    """Analyze an asset's first reference image with the configured vision
    provider and fill in its style guide (key traits, color palette, mood,
    recommended prompt, appearance, wardrobe)."""
    provider = handler.film_director.optional_provider("storyboard")
    if provider is None:
        raise HTTPError(400, "No AI provider configured — open Settings → AI Director to set one up")
    return AssetResponse(asset=handler.film.generate_asset_style_guide(project_id, asset_id, provider))
