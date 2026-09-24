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
    ContinuityResponse,
    CreateAssetRequest,
    CreateSceneRequest,
    CreateShotRequest,
    DeleteVersionResponse,
    ExportPackageRequest,
    FixContinuityRequest,
    FixContinuityResponse,
    ImportGenerationRequest,
    ImportGenerationResponse,
    ImportPackageRequest,
    ImportPackageResponse,
    PackageSummaryResponse,
    ProjectContinuityResponse,
    ReorderRequest,
    ReplaceProjectRequest,
    SavePoseRequest,
    ShotCaptureRequest,
    ShotContinuitySummary,
    UpdateAssetRequest,
    UpdateFilmSettingsRequest,
    UpdateSceneRequest,
    UpdateScriptRequest,
    UpdateShotRequest,
)
from film.film_continuity import (
    ContinuityReport,
    ContinuityWarning,
    check_shot_continuity,
    continuity_level,
    shot_continuity_report,
)
from film.film_models import (
    CompositionObject,
    CompositionTransform,
    FilmAsset,
    FilmAssetStyleGuide,
    FilmPose,
    FilmProject,
    FilmScene,
    FilmShot,
    ShotCharacter,
    ShotGenerationSettings,
    ShotStatus,
    ShotVersion,
    now_ms,
)
from film.film_package import (
    PACKAGE_EXTENSION,
    FilmPackageError,
    PackageSummary,
    export_package,
    import_package,
    inspect_package,
)
from film.film_prompt import synthesize_prompt
from film.film_store import FilmStore, FilmStoreError
from server_utils.path_policy import (
    PathPolicyError,
    is_within,
    require_absolute_file,
    require_destination,
)
from film.knowledge_models import KnowledgeEvent
from film.llm_providers import LLMMessage, LLMProvider
from handlers.base import StateHandlerBase
from handlers.knowledge_handler import KnowledgeHandler
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


def sync_composition_and_cast(project: FilmProject, shot: FilmShot, *, cast_is_authoritative: bool = False) -> None:
    """ONE SHOT STATE invariant: the shot's cast/props and its composer objects
    describe the same thing.

    - A figure placed in the composer that links to a character asset becomes
      part of ``shot.characters``.
    - A character assigned to the shot gets a figure in an existing
      composition; a prop gets a placeholder primitive.
    - Composer objects linked to assets the shot no longer references are
      removed (unlinked figures/primitives are left alone).

    ``cast_is_authoritative`` is set when the caller edited the cast itself
    (storyboard card, director ``assign_character``), so removing a character
    also removes its figure instead of the figure re-adding the character.
    """
    composition = shot.composition
    if composition is None:
        return
    character_ids = {c.asset_id for c in shot.characters}
    prop_ids = set(shot.prop_ids)
    # Composer → cast
    for obj in [] if cast_is_authoritative else composition.objects:
        if obj.type == "figure" and obj.asset_id and obj.asset_id not in character_ids:
            asset = project.asset(obj.asset_id)
            if asset is not None and asset.kind == "character":
                shot.characters.append(ShotCharacter(asset_id=obj.asset_id))
                character_ids.add(obj.asset_id)
        elif obj.type != "figure" and obj.asset_id and obj.asset_id not in prop_ids:
            asset = project.asset(obj.asset_id)
            if asset is not None and asset.kind == "prop":
                shot.prop_ids.append(obj.asset_id)
                prop_ids.add(obj.asset_id)
    # Cast → composer
    linked = {obj.asset_id for obj in composition.objects if obj.asset_id}
    figure_count = sum(1 for obj in composition.objects if obj.type == "figure")
    for index, shot_character in enumerate(shot.characters):
        if shot_character.asset_id in linked:
            continue
        asset = project.asset(shot_character.asset_id)
        if asset is None:
            continue
        composition.objects.append(
            CompositionObject(
                name=asset.name,
                type="figure",
                asset_id=asset.id,
                transform=CompositionTransform(position=((figure_count + index) * 1.2, 0.0, 0.0)),
            )
        )
        linked.add(asset.id)
    for index, prop_id in enumerate(shot.prop_ids):
        if prop_id in linked:
            continue
        asset = project.asset(prop_id)
        if asset is None:
            continue
        composition.objects.append(
            CompositionObject(
                name=asset.name,
                type="cube",
                asset_id=asset.id,
                transform=CompositionTransform(position=(-1.5 - index * 0.8, 0.0, 0.8)),
            )
        )
        linked.add(asset.id)
    # Remove objects whose linked asset the shot no longer uses (or that no longer exists).
    keep: list[CompositionObject] = []
    for obj in composition.objects:
        if obj.asset_id and obj.asset_id not in character_ids and obj.asset_id not in prop_ids:
            continue
        keep.append(obj)
    composition.objects = keep
    valid_ids = {obj.id for obj in composition.objects}
    if composition.framing.ots_foreground_id and composition.framing.ots_foreground_id not in valid_ids:
        composition.framing.ots_foreground_id = None
    if composition.framing.ots_subject_id and composition.framing.ots_subject_id not in valid_ids:
        composition.framing.ots_subject_id = None
    shot.framing = composition.framing


class FilmHandler(StateHandlerBase):
    def __init__(self, state: AppState, lock: RLock, film_root: Path) -> None:
        super().__init__(state, lock)
        self._store = FilmStore(film_root)
        # The preview route serves only files under the app outputs root
        # (film_root's parent); external imports are copied in so they play.
        self._app_outputs = film_root.parent
        self._knowledge: KnowledgeHandler | None = None

    @property
    def store(self) -> FilmStore:
        return self._store

    def attach_knowledge(self, knowledge: KnowledgeHandler) -> None:
        """Give approvals somewhere to be remembered.

        Attached after construction rather than injected, so the two handlers
        can be built in any order and this one keeps working untouched if the
        knowledge engine is never attached.
        """
        self._knowledge = knowledge

    def _record_judgement(
        self,
        *,
        kind: str,
        shot: FilmShot,
        project_id: str,
        scene_id: str,
    ) -> None:
        """Report an approval decision to the knowledge engine, best-effort.

        Called outside any heavy work and after the save, so an opinion about
        the result can never be the reason the result was not stored. The
        prompt travels with it: that is what makes phrase-level patterns
        attributable to something the user actually kept.
        """
        if self._knowledge is None:
            return
        version = shot.version(shot.current_version) if shot.current_version else None
        self._knowledge.record(
            KnowledgeEvent(
                kind=kind,  # type: ignore[arg-type]
                project_id=project_id,
                scene_id=scene_id,
                shot_id=shot.id,
                version_number=shot.current_version,
                model=version.model if version else "",
                provider=version.execution_mode if version else "",
                task="video",
                execution_mode=version.execution_mode if version else "",
                prompt=version.prompt if version else shot.visual_prompt,
                negative_prompt=version.negative_prompt if version else "",
            )
        )

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

    def replace_project(self, project_id: str, req: ReplaceProjectRequest, *, busy_shot_ids: set[str]) -> FilmProject:
        """Replace the whole project facet with a validated snapshot (undo/redo).

        Output files on disk are untouched, so a version restored by undo still
        plays. Refused while any shot of the project is queued or rendering,
        because the queue holds references into the live record.
        """
        with self.lock:
            current = self._load(project_id)
            if busy_shot_ids:
                raise HTTPError(409, "Wait for the queued or running generation to finish before undoing")
            incoming = req.project.model_copy(deep=True)
            incoming.id = current.id
            incoming.schema_version = current.schema_version
            incoming.created_at = current.created_at
            # Composer-derived fields must stay consistent after a restore.
            for scene in incoming.scenes:
                for shot in scene.shots:
                    sync_composition_and_cast(incoming, shot)
                    self._refresh_prompt(incoming, scene, shot)
            self._save(incoming)
            return incoming

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
            clear_gap = bool(data.pop("clear_gap"))
            for key, value in data.items():
                if value is not None:
                    setattr(scene, key, value)
            if clear_location:
                scene.location_id = None
            if clear_gap:
                scene.inter_shot_gap_seconds = None
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
            judgement = ""
            if "status" in provided and req.status is not None:
                if req.status not in _VALID_SHOT_STATUSES:
                    raise HTTPError(400, f"Invalid shot status: {req.status}")
                if req.status != shot.status and req.status in ("approved", "rejected"):
                    # Only a change counts. Re-saving an approved shot is not a
                    # second endorsement of the model that made it.
                    judgement = "version_approved" if req.status == "approved" else "version_rejected"
                shot.status = req.status  # type: ignore[assignment]
            if "visual_prompt" in provided and req.visual_prompt is not None:
                # An explicit prompt edit locks synthesis unless the caller
                # also unlocks it in the same request.
                shot.prompt_locked = True
            for key in provided - {"clear_location", "clear_gap", "status"}:
                value = getattr(req, key)
                if value is not None:
                    # Assign the validated model instances from the request, so
                    # nested models (framing, characters, composition, ...)
                    # land typed rather than as raw dicts.
                    setattr(shot, key, value)
            if clear_location:
                shot.location_id = None
            if req.clear_gap:
                shot.gap_before_seconds = None
            if shot.composition is not None:
                # ONE SHOT STATE: the composition carries the authoritative
                # framing/camera move, so an explicit framing edit (card, director)
                # is written into the composition rather than overwritten by it.
                if "framing" in provided and req.framing is not None and "composition" not in provided:
                    shot.composition.framing = req.framing
                if "camera_move" in provided and req.camera_move is not None and "composition" not in provided:
                    shot.composition.camera_move = req.camera_move
                shot.framing = shot.composition.framing
                shot.camera_move = shot.composition.camera_move
                if shot.status == "draft":
                    shot.status = "composed"
            sync_composition_and_cast(
                project,
                shot,
                cast_is_authoritative=bool(provided & {"characters", "prop_ids"}) and "composition" not in provided,
            )
            shot.updated_at = now_ms()
            self._refresh_prompt(project, scene, shot)
            self._save(project)

        # Outside the lock: the shot is already saved, so recording an opinion
        # about it can never cost the edit.
        if judgement:
            self._record_judgement(kind=judgement, shot=shot, project_id=project_id, scene_id=scene_id)
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

        self._record_judgement(
            kind="version_promoted", shot=shot, project_id=project_id, scene_id=scene_id
        )
        return shot

    def delete_version(
        self, project_id: str, scene_id: str, shot_id: str, number: int, *, force: bool = False
    ) -> DeleteVersionResponse:
        """Remove one take's media, keeping the record of it.

        Deleting a take is not the same as deleting a shot, and it must not
        quietly undo a decision the user already made:

        * The take the shot is currently on is refused unless the caller says
          it means it, and the take on an *approved* shot is refused outright —
          throwing away the render that was signed off is not an edit, it is a
          loss.
        * A take still rendering is refused: the worker would write its output
          into a file this call just removed.
        * The record survives as a tombstone. Its number is never reused and
          its prompt, model, seed and snapshot stay, so a deleted take can
          still be explained — and re-rendered from exactly what produced it.
        * Media is only removed from inside this app's own outputs. A version
          imported from elsewhere (Quick Mode, an analysed clip) points at a
          file the user owns, and that file is left alone and reported as kept.
        """
        removed_path = ""
        media = "missing"
        with self.lock:
            project = self._load(project_id)
            scene = self._require_scene(project, scene_id)
            shot = self._require_shot(scene, shot_id)
            version = shot.version(number)
            if version is None:
                raise HTTPError(404, f"Version not found: {number}")
            if version.status == "deleted":
                raise HTTPError(400, f"Version {number} is already deleted")
            if version.status in ("queued", "generating"):
                raise HTTPError(400, "That take is still rendering — cancel it before deleting it")
            if shot.current_version == number:
                if shot.status == "approved":
                    raise HTTPError(
                        400,
                        "That is the approved take. Approve a different one, or set the shot back "
                        "to review, before deleting it.",
                    )
                if not force:
                    raise HTTPError(
                        409,
                        f"Version {number} is the take this shot is currently on. "
                        "Delete it with force=true, or promote another take first.",
                    )

            media, removed_path = self._remove_version_media(project_id, version)
            version.status = "deleted"
            version.deleted_at = now_ms()
            version.deleted_media = media
            version.output_path = ""
            version.error = ""

            if shot.current_version == number:
                # Fall back to the newest take that still has media, so the
                # shot shows something rather than a gap.
                survivor = next(
                    (
                        candidate.number
                        for candidate in sorted(shot.versions, key=lambda v: v.number, reverse=True)
                        if candidate.status == "complete"
                    ),
                    None,
                )
                shot.current_version = survivor
                if survivor is None and shot.status in ("review", "approved", "rejected"):
                    shot.status = "ready" if shot.capture_path else "draft"

            shot.updated_at = now_ms()
            self._save(project)
            remaining = sum(1 for v in shot.versions if v.status == "complete")
            current = shot.current_version

        # Outside the lock, and after the save: an opinion about a take can
        # never be the reason the deletion did not stick.
        if self._knowledge is not None:
            self._knowledge.record(
                KnowledgeEvent(
                    kind="version_deleted",
                    project_id=project_id,
                    scene_id=scene_id,
                    shot_id=shot_id,
                    version_number=number,
                    model=version.model,
                    provider=version.execution_mode,
                    task="video",
                    execution_mode=version.execution_mode,
                    prompt=version.prompt,
                )
            )

        return DeleteVersionResponse(
            status="deleted",
            number=number,
            media=media,
            # The path is returned so the renderer can find any timeline clip
            # that pointed at it and mark it, rather than silently showing a
            # clip whose file has gone.
            removed_path=removed_path,
            current_version=current,
            remaining_versions=remaining,
        )

    def _remove_version_media(self, project_id: str, version: ShotVersion) -> tuple[str, str]:
        """Delete the take's output, but only from inside this app's outputs.

        Returns (what happened, the path it was at). A version imported from
        Quick Mode or an analysed clip points at a file the user owns; deleting
        that because they tidied up a take would be destroying their own media.
        """
        if not version.output_path:
            return "missing", ""
        path = Path(version.output_path)
        outputs = self._store.outputs_dir(project_id)
        if not is_within(outputs, path):
            return "kept", version.output_path
        try:
            if not path.is_file():
                return "missing", version.output_path
            path.unlink()
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
            return "kept", version.output_path
        return "removed", version.output_path

    # ---- Quick Mode → Film conversion ------------------------------------

    def _previewable_copy(self, project_id: str, source: Path) -> Path:
        """Return a path the /api/film/output preview route can serve.

        Files already under the outputs root are used in place. Anything else
        (a clip from the user's Videos folder) is copied into the project's
        outputs so shot cards, the drawer and the composer can play it. The
        user's original is never moved or modified.
        """
        if is_within(self._app_outputs, source):
            return source
        import shutil
        import uuid

        destination_dir = self._store.outputs_dir(project_id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"imported-{uuid.uuid4().hex[:10]}{source.suffix.lower()}"
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise HTTPError(500, f"Could not copy the imported clip for preview: {exc}") from exc
        return destination

    def import_generation(self, project_id: str, req: ImportGenerationRequest) -> ImportGenerationResponse:
        """Wrap an already-rendered clip as a new scene/shot whose version 1 is
        that clip, so a Quick Mode result can be edited in the Film Maker with
        prompt, model, resolution, duration, seed and output all preserved."""
        prompt = req.prompt.strip()
        if not prompt:
            raise HTTPError(400, "prompt is required")
        try:
            output = require_absolute_file(
                req.output_path, what="Generated video", allowed_suffixes=(".mp4", ".webm", ".mov", ".m4v", ".mkv")
            )
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        duration = max(0.5, min(60.0, float(req.duration_seconds)))
        fps = max(1, min(120, int(req.fps)))
        aspect: str = req.aspect_ratio if req.aspect_ratio in ("16:9", "9:16") else "16:9"
        with self.lock:
            project = self._load(project_id)
            output = self._previewable_copy(project_id, output)
            if req.project_name and not project.name:
                project.name = req.project_name
            scene = FilmScene(order=len(project.scenes), title=f"Scene {len(project.scenes) + 1}", description=prompt[:200])
            shot = FilmShot(
                order=0,
                title=req.title.strip() or "Shot 1",
                description=prompt,
                duration_seconds=duration,
                visual_prompt=prompt,
                negative_prompt=req.negative_prompt,
                prompt_locked=True,
                generation=ShotGenerationSettings(
                    model=req.model,
                    resolution=req.resolution,
                    fps=fps,
                    seed=req.seed,
                    aspect_ratio=aspect,  # type: ignore[arg-type]
                    use_capture_as_reference=False,
                ),
                status="review",
            )
            shot.versions.append(
                ShotVersion(
                    number=1,
                    kind="final",
                    status="complete",
                    prompt=prompt,
                    negative_prompt=req.negative_prompt,
                    model=req.model,
                    resolution=req.resolution,
                    fps=fps,
                    duration_seconds=duration,
                    seed=req.seed,
                    capture_path=req.input_image_path if req.mode == "image-to-video" else "",
                    output_path=str(output),
                )
            )
            shot.current_version = 1
            scene.shots.append(shot)
            project.scenes.append(scene)
            self._save(project)
            return ImportGenerationResponse(project=project, scene_id=scene.id, shot_id=shot.id, version_number=1)

    # ---- Packages (export / import) ---------------------------------------

    @staticmethod
    def _summary_response(summary: PackageSummary, path: str = "") -> PackageSummaryResponse:
        return PackageSummaryResponse(
            project_id=summary.project_id,
            project_name=summary.project_name,
            schema_version=summary.schema_version,
            scenes=summary.scenes,
            shots=summary.shots,
            assets=summary.assets,
            media_files=summary.media_files,
            includes_outputs=summary.includes_outputs,
            total_bytes=summary.total_bytes,
            warnings=summary.warnings,
            path=path,
        )

    def export_package(self, project_id: str, req: ExportPackageRequest) -> PackageSummaryResponse:
        try:
            destination = require_destination(req.destination_path, suffix=PACKAGE_EXTENSION, what="destination_path")
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        with self.lock:
            self._load(project_id)  # 400 on bad id; creates the facet if missing
            try:
                summary = export_package(
                    self._store,
                    project_id,
                    destination,
                    include_outputs=req.include_outputs,
                    host_project=req.host_project,
                )
            except (FilmStoreError, FilmPackageError, OSError) as exc:
                raise HTTPError(400, f"Export failed: {exc}") from exc
        return self._summary_response(summary, path=str(destination))

    def inspect_package(self, package_path: str) -> PackageSummaryResponse:
        try:
            path = require_absolute_file(package_path, what="package_path", allowed_suffixes=(PACKAGE_EXTENSION, ".zip"))
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        try:
            summary = inspect_package(path)
        except FilmPackageError as exc:
            raise HTTPError(400, str(exc)) from exc
        return self._summary_response(summary, path=str(path))

    def import_package(self, project_id: str, req: ImportPackageRequest) -> ImportPackageResponse:
        try:
            path = require_absolute_file(req.package_path, what="package_path", allowed_suffixes=(PACKAGE_EXTENSION, ".zip"))
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        with self.lock:
            current = self._load(project_id)
            if (current.scenes or current.assets or current.script.content.strip()) and not req.replace:
                raise HTTPError(
                    409,
                    "This project already has content. Import into a new project, or pass replace=true to overwrite it.",
                )
            try:
                result = import_package(self._store, path, project_id)
            except FilmPackageError as exc:
                raise HTTPError(400, str(exc)) from exc
            except FilmStoreError as exc:
                raise HTTPError(400, str(exc)) from exc
        return ImportPackageResponse(
            summary=self._summary_response(result.summary, path=str(path)),
            project=result.project,
            host_project=result.host_project,
            output_path_map=result.output_path_map,
        )

    # ---- Continuity / media ----------------------------------------------

    def continuity(self, project_id: str, shot_id: str) -> list[ContinuityWarning]:
        return self.continuity_report(project_id, shot_id).warnings

    def continuity_report(self, project_id: str, shot_id: str) -> ContinuityReport:
        with self.lock:
            project = self._load(project_id)
        found = project.find_shot(shot_id)
        if found is None:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        scene, shot = found
        return shot_continuity_report(project, scene, shot)

    def project_continuity(self, project_id: str) -> ProjectContinuityResponse:
        with self.lock:
            project = self._load(project_id)
        summaries: list[ShotContinuitySummary] = []
        counts: dict[str, int] = {"good": 0, "minor": 0, "significant": 0, "broken": 0}
        worst: list[ContinuityWarning] = []
        for scene in sorted(project.scenes, key=lambda s: s.order):
            for shot in sorted(scene.shots, key=lambda s: s.order):
                warnings = check_shot_continuity(project, scene, shot)
                level = continuity_level(warnings)
                counts[level] = counts.get(level, 0) + 1
                worst.extend(warnings)
                summaries.append(
                    ShotContinuitySummary(shot_id=shot.id, scene_id=scene.id, level=level, warning_count=len(warnings))
                )
        return ProjectContinuityResponse(level=continuity_level(worst), shots=summaries, counts=counts)

    def fix_continuity(self, project_id: str, shot_id: str, req: FixContinuityRequest) -> FixContinuityResponse:
        """Apply the built-in repair for one warning kind. Each fix is the same
        mutation the user could make by hand in the UI."""
        with self.lock:
            project = self._load(project_id)
            found = project.find_shot(shot_id)
            if found is None:
                raise HTTPError(404, f"Shot not found: {shot_id}")
            scene, shot = found
            message = ""
            kind = req.kind
            if kind == "character_not_in_scene":
                ids = [c.asset_id for c in shot.characters if not req.subject_id or c.asset_id == req.subject_id]
                added = [i for i in ids if i not in scene.character_ids]
                scene.character_ids.extend(added)
                message = f"Added {len(added)} character(s) to the scene's cast."
            elif kind == "prop_not_in_scene":
                ids = [p for p in shot.prop_ids if not req.subject_id or p == req.subject_id]
                added = [i for i in ids if i not in scene.prop_ids]
                scene.prop_ids.extend(added)
                message = f"Added {len(added)} prop(s) to the scene."
            elif kind == "location_mismatch":
                if scene.location_id is None:
                    raise HTTPError(400, "The scene has no location to align to")
                shot.location_id = scene.location_id
                message = "Shot now uses the scene's location."
            elif kind == "missing_asset":
                before = len(shot.characters) + len(shot.prop_ids) + (1 if shot.location_id else 0)
                shot.characters = [c for c in shot.characters if project.asset(c.asset_id) is not None]
                shot.prop_ids = [p for p in shot.prop_ids if project.asset(p) is not None]
                if shot.location_id is not None and project.asset(shot.location_id) is None:
                    shot.location_id = None
                scene.character_ids = [c for c in scene.character_ids if project.asset(c) is not None]
                scene.prop_ids = [p for p in scene.prop_ids if project.asset(p) is not None]
                after = len(shot.characters) + len(shot.prop_ids) + (1 if shot.location_id else 0)
                message = f"Removed {before - after} dangling reference(s)."
            elif kind == "missing_capture":
                shot.generation.use_capture_as_reference = False
                message = "The shot will generate from text only until a capture exists."
            elif kind == "missing_previous_output":
                shot.generation.continue_from_previous = False
                message = "Continue-from-previous turned off for this shot."
            elif kind == "duration_invalid":
                shot.duration_seconds = 4.0
                message = "Duration set to 4 seconds."
            else:
                report = shot_continuity_report(project, scene, shot)
                return FixContinuityResponse(
                    fixed=False,
                    message="This warning needs a creative decision — regenerate the earlier shot or restore the wardrobe.",
                    report=ContinuityResponse(level=report.level, warnings=report.warnings),
                    shot=shot,
                )
            self._refresh_prompt(project, scene, shot)
            shot.updated_at = now_ms()
            self._save(project)
            report = shot_continuity_report(project, scene, shot)
            return FixContinuityResponse(
                fixed=True,
                message=message,
                report=ContinuityResponse(level=report.level, warnings=report.warnings),
                shot=shot,
            )

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

    # ---- Style guide generation -------------------------------------------

    def generate_asset_style_guide(
        self, project_id: str, asset_id: str, provider: LLMProvider
    ) -> FilmAsset:
        """Analyze an asset's first reference image with the vision provider
        and fill in its style guide and derived appearance/wardrobe fields."""
        import json
        import re
        from typing import cast

        with self.lock:
            project = self._load(project_id)
            asset = project.asset(asset_id)
            if asset is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            if not asset.reference_images:
                raise HTTPError(400, "Asset has no reference image to analyze")
            ref_relative = asset.reference_images[0]
        try:
            ref_path = self._store.resolve_media_path(project_id, ref_relative)
        except FilmStoreError as exc:
            raise HTTPError(400, str(exc)) from exc
        if not ref_path.is_file():
            raise HTTPError(400, f"Reference image not found: {ref_relative}")

        raw = ref_path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        mime = "image/png" if ref_path.suffix.lower() == ".png" else "image/jpeg"
        data_url = f"data:{mime};base64,{encoded}"

        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"You are a visual development designer specializing in {asset.kind} assets. Analyze this reference image and return JSON ONLY: "
                    "{key_traits: [...], color_palette: [...], mood: '...', "
                    "recommended_prompt: '...', appearance: '...', wardrobe: '...', "
                    "description: '...'}. Only describe what you can see. Mark uncertain details."
                ),
            ),
            LLMMessage(
                role="user",
                content="Analyze this reference image.",
                images=[data_url],
            ),
        ]

        reply = provider.chat(messages, json_mode=True)
        text = reply.text.strip()

        # Tolerate small-model quirks — extract the first JSON object.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            parsed = json.loads(match.group(0) if match else text)
        except (json.JSONDecodeError, AttributeError) as exc:
            raise HTTPError(502, f"Style guide generation returned unparseable JSON: {text[:200]}") from exc

        if not isinstance(parsed, dict):
            raise HTTPError(502, "Style guide response must be a JSON object")
        parsed = cast(dict[str, object], parsed)

        def clean_text(value: object) -> str:
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                return "; ".join(
                    item.strip() for item in cast(list[object], value)
                    if isinstance(item, str) and item.strip()
                )
            return ""

        def clean_list(value: object) -> list[str]:
            if isinstance(value, str):
                return [value.strip()] if value.strip() else []
            if isinstance(value, list):
                return [item.strip() for item in cast(list[object], value) if isinstance(item, str) and item.strip()]
            return []

        key_traits: list[str] = []
        raw_traits = parsed.get("key_traits", [])
        key_traits = clean_list(raw_traits)

        color_palette: list[str] = []
        raw_palette = parsed.get("color_palette", [])
        color_palette = clean_list(raw_palette)

        mood = clean_text(parsed.get("mood", ""))
        recommended_prompt = clean_text(parsed.get("recommended_prompt", ""))
        appearance = clean_text(parsed.get("appearance", ""))
        wardrobe = clean_text(parsed.get("wardrobe", ""))
        description = clean_text(parsed.get("description", ""))

        with self.lock:
            project = self._load(project_id)
            asset = project.asset(asset_id)
            if asset is None:
                raise HTTPError(404, f"Asset not found: {asset_id}")
            asset.style_guide = FilmAssetStyleGuide(
                key_traits=key_traits,
                color_palette=color_palette,
                mood=mood,
                recommended_prompt=recommended_prompt,
            )
            if appearance:
                asset.appearance = appearance
            if wardrobe:
                asset.wardrobe = wardrobe
            if description:
                asset.description = description
            if asset.kind == "style" and recommended_prompt:
                asset.style_prompt = recommended_prompt
            asset.updated_at = now_ms()
            self._save(project)
            return asset
