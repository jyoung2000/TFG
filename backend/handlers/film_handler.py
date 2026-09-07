"""Film project CRUD: script, assets, scenes, shots, captures, poses.

All read-modify-write cycles on a film project happen under the shared app
lock; the store's writes are atomic. The generation queue lives in
film_generation_handler.
"""

from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path
from threading import RLock

from _routes._errors import HTTPError
from film.film_api_types import (
    AddAssetReferenceRequest,
    CreateAssetRequest,
    CreateSceneRequest,
    CreateShotRequest,
    ReorderRequest,
    SavePoseRequest,
    ShotCaptureRequest,
    UpdateAssetRequest,
    UpdateFilmSettingsRequest,
    UpdateSceneRequest,
    UpdateScriptRequest,
    UpdateShotRequest,
)
from film.film_continuity import ContinuityWarning, check_shot_continuity
from film.film_models import (
    FilmAsset,
    FilmPose,
    FilmProject,
    FilmScene,
    FilmShot,
    ShotCharacter,
    ShotStatus,
    now_ms,
)
from film.film_prompt import synthesize_prompt
from film.film_store import FilmStore, FilmStoreError
from handlers.base import StateHandlerBase
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

_VALID_SHOT_STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "composed",
        "ready",
        "queued",
        "generating",
        "review",
        "approved",
        "rejected",
    }
)

_MAX_CAPTURE_BYTES = 20 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def decode_image_base64(data: str, *, require_png: bool = True) -> bytes:
    """Decode a base64 (optionally data-URL) image payload with sanity checks."""
    if data.startswith("data:"):
        _, _, data = data.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPError(400, "Invalid base64 image payload") from exc
    if len(raw) > _MAX_CAPTURE_BYTES:
        raise HTTPError(400, "Image payload too large")
    if require_png and not raw.startswith(_PNG_MAGIC):
        raise HTTPError(400, "Image payload is not a PNG")
    return raw


class FilmHandler(StateHandlerBase):
    def __init__(self, state: AppState, lock: RLock, film_root: Path) -> None:
        super().__init__(state, lock)
        self._store = FilmStore(film_root)

    @property
    def store(self) -> FilmStore:
        return self._store

    # ---- Loading helpers -------------------------------------------------

    def _load(self, project_id: str) -> FilmProject:
        try:
            return self._store.load(project_id)
        except FilmStoreError as exc:
            raise HTTPError(400, str(exc)) from exc

    def _save(self, project: FilmProject) -> None:
        project.updated_at = now_ms()
        self._store.save(project)

    def _require_scene(self, project: FilmProject, scene_id: str) -> FilmScene:
        scene = project.scene(scene_id)
        if scene is None:
            raise HTTPError(404, f"Scene not found: {scene_id}")
        return scene

    def _require_shot(self, scene: FilmScene, shot_id: str) -> FilmShot:
        shot = scene.shot(shot_id)
        if shot is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        return shot

    def _refresh_prompt(self, project: FilmProject, scene: FilmScene, shot: FilmShot) -> None:
        if not shot.prompt_locked:
            shot.visual_prompt = synthesize_prompt(project, scene, shot)

    # ---- Project ---------------------------------------------------------

    def get_project(self, project_id: str) -> FilmProject:
        with self.lock:
            return self._load(project_id)

    def update_script(self, project_id: str, req: UpdateScriptRequest) -> FilmProject:
        with self.lock:
            project = self._load(project_id)
            project.script.content = req.content
            project.script.updated_at = now_ms()
            self._save(project)
            return project

    def update_settings(self, project_id: str, req: UpdateFilmSettingsRequest) -> FilmProject:
        with self.lock:
            project = self._load(project_id)
            project.settings = req.settings
            self._save(project)
            return project

    # ---- Assets ----------------------------------------------------------

    def create_asset(self, project_id: str, req: CreateAssetRequest) -> FilmAsset:
        if not req.name.strip():
            raise HTTPError(400, "Asset name is required")
        with self.lock:
            project = self._load(project_id)
            asset = FilmAsset(**req.model_dump())
            project.assets.append(asset)
            self._save(project)
            return asset

    def update_asset(self, project_id: str, asset_id: str, req: UpdateAssetRequest) -> FilmAsset:
        with self.lock:
            project = self._load(project_id)
            asset = project.asset(asset_id)
            if asset is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            updates = {key: value for key, value in req.model_dump().items() if value is not None}
            for key, value in updates.items():
                setattr(asset, key, value)
            asset.updated_at = now_ms()
            self._save(project)
            return asset

    def delete_asset(self, project_id: str, asset_id: str) -> None:
        with self.lock:
            project = self._load(project_id)
            if project.asset(asset_id) is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            project.assets = [a for a in project.assets if a.id != asset_id]
            # Scrub references so shots/scenes never point at a ghost asset.
            for scene in project.scenes:
                if scene.location_id == asset_id:
                    scene.location_id = None
                scene.character_ids = [c for c in scene.character_ids if c != asset_id]
                scene.prop_ids = [p for p in scene.prop_ids if p != asset_id]
                for shot in scene.shots:
                    if shot.location_id == asset_id:
                        shot.location_id = None
                    shot.characters = [c for c in shot.characters if c.asset_id != asset_id]
                    shot.prop_ids = [p for p in shot.prop_ids if p != asset_id]
            self._save(project)

    def add_asset_reference(
        self, project_id: str, asset_id: str, req: AddAssetReferenceRequest
    ) -> FilmAsset:
        raw = decode_image_base64(req.image_base64, require_png=False)
        with self.lock:
            project = self._load(project_id)
            asset = project.asset(asset_id)
            if asset is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            relative = self._store.save_reference_image(project_id, req.name_hint, raw)
            asset.reference_images.append(relative)
            asset.updated_at = now_ms()
            self._save(project)
            return asset

    # ---- Scenes ----------------------------------------------------------

    def create_scene(self, project_id: str, req: CreateSceneRequest) -> FilmScene:
        with self.lock:
            project = self._load(project_id)
            scene = FilmScene(order=len(project.scenes), **req.model_dump())
            if not scene.title:
                scene.title = f"Scene {len(project.scenes) + 1}"
            project.scenes.append(scene)
            self._save(project)
            return scene

    def update_scene(self, project_id: str, scene_id: str, req: UpdateSceneRequest) -> FilmScene:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            data = req.model_dump()
            clear_location = bool(data.pop("clear_location"))
            for key, value in data.items():
                if value is not None:
                    setattr(scene, key, value)
            if clear_location:
                scene.location_id = None
            for shot in scene.shots:
                self._refresh_prompt(project, scene, shot)
            self._save(project)
            return scene

    def delete_scene(self, project_id: str, scene_id: str) -> None:
        with self.lock:
            project = self._load(project_id)
            self._require_scene(project, scene_id)
            project.scenes = [s for s in project.scenes if s.id != scene_id]
            for order, scene in enumerate(sorted(project.scenes, key=lambda s: s.order)):
                scene.order = order
            self._save(project)

    def reorder_scenes(self, project_id: str, req: ReorderRequest) -> FilmProject:
        with self.lock:
            project = self._load(project_id)
            existing = {scene.id for scene in project.scenes}
            if set(req.ordered_ids) != existing or len(req.ordered_ids) != len(project.scenes):
                raise HTTPError(400, "ordered_ids must be a permutation of the project's scene ids")
            order_by_id = {scene_id: index for index, scene_id in enumerate(req.ordered_ids)}
            for scene in project.scenes:
                scene.order = order_by_id[scene.id]
            project.scenes.sort(key=lambda s: s.order)
            self._save(project)
            return project

    # ---- Shots -----------------------------------------------------------

    def create_shot(self, project_id: str, scene_id: str, req: CreateShotRequest) -> FilmShot:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            shot = FilmShot(order=len(scene.shots), **req.model_dump())
            if not shot.title:
                shot.title = f"Shot {len(scene.shots) + 1}"
            # New shots inherit the scene's cast and location as a starting point.
            shot.location_id = scene.location_id
            shot.characters = [ShotCharacter(asset_id=cid) for cid in scene.character_ids]
            self._refresh_prompt(project, scene, shot)
            scene.shots.append(shot)
            self._save(project)
            return shot

    def update_shot(
        self, project_id: str, scene_id: str, shot_id: str, req: UpdateShotRequest
    ) -> FilmShot:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            shot = self._require_shot(scene, shot_id)
            provided = set(req.model_fields_set)
            clear_location = req.clear_location
            if "status" in provided and req.status is not None:
                if req.status not in _VALID_SHOT_STATUSES:
                    raise HTTPError(400, f"Invalid shot status: {req.status}")
                shot.status = req.status  # type: ignore[assignment]
            if "visual_prompt" in provided and req.visual_prompt is not None:
                # An explicit prompt edit locks synthesis unless the caller
                # also unlocks it in the same request.
                shot.prompt_locked = True
            for key in provided - {"clear_location", "status"}:
                value = getattr(req, key)
                if value is not None:
                    # Assign the validated model instances from the request, so
                    # nested models (framing, characters, composition, ...)
                    # land typed rather than as raw dicts.
                    setattr(shot, key, value)
            if clear_location:
                shot.location_id = None
            if shot.composition is not None:
                shot.framing = shot.composition.framing
                shot.camera_move = shot.composition.camera_move
                if shot.status == "draft":
                    shot.status = "composed"
            shot.updated_at = now_ms()
            self._refresh_prompt(project, scene, shot)
            self._save(project)
            return shot

    def delete_shot(self, project_id: str, scene_id: str, shot_id: str) -> None:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            self._require_shot(scene, shot_id)
            scene.shots = [s for s in scene.shots if s.id != shot_id]
            for order, shot in enumerate(sorted(scene.shots, key=lambda s: s.order)):
                shot.order = order
            self._save(project)

    def reorder_shots(self, project_id: str, scene_id: str, req: ReorderRequest) -> FilmScene:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            existing = {shot.id for shot in scene.shots}
            if set(req.ordered_ids) != existing or len(req.ordered_ids) != len(scene.shots):
                raise HTTPError(400, "ordered_ids must be a permutation of the scene's shot ids")
            order_by_id = {shot_id: index for index, shot_id in enumerate(req.ordered_ids)}
            for shot in scene.shots:
                shot.order = order_by_id[shot.id]
            scene.shots.sort(key=lambda s: s.order)
            self._save(project)
            return scene

    def duplicate_shot(self, project_id: str, scene_id: str, shot_id: str) -> FilmShot:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            source = self._require_shot(scene, shot_id)
            copy = source.model_copy(deep=True)
            copy.id = FilmShot().id  # fresh id
            copy.title = f"{source.title} (copy)" if source.title else "Shot (copy)"
            copy.order = len(scene.shots)
            copy.versions = []
            copy.current_version = None
            copy.capture_path = ""
            copy.status = "composed" if copy.composition is not None else "draft"
            copy.created_at = now_ms()
            copy.updated_at = now_ms()
            scene.shots.append(copy)
            self._save(project)
            return copy

    # ---- Capture ---------------------------------------------------------

    def capture_shot(
        self, project_id: str, scene_id: str, shot_id: str, req: ShotCaptureRequest
    ) -> FilmShot:
        raw = decode_image_base64(req.image_base64)
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            shot = self._require_shot(scene, shot_id)
            shot.composition = req.composition
            shot.framing = req.composition.framing
            shot.camera_move = req.composition.camera_move
            shot.capture_path = self._store.save_capture(
                project_id, shot_id, raw, req.composition.model_dump_json(indent=2)
            )
            if shot.status in ("draft", "composed"):
                shot.status = "ready"
            shot.updated_at = now_ms()
            self._refresh_prompt(project, scene, shot)
            self._save(project)
            return shot

    # ---- Poses -----------------------------------------------------------

    def save_pose(self, project_id: str, req: SavePoseRequest) -> FilmPose:
        if not req.name.strip():
            raise HTTPError(400, "Pose name is required")
        with self.lock:
            project = self._load(project_id)
            pose = FilmPose(name=req.name.strip(), category=req.category, joints=req.joints)
            project.pose_library = [p for p in project.pose_library if p.name != pose.name]
            project.pose_library.append(pose)
            self._save(project)
            return pose

    def delete_pose(self, project_id: str, pose_id: str) -> None:
        with self.lock:
            project = self._load(project_id)
            if not any(p.id == pose_id for p in project.pose_library):
                raise HTTPError(404, f"Pose not found: {pose_id}")
            project.pose_library = [p for p in project.pose_library if p.id != pose_id]
            self._save(project)

    # ---- Versions --------------------------------------------------------

    def promote_version(self, project_id: str, scene_id: str, shot_id: str, number: int) -> FilmShot:
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            shot = self._require_shot(scene, shot_id)
            version = shot.version(number)
            if version is None:
                raise HTTPError(404, f"Version not found: {number}")
            if version.status != "complete":
                raise HTTPError(400, "Only completed versions can be promoted")
            shot.current_version = number
            shot.status = "review" if shot.status not in ("approved", "rejected") else shot.status
            shot.updated_at = now_ms()
            self._save(project)
            return shot

    # ---- Continuity / media ----------------------------------------------

    def continuity(self, project_id: str, shot_id: str) -> list[ContinuityWarning]:
        with self.lock:
            project = self._load(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        scene, shot = found
        return check_shot_continuity(project, scene, shot)

    def media_path(self, project_id: str, relative: str) -> Path:
        try:
            path = self._store.resolve_media_path(project_id, relative)
        except FilmStoreError as exc:
            raise HTTPError(400, str(exc)) from exc
        if not path.is_file():
            raise HTTPError(404, f"Media not found: {relative}")
        return path

    def update_shot_status(self, project_id: str, shot_id: str, status: ShotStatus) -> None:
        """Internal helper used by the generation queue."""
        with self.lock:
            project = self._load(project_id)
            found = project.find_shot(shot_id)
            if found is None:
                return
            _, shot = found
            shot.status = status
            shot.updated_at = now_ms()
            self._save(project)
