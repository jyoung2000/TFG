"""Film shot generation: queue, request adaptation, capabilities.

The film queue sits ON TOP of the host's single-generation-slot pipeline: jobs
are drained sequentially by one background worker that delegates each job to
``VideoGenerationHandler.generate`` — so all three execution paths (WanGP
bridge, forced LTX API, local pipeline), progress reporting and cancellation
are reused untouched. Job state is persisted on the shot's version record at
every transition, so a backend restart leaves shots resumable instead of lost.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import cast

from _routes._errors import HTTPError
from api_types import GenerateVideoRequest, VideoCameraMotion
from film.film_api_types import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    FilmCapabilitiesResponse,
    FilmModelCapability,
    FilmQualityProfile,
    FilmQueueResponse,
    GenerateShotRequest,
    QueuedJob,
    QueueShotResponse,
)
from film.film_continuity import check_shot_continuity
from film.film_models import (
    FilmProject,
    FilmShot,
    ShotVersion,
    VersionKind,
    now_ms,
)
from film.film_prompt import synthesize_negative_prompt, synthesize_prompt
from handlers.base import StateHandlerBase
from handlers.film_handler import FilmHandler
from handlers.generation_handler import GenerationHandler
from handlers.video_generation_handler import VideoGenerationHandler, get_allowed_durations
from runtime_config.model_download_specs import MODEL_FILE_ORDER, resolve_required_model_types
from runtime_config.runtime_config import RuntimeConfig
from services.interfaces import GpuInfo, TaskRunner, VideoProcessor
from services.wangp_bridge import WanGPBridge
from state.app_state_types import AppState

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


def _system_ram_gb() -> float | None:
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
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
    ) -> None:
        super().__init__(state, lock)
        self._film = film_handler
        self._video_generation = video_generation_handler
        self._generation = generation_handler
        self._gpu_info = gpu_info
        self._video_processor = video_processor
        self._task_runner = task_runner
        self._config = config
        self._wangp_bridge = wangp_bridge
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

            version = self._create_version(project, shot, req.kind)
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
            )
            self._queue.append(job)
            self._ensure_worker()
            return QueueShotResponse(
                status="queued", version_number=version.number, warnings=warnings
            )

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
        for scene_id, shot_id in targets:
            try:
                response = self.queue_shot(
                    project_id, scene_id, shot_id, GenerateShotRequest(kind=req.kind)
                )
            except HTTPError as exc:
                if exc.status_code == 409:
                    continue  # already queued/generating, or strict continuity
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
        return BatchGenerateResponse(status="queued", queued=queued)

    def get_queue(self) -> FilmQueueResponse:
        with self.lock:
            active = self._active.to_payload("generating") if self._active is not None else None
            pending = [job.to_payload("queued") for job in self._queue]
            paused = self._paused
        progress: int | None = None
        phase = ""
        if active is not None:
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
        self, project: FilmProject, shot: FilmShot, kind: VersionKind
    ) -> ShotVersion:
        settings = project.settings
        generation = shot.generation

        scene_and_shot = project.find_shot(shot.id)
        assert scene_and_shot is not None
        scene = scene_and_shot[0]

        prompt = shot.visual_prompt if shot.prompt_locked and shot.visual_prompt else synthesize_prompt(project, scene, shot)
        negative = synthesize_negative_prompt(project, shot)

        if kind == "preview":
            model = "fast"
            resolution = settings.preview_resolution or "540p"
            duration = min(shot.duration_seconds, settings.preview_max_seconds or 4.0)
        else:
            model, resolution = self._resolve_final_profile(project, shot)
            duration = shot.duration_seconds

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
            seed=generation.seed,
            capture_path=capture_path,
            wardrobe_snapshot=wardrobe_snapshot,
            shot_snapshot=snapshot,
            execution_mode=self._execution_mode(),
        )

    def _execution_mode(self) -> str:
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
                self._run_job(job)
        finally:
            with self.lock:
                if not self._queue or self._paused:
                    self._active = None
                    self._worker_running = False

    def _run_job(self, job: _QueuedShotJob) -> None:
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
            response = self._video_generation.generate(request)
        except HTTPError as exc:
            self._finish_version(job, status="failed", error=str(exc.detail), telemetry=self._telemetry(started))
            return
        except Exception as exc:  # noqa: BLE001 - queue must survive any job failure
            self._finish_version(job, status="failed", error=str(exc), telemetry=self._telemetry(started))
            return
        finally:
            if restore_seed is not None:
                with self.lock:
                    settings = self.state.app_settings
                    settings.seed_locked, settings.locked_seed = restore_seed
        telemetry = self._telemetry(started)
        if response.status == "complete" and response.video_path:
            self._finish_version(
                job, status="complete", output_path=response.video_path, telemetry=telemetry, seed_used=response.seed
            )
        elif response.status == "cancelled":
            self._finish_version(job, status="cancelled", error="Cancelled", telemetry=telemetry)
        else:
            self._finish_version(job, status="failed", error=f"Generation ended with status {response.status}", telemetry=telemetry)

    def _telemetry(self, started: float) -> dict[str, object]:
        """Wall-clock time plus whatever the GPU service can observe. Peak VRAM
        is the post-job used figure — an estimate, labelled as such."""
        payload: dict[str, object] = {"generation_seconds": round(time.perf_counter() - started, 2)}
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
            _, shot = found
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
        )
        return request, version.seed

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
            if status == "complete":
                shot.current_version = version.number
                shot.status = "review"
            elif status == "cancelled":
                shot.status = "ready" if shot.capture_path else "composed"
            else:
                shot.status = "ready" if shot.capture_path else "composed"
            shot.updated_at = now_ms()
            self._film.store.save(project)

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
        vram_gb = float(vram_gb_int) if vram_gb_int is not None else None

        def fits(minimum: float | None) -> bool | None:
            if minimum is None or vram_gb is None:
                return None
            return vram_gb >= minimum

        with self.lock:
            settings = self.state.app_settings
            has_api_key = bool(settings.ltx_api_key.strip())
            use_local_text_encoder = settings.use_local_text_encoder
            available = dict(self.state.available_files)

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

        verdict, verdict_level = self._gpu_verdict(vram_gb, execution_mode)
        return FilmCapabilitiesResponse(
            gpu_name=gpu_name,
            gpu_vram_gb=vram_gb,
            execution_mode=execution_mode,
            gpu_verdict=verdict,
            gpu_verdict_level=verdict_level,
            models=models,
            total_required_download_gb=total_required_download_gb,
            text_encoder_optional=text_encoder_optional,
            profiles=self._quality_profiles(vram_gb, execution_mode, models),
            models_path=self._models_path(),
            system_ram_gb=_system_ram_gb(),
            cuda_available=self._gpu_info.get_cuda_available(),
            vram_note=(
                "VRAM figures are from this app's documentation: the WanGP bridge runs on "
                "as low as 6 GB VRAM; the native local LTX pipeline targets ~32 GB. "
                "API models run in the cloud and need no local VRAM."
            ),
        )
