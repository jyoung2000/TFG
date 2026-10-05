"""Film shot generation: queue, request adaptation, capabilities.

The film queue sits ON TOP of the host's single-generation-slot pipeline: jobs
are drained sequentially by one background worker that delegates each job to
``VideoGenerationHandler.generate`` — so all three execution paths (WanGP
bridge, forced LTX API, local pipeline), progress reporting and cancellation
are reused untouched. Job state is persisted on the shot's version record at
every transition, so a backend restart leaves shots resumable instead of lost.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Any, cast

from _routes._errors import HTTPError
from api_types import GenerateImageRequest, GenerateVideoRequest, VideoCameraMotion, LoraUse
import numpy as np
from PIL import Image

from film.film_api_types import (
    AddAssetReferenceRequest,
    ApplyStyleRequest,
    ApplyStyleResponse,
    BatchGenerateRequest,
    BatchGenerateResponse,
    SkippedShot,
    FilmCapabilitiesResponse,
    FilmModelCapability,
    FilmQualityProfile,
    FilmQueueResponse,
    GenerateAssetReferenceRequest,
    GenerateAssetReferenceResponse,
    GenerateShotRequest,
    QueuedJob,
    QueueShotResponse,
    ReplaceProjectRequest,
    AngleSetRequest,
    AngleShot,
    FramesRequest,
    FramesResponse,
    PreviewRenderRequest,
    PreviewRenderResponse,
    ReferenceSheetRequest,
    ReferenceSheetResponse,
    UpdateAssetRequest,
)
from film.multi_angle import (
    ANGLES_LORA_FILE, ANGLES_LORA_FOLDER, ANGLES_LORA_STRENGTH, LIGHTNING_LORA_FILE, QWEN_ANGLES_LABEL, QWEN_EDIT_2511, ZERO123PP, ZERO123PP_LABEL,
    LORA_ANGLE_SHOTS, LORA_ANGLE_SIZE, AngleEngine, angle_prompt, sheet_angle_prompt,
)
from services.multiview import MultiViewGenerator
from film.face_lock import FRONT_YAW, MAX_YAW_SHIFT, PROFILE_YAW, blend_face, fit_size, framing_kept, head_square, is_close_up, yaw
from film.identity_dataset import PERSON_WORDS, face_crop, face_crop_name, rare_trigger, source_crops
from services.face_match import SAME_PERSON, FaceMatcher, similarity
from film.training_api_types import ImportDatasetItemsRequest
from film.training_models import Dataset, LoraEntry
from film.film_continuity import check_shot_continuity
from film.media_providers import MediaSpec
from film.media_runner import MediaRunResult, MediaRunner, image_data_url, suffix_for
from film.provider_tiers import Task, Tier, TierPlan, default_order, plan as plan_tiers, run_with_fallback
from film.film_models import (
    FilmAsset,
    FilmProject,
    FilmShot,
    ShotVersion,
    VersionKind,
    now_ms,
)
from film.asset_mentions import mentioned_styles, with_mentions
from film.style_transfer import STYLE_TRANSFER_MODELS, USO_MODEL, USO_STEPS, pick_style_images, style_slots, style_text, transfer_mode, transfer_prompt
from film.film_prompt import synthesize_negative_prompt, synthesize_prompt
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from handlers.knowledge_handler import KnowledgeHandler
from handlers.generation_handler import GenerationHandler
from handlers.jobs_handler import JobsHandler
from handlers.training_handler import TrainingHandler
from handlers.taste_handler import TasteHandler
from handlers.vision_handler import VisionHandler
from services.similarity.metrics import cosine_similarity
from handlers.image_generation_handler import ImageGenerationHandler
from handlers.video_generation_handler import VideoGenerationHandler, get_allowed_durations
from runtime_config.model_download_specs import MODEL_FILE_ORDER, resolve_required_model_types
from runtime_config.runtime_config import RuntimeConfig
from services.interfaces import GpuInfo, TaskRunner, VideoProcessor
from services.wangp_bridge import WanGPBridge
from state.app_state_types import AppState
from logging_policy import log_background_exception

logger = logging.getLogger(__name__)

# Camera moves the host pipeline understands natively; everything else rides
# in the prompt text (film_prompt already phrases it) with motion "none".
_CAMERA_MOVE_TO_HOST: dict[str, VideoCameraMotion] = {
    "static": "static",
    "push_in": "dolly_in",
    "pull_out": "dolly_out",
    "dolly_left": "dolly_left",
    "dolly_right": "dolly_right",
    "tilt_up": "jib_up",
    "tilt_down": "jib_down",
    "pan_left": "none",
    "pan_right": "none",
    "orbit": "none",
    "follow": "none",
}

_LOCAL_RESOLUTIONS = ["540p", "720p", "1080p"]
_FORCED_API_RESOLUTIONS = ["1080p", "1440p", "2160p"]

# Documented figures from this repository's README: the WanGP bridge runs on
# "as low as 6 GB VRAM"; the native local LTX pipeline needs ~32 GB.
_WANGP_MIN_VRAM_GB = 6.0
_NATIVE_LOCAL_MIN_VRAM_GB = 32.0

# Quality profiles: id -> (model, resolution, label, description). "custom"
# means the shot's own model/resolution fields. Recommended profile by VRAM:
# < 8 GB fast_preview, 8-16 GB balanced (e.g. RTX 4070 12 GB), >= 16 GB quality.
QUALITY_PROFILES: dict[str, tuple[str, str, str, str]] = {
    "fast_preview": ("fast", "540p", "Fast Preview", "Fastest turnaround for blocking and timing checks."),
    "balanced": ("fast", "720p", "Balanced", "Good detail at a sensible render time; the default for 8-16 GB GPUs."),
    "quality": ("pro", "1080p", "Quality", "Highest quality; slowest and most VRAM-hungry."),
}
_INTERRUPTED_ERROR = "Interrupted: the app restarted while this job was queued or generating"


def _wangp_family(architecture: str) -> str:
    key = architecture.lower()
    for prefix, family in (
        ("ltx2", "ltx2"),
        ("ltx", "ltx"),
        ("vace", "wan"),
        ("t2v", "wan"),
        ("i2v", "wan"),
        ("ti2v", "wan"),
        ("flf2v", "wan"),
        ("fantasy", "wan"),
        ("animate", "wan"),
        ("hunyuan", "hunyuan"),
        ("z_image", "z_image"),
        ("flux", "flux"),
        ("qwen", "qwen"),
        ("ovi", "ovi"),
        ("ace_step", "ace_step"),
        ("k5", "k5"),
        ("minimax", "minimax"),
        ("lucy", "lucy"),
        ("kiwi", "kiwi"),
        ("chrono", "chrono"),
    ):
        if key.startswith(prefix):
            return family
    return key.split("_")[0] if key else "unknown"


def _wangp_task(architecture: str) -> str:
    key = architecture.lower()
    if any(token in key for token in ("ace_step", "stable_audio", "chatterbox", "dramabox", "audio", "mmaudio")):
        return "audio"
    if any(token in key for token in ("z_image", "flux", "qwen", "bernini", "hidream", "sd3")):
        return "image"
    if "edit" in key and "ltx" not in key:
        return "edit"
    return "video"


_image_data_url = image_data_url


def _system_ram_gb() -> float | None:
    """Total physical RAM in GB, or None when it cannot be determined.

    ``os.sysconf`` exists only on POSIX (absent from Windows typeshed), so
    access it through an explicitly-typed Any to keep pyright strict clean
    on every platform; the ctypes global-memory call below covers Windows.
    """
    sysconf: Any | None = getattr(os, "sysconf", None)
    if sysconf is not None:
        try:
            pages = sysconf("SC_PHYS_PAGES")
            page_size = sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_size > 0:
                return round(pages * page_size / 1024**3, 1)
        except (ValueError, OSError, AttributeError):
            pass
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        kernel32 = getattr(ctypes, "windll", None)
        if kernel32 is not None and kernel32.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / 1024**3, 1)
    except Exception:  # noqa: BLE001 - best effort on non-Windows
        pass
    return None


@dataclass(slots=True)
class _QueuedShotJob:
    project_id: str
    scene_id: str
    shot_id: str
    shot_title: str
    kind: VersionKind
    version_number: int
    #: History job id ("" when the jobs handler is not attached).
    job_id: str = ""

    def to_payload(self, status: str) -> QueuedJob:
        return QueuedJob(
            project_id=self.project_id,
            scene_id=self.scene_id,
            shot_id=self.shot_id,
            shot_title=self.shot_title,
            kind=self.kind,
            version_number=self.version_number,
            status=status,
        )


#: Angle-set prompt pieces. With a composer guide ("KI") the first image is
#: the posed mannequin at the angle, the second the person to put there.
ANGLE_SUBJECT = "the same person as in the reference image, same face, same hair, same body, same outfit"
#: The face crop of the identity photo, named by its place among the references.
FACE_FROM = "with exactly the face of the {nth} image, a close-up of the same person"
ANGLE_SUBJECT_POSED = "the person from the second image, in exactly the pose, camera angle and framing of the figure in the first image, same face, same hair, same body, same outfit"
#: Live pose preview: the viewfinder (posed mannequin) is the scene, the photo the person.
PREVIEW_SUBJECT = "the person from the second image, in exactly the pose, camera angle and framing of the figure in the first image"
PREVIEW_KEEP = "same face, same hair, same body, same outfit and same lighting as the second image, in the setting and background of the second image, not the grey 3D studio of the first image, photo, sharp focus"
PREVIEW_SEED = 7
PREVIEW_MAX_EDGE = 1024
FRAME_CAST = "the people from the reference images as the characters, same faces, same hair, same outfits"
#: The sheet's named views, spelled out: named only, the three-quarter and
#: profile views came back facing the camera (QA pass 2026-10-02).
SHEET_VIEW_WORDS = {
    "front view": "front view, facing the camera",
    "three-quarter view": "three-quarter view, body and face turned 45 degrees to the side",
    "profile view": "side profile view, body and face turned 90 degrees, seen exactly from the side",
    "back view": "back view, seen from behind, facing away from the camera",
}
#: "full body" alone still cropped the head and the feet off character views.
FULL_FIGURE = "full body from head to feet, the whole head and both feet in frame, centered with space above the head and below the feet"
#: How many renders compete for each view when a face matcher is installed.
FACE_CANDIDATES = 3
#: Face lock (film.face_lock): the re-composed head, the seeds tried, and how
#: much of the style sheet's view is its head (3.2 face sides: hair and neck).
FACE_LOCK_PROMPT = "close-up of the head and shoulders, exactly the face of the second image: same eyes, nose, lips, jaw, brows and skin"
#: For a turned head: the identity prompt pulled it toward the sheet's front face.
FACE_LOCK_TURNED_PROMPT = (
    "the person from the second image with exactly the head angle, head turn, gaze direction and expression of the first image, "
    "exactly the face of the second image: same eyes, nose, lips, jaw, brows and skin"
)
#: The outfit pass (film.face_lock): the render is the scene, the style sheet's
#: front view the person.
OUTFIT_LOCK_PROMPT = (
    "the person from the second image, in exactly the pose, camera angle, framing, setting, background and lighting of the first image, "
    "wearing exactly the outfit of the second image: the same clothes, materials and details, same face, same hair, same body, "
    "photo, sharp focus, detailed face"
)
OUTFIT_LOCK_SEED = 11
FACE_LOCK_SEEDS = (11, 22)
FACE_LOCK_SIZE = 768
FACE_LOCK_REFERENCE_SCALE = 3.2
#: A generated view this close to the photo's face also trains as a face close-up.
FACE_CROP_MIN = 0.6
#: A candidate this close to the photo's face ends the search early.
FACE_GOOD_ENOUGH = 0.7
ANGLE_QUALITY = "photo, sharp focus, detailed face, natural skin texture, plain light grey studio background, soft even studio light"
#: A LoRA dataset wants 15-30 varied images; more angles per call is a queue.
ANGLE_SET_MAX = 24


def _decode_image(data: str) -> bytes:
    payload = data.split(",", 1)[1] if data.startswith("data:") else data
    return base64.b64decode(payload)


#: SFace matches frontal faces. MEASURED 2026-10-04 (r75): Qwen angles of one photo,
#: all visibly the same woman, scored 0.25/0.28 in profile and 0.355/0.356 at three
#: quarters against SAME_PERSON 0.363; strangers from FLUX.2 angles scored 0.1-0.25.
THREE_QUARTER_SAME_PERSON = 0.30


def _same_person_floor(image: str) -> float:
    """The face score a generated view needs to stay in a LoRA dataset, by its view:
    a profile is not judged (its score is kept, like a back view's absence)."""
    stem = f"-{Path(image).stem.lower()}-"
    if "-profile-" in stem:
        return -1.0
    if "-34-" in stem:
        return THREE_QUARTER_SAME_PERSON
    return SAME_PERSON


def lora_fits(target: str, model_type: str) -> bool:
    """Whether a LoRA trained for `target` (film/training_models.py LORA_TARGETS)
    belongs on `model_type`: same model family only."""
    model = model_type.lower()
    family = (
        "ltx2" if model.startswith("ltx2") else
        "z_image" if model.startswith("z_image") else
        "flux" if model.startswith("flux") else
        "qwen_image" if model.startswith("qwen_image") else
        "wan22" if "_2_2" in model else
        ""
    )
    return bool(family) and family == target


def _saved_as(relative: str, name_hint: str) -> bool:
    """Whether a reference image was saved under `name_hint` (FilmStore keeps
    [A-Za-z0-9._-] and turns the rest into "-": "Raven QA (x)" -> "Raven-QA--x-")."""
    return Path(relative).stem.endswith("-" + re.sub(r"[^A-Za-z0-9._-]", "-", name_hint))


class FilmGenerationHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        film_handler: FilmHandler,
        video_generation_handler: VideoGenerationHandler,
        generation_handler: GenerationHandler,
        gpu_info: GpuInfo,
        video_processor: VideoProcessor,
        task_runner: TaskRunner,
        config: RuntimeConfig,
        wangp_bridge: WanGPBridge | None = None,
        media_runner: MediaRunner | None = None,
        image_generation_handler: ImageGenerationHandler | None = None,
        jobs: JobsHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._jobs = jobs
        self._film = film_handler
        self._video_generation = video_generation_handler
        self._generation = generation_handler
        self._gpu_info = gpu_info
        self._video_processor = video_processor
        self._task_runner = task_runner
        self._config = config
        self._wangp_bridge = wangp_bridge
        self._media_runner = media_runner
        self._image_generation = image_generation_handler
        # Optional on purpose: the queue works without it, and learning is
        # never allowed to be a reason a render fails.
        self._knowledge: KnowledgeHandler | None = None
        #: Registry lookups for asset-bound LoRAs (phase 7); optional like knowledge.
        self._training: TrainingHandler | None = None
        self._vision: VisionHandler | None = None
        self._face_matcher_service: FaceMatcher | None = None
        #: Thumbs up / down (film/taste.py): what a character's LoRA learns from.
        self._taste: TasteHandler | None = None
        #: Zero123++ (services.multiview): an object's six-view turnaround.
        self._multiview: MultiViewGenerator | None = None
        # Set while a hosted job runs, so the queue can report and cancel it.
        self._hosted_cancel = False
        self._hosted_progress: tuple[int, str] | None = None
        self._queue: deque[_QueuedShotJob] = deque()
        self._active: _QueuedShotJob | None = None
        self._worker_running = False
        self._paused = False

    # ---- Startup recovery ----------------------------------------------

    def recover_interrupted_jobs(self) -> int:
        """Fail versions left 'queued'/'generating' by a previous process so no
        shot is stuck in a generating state after a restart. Returns the count."""
        recovered = 0
        with self.lock:
            for project_id in self._film.store.list_project_ids():
                try:
                    project = self._film.store.load(project_id)
                except Exception as exc:  # noqa: BLE001 - one corrupt project must not block startup
                    logger.warning("Skipping film project %s during recovery: %s", project_id, exc)
                    continue
                changed = False
                for scene in project.scenes:
                    for shot in scene.shots:
                        for version in shot.versions:
                            if version.status in ("queued", "generating"):
                                version.status = "failed"
                                version.error = _INTERRUPTED_ERROR
                                changed = True
                                recovered += 1
                        if shot.status in ("queued", "generating"):
                            shot.status = "ready" if shot.capture_path else "composed"
                            shot.updated_at = now_ms()
                            changed = True
                if changed:
                    self._film.store.save(project)
        if recovered:
            logger.info("Recovered %d interrupted film generation job(s)", recovered)
        return recovered

    # ---- Queueing --------------------------------------------------------

    def queue_shot(
        self, project_id: str, scene_id: str, shot_id: str, req: GenerateShotRequest
    ) -> QueueShotResponse:
        with self.lock:
            project = self._film.store.load(project_id)
            scene = project.scene(scene_id)
            if scene is None:
                raise HTTPError(404, f"Scene not found: {scene_id}")
            shot = scene.shot(shot_id)
            if shot is None:
                raise HTTPError(404, f"Shot not found: {shot_id}")
            if any(job.shot_id == shot_id for job in self._queue) or (
                self._active is not None and self._active.shot_id == shot_id
            ):
                raise HTTPError(409, "This shot is already queued or generating")

            warnings = check_shot_continuity(project, scene, shot)
            if warnings and project.settings.strict_continuity:
                raise HTTPError(
                    409,
                    "Strict continuity is enabled and this shot has continuity warnings: "
                    + "; ".join(w.message for w in warnings),
                )

            version = self._create_version(project, shot, req.kind, req)
            shot.versions.append(version)
            shot.status = "queued"
            shot.updated_at = now_ms()
            self._film.store.save(project)

            job = _QueuedShotJob(
                project_id=project_id,
                scene_id=scene_id,
                shot_id=shot_id,
                shot_title=shot.title,
                kind=req.kind,
                version_number=version.number,
                job_id=self._open_history_job(project, shot, version),
            )
            self._queue.append(job)
            self._ensure_worker()
            return QueueShotResponse(
                status="queued", version_number=version.number, warnings=warnings
            )

    def _open_history_job(self, project: FilmProject, shot: FilmShot, version: ShotVersion) -> str:
        if self._jobs is None:
            return ""
        return self._jobs.queue(
            "video_gen",
            title=f"{shot.title or 'Shot'} · v{version.number} ({version.kind})",
            model=version.model,
            provider=self._media_selection(project.id)[0],
            seed=version.seed,
            prompt=version.prompt,
            negative_prompt=version.negative_prompt,
            params={
                "kind": version.kind,
                "resolution": version.resolution,
                "fps": version.fps,
                "duration_seconds": version.duration_seconds,
                "version_number": version.number,
            },
            inputs={"capture_path": shot.capture_path} if shot.capture_path else {},
            project_id=project.id,
            shot_id=shot.id,
        ).id

    def queue_batch(self, project_id: str, req: BatchGenerateRequest) -> BatchGenerateResponse:
        with self.lock:
            project = self._film.store.load(project_id)
            targets: list[tuple[str, str]] = []  # (scene_id, shot_id)
            if req.shot_ids:
                for shot_id in req.shot_ids:
                    found = project.find_shot(shot_id)
                    if found is None:
                        raise HTTPError(404, f"Shot not found: {shot_id}")
                    targets.append((found[0].id, found[1].id))
            elif req.scene_id is not None:
                scene = project.scene(req.scene_id)
                if scene is None:
                    raise HTTPError(404, f"Scene not found: {req.scene_id}")
                targets.extend(
                    (scene.id, shot.id) for shot in sorted(scene.shots, key=lambda s: s.order)
                )
            else:
                for scene in sorted(project.scenes, key=lambda s: s.order):
                    targets.extend(
                        (scene.id, shot.id) for shot in sorted(scene.shots, key=lambda s: s.order)
                    )

        queued: list[QueuedJob] = []
        skipped: list[SkippedShot] = []
        for scene_id, shot_id in targets:
            try:
                response = self.queue_shot(
                    project_id, scene_id, shot_id, GenerateShotRequest(kind=req.kind)
                )
            except HTTPError as exc:
                if exc.status_code == 409:
                    # Already queued / generating, or strict continuity: say so.
                    skipped.append(SkippedShot(shot_id=shot_id, reason=str(exc.detail)))
                    continue
                raise
            queued.append(
                QueuedJob(
                    project_id=project_id,
                    scene_id=scene_id,
                    shot_id=shot_id,
                    shot_title="",
                    kind=req.kind,
                    version_number=response.version_number,
                    status="queued",
                )
            )
        return BatchGenerateResponse(status="queued", queued=queued, skipped=skipped)

    def replace_project(self, project_id: str, req: ReplaceProjectRequest) -> FilmProject:
        """Undo/redo snapshot restore, guarded by the queue: a shot that is
        queued or rendering pins the live record."""
        with self.lock:
            busy = {job.shot_id for job in self._queue if job.project_id == project_id}
            if self._active is not None and self._active.project_id == project_id:
                busy.add(self._active.shot_id)
        return self._film.replace_project(project_id, req, busy_shot_ids=busy)

    def get_queue(self) -> FilmQueueResponse:
        with self.lock:
            active = self._active.to_payload("generating") if self._active is not None else None
            pending = [job.to_payload("queued") for job in self._queue]
            paused = self._paused
        progress: int | None = None
        phase = ""
        with self.lock:
            hosted = self._hosted_progress
        if active is not None and hosted is not None:
            progress, phase = hosted
        elif active is not None:
            try:
                snapshot = self._generation.get_generation_progress()
                progress = snapshot.progress
                phase = snapshot.phase
            except Exception:  # noqa: BLE001 - progress is advisory
                progress = None
        return FilmQueueResponse(active=active, pending=pending, paused=paused, progress=progress, phase=phase)

    def cancel_all(self) -> FilmQueueResponse:
        with self.lock:
            drained = list(self._queue)
            self._queue.clear()
        for job in drained:
            self._finish_version(job, status="cancelled", error="Cancelled before start")
        if self._active is not None:
            self._generation.cancel_generation()
        return self.get_queue()

    def pause(self) -> FilmQueueResponse:
        """Stop starting new jobs; the active job (if any) finishes normally."""
        with self.lock:
            self._paused = True
        return self.get_queue()

    def resume(self) -> FilmQueueResponse:
        with self.lock:
            self._paused = False
            if self._queue:
                self._ensure_worker()
        return self.get_queue()

    def cancel_job(self, shot_id: str) -> FilmQueueResponse:
        """Cancel one shot: drop it from the pending queue, or cancel the host
        generation when it is the active job."""
        removed: _QueuedShotJob | None = None
        cancel_active = False
        with self.lock:
            for job in list(self._queue):
                if job.shot_id == shot_id:
                    self._queue.remove(job)
                    removed = job
                    break
            if removed is None and self._active is not None and self._active.shot_id == shot_id:
                cancel_active = True
        if removed is not None:
            self._finish_version(removed, status="cancelled", error="Cancelled before start")
        elif cancel_active:
            with self.lock:
                hosted = self._hosted_progress is not None
                if hosted:
                    self._hosted_cancel = True
            if not hosted:
                self._generation.cancel_generation()
        else:
            raise HTTPError(404, "That shot is not queued or generating")
        return self.get_queue()

    def move(self, shot_id: str, index: int) -> FilmQueueResponse:
        """Move a pending shot to a specific position in the queue."""
        with self.lock:
            jobs = list(self._queue)
            job = next((j for j in jobs if j.shot_id == shot_id), None)
            if job is None:
                raise HTTPError(404, "That shot is not in the pending queue")
            jobs.remove(job)
            jobs.insert(max(0, min(index, len(jobs))), job)
            self._queue = deque(jobs)
        return self.get_queue()

    def prioritize(self, shot_id: str) -> FilmQueueResponse:
        """Move a pending shot to the front of the queue."""
        with self.lock:
            for job in list(self._queue):
                if job.shot_id == shot_id:
                    self._queue.remove(job)
                    self._queue.appendleft(job)
                    break
            else:
                raise HTTPError(404, "That shot is not in the pending queue")
        return self.get_queue()

    # ---- Version construction -------------------------------------------

    def _create_version(
        self, project: FilmProject, shot: FilmShot, kind: VersionKind, req: GenerateShotRequest | None = None
    ) -> ShotVersion:
        settings = project.settings
        generation = shot.generation

        scene_and_shot = project.find_shot(shot.id)
        assert scene_and_shot is not None
        scene = scene_and_shot[0]
        shot = with_mentions(project, shot)

        prompt = shot.visual_prompt if shot.prompt_locked and shot.visual_prompt else synthesize_prompt(project, scene, shot)
        negative = synthesize_negative_prompt(project, shot)

        if kind == "preview":
            model = "fast"
            resolution = settings.preview_resolution or "540p"
            duration = min(shot.duration_seconds, settings.preview_max_seconds or 4.0)
        else:
            model, resolution = self._resolve_final_profile(project, shot)
            duration = shot.duration_seconds

        if req is not None and req.duration_seconds is not None and req.duration_seconds > 0:
            # Video Reproduce snaps to the model's allowed durations itself.
            duration = req.duration_seconds
        duration_int = max(1, round(duration))
        if self._config.force_api_generations and not self._config.wangp_enabled:
            resolution = resolution if resolution in _FORCED_API_RESOLUTIONS else "1080p"
            allowed = sorted(get_allowed_durations(f"ltx-2-3-{model}", resolution, generation.fps))
            duration_int = min(allowed, key=lambda d: abs(d - duration_int))

        wardrobe_snapshot: dict[str, str] = {}
        for shot_character in shot.characters:
            asset = project.asset(shot_character.asset_id)
            if asset is not None:
                wardrobe_snapshot[asset.id] = asset.wardrobe

        capture_path = shot.capture_path if generation.use_capture_as_reference else ""
        if not capture_path and shot.frame_path:
            # The storyboard frame (composed from the style guide) starts the video.
            capture_path = shot.frame_path
        if req is not None and req.capture_path:
            capture_path = req.capture_path
        end_capture_path = req.end_capture_path if req is not None else ""
        if not end_capture_path and shot.end_frame_path and capture_path == shot.frame_path:
            end_capture_path = shot.end_frame_path
        seed = generation.seed
        if req is not None and req.seed is not None:
            seed = req.seed

        snapshot: dict[str, object] = {
            "title": shot.title,
            "description": shot.description,
            "visual_prompt": shot.visual_prompt,
            "negative_prompt": shot.negative_prompt,
            "framing": shot.framing.model_dump(),
            "camera_move": shot.camera_move,
            "duration_seconds": shot.duration_seconds,
            "characters": [c.model_dump() for c in shot.characters],
            "location_id": shot.location_id,
            "prop_ids": list(shot.prop_ids),
            "generation": generation.model_dump(),
            "capture_path": shot.capture_path,
            "composition_objects": len(shot.composition.objects) if shot.composition else 0,
            "aspect_ratio": generation.aspect_ratio,
        }
        return ShotVersion(
            number=(max((v.number for v in shot.versions), default=0) + 1),
            kind=kind,
            status="queued",
            prompt=prompt,
            negative_prompt=negative,
            model=model,
            resolution=resolution,
            fps=generation.fps,
            duration_seconds=float(duration_int),
            seed=seed,
            capture_path=capture_path,
            end_capture_path=end_capture_path,
            control_video_path=req.control_video_path if req is not None else "",
            control_strength=req.control_strength if req is not None else None,
            wardrobe_snapshot=wardrobe_snapshot,
            shot_snapshot=snapshot,
            execution_mode=self._execution_mode(project.settings.media_provider),
        )

    def _execution_mode(self, project_provider: str = "") -> str:
        with self.lock:
            app_provider = self.state.app_settings.media_provider
        provider = (project_provider or app_provider or "local").strip()
        if provider != "local":
            return provider
        if self._config.wangp_enabled:
            return "wangp"
        if self._config.force_api_generations:
            return "api"
        return "local"

    @staticmethod
    def _resolve_final_profile(project: FilmProject, shot: FilmShot) -> tuple[str, str]:
        """Model + resolution for a final render: explicit shot fields win
        (custom), otherwise the shot's / project's quality profile."""
        generation = shot.generation
        settings = project.settings
        preset = generation.quality_preset
        if preset == "project":
            preset = settings.default_quality_preset
        profile = QUALITY_PROFILES.get(preset)
        if preset == "custom" or profile is None or generation.model or generation.resolution:
            fallback_model, fallback_resolution = (profile[0], profile[1]) if profile else ("fast", "720p")
            model = generation.model or settings.default_model or fallback_model
            resolution = generation.resolution or settings.default_resolution or fallback_resolution
            return model, resolution
        return profile[0], profile[1]

    def guided_video_available(self) -> bool:
        """Whether a fast guided video model (VACE) can render reproduce's
        frames + reference-clip rung."""
        return self._video_generation.guided_model_available()

    def is_pending(self, shot_id: str) -> bool:
        """Whether this shot is queued or rendering right now."""
        with self.lock:
            return any(job.shot_id == shot_id for job in self._queue) or (
                self._active is not None and self._active.shot_id == shot_id
            )

    # ---- Worker ----------------------------------------------------------

    def _ensure_worker(self) -> None:
        """Start the drain worker if it isn't running. Caller holds the lock."""
        if self._worker_running or self._paused:
            return
        self._worker_running = True
        self._task_runner.run_background(
            target=self._drain_queue,
            task_name="film-generation-queue",
            on_error=lambda exc: self._mark_worker_stopped(),
        )

    def _mark_worker_stopped(self) -> None:
        with self.lock:
            self._worker_running = False

    def _drain_queue(self) -> None:
        try:
            while True:
                with self.lock:
                    if not self._queue or self._paused:
                        self._active = None
                        self._worker_running = False
                        return
                    job = self._queue.popleft()
                    self._active = job
                try:
                    self._run_job(job)
                except Exception as exc:  # noqa: BLE001 - one bad take must not stop the queue
                    log_background_exception(f"film-generation-queue:{job.shot_id}", exc)
                    try:
                        self._finish_version(job, status="failed", error=f"Render queue error: {exc}")
                    except Exception as record_exc:  # noqa: BLE001 - recording the failure is best effort
                        log_background_exception(f"film-generation-queue:{job.shot_id}:record", record_exc)
        finally:
            with self.lock:
                if not self._queue or self._paused:
                    self._active = None
                    self._worker_running = False

    def _run_job(self, job: _QueuedShotJob) -> None:
        provider, model = self._media_selection(job.project_id)
        if provider != "local":
            self._run_hosted_job(job, provider, model)
            return
        tiers = self._tier_plan(job.project_id, "t2v").usable
        if tiers and tiers[0].provider != "local":
            # The tier list puts a hosted provider first for this task.
            self._run_hosted_job(job, tiers[0].provider, tiers[0].model)
            return
        prepared = self._prepare_request(job)
        if prepared is None:
            return
        request, seed = prepared

        # A per-shot seed rides through the host's locked-seed mechanism for
        # exactly this job; the user's own seed settings are restored after.
        restore_seed: tuple[bool, int] | None = None
        if seed is not None:
            with self.lock:
                settings = self.state.app_settings
                restore_seed = (settings.seed_locked, settings.locked_seed)
                settings.seed_locked = True
                settings.locked_seed = seed
        started = time.perf_counter()
        try:
            response = self._video_generation.generate(request, job_id=job.job_id or None, seed=seed, allow_fallback=False)
        except HTTPError as exc:
            self._local_failed(job, str(exc.detail), self._telemetry(started))
            return
        except Exception as exc:  # noqa: BLE001 - queue must survive any job failure
            self._local_failed(job, str(exc), self._telemetry(started))
            return
        finally:
            if restore_seed is not None:
                with self.lock:
                    settings = self.state.app_settings
                    settings.seed_locked, settings.locked_seed = restore_seed
        telemetry = self._telemetry(started)
        telemetry["render_model"] = self._video_generation.render_model_for(request)
        if response.status == "complete" and response.video_path:
            self._finish_version(
                job, status="complete", output_path=response.video_path, telemetry=telemetry, seed_used=response.seed
            )
        elif response.status == "cancelled":
            self._finish_version(job, status="cancelled", error="Cancelled", telemetry=telemetry)
        else:
            self._local_failed(job, f"Generation ended with status {response.status}", telemetry)

    def _local_failed(self, job: _QueuedShotJob, error: str, telemetry: dict[str, Any]) -> None:
        """A local render failed: move to the next usable tier, else record the failure."""
        hosted = [t for t in self._tier_plan(job.project_id, "t2v").usable if t.provider != "local"]
        if not hosted or self._hosted_cancelled_flag():
            self._finish_version(job, status="failed", error=error, telemetry=telemetry)
            return
        logger.info("Local render failed (%s); falling back to %s", error, hosted[0].provider)
        if job.job_id and self._jobs is not None:
            self._jobs.progress(job.job_id, 0.0, f"Local failed: {error[:120]} — trying {hosted[0].provider}")
        self._run_hosted_job(job, hosted[0].provider, hosted[0].model, fallback_from=("local", error))

    def _hosted_cancelled_flag(self) -> bool:
        with self.lock:
            return self._hosted_cancel

    # ---- Tiered fallback ---------------------------------------------------

    def _tier_plan(self, project_id: str, task: Task) -> TierPlan:
        """The provider order for this project and task, checked against keys,
        model ids and the capability catalog (film/provider_tiers.py)."""
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        project_provider, project_video, project_image = "", "", ""
        try:
            project = self._film.store.load(project_id)
            project_provider = (project.settings.media_provider or "").strip()
            project_video = (project.settings.video_model or "").strip()
            project_image = (project.settings.image_model or "").strip()
        except Exception:  # noqa: BLE001 - a missing project is handled downstream
            pass
        if project_provider:
            order = [project_provider]
        else:
            order = list(settings.media_tiers.get(task) or default_order(settings.media_provider))
        image_task = task in ("t2i", "i2i", "edit")

        def models(provider: str, _task: Task) -> str:
            own = project_image if image_task else project_video
            if project_provider == provider and own:
                return own
            return settings.default_image_model if image_task else settings.default_video_model

        local_available = self._config.wangp_enabled or not self._config.force_api_generations or bool(settings.ltx_api_key.strip())
        return plan_tiers(task, order=order, local_available=local_available, keys=settings.media_api_key, models=models)

    def tier_preview(self, project_id: str) -> dict[str, list[dict[str, str]]]:
        """What Settings shows: per task, the resolved tiers and why any is skipped."""
        out: dict[str, list[dict[str, str]]] = {}
        for task in ("t2i", "i2i", "t2v", "i2v", "edit"):
            out[task] = [{"provider": t.provider, "model": t.model, "skip_reason": t.skip_reason} for t in self._tier_plan(project_id, task).tiers]
        return out

    # ---- Reference images --------------------------------------------------

    # A standing figure is about 1:1.8; at 3:4 the model filled the frame with
    # the torso and cut off the head and the feet (QA pass 2026-10-02).
    _REFERENCE_SIZES: dict[str, tuple[int, int]] = {
        "character": (768, 1344),
        "location": (1344, 768),
        "prop": (1024, 1024),
    }

    @staticmethod
    def _reference_prompt(asset: FilmAsset, style_prompt: str, framing: str = FULL_FIGURE) -> str:
        """Describe the asset the way the continuity fields already describe it,
        so a generated reference matches what the shot prompts will say."""
        parts: list[str] = []
        if asset.kind == "character":
            parts.append(f"Character reference sheet of {asset.name}")
            for value in (asset.appearance, asset.wardrobe, asset.accessories):
                if value.strip():
                    parts.append(value.strip())
            parts.append(", ".join(p for p in ("neutral studio background", framing, "even lighting, photoreal") if p))
        elif asset.kind == "location":
            parts.append(f"Establishing view of {asset.name}")
            for value in (asset.environment, asset.lighting, asset.atmosphere, asset.time_of_day):
                if value.strip():
                    parts.append(value.strip())
            parts.append("wide angle, no people, photoreal")
        else:
            parts.append(f"Product-style reference of the prop {asset.name}")
            for value in (asset.prop_details, asset.description):
                if value.strip():
                    parts.append(value.strip())
            parts.append("neutral background, even lighting")
        if asset.description.strip() and asset.kind == "character":
            parts.insert(1, asset.description.strip())
        if style_prompt.strip():
            parts.append(style_prompt.strip())
        if asset.style_guide and asset.style_guide.recommended_prompt.strip():
            parts.append(asset.style_guide.recommended_prompt.strip())
        return ", ".join(part for part in parts if part)

    def generate_asset_reference(
        self, project_id: str, asset_id: str, req: GenerateAssetReferenceRequest
    ) -> GenerateAssetReferenceResponse:
        """Generate a reference image for an asset with the selected image
        model — locally when the project generates locally, otherwise on the
        chosen hosted provider."""
        project = self._film.get_project(project_id)
        asset = project.asset(asset_id)
        if asset is None:
            raise HTTPError(404, f"Asset not found: {asset_id}")
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        provider = (project.settings.media_provider or settings.media_provider or "local").strip()
        model = (project.settings.image_model or settings.default_image_model).strip()
        prompt = req.prompt.strip() or self._reference_prompt(asset, project.settings.style_prompt)
        width, height = self._REFERENCE_SIZES.get(asset.kind, (1024, 1024))

        tiers = self._tier_plan(project_id, "t2i").tiers if not project.settings.media_provider else []
        if provider == "local" and tiers:
            # Local first, then whichever hosted tiers are configured for stills.
            def attempt(tier: Tier) -> MediaRunResult:
                if tier.provider == "local":
                    try:
                        return MediaRunResult(status="complete", content=self._local_reference_image(prompt, width, height))
                    except HTTPError as exc:
                        return MediaRunResult(status="failed", error=str(exc.detail))
                runner = self._media_runner
                if runner is None:  # pragma: no cover - wired in AppHandler
                    return MediaRunResult(status="failed", error="Hosted generation is not available in this build")
                return runner.run(provider=tier.provider, api_key=settings.media_api_key(tier.provider), spec=MediaSpec(model=tier.model, prompt=prompt, task="image", width=width, height=height))

            outcome = run_with_fallback(tiers, attempt)
            if outcome.result.status != "complete":
                raise HTTPError(502, outcome.result.error or "No provider returned an image")
            image_bytes = outcome.result.content
            provider = outcome.provider
            if outcome.fell_back:
                logger.info("Reference image: %s", outcome.note())
                model = next((t.model for t in tiers if t.provider == provider), model)
        elif provider == "local":
            image_bytes = self._local_reference_image(prompt, width, height)
        else:
            api_key = settings.media_api_key(provider)
            if not api_key:
                raise HTTPError(400, f"{provider.upper()}_KEY_MISSING: add the {provider} API key in Settings → API Keys")
            runner = self._media_runner
            if runner is None:  # pragma: no cover - wired in AppHandler
                raise HTTPError(500, "Hosted generation is not available in this build")
            result = runner.run(
                provider=provider,
                api_key=api_key,
                spec=MediaSpec(model=model, prompt=prompt, task="image", width=width, height=height),
            )
            if result.status != "complete":
                raise HTTPError(502, result.error or f"{provider} did not return an image")
            image_bytes = result.content

        encoded = base64.b64encode(image_bytes).decode("ascii")
        updated = self._film.add_asset_reference(
            project_id, asset_id, AddAssetReferenceRequest(image_base64=encoded, name_hint=f"{asset.name}-{req.view.strip().replace(' ', '-') or 'ai'}")
        )
        return GenerateAssetReferenceResponse(
            asset=updated,
            prompt=prompt,
            provider=provider,
            model=model or ("local image pipeline" if provider == "local" else ""),
            reference_path=updated.reference_images[-1] if updated.reference_images else "",
        )

    def _local_reference_image(self, prompt: str, width: int, height: int) -> bytes:
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        response = handler.generate(GenerateImageRequest(prompt=prompt, width=width, height=height, numImages=1))
        paths = response.image_paths or []
        if response.status != "complete" or not paths:
            raise HTTPError(502, "The local image model did not return an image")
        try:
            return Path(paths[0]).read_bytes()
        except OSError as exc:
            raise HTTPError(502, f"Could not read the generated image: {exc}") from exc

    # ---- Hosted providers -------------------------------------------------

    def _media_selection(self, project_id: str) -> tuple[str, str]:
        """(provider, model id) for this project: its own choice, else the app default."""
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
        try:
            project = self._film.store.load(project_id)
            project_provider = project.settings.media_provider
            project_model = project.settings.video_model
        except Exception:  # noqa: BLE001 - a missing project is handled downstream
            project_provider, project_model = "", ""
        provider = (project_provider or settings.media_provider or "local").strip()
        model = (project_model or settings.default_video_model).strip()
        return provider, model

    def _run_hosted_job(self, job: _QueuedShotJob, provider: str, model: str, *, fallback_from: tuple[str, str] | None = None) -> None:
        """Render one shot on a hosted provider, then store the file exactly
        like a local render so versions, timeline and export behave the same."""
        prepared = self._prepare_request(job)
        if prepared is None:
            return
        request, seed = prepared
        with self.lock:
            settings = self.state.app_settings.model_copy(deep=True)
            self._hosted_cancel = False
            self._hosted_progress = (0, f"Preparing {provider} job")
        if job.job_id and self._jobs is not None:
            self._jobs.annotate(job.job_id, provider=provider, model=model, seed=seed)
            self._jobs.mark_running(job.job_id, phase=f"Preparing {provider} job")
        api_key = settings.media_api_key(provider)
        started = time.perf_counter()
        if not api_key:
            self._clear_hosted()
            self._finish_version(
                job,
                status="failed",
                error=f"{provider.upper()}_KEY_MISSING: add the {provider} API key in Settings → API Keys, or switch this project back to local generation.",
                telemetry=self._telemetry(started, execution_mode=provider),
            )
            return

        spec = MediaSpec(
            model=model,
            prompt=request.prompt,
            task="video",
            negative_prompt=request.negativePrompt,
            duration_seconds=float(request.duration),
            fps=int(float(request.fps)),
            aspect_ratio=request.aspectRatio,
            resolution=request.resolution,
            seed=seed,
            image_data_url=_image_data_url(request.imagePath),
        )
        runner = self._media_runner
        if runner is None:  # pragma: no cover - wired in AppHandler
            self._clear_hosted()
            self._finish_version(job, status="failed", error="Hosted generation is not available in this build", telemetry=self._telemetry(started, execution_mode=provider))
            return
        # This provider first, then any later hosted tiers configured for the task.
        later = [t for t in self._tier_plan(job.project_id, "t2v").usable if t.provider not in ("local", provider)]
        tiers = [Tier(provider, model), *later]

        def attempt(tier: Tier) -> MediaRunResult:
            if job.job_id and self._jobs is not None and tier.provider != provider:
                self._jobs.annotate(job.job_id, provider=tier.provider, model=tier.model)
            return runner.run(
                provider=tier.provider,
                api_key=settings.media_api_key(tier.provider),
                spec=replace(spec, model=tier.model),
                is_cancelled=self._hosted_cancelled,
                on_progress=self._report_hosted_progress,
            )

        outcome = run_with_fallback(tiers, attempt, is_cancelled=self._hosted_cancelled)
        result = outcome.result
        if outcome.provider:
            provider = outcome.provider
        attempts = ([fallback_from] if fallback_from else []) + outcome.attempts
        telemetry = self._telemetry(started, execution_mode=provider)
        if attempts:
            telemetry["fallback"] = [{"provider": p, "error": e} for p, e in attempts]
            if job.job_id and self._jobs is not None:
                self._jobs.annotate(job.job_id, metrics={"fallback": "; ".join(f"{p}: {e[:80]}" for p, e in attempts)})
        if result.status == "cancelled":
            self._clear_hosted()
            self._finish_version(job, status="cancelled", error="Cancelled", telemetry=telemetry)
            return
        if result.status == "failed":
            self._clear_hosted()
            self._finish_version(job, status="failed", error=result.error, telemetry=telemetry)
            return
        try:
            outputs = self._config.outputs_dir
            outputs.mkdir(parents=True, exist_ok=True)
            suffix = suffix_for(result.media_url, "video")
            target = outputs / f"film-{provider}-{job.shot_id}-v{job.version_number}-{now_ms()}{suffix}"
            target.write_bytes(result.content)
        except OSError as exc:
            self._clear_hosted()
            self._finish_version(job, status="failed", error=f"Could not save the {provider} result: {exc}", telemetry=telemetry)
            return
        self._clear_hosted()
        self._finish_version(job, status="complete", output_path=str(target), telemetry=telemetry, seed_used=seed)

    def _hosted_cancelled(self) -> bool:
        with self.lock:
            return self._hosted_cancel

    def _report_hosted_progress(self, percent: int, phase: str) -> None:
        with self.lock:
            self._hosted_progress = (percent, phase)
            active = self._active
        if active is not None and active.job_id and self._jobs is not None:
            self._jobs.progress(active.job_id, percent, phase)

    def _clear_hosted(self) -> None:
        with self.lock:
            self._hosted_progress = None
            self._hosted_cancel = False

    def _telemetry(self, started: float, execution_mode: str = "") -> dict[str, object]:
        """Wall-clock time plus whatever the GPU service can observe. Peak VRAM
        is the post-job used figure — an estimate, labelled as such."""
        payload: dict[str, object] = {"generation_seconds": round(time.perf_counter() - started, 2)}
        if execution_mode:
            payload["execution_mode"] = execution_mode
        try:
            info = self._gpu_info.get_gpu_info()
            payload["gpu_name"] = str(info.get("name", "") or "")
            used = info.get("vramUsed", 0)
            if used > 0:
                payload["peak_vram_gb"] = round(float(used) / 1024.0, 2)
        except Exception:  # noqa: BLE001 - telemetry is advisory
            pass
        return payload

    def _prepare_request(self, job: _QueuedShotJob) -> tuple[GenerateVideoRequest, int | None] | None:
        with self.lock:
            project = self._film.store.load(job.project_id)
            found = project.find_shot(job.shot_id)
            if found is None:
                return None
            scene_id, shot = found[0].id, found[1]
            version = shot.version(job.version_number)
            if version is None:
                return None
            version.status = "generating"
            shot.status = "generating"
            shot.updated_at = now_ms()
            self._film.store.save(project)

            image_path: str | None = None
            if version.capture_path:
                capture = self._film.store.resolve_media_path(job.project_id, version.capture_path)
                if capture.is_file():
                    image_path = str(capture)
            if image_path is None and shot.generation.continue_from_previous:
                image_path = self._extract_previous_frame(project, shot, job)

            camera_motion = _CAMERA_MOVE_TO_HOST.get(shot.camera_move, "none")
            aspect_ratio = shot.generation.aspect_ratio
            control_video = self._deliver_pass(job.project_id, shot.generation.control_video)
            depth_video = self._deliver_pass(job.project_id, shot.generation.depth_video)
            end_frame: str | None = None
            if version.end_capture_path:
                end_capture = self._film.store.resolve_media_path(job.project_id, version.end_capture_path)
                end_frame = str(end_capture) if end_capture.is_file() else None
            if version.control_video_path:
                # A per-version control clip (Video Reproduce's reference_video
                # rung) replaces the shot's Deliver pass for this render only.
                clip = self._film.store.resolve_media_path(job.project_id, version.control_video_path)
                control_video = str(clip) if clip.is_file() else control_video
            cast_shot = with_mentions(project, shot)
            seed_lock = self.asset_seed_lock(project, cast_shot)
            if version.seed is None and seed_lock is not None:
                version.seed = seed_lock
                self._film.store.save(project)
            reference_images = [
                str(self._film.store.resolve_media_path(job.project_id, asset.reference_images[0]))
                for asset in (project.asset(c.asset_id) for c in cast_shot.characters)
                if asset is not None and asset.reference_images and asset.lora_id == ""
            ][:2]

        request = GenerateVideoRequest(
            prompt=version.prompt,
            resolution=version.resolution,
            model=version.model,
            cameraMotion=camera_motion,
            negativePrompt=version.negative_prompt,
            duration=str(int(version.duration_seconds)),
            fps=str(version.fps),
            audio="false",
            imagePath=image_path,
            audioPath=None,
            aspectRatio=aspect_ratio,
            controlVideoPath=control_video,
            depthVideoPath=depth_video,
            loras=[],
            referenceImagePaths=[p for p in reference_images if Path(p).is_file()],
            endFramePath=end_frame,
            controlStrength=version.control_strength if version.control_video_path else None,
        )
        model_type = self._video_generation.render_model_for(request)
        if image_path is None and "i2v" in model_type.lower():
            # An image-to-video model takes its people from the first frame: compose
            # one from the style guide first (and keep it on the storyboard).
            try:
                framed = self.generate_frame(job.project_id, scene_id, job.shot_id)
                start = self._film.store.resolve_media_path(job.project_id, framed.frame_path)
                end = self._film.store.resolve_media_path(job.project_id, framed.end_frame_path) if framed.end_frame_path else None
                request = request.model_copy(update={
                    "imagePath": str(start),
                    "endFramePath": request.endFramePath or (str(end) if end is not None and end.is_file() else None),
                })
            except HTTPError as exc:
                logger.warning("No start frame for shot %s: %s", job.shot_id, exc.detail)
        # A LoRA goes only to the model family it was trained for: a Z-Image character
        # LoRA does nothing good in LTX-2 or Wan (2026-10-04).
        request = request.model_copy(update={"loras": self.asset_loras(project, cast_shot, model_type)})
        return request, version.seed

    def _deliver_pass(self, project_id: str, relative: str) -> str | None:
        """Absolute path of a Deliver pass inside the project, or None."""
        if not relative:
            return None
        try:
            path = self._film.store.resolve_media_path(project_id, relative)
        except Exception:  # noqa: BLE001 - a stale or escaping path is simply not a control signal
            return None
        return str(path) if path.is_file() else None

    def _extract_previous_frame(
        self, project: FilmProject, shot: FilmShot, job: _QueuedShotJob
    ) -> str | None:
        previous = project.previous_shot(shot.id)
        if previous is None or previous.current_version is None:
            return None
        version = previous.version(previous.current_version)
        if version is None or not version.output_path:
            return None
        try:
            cap = self._video_processor.open_video(version.output_path)
            try:
                info = self._video_processor.get_video_info(cap)
                last_index = max(0, info["frame_count"] - 1)
                frame = self._video_processor.read_frame(cap, last_index)
                if frame is None:
                    return None
                jpeg = self._video_processor.encode_frame_jpeg(frame, quality=92)
            finally:
                self._video_processor.release(cap)
            captures = self._film.store.captures_dir(job.project_id)
            captures.mkdir(parents=True, exist_ok=True)
            target = captures / f"{shot.id}-continue.jpg"
            target.write_bytes(jpeg)
            return str(target)
        except Exception as exc:  # noqa: BLE001 - continuation is best-effort
            logger.warning("Could not extract previous-shot frame: %s", exc)
            return None

    def _finish_version(
        self,
        job: _QueuedShotJob,
        *,
        status: str,
        output_path: str = "",
        error: str = "",
        telemetry: dict[str, object] | None = None,
        seed_used: int | None = None,
    ) -> None:
        with self.lock:
            project = self._film.store.load(job.project_id)
            found = project.find_shot(job.shot_id)
            if found is None:
                return
            _, shot = found
            version = shot.version(job.version_number)
            if version is None:
                return
            version.status = status  # type: ignore[assignment]
            version.output_path = output_path
            version.error = error
            if seed_used is not None and version.seed is None:
                version.seed = seed_used
            if telemetry:
                seconds = telemetry.get("generation_seconds")
                if isinstance(seconds, (int, float)):
                    version.generation_seconds = float(seconds)
                gpu_name = telemetry.get("gpu_name")
                if isinstance(gpu_name, str):
                    version.gpu_name = gpu_name
                peak = telemetry.get("peak_vram_gb")
                if isinstance(peak, (int, float)):
                    version.peak_vram_gb = float(peak)
                render_model = telemetry.get("render_model")
                if isinstance(render_model, str) and render_model:
                    version.render_model = render_model
                mode = telemetry.get("execution_mode")
                if isinstance(mode, str) and mode:
                    version.execution_mode = mode
            if status == "complete":
                shot.current_version = version.number
                shot.status = "review"
            elif status == "cancelled":
                shot.status = "ready" if shot.capture_path else "composed"
            else:
                shot.status = "ready" if shot.capture_path else "composed"
            shot.updated_at = now_ms()
            self._film.store.save(project)
            recorded = (
                version.model,
                version.execution_mode,
                version.prompt,
                version.negative_prompt,
                version.generation_seconds,
            )
            job_metrics: dict[str, object] = {}
            if version.generation_seconds is not None:
                job_metrics["seconds"] = version.generation_seconds
            if version.peak_vram_gb is not None:
                job_metrics["peak_vram_mb"] = round(version.peak_vram_gb * 1024)
            if version.gpu_name:
                job_metrics["gpu_name"] = version.gpu_name

        if status == "complete" and output_path:
            score = self._consistency_score(job.project_id, job.shot_id, output_path)
            if score is not None:
                job_metrics["consistency"] = score

        if job.job_id and self._jobs is not None:
            metrics = {k: v for k, v in job_metrics.items()}
            if status == "complete" and output_path:
                self._jobs.complete(job.job_id, [output_path], metrics=metrics)
                if seed_used is not None:
                    self._jobs.annotate(job.job_id, seed=seed_used)
            elif status == "cancelled":
                self._jobs.mark_cancelled(job.job_id, reason=error or "Cancelled")
            else:
                self._jobs.fail(job.job_id, error or "Generation failed", metrics=metrics)

        # Outside the lock: learning is advisory and must never hold up a render
        # or fail one. The handler itself declines if the user switched it off.
        if self._knowledge is not None:
            outcome = {"complete": "success", "cancelled": "cancelled"}.get(status, "failure")
            model, mode, prompt, negative, seconds = recorded
            self._knowledge.record_generation(
                outcome=outcome,
                model=model,
                provider=mode,
                project_id=job.project_id,
                scene_id=job.scene_id,
                shot_id=job.shot_id,
                version_number=job.version_number,
                task="video",
                execution_mode=mode,
                prompt=prompt,
                negative_prompt=negative,
                duration_seconds=seconds,
                error=error,
            )

    def _consistency_score(self, project_id: str, shot_id: str, output_path: str) -> float | None:
        """Cross-frame consistency (phase 7): CLIP cosine between the shot's
        first frame and the reference image of each character in it, averaged.
        Best effort — never fails a render, None when nothing to compare."""
        if self._vision is None:
            return None
        try:
            project = self._film.store.load(project_id)
            found = project.find_shot(shot_id)
            if found is None:
                return None
            _, shot = found
            references = [
                self._film.store.resolve_media_path(project_id, asset.reference_images[0])
                for asset in (project.asset(c.asset_id) for c in shot.characters)
                if asset is not None and asset.reference_images
            ]
            references = [r for r in references if r.is_file()]
            if not references:
                return None
            cap = self._video_processor.open_video(output_path)
            try:
                frame = self._video_processor.read_frame(cap, 0)
                if frame is None:
                    return None
                jpeg = self._video_processor.encode_frame_jpeg(frame, quality=90)
            finally:
                self._video_processor.release(cap)
            # A scratch file, never project media: it must not show up in packages or the assets gallery.
            with tempfile.NamedTemporaryFile(prefix=f"{shot.id}-consistency-", suffix=".jpg", delete=False) as handle:
                handle.write(jpeg)
                probe = Path(handle.name)
            try:
                frame_vector = self._vision.embed(str(probe), "clip")
            finally:
                probe.unlink(missing_ok=True)
            scores: list[float] = []
            for reference in references:
                vector = self._vision.embed(str(reference), "clip")
                scores.append(cosine_similarity(frame_vector, vector))
            return round(sum(scores) / len(scores), 4) if scores else None
        except Exception as exc:  # noqa: BLE001 - advisory metric
            logger.info("Consistency score unavailable: %s", exc)
            return None

    def generate_reference_sheet(self, project_id: str, asset_id: str, req: ReferenceSheetRequest) -> ReferenceSheetResponse:
        """Consistency Kit: the same asset from several angles with one seed and
        its bound LoRA, saved as reference images (local image model only)."""
        project = self._film.get_project(project_id)
        asset = project.asset(asset_id)
        if asset is None:
            raise HTTPError(404, f"Asset not found: {asset_id}")
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        views = [v.strip() for v in req.views if v.strip()][:6] or ["front view"]
        seed = req.seed if req.seed is not None else asset.seed_lock
        if seed is None:
            seed = int(time.time()) % 2_000_000_000
        base = self._reference_prompt(asset, project.settings.style_prompt)
        trigger = asset.lora_trigger.strip()
        loras: list[LoraUse] = []
        if asset.lora_id and self._training is not None:
            try:
                entry = self._training.get_lora(asset.lora_id)
                loras.append(LoraUse(name=entry.file, multiplier=asset.lora_multiplier or entry.default_multiplier))
                trigger = trigger or entry.trigger
            except HTTPError:
                pass
        width, height = self._REFERENCE_SIZES.get(asset.kind, (1024, 1024))
        # With an image of the asset and a model that composes from it, every
        # view keeps that person; text alone drifted between views.
        identity = self._identity_image(project_id, asset, "")
        reference_model = handler.reference_model() if identity is not None else None
        engine = self._angle_engine(asset.kind) if identity is not None else None
        qwen = engine if engine is not None and engine.kind == "qwen" and engine.lora is not None else None
        if identity is not None and engine is not None and engine.kind == "zero123":
            # An object's style sheet is Zero123++'s turnaround of its photo (user,
            # 2026-10-04: "use zero123 for object styleguide and loras").
            return self._object_turnaround(project_id, asset, identity, seed)
        # A re-render replaces each view it renders (QA 2026-10-02: they piled
        # up among the references and in the LoRA dataset); never the identity.
        before = list(asset.reference_images)
        identity_ref = before[0] if before else ""
        face = self._identity_face(project_id, asset, identity) if identity is not None and reference_model else None
        identity_vector = self._face_vector(identity) if identity is not None else None
        prompts: list[str] = []
        paths: list[str] = []
        scores: list[float | None] = []
        for view in views:
            prompt = ", ".join(p for p in (trigger, base, SHEET_VIEW_WORDS.get(view, view), "consistent character sheet, same person, same outfit") if p)
            turn = sheet_angle_prompt(view) if qwen is not None else None
            prompts.append(turn or prompt)
            if identity is not None and qwen is not None and qwen.lora is not None and turn:
                # FLUX.2's sheet turned only in words (its profile faced the camera, 2026-10-03).
                chosen, score = self._best_render(
                    handler, GenerateImageRequest(prompt=turn, width=width, height=height, numImages=1, model=qwen.model,
                                                  loras=self._qwen_loras(qwen.lora)),
                    seed=seed, references=[str(identity)], mode="KI", identity_vector=identity_vector, candidates=1,
                )
            elif identity is not None and reference_model:
                lead = f"{ANGLE_SUBJECT}, {FACE_FROM.format(nth='second')}" if face else ANGLE_SUBJECT
                chosen, score = self._best_render(
                    handler, GenerateImageRequest(prompt=f"{lead}, {prompt}", width=width, height=height, numImages=1, model=reference_model),
                    seed=seed, references=[str(identity), *([str(face)] if face else [])], mode="I", identity_vector=identity_vector,
                )
            else:
                chosen, score = self._best_render(
                    handler, GenerateImageRequest(prompt=prompt, width=width, height=height, numImages=1, loras=loras),
                    seed=seed, references=None, mode="", identity_vector=identity_vector,
                )
            scores.append(score)
            encoded = base64.b64encode(chosen.read_bytes()).decode("ascii")
            token = view.replace(" ", "-")
            updated = self._film.add_asset_reference(project_id, asset_id, AddAssetReferenceRequest(image_base64=encoded, name_hint=f"{asset.name}-{token}"))
            paths.append(updated.reference_images[-1])
            for stale in before:
                if stale != identity_ref and Path(stale).stem.endswith(f"-{token}") and stale in updated.reference_images:
                    updated = self._film.delete_asset_reference(project_id, asset_id, stale)
        asset = self._film.get_project(project_id).asset(asset_id)
        assert asset is not None
        if asset.seed_lock is None:
            asset = self._film.update_asset(project_id, asset_id, UpdateAssetRequest(seed_lock=seed))
        return ReferenceSheetResponse(asset=asset, prompts=prompts, seed=seed, reference_paths=paths, face_scores=scores)

    def _face_vector(self, image: Path) -> list[float] | None:
        matcher = self._faces()
        if matcher is None:
            return None
        return matcher.embedding(str(image)) or None

    def _identity_face(self, project_id: str, asset: FilmAsset, identity: Path) -> Path | None:
        """A close-up of the identity photo's face, cached beside the captures:
        in a full-length photo the face is ~200 px, too little for FLUX.2 to keep
        it across angles (MEASURED 2026-10-02, SFace ~0.34 -> ~0.47 with the crop)."""
        if self._vision is None:
            return None
        folder = self._film.store.captures_dir(project_id) / "identity-faces"
        target = folder / f"{asset.id}-{identity.stem[:40]}-face.png"
        if target.is_file() and target.stat().st_mtime >= identity.stat().st_mtime:
            return target
        try:
            found = self._vision.vision.detect(str(identity), "caption_to_phrase_grounding", "face")
        except Exception as exc:  # noqa: BLE001 - the photo alone still works
            logger.info("No face found in %s: %s", identity.name, exc)
            return None
        if not found.regions:
            return None
        region = max(found.regions, key=lambda r: r.score)
        with Image.open(identity) as image:
            crops = dict(source_crops(image.convert("RGB"), region.bbox))
        crop = crops.get("source-face")
        if crop is None:
            return None
        folder.mkdir(parents=True, exist_ok=True)
        crop.save(target)
        return target

    def _best_render(
        self, handler: ImageGenerationHandler, request: GenerateImageRequest, *, seed: int,
        references: list[str] | None, mode: str, identity_vector: list[float] | None, candidates: int = FACE_CANDIDATES,
    ) -> tuple[Path, float | None]:
        """Render a view; with a face matcher, up to FACE_CANDIDATES seeds and keep
        the one whose face is closest to the identity photo (one close enough ends
        the search). A view with no face (a back view) keeps the first render."""
        matcher = self._faces()
        count = candidates if matcher is not None and identity_vector else 1
        best: Path | None = None
        best_score: float | None = None
        for attempt in range(count):
            if references is None:
                response = handler.generate(request, seed=seed + attempt * 1009)
            else:
                response = handler.generate(request, seed=seed + attempt * 1009, reference_images=references, reference_mode=mode)
            out_paths = response.image_paths or []
            if response.status != "complete" or not out_paths:
                raise HTTPError(502, "The image model did not return an image")
            path = Path(out_paths[0])
            if matcher is None or not identity_vector:
                return path, None
            vector = matcher.embedding(str(path))
            score = round(similarity(identity_vector, vector), 4) if vector else None
            if best is None or (score is not None and (best_score is None or score > best_score)):
                best, best_score = path, score
            if best_score is not None and best_score >= FACE_GOOD_ENOUGH:
                break
        assert best is not None
        return best, best_score

    def _identity_image(self, project_id: str, asset: FilmAsset, chosen: str) -> Path | None:
        """The asset's image every angle is composed from: `chosen` when it is
        one of its references, else the first reference."""
        candidates = [chosen] if chosen and chosen in asset.reference_images else list(asset.reference_images[:1])
        for relative in candidates:
            try:
                path = self._film.store.resolve_media_path(project_id, relative)
            except Exception:  # noqa: BLE001 - a stale path is simply not an identity
                continue
            if path.is_file():
                return path
        return None

    def generate_angle_set(self, project_id: str, asset_id: str, req: AngleSetRequest, size: tuple[int, int] | None = None) -> ReferenceSheetResponse:
        """Multi-angle shots of an asset for consistency and LoRA training. Each
        angle is composed by FLUX.2 from the asset's reference image (identity)
        and, from the 3D composer, the posed mannequin at that angle (pose,
        camera, framing): "KI" = the guide is the scene, the image the person.
        MEASURED (RTX 4070, FLUX.2 Klein 4B): front / three-quarter / profile /
        back kept the face, hair and outfit, ~7.6 s per angle once loaded."""
        project = self._film.get_project(project_id)
        asset = project.asset(asset_id)
        if asset is None:
            raise HTTPError(404, f"Asset not found: {asset_id}")
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        shots = [s for s in req.shots if s.view.strip()][:ANGLE_SET_MAX]
        if not shots:
            raise HTTPError(400, "Pick at least one angle")
        identity = self._identity_image(project_id, asset, req.identity_path)
        if identity is None:
            raise HTTPError(400, "Give the asset a reference image first (upload or generate one): every angle is composed from it")
        engine = self._angle_engine(asset.kind)
        if engine is None:
            raise HTTPError(400, "Multi-angle shots need Qwen-Image-Edit-2511, Zero123++ or FLUX.2 Klein installed (Settings → AI Models)")
        seed = req.seed if req.seed is not None else asset.seed_lock
        if seed is None:
            seed = int(time.time()) % 2_000_000_000
        if engine.kind == "zero123":
            return self._object_turnaround(project_id, asset, identity, seed)
        model = engine.model
        # Each angle says its own framing (full / medium / close-up); the sheet's
        # "full body ... head to feet" made every close-up a full shot (QA 2026-10-02).
        base = self._reference_prompt(asset, project.settings.style_prompt, framing="").replace(f"Character reference sheet of {asset.name}", asset.name)
        before = list(asset.reference_images)
        identity_ref = req.identity_path if req.identity_path in before else (before[0] if before else "")
        width, height = size or self._REFERENCE_SIZES.get(asset.kind, (1024, 1024))
        guides = self._film.store.captures_dir(project_id) / "angle-guides"
        face = self._identity_face(project_id, asset, identity)
        identity_vector = self._face_vector(identity)
        people = [str(identity), *([str(face)] if face else [])]
        prompts: list[str] = []
        paths: list[str] = []
        scores: list[float | None] = []
        for index, shot in enumerate(shots):
            loras: list[LoraUse] = []
            if engine.kind == "qwen" and engine.lora is not None:
                # The LoRA turns the camera around the photo: no mannequin guide, no description.
                prompt, references, mode = angle_prompt(shot.name), [str(identity)], "KI"
                loras = self._qwen_loras(engine.lora)
            else:
                references = people
                mode = "I"
                lead = f"{ANGLE_SUBJECT}, {FACE_FROM.format(nth='second')}" if face else ANGLE_SUBJECT
                if shot.guide_base64.strip():
                    guides.mkdir(parents=True, exist_ok=True)
                    guide = guides / f"{asset.id}-{index:02d}.png"
                    guide.write_bytes(_decode_image(shot.guide_base64))
                    references = [str(guide), *people]
                    mode = "KI"
                    lead = f"{ANGLE_SUBJECT_POSED}, {FACE_FROM.format(nth='third')}" if face else ANGLE_SUBJECT_POSED
                prompt = ", ".join(p for p in (lead, shot.view.strip(), base, ANGLE_QUALITY) if p)
            prompts.append(prompt)
            chosen, score = self._best_render(
                handler, GenerateImageRequest(prompt=prompt, width=width, height=height, numImages=1, model=model, loras=loras),
                seed=seed, references=references, mode=mode, identity_vector=identity_vector,
                # MEASURED 2026-10-04: Qwen 2511 int8 ~8 min an image at 30 steps (148 s with Lightning); one seed per angle.
                candidates=1 if engine.kind == "qwen" else FACE_CANDIDATES,
            )
            scores.append(score)
            encoded = base64.b64encode(chosen.read_bytes()).decode("ascii")
            name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in shot.name.strip().lower()) or f"angle-{index + 1}"
            updated = self._film.add_asset_reference(project_id, asset_id, AddAssetReferenceRequest(image_base64=encoded, name_hint=f"{asset.name}-{name}"))
            paths.append(updated.reference_images[-1])
            # A re-generated angle replaces its earlier image, as the sheet does.
            for stale in before:
                if stale != identity_ref and _saved_as(stale, f"{asset.name}-{name}") and stale in updated.reference_images:
                    updated = self._film.delete_asset_reference(project_id, asset_id, stale)
        asset = self._film.get_project(project_id).asset(asset_id)
        assert asset is not None
        if asset.seed_lock is None:
            asset = self._film.update_asset(project_id, asset_id, UpdateAssetRequest(seed_lock=seed))
        return ReferenceSheetResponse(asset=asset, prompts=prompts, seed=seed, reference_paths=paths, face_scores=scores)

    def _cast_references(self, project: FilmProject, shot: FilmShot) -> list[str]:
        """The first image of each character in the shot (at most two)."""
        out: list[str] = []
        for character in shot.characters:
            asset = project.asset(character.asset_id)
            if asset is None or not asset.reference_images:
                continue
            path = self._identity_image(project.id, asset, "")
            if path is not None:
                out.append(str(path))
        return out[:2]

    def generate_frame(self, project_id: str, scene_id: str, shot_id: str) -> FilmShot:
        """A storyboard frame for one shot: a still of what it describes, from
        its prompt, with the cast composed in from their reference images
        when FLUX.2 is installed (so they stay the same people shot to shot)."""
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        project = self._film.get_project(project_id)
        found = project.find_shot(shot_id)
        if found is None or found[0].id != scene_id:
            raise HTTPError(404, f"Shot not found: {shot_id}")
        scene, stored = found
        # `@Name` in the shot's text puts that asset in the cast (film/asset_mentions.py).
        shot = with_mentions(project, stored)
        prompt = shot.visual_prompt if shot.prompt_locked and shot.visual_prompt else synthesize_prompt(project, scene, shot)
        landscape = shot.generation.aspect_ratio != "9:16"
        width, height = (1024, 576) if landscape else (576, 1024)
        captures = self._film.store.captures_dir(project_id)
        captures.mkdir(parents=True, exist_ok=True)
        frame_file = captures / f"{shot.id}-frame.png"
        end_relative = ""
        cast = self._style_cast(project, shot)
        # `@Style` in the shot: the frame is drawn in that saved art style.
        styles = mentioned_styles(project, stored)
        look = style_text(styles[0]) if styles else ""
        style = self._style_composer() if cast else None
        if cast and style is not None:
            # Qwen-Image-Edit composes the cast from their style-guide images (user,
            # 2026-10-04: "ensure the videos are accurate to the styleguide"): the
            # image-to-video model takes its people from this frame.
            size = (1360, 768) if landscape else (768, 1360)
            frame_file.write_bytes(self._compose_frame(handler, style, prompt, cast, size, look=look).read_bytes())
            if shot.action.strip():
                # The end of the shot, from the start frame and the same people: the
                # video ends on the style guide too.
                end_prompt = (f"The same shot a few seconds later, at the end of: {shot.action.strip()}. "
                              "The same place, camera angle, framing and lighting as picture 1")
                end_file = captures / f"{shot.id}-frame-end.png"
                end_file.write_bytes(self._compose_frame(handler, style, end_prompt, cast[:2], size, scene=frame_file, look=look).read_bytes())
                end_relative = f"captures/{shot.id}-frame-end.png"
        else:
            references = self._cast_references(project, shot)
            model = handler.reference_model() if references else None
            if references and model:
                response = handler.generate(
                    GenerateImageRequest(prompt=f"{FRAME_CAST}, {prompt}", width=width, height=height, numImages=1, model=model),
                    reference_images=references, reference_mode="I",
                )
            else:
                response = handler.generate(GenerateImageRequest(prompt=prompt, width=width, height=height, numImages=1))
            paths = response.image_paths or []
            if response.status != "complete" or not paths:
                raise HTTPError(502, "The image model did not return a frame")
            frame_file.write_bytes(Path(paths[0]).read_bytes())
        if styles and styles[0].reference_images:
            # Then redrawn in the style from its pictures (USO, else Klein): the words
            # alone gave a photo whatever the style said.
            model = self._style_model()
            if model is not None:
                for file in [frame_file, *([captures / f"{shot.id}-frame-end.png"] if end_relative else [])]:
                    out, _ = self._restyle(handler, model, project_id, styles[0], file)
                    file.write_bytes(out.read_bytes())
        with self.lock:
            project = self._film.store.load(project_id)
            found = project.find_shot(shot_id)
            if found is None:
                raise HTTPError(404, f"Shot not found: {shot_id}")
            found[1].frame_path = f"captures/{shot.id}-frame.png"
            found[1].end_frame_path = end_relative
            found[1].updated_at = now_ms()
            self._film.store.save(project)
            return found[1]

    def _style_cast(self, project: FilmProject, shot: FilmShot) -> list[tuple[str, str, Path]]:
        """(name, kind, style-guide image) of the shot's cast for a composed frame:
        its characters (two at most), then its props; three pictures at most."""
        out: list[tuple[str, str, Path]] = []
        assets = [project.asset(c.asset_id) for c in shot.characters][:2] + [project.asset(p) for p in shot.prop_ids]
        for asset in assets:
            if asset is None or len(out) >= 3:
                continue
            image = self._identity_image(project.id, asset, "")
            if image is not None:
                out.append((asset.name.strip() or asset.kind, asset.kind, image))
        return out

    def _style_composer(self) -> list[LoraUse] | None:
        """Qwen-Image-Edit-2511's LoRAs for a composed frame when it can make one: the
        Lightning 8-step LoRA (without it 30 steps took ~10 minutes; 2026-10-04)."""
        handler = self._image_generation
        if handler is None or self._training is None or not handler.model_installed(QWEN_EDIT_2511):
            return None
        lightning = self._training.lora_root() / ANGLES_LORA_FOLDER / LIGHTNING_LORA_FILE
        return [LoraUse(name=str(lightning), multiplier=1.0)] if lightning.is_file() else None

    def _compose_frame(
        self, handler: ImageGenerationHandler, loras: list[LoraUse], prompt: str, cast: list[tuple[str, str, Path]],
        size: tuple[int, int], *, scene: Path | None = None, look: str = "",
    ) -> Path:
        """One Qwen-Image-Edit frame of `prompt` with the cast from their pictures
        (after `scene`, the picture of the place, when given)."""
        first = 2 if scene is not None else 1
        who = "; ".join(
            f"{name} is the person in picture {first + i}, with exactly that face, hair, body and outfit" if kind == "character"
            else f"the {name} is the object in picture {first + i}, exactly as it looks there"
            for i, (name, kind, _) in enumerate(cast)
        )
        references = ([str(scene)] if scene is not None else []) + [str(path) for _, _, path in cast]
        response = handler.generate(
            GenerateImageRequest(prompt=f"{prompt.rstrip('. ')}. {who}. {f'A film still in this art style: {look}' if look else 'A photorealistic film still'}.", width=size[0], height=size[1],
                                 numImages=1, model=QWEN_EDIT_2511, loras=loras),
            reference_images=references, reference_mode="KI" if scene is not None else "I",
        )
        paths = response.image_paths or []
        if response.status != "complete" or not paths:
            raise HTTPError(502, "The image model did not return a frame")
        return Path(paths[0])

    def _style_model(self) -> str | None:
        """The installed style-transfer model, best first (film/style_transfer.py)."""
        handler = self._image_generation
        if handler is None:
            return None
        return next((m for m in STYLE_TRANSFER_MODELS if handler.model_installed(m)), None)

    def _style_images(self, project_id: str, style: FilmAsset, count: int) -> list[str]:
        """`count` of the style's pictures on disk, the user's grades deciding which."""
        paths: list[str] = []
        for relative in style.reference_images:
            try:
                path = self._film.store.resolve_media_path(project_id, relative)
            except Exception:  # noqa: BLE001 - a stale path is simply not a style picture
                continue
            if path.is_file():
                paths.append(str(path))
        taste = self._taste
        return pick_style_images(
            paths, count=count,
            rejected=taste.rejected if taste is not None else (lambda _: False),
            liked=taste.liked if taste is not None else (lambda _: False),
        )

    def _restyle(
        self, handler: ImageGenerationHandler, model: str, project_id: str, style: FilmAsset, source: Path,
        *, subject: str = "", seed: int | None = None,
    ) -> tuple[Path, list[str]]:
        """`source` redrawn in `style` by `model`: the picture first, then the style's."""
        images = self._style_images(project_id, style, style_slots(model))
        if not images:
            raise HTTPError(400, f"The style {style.name} has no pictures: add an image of the art style first")
        with Image.open(source) as opened:
            width, height = opened.size
        scale = min(1.0, 1360 / max(width, height))
        width, height = max(256, int(width * scale) // 16 * 16), max(256, int(height * scale) // 16 * 16)
        request = GenerateImageRequest(
            prompt=transfer_prompt(model, style_text(style), subject=subject, styles=len(images)),
            width=width, height=height, numImages=1, model=model, faceLock=False, outfitLock=False,
            numSteps=USO_STEPS if model == USO_MODEL else 4,
        )
        response = handler.generate(
            request, seed=seed, reference_images=[str(source), *images], reference_mode=transfer_mode(model, has_content=True),
        )
        paths = response.image_paths or []
        if response.status != "complete" or not paths:
            raise HTTPError(502, "The image model did not return the restyled picture")
        return Path(paths[0]), images

    def apply_style(self, project_id: str, style_id: str, req: ApplyStyleRequest) -> ApplyStyleResponse:
        """A picture redrawn in a saved style: a shot's frame (and end frame), or a
        project image, kept in captures; the original stays on disk."""
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        project = self._film.get_project(project_id)
        style = project.asset(style_id)
        if style is None:
            raise HTTPError(404, f"Asset not found: {style_id}")
        if style.kind != "style":
            raise HTTPError(400, f"{style.name} is a {style.kind}, not a style")
        model = self._style_model()
        if model is None:
            raise HTTPError(400, "No style-transfer model is installed: download FLUX.1 USO Dev or FLUX.2 Klein in the Models tab")
        relatives: list[str] = []
        if req.shot_id:
            found = project.find_shot(req.shot_id)
            if found is None:
                raise HTTPError(404, f"Shot not found: {req.shot_id}")
            if not found[1].frame_path:
                raise HTTPError(400, "The shot has no frame yet: generate its frame first")
            relatives = [found[1].frame_path, *([found[1].end_frame_path] if found[1].end_frame_path else [])]
        elif req.image_path.strip():
            relatives = [req.image_path.strip()]
        else:
            raise HTTPError(400, "Pick a shot or an image to restyle")
        if req.target_asset_id and project.asset(req.target_asset_id) is None:
            raise HTTPError(404, f"Asset not found: {req.target_asset_id}")
        captures = self._film.store.captures_dir(project_id)
        captures.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", style.name.lower()).strip("-") or "style"
        made: list[str] = []
        used: list[str] = []
        for relative in relatives:
            try:
                source = self._film.store.resolve_media_path(project_id, relative)
            except Exception as exc:  # noqa: BLE001
                raise HTTPError(400, f"Image not found: {relative}") from exc
            if not source.is_file():
                raise HTTPError(400, f"Image not found: {relative}")
            out, used = self._restyle(handler, model, project_id, style, source, subject=req.subject, seed=req.seed)
            name = f"{Path(relative).stem}-{slug}-{now_ms()}.png"
            (captures / name).write_bytes(out.read_bytes())
            made.append(f"captures/{name}")
        with self.lock:
            project = self._film.store.load(project_id)
            shot: FilmShot | None = None
            asset: FilmAsset | None = None
            if req.shot_id:
                found = project.find_shot(req.shot_id)
                if found is not None:
                    shot = found[1]
                    shot.frame_path = made[0]
                    if len(made) > 1:
                        shot.end_frame_path = made[1]
                    shot.updated_at = now_ms()
            if req.target_asset_id:
                asset = project.asset(req.target_asset_id)
                if asset is not None:
                    asset.reference_images.append(made[0])
                    asset.updated_at = now_ms()
            self._film.store.save(project)
        return ApplyStyleResponse(image_path=made[0], model=model, style_images=used, shot=shot, asset=asset)

    def generate_frames(self, project_id: str, req: FramesRequest) -> FramesResponse:
        """Storyboard frames for every shot (by default only those with no
        picture yet: no frame, composer capture or finished render)."""
        project = self._film.get_project(project_id)
        generated, skipped = 0, 0
        failed: list[str] = []
        for scene in sorted(project.scenes, key=lambda s: s.order):
            for shot in sorted(scene.shots, key=lambda s: s.order):
                rendered = any(v.status == "complete" and v.output_path for v in shot.versions)
                if req.missing_only and (shot.frame_path or shot.capture_path or rendered):
                    skipped += 1
                    continue
                try:
                    self.generate_frame(project_id, scene.id, shot.id)
                    generated += 1
                except HTTPError as exc:
                    failed.append(f"{shot.title or shot.id}: {exc.detail}")
        return FramesResponse(generated=generated, skipped=skipped, failed=failed)

    def preview_render(self, project_id: str, req: PreviewRenderRequest) -> PreviewRenderResponse:
        """The photo as the 3D model is now posed: FLUX.2 composes the person
        from the original photo into the pose, camera angle and framing of
        the composer's viewfinder. A fixed seed, so successive previews differ
        by the edit, not by chance. Throwaway: no History job, and no file left in the project
        or the outputs folder."""
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        model = handler.reference_model()
        if model is None:
            raise HTTPError(400, "Live previews need FLUX.2 Klein installed (Settings → AI Models)")
        folder = self._film.store.captures_dir(project_id) / "previews"
        if req.reference_path:
            try:
                photo = self._film.store.resolve_media_path(project_id, req.reference_path)
            except HTTPError:
                raise
            except Exception as exc:  # noqa: BLE001 - an escaping or malformed path
                raise HTTPError(400, f"The photo is not part of this project: {exc}") from exc
            if not photo.is_file():
                raise HTTPError(404, "The original photo is no longer on disk")
        elif req.reference_base64:
            folder.mkdir(parents=True, exist_ok=True)
            photo = folder / "pose-original.png"
            photo.write_bytes(_decode_image(req.reference_base64))
        else:
            raise HTTPError(400, "A preview needs the original photo or frame to keep")
        scale = min(1.0, PREVIEW_MAX_EDGE / max(1, req.width, req.height))
        width = max(256, int(req.width * scale) // 16 * 16)
        height = max(256, int(req.height * scale) // 16 * 16)
        folder.mkdir(parents=True, exist_ok=True)
        guide = folder / "pose-guide.png"
        guide.write_bytes(_decode_image(req.guide_base64))
        prompt = ", ".join(p for p in (PREVIEW_SUBJECT, req.pose.strip(), req.prompt.strip(), PREVIEW_KEEP) if p)
        started = time.perf_counter()
        response = handler.generate(
            GenerateImageRequest(prompt=prompt, width=width, height=height, numImages=1, model=model),
            seed=req.seed if req.seed is not None else PREVIEW_SEED,
            reference_images=[str(guide), str(photo)], reference_mode="KI", record=False,
        )
        paths = response.image_paths or []
        if response.status != "complete" or not paths:
            raise HTTPError(502, "The image model did not return a preview")
        out = Path(paths[0])
        mime = "image/png" if out.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(out.read_bytes()).decode("ascii")
        # Throwaway: the preview leaves no file in the outputs folder.
        for leftover in [*paths, str(guide)]:
            Path(leftover).unlink(missing_ok=True)
        return PreviewRenderResponse(image=f"data:{mime};base64,{encoded}", seconds=round(time.perf_counter() - started, 2), model=model)

    def asset_dataset(self, project_id: str, asset_id: str, *, angles: bool = False) -> Dataset:
        """The asset's images as a LoRA training dataset (character preset for
        people), its trigger the asset's LoRA trigger or its name. With `angles`,
        the angles a LoRA needs that the asset lacks are rendered first."""
        if self._training is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Training is not available in this build")
        project = self._film.get_project(project_id)
        asset = project.asset(asset_id)
        if asset is None:
            raise HTTPError(404, f"Asset not found: {asset_id}")
        if angles and asset.kind != "style":
            self._lora_angles(project_id, asset)
            asset = self._film.get_project(project_id).asset(asset_id)
            assert asset is not None
        images: list[str] = []
        for relative in asset.reference_images:
            try:
                path = self._film.store.resolve_media_path(project_id, relative)
            except Exception:  # noqa: BLE001
                continue
            if path.is_file():
                images.append(str(path))
        if not images:
            raise HTTPError(400, "The asset has no images yet: generate a multi-angle set first")
        # The user's grades (film/taste.py): style-guide and angle images graded
        # down stay out (never the identity photo); renders graded up that were
        # made with this character's LoRA come in, face-checked like the rest.
        if self._taste is not None:
            taste = self._taste
            images = [images[0], *(i for i in images[1:] if not taste.rejected(i))]
            if asset.lora_id:
                try:
                    bound = self._training.get_lora(asset.lora_id).file
                except HTTPError:
                    bound = ""
                images += [r for r in taste.liked_renders(bound) if r not in images]
        preset = {"character": "character", "style": "style"}.get(asset.kind, "object")
        # A character's default trigger is a rare token: "raven" rendered the bird (2026-10-02).
        name_trigger = "".join(ch for ch in asset.name.lower() if ch.isalnum() or ch == "_") or "subject"
        trigger = asset.lora_trigger.strip() or (rare_trigger(asset.name) if preset == "character" else name_trigger)
        dataset = self._training.create_dataset(name=f"{asset.name} (asset)", preset=preset, trigger=trigger)  # type: ignore[arg-type]
        if preset != "character":
            return self._training.import_items(dataset.id, ImportDatasetItemsRequest(image_paths=images))
        # Generated images whose face is not the photo's person are left out: they
        # taught Raven's LoRA a blend of strangers (SFace 0.25-0.43, 2026-10-02).
        scores: dict[str, float | None] = {}
        reference = self._face_vector(Path(images[0]))
        if reference is not None:
            kept = [images[0]]
            scores[images[0]] = 1.0
            for image in images[1:]:
                vector = self._face_vector(Path(image))
                score = round(similarity(reference, vector), 4) if vector else None
                if score is None or score >= _same_person_floor(image):
                    kept.append(image)
                    scores[image] = score
            images = kept
        # The real photo, weighted up: twice, plus head and upper-body crops of it.
        with tempfile.TemporaryDirectory(prefix="lora-source-") as folder:
            crops = self._source_crops(Path(images[0]), Path(folder), asset.name)
            extra = [images[0], *crops]
            # ...and a close-up of every generated view whose face matches well.
            face_crops = self._face_crops(images[1:], scores, reference, Path(folder))
            scores.update(face_crops)
            dataset = self._training.import_items(dataset.id, ImportDatasetItemsRequest(image_paths=[images[0], *extra, *images[1:], *face_crops]))
        # Each image keeps its face score for the Train screen. The full-body views
        # train twice per epoch, everything else once. MEASURED 2026-10-02: weighting
        # the photo, its crops and the sheet 3x scored 0.331 vs 0.354 unweighted and
        # the trigger alone lost the outfit - the outfit lives in the full-body
        # shots. MEASURED 2026-10-03: the face close-ups lifted the face (0.452 ->
        # 0.518) but crowded those shots out (a bikini at 180-240 steps); doubling
        # them brought the outfit back by step 160.
        weights: dict[str, tuple[int, float | None]] = {
            Path(image).name: (2 if "-full-" in Path(image).name else 1, scores.get(image)) for image in [images[0], *crops, *images[1:], *face_crops]
        }
        return self._training.set_item_weights(dataset.id, weights)

    def _lora_angles(self, project_id: str, asset: FilmAsset) -> None:
        """Render the LoRA angles the asset lacks (user, 2026-10-04: "use qwen to make
        multiple angles ... for z-image turbo LoRA's ... use zero123 for object
        styleguide and loras"): Zero123++'s turnaround, or Qwen's LORA_ANGLE_SHOTS at
        ~1 MP. FLUX.2 without the composer's guides only turned in words: no angles."""
        identity = self._identity_image(project_id, asset, "")
        engine = self._angle_engine(asset.kind) if identity is not None else None
        if identity is None or engine is None:
            return
        seed = asset.seed_lock if asset.seed_lock is not None else int(time.time()) % 2_000_000_000
        if engine.kind == "zero123":
            if not any("-z123-" in Path(r).stem for r in asset.reference_images):
                self._object_turnaround(project_id, asset, identity, seed)
            return
        if engine.kind != "qwen":
            return
        missing = [s for s in LORA_ANGLE_SHOTS if not any(_saved_as(r, f"{asset.name}-{s}") for r in asset.reference_images)]
        if missing:
            shots = [AngleShot(name=s, view=s.replace("-", " ")) for s in missing]
            self.generate_angle_set(project_id, asset.id, AngleSetRequest(shots=shots, seed=seed), size=LORA_ANGLE_SIZE)

    def _face_crops(self, images: list[str], scores: dict[str, float | None], reference: list[float] | None, folder: Path) -> dict[str, float | None]:
        """Head-and-shoulders crops of the generated views whose face matches the
        photo well, each kept only when the crop itself still matches: path -> score."""
        matcher = self._faces()
        if matcher is None or reference is None:
            return {}
        out: dict[str, float | None] = {}
        for image in images:
            score = scores.get(image)
            if score is None or score < FACE_CROP_MIN:
                continue
            box = matcher.face_box(image)
            if box is None:
                continue
            with Image.open(image) as opened:
                crop = face_crop(opened.convert("RGB"), box)
            if crop is None:
                continue
            path = folder / f"{face_crop_name(Path(image).stem)}.png"
            crop.save(path)
            vector = matcher.embedding(str(path))
            crop_score = round(similarity(reference, vector), 4) if vector else None
            if crop_score is not None and crop_score >= FACE_CROP_MIN:
                out[str(path)] = crop_score
        return out

    def _source_crops(self, photo: Path, folder: Path, name: str) -> list[str]:
        """Crops around the face Florence finds in the photo; none when it finds none."""
        if self._vision is None:
            return []
        try:
            found = self._vision.vision.detect(str(photo), "caption_to_phrase_grounding", "face")
        except Exception as exc:  # noqa: BLE001 - crops are a bonus; the dataset stands without them
            logger.info("No face crops for %s: %s", photo.name, exc)
            return []
        if not found.regions:
            return []
        face = max(found.regions, key=lambda region: region.score)
        out: list[str] = []
        with Image.open(photo) as image:
            for suffix, crop in source_crops(image.convert("RGB"), face.bbox):
                path = folder / f"{name}-{suffix}.png"
                crop.save(path)
                out.append(str(path))
        return out

    #: The views a LoRA preview renders, from the trigger alone.
    PREVIEW_VIEWS = (
        "close-up portrait, front view",
        "medium shot, three-quarter view from the left",
        "full body shot, front view",
        "full body shot, profile view from the left",
    )

    def preview_lora(self, lora_id: str) -> LoraEntry:
        """The standard views rendered with the LoRA from its trigger alone - what
        the LoRA knows, with no description to lean on - each face scored against
        the dataset's photo (user, 2026-10-02: "a preview of the LoRA where we can
        see the different LoRA angle images in the software")."""
        if self._training is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Training is not available in this build")
        handler = self._image_generation
        if handler is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "Local image generation is not available in this build")
        entry = self._training.get_lora(lora_id)
        person = "person"
        photo: Path | None = None
        if entry.dataset_id:
            try:
                dataset = self._training.get_dataset(entry.dataset_id)
            except HTTPError:
                dataset = None
            if dataset is not None and dataset.items:
                first = dataset.items[0]
                words = [w.strip() for w in first.caption.split(",")]
                if len(words) >= 2 and words[1] in PERSON_WORDS:
                    person = words[1]
                photo = self._training.media_path(dataset.id, first.file)
        identity_vector = self._face_vector(photo) if photo is not None and photo.is_file() else None
        folder = self._training.preview_root() / entry.id
        folder.mkdir(parents=True, exist_ok=True)
        loras = [LoraUse(name=entry.file, multiplier=entry.default_multiplier or 1.0)]
        # The preview shows what a render gives: face-locked to the style sheet when it can be.
        identity = self._lora_identity(loras)
        paths: list[str] = []
        scores: list[float | None] = []
        for index, view in enumerate(self.PREVIEW_VIEWS):
            prompt = ", ".join(p for p in (entry.trigger, person, view) if p)
            response = handler.generate(GenerateImageRequest(prompt=prompt, width=768, height=1024, numImages=1, loras=loras), seed=PREVIEW_SEED + index)
            out_paths = response.image_paths or []
            if response.status != "complete" or not out_paths:
                raise HTTPError(502, "The image model did not return a preview")
            source = Path(out_paths[0])
            target = folder / f"{index + 1:02d}{source.suffix.lower() or '.png'}"
            shutil.copyfile(source, target)
            paths.append(str(target))
            if identity is not None:
                scores.append(self._lock_sheet(target, identity, outfit=True)[0])
                continue
            vector = self._face_vector(target) if identity_vector else None
            scores.append(round(similarity(identity_vector, vector), 4) if identity_vector and vector else None)
        return self._training.set_lora_preview(entry.id, paths, scores)

    def sheet_lock(self, paths: list[str], loras: list[LoraUse], *, outfit: bool = True) -> tuple[list[float | None], list[bool]] | None:
        """Each image locked to the style sheet of the first character LoRA in
        `loras` that was trained here (film.face_lock): the outfit re-composed
        from the sheet's front view (medium and full shots, with `outfit`), then
        the face from the sheet's head, kept only when it then matches the
        photo better. Returns (each image's face score after, whether its
        outfit was re-composed); None when no LoRA has a character to lock to."""
        identity = self._lora_identity(loras)
        if identity is None:
            return None
        results = [self._lock_sheet(Path(path), identity, outfit=outfit) for path in paths]
        return [score for score, _ in results], [dressed for _, dressed in results]

    def _lock_sheet(self, path: Path, identity: tuple[Path, Path, list[float]], *, outfit: bool) -> tuple[float | None, bool]:
        head, sheet, reference = identity
        dressed = self._lock_outfit(path, sheet) if outfit else False
        return self._lock_face(path, head, reference), dressed

    def _lock_outfit(self, path: Path, sheet: Path) -> bool:
        """One image's outfit pass: the whole character re-composed from the
        style sheet's front view, the image as the scene. Kept only when the
        shot stayed the shot; close-ups and profiles are left alone."""
        matcher = self._faces()
        handler = self._image_generation
        model = handler.reference_model() if handler is not None else None
        if matcher is None or handler is None or model is None:
            return False
        found = matcher.face_points(str(path))
        if found is None:
            return False  # no face to check the framing by (a back view)
        box, points = found
        with Image.open(path) as opened:
            width, height = opened.size
        turn = yaw(points)
        if is_close_up(box, width) or abs(turn) > PROFILE_YAW:
            return False
        render_width, render_height = fit_size(width, height)
        response = handler.generate(
            GenerateImageRequest(prompt=OUTFIT_LOCK_PROMPT, width=render_width, height=render_height, numImages=1, model=model),
            seed=OUTFIT_LOCK_SEED, reference_images=[str(path), str(sheet)], reference_mode="KI", record=False,
        )
        outs = response.image_paths or []
        if response.status != "complete" or not outs:
            return False
        rendered = Path(outs[0])
        with tempfile.TemporaryDirectory(prefix="outfitlock-") as folder:
            candidate = Path(folder) / "outfit-candidate.png"
            with Image.open(rendered) as made:
                dressed = made.convert("RGB")
                if dressed.size != (width, height):
                    dressed = dressed.resize((width, height), Image.Resampling.LANCZOS)
                dressed.save(candidate)
            rendered.unlink(missing_ok=True)
            after = matcher.face_points(str(candidate))
            if after is None or not framing_kept(box, after[0]) or abs(yaw(after[1]) - turn) > MAX_YAW_SHIFT:
                return False
            if path.suffix.lower() in (".jpg", ".jpeg"):
                dressed.save(path, quality=95)
            else:
                dressed.save(path)
        return True

    def _lora_identity(self, loras: list[LoraUse]) -> tuple[Path, Path, list[float]] | None:
        """(the style sheet's head, its whole front view, the photo's face vector)
        of the first LoRA trained from a character dataset; None without the
        models to lock with."""
        matcher = self._faces()
        handler = self._image_generation
        if self._training is None or matcher is None or handler is None or handler.reference_model() is None:
            return None
        for use in loras:
            entry = self._training.lora_for_file(use.name)
            if entry is None or not entry.dataset_id:
                continue
            try:
                dataset = self._training.get_dataset(entry.dataset_id)
            except HTTPError:
                continue
            if not dataset.items:
                continue
            photo = self._training.media_path(dataset.id, dataset.items[0].file)
            vector = matcher.embedding(str(photo)) if photo.is_file() else None
            if not vector:
                continue
            sheet = next((item for item in dataset.items if "front-view" in item.file), dataset.items[0])
            front = self._training.media_path(dataset.id, sheet.file)
            return self._identity_head(entry.id, front), front, vector
        return None

    def _identity_head(self, lora_id: str, image: Path) -> Path:
        """The head of the style sheet's front view, cached beside the LoRA's
        previews; the whole view when no face is found in it."""
        assert self._training is not None
        target = self._training.preview_root() / lora_id / f"identity-{image.stem[:60]}.png"
        if target.is_file() and target.stat().st_mtime >= image.stat().st_mtime:
            return target
        matcher = self._faces()
        found = matcher.face_points(str(image)) if matcher is not None else None
        if found is None:
            return image
        with Image.open(image) as opened:
            rgb = opened.convert("RGB")
            square = head_square(found[0], rgb.width, rgb.height, scale=FACE_LOCK_REFERENCE_SCALE)
            if square is None:
                return image
            left, top, side = square
            target.parent.mkdir(parents=True, exist_ok=True)
            rgb.crop((left, top, left + side, top + side)).save(target)
        return target

    def _lock_face(self, path: Path, head_reference: Path, reference: list[float]) -> float | None:
        """One image's face lock; returns its face score after (or as it was)."""
        matcher = self._faces()
        handler = self._image_generation
        model = handler.reference_model() if handler is not None else None
        if matcher is None or handler is None or model is None:
            return None
        vector = matcher.embedding(str(path))
        before = round(similarity(reference, vector), 4) if vector else None
        found = matcher.face_points(str(path))
        if found is None:
            return before
        box, points = found
        turn = yaw(points)
        if abs(turn) > PROFILE_YAW:
            return before  # a profile: the style sheet has no side face to lock it to
        prompt = FACE_LOCK_PROMPT if abs(turn) <= FRONT_YAW else FACE_LOCK_TURNED_PROMPT
        with Image.open(path) as opened:
            image = np.asarray(opened.convert("RGB"))
        square = head_square(box, image.shape[1], image.shape[0])
        if square is None:
            return before
        left, top, side = square
        best_score, best = before, None
        with tempfile.TemporaryDirectory(prefix="facelock-") as folder:
            guide = Path(folder) / f"{path.stem}-guide.png"
            Image.fromarray(image[top:top + side, left:left + side]).save(guide)
            for attempt, seed in enumerate(FACE_LOCK_SEEDS):
                response = handler.generate(
                    GenerateImageRequest(prompt=prompt, width=FACE_LOCK_SIZE, height=FACE_LOCK_SIZE, numImages=1, model=model),
                    seed=seed, reference_images=[str(guide), str(head_reference)], reference_mode="KI", record=False,
                )
                outs = response.image_paths or []
                if response.status != "complete" or not outs:
                    break
                rendered = Path(outs[0])
                head_file = Path(folder) / f"{rendered.stem}-head.png"
                with Image.open(rendered) as made:
                    made.convert("RGB").resize((side, side), Image.Resampling.LANCZOS).save(head_file)
                rendered.unlink(missing_ok=True)
                head_found = matcher.face_points(str(head_file))
                if head_found is None or abs(yaw(head_found[1]) - turn) > MAX_YAW_SHIFT:
                    continue  # no face, or the head turned: the pose is the render's
                with Image.open(head_file) as opened_head:
                    head = np.asarray(opened_head.convert("RGB"))
                blended = blend_face(image, head, (left, top), head_found[1], points, box)
                if blended is None:
                    continue
                candidate = Path(folder) / f"{path.stem}-facelock-{attempt}.png"
                Image.fromarray(blended).save(candidate)
                locked = matcher.embedding(str(candidate))
                score = round(similarity(reference, locked), 4) if locked else None
                if score is not None and (best_score is None or score > best_score):
                    best_score, best = score, blended
                if best_score is not None and best_score >= FACE_GOOD_ENOUGH:
                    break
        if best is not None:
            locked_image = Image.fromarray(best)
            if path.suffix.lower() in (".jpg", ".jpeg"):
                locked_image.save(path, quality=95)
            else:
                locked_image.save(path)
        return best_score

    def attach_taste(self, taste: TasteHandler) -> None:
        self._taste = taste

    def attach_multiview(self, multiview: MultiViewGenerator) -> None:
        self._multiview = multiview

    # ---- multi-angle engines (film.multi_angle) -------------------------------

    def _qwen_angles_lora(self) -> Path | None:
        if self._training is None:
            return None
        path = self._training.lora_root() / ANGLES_LORA_FOLDER / ANGLES_LORA_FILE
        return path if path.is_file() else None

    def _qwen_loras(self, angles: Path) -> list[LoraUse]:
        """The Multiple-Angles LoRA, plus the Lightning 8-step LoRA when it sits beside it."""
        loras = [LoraUse(name=str(angles), multiplier=ANGLES_LORA_STRENGTH)]
        lightning = angles.parent / LIGHTNING_LORA_FILE
        if lightning.is_file():
            loras.append(LoraUse(name=str(lightning), multiplier=1.0))
        return loras

    def _angle_engines(self) -> dict[str, AngleEngine]:
        """Every multi-angle engine installed here, by its settings id."""
        handler = self._image_generation
        engines: dict[str, AngleEngine] = {}
        lora = self._qwen_angles_lora()
        if handler is not None and lora is not None and handler.model_installed(QWEN_EDIT_2511):
            engines[QWEN_EDIT_2511] = AngleEngine("qwen", QWEN_EDIT_2511, QWEN_ANGLES_LABEL, lora)
        if self._multiview is not None and self._multiview.available():
            engines[ZERO123PP] = AngleEngine("zero123", ZERO123PP, ZERO123PP_LABEL)
        flux = handler.reference_model() if handler is not None else None
        if flux is not None and flux != QWEN_EDIT_2511:
            engines[flux] = AngleEngine("flux", flux, f"FLUX.2 Klein ({flux})")
        return engines

    def _angle_engine(self, asset_kind: str) -> AngleEngine | None:
        """The engine for an asset's angles: the one chosen in Settings when it is
        installed, else the best installed - Zero123++ then Qwen for objects
        (props), Qwen for characters and scenes, FLUX.2 last."""
        engines = self._angle_engines()
        with self.lock:
            settings = self.state.app_settings
            chosen = settings.object_angle_model if asset_kind == "prop" else settings.character_angle_model
        if chosen in engines:
            return engines[chosen]
        order = [ZERO123PP, QWEN_EDIT_2511] if asset_kind == "prop" else [QWEN_EDIT_2511]
        for engine_id in order:
            if engine_id in engines:
                return engines[engine_id]
        return next((e for e in engines.values() if e.kind == "flux"), None)

    def multi_angle_status(self) -> dict[str, object]:
        """What renders angles for characters and for objects now, and every
        choice Settings can offer (installed or not)."""
        engines = self._angle_engines()
        character = self._angle_engine("character")
        obj = self._angle_engine("prop")
        flux = next((e.model for e in engines.values() if e.kind == "flux"), "flux2_klein_4b")
        choices = [
            {"id": "", "label": "Best installed (automatic)", "installed": True},
            {"id": QWEN_EDIT_2511, "label": QWEN_ANGLES_LABEL, "installed": QWEN_EDIT_2511 in engines},
            {"id": ZERO123PP, "label": f"{ZERO123PP_LABEL} (objects; non-commercial licence)", "installed": ZERO123PP in engines},
            {"id": flux, "label": f"FLUX.2 Klein ({flux})", "installed": flux in engines},
        ]
        return {"characters": character.label if character else "", "objects": obj.label if obj else "", "choices": choices}

    def _object_turnaround(self, project_id: str, asset: FilmAsset, identity: Path, seed: int) -> ReferenceSheetResponse:
        """Zero123++'s six views of an object around its photo, added to the asset."""
        assert self._multiview is not None
        try:
            views = self._multiview.generate(str(identity), seed=seed)
        finally:
            self._multiview.unload()  # give the GPU back to WanGP
        prompts: list[str] = []
        paths: list[str] = []
        before = list(asset.reference_images)
        updated = asset
        for view in views:
            slug = "".join(ch if ch.isalnum() else "-" for ch in view.label.lower())
            prompts.append(f"Zero123++: {view.label} (azimuth {view.azimuth}, elevation {view.elevation})")
            encoded = base64.b64encode(Path(view.path).read_bytes()).decode("ascii")
            updated = self._film.add_asset_reference(project_id, asset.id, AddAssetReferenceRequest(image_base64=encoded, name_hint=f"{asset.name}-z123-{slug}"))
            paths.append(updated.reference_images[-1])
            for stale in before:
                if _saved_as(stale, f"{asset.name}-z123-{slug}") and stale in updated.reference_images:
                    updated = self._film.delete_asset_reference(project_id, asset.id, stale)
        fresh = self._film.get_project(project_id).asset(asset.id)
        assert fresh is not None
        return ReferenceSheetResponse(asset=fresh, prompts=prompts, seed=seed, reference_paths=paths, face_scores=[None] * len(paths))

    def attach_training(self, training: TrainingHandler, vision: VisionHandler | None = None, face_matcher: FaceMatcher | None = None) -> None:
        self._training = training
        self._vision = vision
        self._face_matcher_service = face_matcher

    def _faces(self) -> FaceMatcher | None:
        """The face matcher when it can run (its model files present)."""
        matcher = self._face_matcher_service
        return matcher if matcher is not None and matcher.available() else None

    def asset_loras(self, project: FilmProject, shot: FilmShot, model_type: str | None = None) -> list[LoraUse]:
        """Every LoRA bound to an asset the shot references, deduplicated; with a
        `model_type`, only those trained for that model's family."""
        if self._training is None:
            return []
        out: list[LoraUse] = []
        seen: set[str] = set()
        asset_ids = [c.asset_id for c in shot.characters] + list(shot.prop_ids) + ([shot.location_id] if shot.location_id else [])
        for asset_id in asset_ids:
            asset = project.asset(asset_id)
            if asset is None or not asset.lora_id or asset.lora_id in seen:
                continue
            seen.add(asset.lora_id)
            try:
                entry = self._training.get_lora(asset.lora_id)
            except HTTPError:
                continue
            if model_type is not None and not lora_fits(entry.target, model_type):
                continue
            out.append(LoraUse(name=entry.file, multiplier=asset.lora_multiplier if asset.lora_multiplier > 0 else entry.default_multiplier))
        return out

    @staticmethod
    def asset_seed_lock(project: FilmProject, shot: FilmShot) -> int | None:
        for character in shot.characters:
            asset = project.asset(character.asset_id)
            if asset is not None and asset.seed_lock is not None:
                return asset.seed_lock
        return None

    def attach_knowledge(self, knowledge: KnowledgeHandler) -> None:
        """Give the queue somewhere to report outcomes.

        Set after construction rather than injected, so the knowledge handler
        can be built in any order relative to this one and the queue keeps
        working if it is never attached.
        """
        self._knowledge = knowledge

    # ---- Capabilities ----------------------------------------------------

    def _gpu_verdict(self, vram_gb: float | None, execution_mode: str) -> tuple[str, str]:
        """One-sentence compatibility verdict + severity for the detected GPU.

        Thresholds come from this repository's documented requirements: the
        WanGP bridge runs on 6 GB+ VRAM; the native local pipeline on ~32 GB.
        """
        if execution_mode == "api":
            if vram_gb is None:
                return (
                    "No CUDA GPU detected — generation runs through the cloud API. "
                    "Local generation needs an NVIDIA GPU (6 GB+ with WanGP).",
                    "none",
                )
            return (
                f"Cloud API mode — your {vram_gb:.0f} GB GPU is not used for generation. "
                "A WanGP checkout enables local generation on 6 GB+ GPUs.",
                "partial",
            )
        if vram_gb is None:
            return (
                "GPU VRAM could not be detected — compatibility badges are unavailable. "
                "Downloads still work; generation will report clear errors if the GPU is insufficient.",
                "partial",
            )
        if vram_gb >= _NATIVE_LOCAL_MIN_VRAM_GB:
            return (
                f"{vram_gb:.0f} GB VRAM fits every local path: the native LTX pipeline "
                f"(~{_NATIVE_LOCAL_MIN_VRAM_GB:.0f} GB) and WanGP ({_WANGP_MIN_VRAM_GB:.0f} GB+).",
                "ok",
            )
        if vram_gb >= _WANGP_MIN_VRAM_GB:
            return (
                f"{vram_gb:.0f} GB VRAM fits the WanGP path ({_WANGP_MIN_VRAM_GB:.0f} GB+). "
                f"The native local pipeline needs ~{_NATIVE_LOCAL_MIN_VRAM_GB:.0f} GB and may not run.",
                "ok" if execution_mode == "wangp" else "partial",
            )
        return (
            f"{vram_gb:.0f} GB VRAM is below the documented {_WANGP_MIN_VRAM_GB:.0f} GB minimum "
            "for local generation — use the cloud API mode.",
            "none",
        )

    @staticmethod
    def _quality_profiles(
        vram_gb: float | None, execution_mode: str, models: list[FilmModelCapability]
    ) -> list[FilmQualityProfile]:
        """Quality presets evaluated against the detected GPU. On the API path
        everything 'fits'; locally the video model's fit applies to all presets."""
        if vram_gb is None:
            recommended = "balanced"
        elif vram_gb < 8:
            recommended = "fast_preview"
        elif vram_gb < 16:
            recommended = "balanced"
        else:
            recommended = "quality"
        video_fit: bool | None = None
        if execution_mode == "api":
            video_fit = True
        else:
            for model in models:
                if "video" in model.modes and model.required and model.download_state != "not_configured":
                    video_fit = model.fits_gpu
                    break
        profiles: list[FilmQualityProfile] = []
        for profile_id, (model, resolution, label, description) in QUALITY_PROFILES.items():
            if execution_mode == "api" and resolution not in _FORCED_API_RESOLUTIONS:
                resolution = "1080p"
            profiles.append(
                FilmQualityProfile(
                    id=profile_id,
                    label=label,
                    model=model,
                    resolution=resolution,
                    description=description,
                    recommended=profile_id == recommended,
                    fits_gpu=video_fit,
                )
            )
        profiles.append(
            FilmQualityProfile(
                id="custom",
                label="Custom",
                model="",
                resolution="",
                description="Use the model and resolution set on each shot.",
                recommended=False,
                fits_gpu=None,
            )
        )
        return profiles

    def _models_path(self) -> str:
        if self._config.wangp_enabled and self._config.wangp_root is not None:
            return str(self._config.wangp_root / "ckpts")
        return str(self._config.models_dir)

    def _wangp_model_rows(self, fits: Callable[[float | None], bool | None]) -> list[FilmModelCapability]:
        """Rows for WanGP mode from the checkout's own model definitions. The
        configured video/image types are 'active'; other LTX/video families
        are 'available' (WanGP downloads them on first use) or 'installed'."""
        active_video = self._config.wangp_video_model_type
        active_image = self._config.wangp_image_model_type
        definitions = self._wangp_bridge.list_model_definitions() if self._wangp_bridge is not None else []
        rows: list[FilmModelCapability] = []
        seen: set[str] = set()
        for definition in definitions:
            model_id = str(definition.get("id", ""))
            architecture = str(definition.get("architecture", ""))
            family = _wangp_family(architecture or model_id)
            task = _wangp_task(architecture or model_id)
            if task not in ("video", "image"):
                continue  # audio / LLM defaults are not film models
            installed = bool(definition.get("installed", False))
            is_active = model_id in (active_video, active_image)
            state = "active" if is_active else "installed" if installed else "available"
            quant_raw = definition.get("quantized_variants", [])
            quant = ", ".join(str(q) for q in cast(list[object], quant_raw)) if isinstance(quant_raw, list) else ""
            minimum = _WANGP_MIN_VRAM_GB if family.startswith("ltx") or family in ("wan", "hunyuan", "z_image", "flux") else None
            rows.append(
                FilmModelCapability(
                    id=model_id,
                    label=f"WanGP · {definition.get('name', model_id)}",
                    modes=["video"] if task == "video" else ["image"],
                    supports_image_to_video=task == "video",
                    supports_text_to_video=task == "video",
                    supports_reference_images=task == "video",
                    supports_audio=family.startswith("ltx"),
                    downloaded=installed or is_active,
                    download_state="managed_by_wangp",
                    execution="wangp",
                    required=is_active,
                    estimated_min_vram_gb=minimum,
                    fits_gpu=fits(minimum),
                    supported_resolutions=_LOCAL_RESOLUTIONS if task == "video" else [],
                    family=family,
                    task=task,
                    description=str(definition.get("description", ""))[:240],
                    quantization=quant,
                    state=state,
                    is_active=is_active,
                    vram_is_estimate=True,
                )
            )
            seen.add(model_id)
        # Always show the configured types even if the checkout has no definition for them.
        for model_id, task in ((active_video, "video"), (active_image, "image")):
            if model_id in seen:
                continue
            rows.append(
                FilmModelCapability(
                    id=model_id,
                    label=f"WanGP · {model_id}",
                    modes=[task],
                    supports_image_to_video=task == "video",
                    supports_text_to_video=task == "video",
                    supports_reference_images=task == "video",
                    supports_audio=task == "video",
                    downloaded=True,
                    download_state="managed_by_wangp",
                    execution="wangp",
                    estimated_min_vram_gb=_WANGP_MIN_VRAM_GB,
                    fits_gpu=fits(_WANGP_MIN_VRAM_GB),
                    supported_resolutions=_LOCAL_RESOLUTIONS if task == "video" else [],
                    family=_wangp_family(model_id),
                    task=task,
                    state="active",
                    is_active=True,
                )
            )
        # Active rows first, then installed, then available; stable within groups.
        order = {"active": 0, "installed": 1, "available": 2}
        rows.sort(key=lambda r: (order.get(r.state, 3), r.family, r.id))
        return rows

    def capabilities(self) -> FilmCapabilitiesResponse:
        gpu_name = self._gpu_info.get_device_name()
        vram_gb_int = self._gpu_info.get_vram_total_gb()
        detected_vram_gb = float(vram_gb_int) if vram_gb_int is not None else None

        with self.lock:
            settings = self.state.app_settings
            has_api_key = bool(settings.ltx_api_key.strip())
            use_local_text_encoder = settings.use_local_text_encoder
            available = dict(self.state.available_files)

        # A user-set VRAM budget caps the memory fit recommendations assume
        # (headroom for the desktop compositor etc.). The detected total is
        # still reported alongside.
        vram_budget_gb = settings.gpu_vram_budget_gb
        effective_vram_gb = detected_vram_gb
        if vram_budget_gb is not None and (detected_vram_gb is None or vram_budget_gb < detected_vram_gb):
            effective_vram_gb = vram_budget_gb

        def fits(minimum: float | None) -> bool | None:
            if minimum is None or effective_vram_gb is None:
                return None
            return effective_vram_gb >= minimum

        total_required_download_gb: float | None = None
        text_encoder_optional = False

        models: list[FilmModelCapability] = []
        if self._config.wangp_enabled:
            execution_mode = "wangp"
            models.extend(self._wangp_model_rows(fits))
        elif self._config.force_api_generations:
            execution_mode = "api"
            for api_id, label in (("fast", "LTX-2.3 Fast (API)"), ("pro", "LTX-2.3 Pro (API)")):
                models.append(
                    FilmModelCapability(
                        id=api_id,
                        label=label,
                        modes=["video"],
                        supports_image_to_video=True,
                        supports_text_to_video=True,
                        supports_reference_images=True,
                        supports_audio=(api_id == "pro"),
                        downloaded=True,
                        download_state="cloud",
                        execution="api",
                        estimated_min_vram_gb=None,
                        fits_gpu=None,
                        supported_resolutions=_FORCED_API_RESOLUTIONS,
                        family="ltx2",
                        task="video",
                        state="active",
                        is_active=True,
                        vram_is_estimate=False,
                    )
                )
        else:
            execution_mode = "local"
            required_types = resolve_required_model_types(
                self._config.required_model_types,
                has_api_key=has_api_key,
                use_local_text_encoder=use_local_text_encoder,
            )
            text_encoder_optional = "text_encoder" not in required_types
            missing_required_bytes = 0
            for model_type in MODEL_FILE_ORDER:
                spec = self._config.spec_for(model_type)
                downloaded = available.get(model_type) is not None
                required = model_type in required_types
                if required and not downloaded:
                    missing_required_bytes += spec.expected_size_bytes
                is_video = model_type in ("checkpoint", "upsampler", "text_encoder")
                minimum = _NATIVE_LOCAL_MIN_VRAM_GB if is_video else None
                models.append(
                    FilmModelCapability(
                        id=model_type,
                        label=spec.description,
                        modes=["video"] if is_video else ["image"],
                        supports_image_to_video=is_video,
                        supports_text_to_video=is_video,
                        supports_reference_images=is_video,
                        supports_audio=False,
                        downloaded=downloaded,
                        download_state="downloaded" if downloaded else "not_downloaded",
                        execution="local",
                        required=required,
                        disk_size_gb=round(spec.expected_size_bytes / 1_000_000_000, 1),
                        estimated_min_vram_gb=minimum,
                        fits_gpu=fits(minimum),
                        supported_resolutions=_LOCAL_RESOLUTIONS if is_video else [],
                        family="ltx2" if is_video else "z_image",
                        task="video" if is_video else "image",
                        description=spec.description,
                        state=(
                            "installed"
                            if downloaded
                            else "incompatible"
                            if fits(minimum) is False
                            else "available"
                        ),
                        installed_size_gb=round(spec.expected_size_bytes / 1_000_000_000, 1) if downloaded else None,
                        is_active=downloaded and required,
                        vram_is_estimate=True,
                    )
                )
            total_required_download_gb = round(missing_required_bytes / 1_000_000_000, 1)
            # Advisory row: the low-VRAM WanGP path exists even when the bridge
            # is not configured — the compatible option for 6-31 GB GPUs.
            models.append(
                FilmModelCapability(
                    id="wangp-bridge",
                    label="WanGP bridge (low-VRAM local path)",
                    modes=["video", "image"],
                    supports_image_to_video=True,
                    supports_text_to_video=True,
                    supports_reference_images=True,
                    supports_audio=True,
                    downloaded=False,
                    download_state="not_configured",
                    execution="wangp",
                    required=False,
                    estimated_min_vram_gb=_WANGP_MIN_VRAM_GB,
                    fits_gpu=fits(_WANGP_MIN_VRAM_GB),
                    supported_resolutions=_LOCAL_RESOLUTIONS,
                    family="wangp",
                    task="video",
                    description="Set WANGP_ROOT to a Wan2GP checkout to enable this path.",
                    state="incompatible" if fits(_WANGP_MIN_VRAM_GB) is False else "available",
                )
            )

        verdict, verdict_level = self._gpu_verdict(effective_vram_gb, execution_mode)
        if (
            vram_budget_gb is not None
            and detected_vram_gb is not None
            and vram_budget_gb < detected_vram_gb
        ):
            verdict = f"{verdict} VRAM budget {vram_budget_gb:.0f} GB is in effect "                       f"(detected {detected_vram_gb:.0f} GB); fit badges use the budget."
        return FilmCapabilitiesResponse(
            gpu_name=gpu_name,
            gpu_vram_gb=detected_vram_gb,
            vram_budget_gb=vram_budget_gb,
            execution_mode=execution_mode,
            gpu_verdict=verdict,
            gpu_verdict_level=verdict_level,
            models=models,
            total_required_download_gb=total_required_download_gb,
            text_encoder_optional=text_encoder_optional,
            profiles=self._quality_profiles(effective_vram_gb, execution_mode, models),
            models_path=self._models_path(),
            system_ram_gb=_system_ram_gb(),
            cuda_available=self._gpu_info.get_cuda_available(),
            vram_note=(
                "VRAM figures are from this app's documentation: the WanGP bridge runs on "
                "as low as 6 GB VRAM; the native local LTX pipeline targets ~32 GB. "
                "API models run in the cloud and need no local VRAM."
            ),
        )
