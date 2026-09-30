"""Video Reproduce v2: one film-queue job per shot, scored against the source.

The analysed video is reconstructed into an ordinary film project (once),
then every selected shot is rendered round after round through
`FilmGenerationHandler.queue_shot` — never a parallel engine — until its best
candidate reaches the target score, climbing a ladder when it plateaus:
image-to-video from the shot's first frame, then first + last frames, then
the shot's own clip as an LTX-2 raw control video whose strength rises toward
1.0 (the rung that converges on the reference). The duration is snapped to
what the model allows. Each candidate is scored on sampled frames
(phase-4 composite) plus a flow-magnitude match, the best per shot is chosen
(a person can pick another), and the picks are stitched in shot order.

Lineage in History: analysis job → `video_reproduce` parent → one
`video_gen` child per candidate (opened by the film queue inside the parent
scope) → the stitched file on the parent.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

from PIL import Image, UnidentifiedImageError

from _routes._errors import HTTPError
from film.film_api_types import GenerateShotRequest
from film.film_models import FilmProject, ShotVersion
from film.prompt_compiler import compile_from_spec
from film.video_analysis_api_types import VideoRecreationRequest, VideoRecreationResponse
from film.video_analysis_models import AnalyzedShot, VideoAnalysis
from film.video_reproduce_models import (
    MOTION_WEIGHT,
    VISUAL_WEIGHT,
    ReproduceShot,
    VideoCandidate,
    VideoReproduceJob,
    now_ms,
)
from handlers.base import StateHandlerBase
from handlers.film_generation_handler import FilmGenerationHandler
from handlers.film_handler import FilmHandler
from handlers.jobs_handler import JobsHandler
from handlers.knowledge_handler import KnowledgeHandler
from handlers.video_generation_handler import get_allowed_durations
from handlers.vision_handler import VisionHandler
from server_utils.path_policy import is_within
from services.interfaces import TaskRunner
from services.media_probe.media_probe import MediaProbe
from services.motion.motion_analyzer import MotionAnalyzer, MotionSummary
from services.similarity.composite import CompositeScorer, ImageFeatures, ScoreBreakdown
from services.similarity.metrics import luma_array
from services.stitcher.video_stitcher import StitchError, VideoStitcher
from services.vision.deterministic import measure_path
from state.app_state_types import AppState
from server_utils.atomic_file import replace_with_retry

if TYPE_CHECKING:
    from handlers.scene_handler import SceneHandler
    from handlers.video_analysis_handler import VideoAnalysisHandler
    from runtime_config.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

_DOC = "reproduce.json"
_FOLDER = "reproduce"
_FRAME_ROLES = ("start", "middle", "end")
_POLL_SECONDS = 0.25
#: A round must beat the shot's best by this much to count as progress.
_PLATEAU = 0.01
#: Flat rounds on one rung before climbing to the next.
_PLATEAU_ROUNDS = 2
_CONTROL_START = 0.5
_CONTROL_MIN_STEP = 0.05
_CONTROL_MAX_STEP = 0.15
#: Flat rounds at full control strength before the shot admits it.
_CONTROL_PATIENCE = 3


class VideoReproduceHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        video_analysis: VideoAnalysisHandler,
        film_handler: FilmHandler,
        film_generation: FilmGenerationHandler,
        probe: MediaProbe,
        motion: MotionAnalyzer,
        stitcher: VideoStitcher,
        task_runner: TaskRunner,
        config: RuntimeConfig,
        jobs: JobsHandler | None = None,
        vision: VisionHandler | None = None,
        knowledge: KnowledgeHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._analysis = video_analysis
        self._film_generation = film_generation
        self._film = film_handler
        self._probe = probe
        self._motion = motion
        self._stitcher = stitcher
        self._tasks = task_runner
        self._config = config
        self._jobs = jobs
        self._vision = vision
        self._knowledge = knowledge
        self._scorer = CompositeScorer()
        self._active: set[str] = set()
        self._cancelled: set[str] = set()
        self._current_shot: dict[str, str] = {}
        self._scene: SceneHandler | None = None

    # ---- storage -----------------------------------------------------------------

    def _dir(self, analysis_id: str) -> Path:
        return self._analysis.store.directory(analysis_id)

    def _folder(self, analysis_id: str) -> Path:
        folder = self._dir(analysis_id) / _FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _load(self, analysis_id: str) -> VideoReproduceJob | None:
        path = self._dir(analysis_id) / _DOC
        if not path.is_file():
            return None
        try:
            return VideoReproduceJob.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            logger.warning("Unreadable reproduce document for %s: %s", analysis_id, exc)
            return None

    def _save(self, job: VideoReproduceJob) -> VideoReproduceJob:
        job.updated_at = now_ms()
        target = self._dir(job.analysis_id) / _DOC
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        replace_with_retry(tmp, target)
        return job

    def get(self, analysis_id: str) -> VideoReproduceJob:
        self._analysis.load(analysis_id)  # 404 when the analysis is gone
        job = self._load(analysis_id)
        if job is None:
            return VideoReproduceJob(analysis_id=analysis_id, status="idle")
        return job

    def media_path(self, analysis_id: str, relative: str) -> Path:
        """Only files this document recorded: candidate clips (absolute), frame
        thumbnails and the stitched result (both inside the reproduce folder)."""
        job = self.get(analysis_id)
        folder = self._folder(analysis_id)
        clips = {c.path for shot in job.shots for c in shot.candidates if c.path}
        if relative in clips:
            path = Path(relative)
            if path.is_file() and is_within(self._config.outputs_dir, path):
                return path
            raise HTTPError(404, "Candidate clip not found")
        inside = {job.stitched_path, *(frame for shot in job.shots for c in shot.candidates for frame in c.frames)}
        inside.discard("")
        if relative not in inside:
            raise HTTPError(400, "File is not part of this reproduce job")
        path = (folder / relative).resolve()
        if not is_within(folder, path) or not path.is_file():
            raise HTTPError(404, "File not found")
        return path

    # ---- start / cancel ---------------------------------------------------------

    def start(self, analysis_id: str, req: VideoRecreationRequest) -> VideoRecreationResponse:
        analysis = self._analysis.load(analysis_id)
        if not analysis.shots:
            raise HTTPError(400, "No shots available. Detect and analyze shots first.")
        selected = analysis.shots
        if req.shot_ids:
            selected = [s for s in analysis.shots if s.id in req.shot_ids]
            if not selected:
                raise HTTPError(400, "No matching shots found for the provided shot IDs")
        if not any((s.prompts.video and s.prompts.video.strip()) or s.spec.provenance for s in selected):
            raise HTTPError(400, "No valid prompts available for recreation. Analyze shots first.")
        with self.lock:
            if analysis_id in self._active:
                raise HTTPError(409, "This video is already being reproduced")
            self._active.add(analysis_id)
            self._cancelled.discard(analysis_id)

        try:
            project = self._ensure_project(analysis)
            job = self._new_job(analysis, project, selected, req)
            if self._jobs is not None:
                parent = self._jobs.start(
                    "video_reproduce",
                    title=analysis.title or analysis.source.file_name,
                    model=job.model,
                    provider="wangp" if self._config.wangp_enabled else "local",
                    params=req.model_dump(),
                    inputs={"analysis_id": analysis_id, "project_id": project.id, "source": analysis.source.path},
                )
                job.job_id = parent.id
            self._save(job)
        except Exception:
            with self.lock:
                self._active.discard(analysis_id)
            raise

        self._tasks.run_background(
            lambda: self._run(job.analysis_id),
            task_name=f"video-reproduce-{analysis_id}",
            on_error=lambda exc: self._fail(analysis_id, str(exc)),
        )
        return self._response(self.get(analysis_id))

    def cancel(self, analysis_id: str) -> VideoReproduceJob:
        with self.lock:
            active = analysis_id in self._active
            self._cancelled.add(analysis_id)
            shot_id = self._current_shot.get(analysis_id, "")
        if active and shot_id:
            try:
                self._film_generation.cancel_job(shot_id)
            except HTTPError:
                pass
        job = self.get(analysis_id)
        if not active and job.status == "running":
            job.status = "cancelled"
            job.message = "Cancelled"
            self._save(job)
        return job

    def _fail(self, analysis_id: str, message: str) -> None:
        with self.lock:
            self._active.discard(analysis_id)
            self._current_shot.pop(analysis_id, None)
        job = self._load(analysis_id)
        if job is None:
            return
        job.status = "failed"
        job.error = message
        job.message = message
        self._save(job)
        if job.job_id and self._jobs is not None:
            self._jobs.fail(job.job_id, message)

    @staticmethod
    def _response(job: VideoReproduceJob) -> VideoRecreationResponse:
        paths = [c.path for shot in job.shots for c in shot.candidates if c.status == "complete" and c.path]
        return VideoRecreationResponse(
            status=job.status,
            video_paths=paths or None,
            shots_generated=sum(1 for shot in job.shots if any(c.status == "complete" for c in shot.candidates)),
            analysis_id=job.analysis_id,
        )

    # ---- setup --------------------------------------------------------------------

    def attach_scene(self, scene: SceneHandler) -> None:
        """The 3D storyboard seeding (built after this handler in AppHandler)."""
        self._scene = scene

    def _ensure_project(self, analysis: VideoAnalysis) -> FilmProject:
        project: FilmProject | None = None
        if analysis.reconstructed_project_id:
            try:
                project = self._film.store.load(analysis.reconstructed_project_id)
            except Exception:  # noqa: BLE001 - deleted since; rebuild
                project = None
            if project is not None and not self._has_all_shots(project, analysis):
                project = None
        if project is None:
            project = self._analysis.reconstruct(analysis.id)
        # Every reproduced shot opens in the composer with a 3D layout +
        # blockout seeded from its spec; a shot already composed is kept.
        if self._scene is not None:
            if self._scene.seed_missing(project.id, analysis):
                project = self._film.store.load(project.id)
        return project

    @staticmethod
    def _has_all_shots(project: FilmProject, analysis: VideoAnalysis) -> bool:
        linked = {s.source_ref.analysis_shot_id for _, s in _walk(project) if s.source_ref is not None}
        return all(shot.id in linked for shot in analysis.shots)

    def _new_job(self, analysis: VideoAnalysis, project: FilmProject, selected: list[AnalyzedShot], req: VideoRecreationRequest) -> VideoReproduceJob:
        model, resolution, fps = self._profile(project, req.kind)
        target = self._config.wangp_video_model_type if self._config.wangp_enabled else f"ltx-2-3-{model}"
        job = VideoReproduceJob(
            analysis_id=analysis.id,
            project_id=project.id,
            title=analysis.title or analysis.source.file_name,
            kind=req.kind,
            target=target,
            model=self._config.wangp_video_model_type if self._config.wangp_enabled else model,
            resolution=resolution,
            fps=fps,
            candidates_per_shot=req.candidates,
            rounds=req.rounds,
            target_score=req.target_score,
            seed=req.seed,
            status="running",
            message="Preparing shots",
        )
        by_analysis_shot = {s.source_ref.analysis_shot_id: (scene.id, s) for scene, s in _walk(project) if s.source_ref is not None}
        for analysed in selected:
            link = by_analysis_shot.get(analysed.id)
            if link is None:
                raise HTTPError(500, f"Shot {analysed.id} has no storyboard counterpart; rebuild the storyboard")
            scene_id, film_shot = link
            prompt, negative, source = self._prompt_for(analysed, target)
            job.shots.append(
                ReproduceShot(
                    shot_id=analysed.id,
                    index=analysed.index,
                    film_scene_id=scene_id,
                    film_shot_id=film_shot.id,
                    start=analysed.start,
                    end=analysed.end,
                    duration_seconds=self._snap(analysed.duration, model, resolution, fps),
                    start_frame=self._start_frame(analysed),
                    end_frame=self._end_frame(analysed),
                    prompt=prompt,
                    negative_prompt=negative,
                    prompt_source=source,
                )
            )
        return job

    def _profile(self, project: FilmProject, kind: str) -> tuple[str, str, int]:
        settings = project.settings
        if kind == "preview":
            return "fast", settings.preview_resolution or "540p", 24
        model = settings.default_model or "fast"
        resolution = settings.default_resolution or "540p"
        return model, resolution, 24

    @staticmethod
    def _snap(seconds: float, model: str, resolution: str, fps: int) -> float:
        allowed = sorted(get_allowed_durations(f"ltx-2-3-{model}", resolution, fps))
        return float(min(allowed, key=lambda d: abs(d - max(0.5, seconds))))

    @staticmethod
    def _start_frame(shot: AnalyzedShot) -> str:
        for role in ("start", "representative", "middle", "end"):
            for frame in shot.frames:
                if frame.role == role and frame.path:
                    return frame.path
        return shot.frames[0].path if shot.frames else ""

    @staticmethod
    def _end_frame(shot: AnalyzedShot) -> str:
        for frame in shot.frames:
            if frame.role == "end" and frame.path:
                return frame.path
        return ""

    @staticmethod
    def _prompt_for(shot: AnalyzedShot, target: str) -> tuple[str, str, Any]:
        if shot.prompts.edited and shot.prompts.video.strip():
            return shot.prompts.video.strip(), shot.prompts.negative, "user"
        if shot.spec.provenance:
            compiled = compile_from_spec(shot.spec, target)
            if compiled.prompt.strip():
                negative = compiled.negative_prompt or shot.prompts.negative
                return compiled.prompt, negative, "spec"
        return shot.prompts.video.strip(), shot.prompts.negative, "analysis"

    # ---- the loop ------------------------------------------------------------------

    def _ladder(self) -> tuple[str, ...]:
        """Rungs available on this backend. First + last frames and the
        reference clip as a control video go through WanGP only."""
        if self._config.wangp_enabled:
            return ("start_frame", "start_end_frames", "reference_video")
        return ("start_frame",)

    def _run(self, analysis_id: str) -> None:
        try:
            job = self._load(analysis_id)
            if job is None:
                return
            for position, shot in enumerate(job.shots):
                if not self._reproduce_shot(job, shot, position):
                    self._finish(job, "cancelled", "Cancelled")
                    return
            self._pick_bests(job)
            self._stitch(job)
            short = [s for s in job.shots if not s.reached and any(c.status == "complete" for c in s.candidates)]
            if short and all(s.note.startswith("Plateau") for s in short):
                message = self._summary_message(job) + " · " + "; ".join(f"shot {s.index + 1}: {s.note}" for s in short)
                self._finish(job, "plateau", message)
            else:
                self._finish(job, "complete", self._summary_message(job))
        except HTTPError as exc:
            self._fail(analysis_id, str(exc.detail))
        finally:
            with self.lock:
                self._active.discard(analysis_id)
                self._current_shot.pop(analysis_id, None)

    def _reproduce_shot(self, job: VideoReproduceJob, shot: ReproduceShot, position: int) -> bool:
        """Render `shot` until it reaches the target. False when cancelled."""
        ladder = self._ladder()
        rung = 0
        flat = 0
        strength = _CONTROL_START
        best = 0.0
        round_index = 0
        while True:
            if job.rounds is not None and round_index >= job.rounds:
                shot.note = f"Round cap ({job.rounds}) reached at {best:.2f}"
                return True
            round_index += 1
            strategy = ladder[rung]
            control = strength if strategy == "reference_video" else None
            if strategy == "reference_video" and self._reference_clip(job, shot) is None:
                # Never render an unconditioned take under this rung's name.
                shot.note = f"Plateau at {best:.2f}: the reference clip could not be cut from the source (see the log)"
                return True
            produced = False
            for n in range(job.candidates_per_shot):
                if self._is_cancelled(job.analysis_id):
                    return False
                label = f"{strategy} @ {control:.2f}" if control is not None else strategy
                job.message = f"Shot {shot.index + 1}: round {round_index} [{label}], candidate {n + 1} of {job.candidates_per_shot}"
                job.progress = round(min(0.99, (position + min(0.95, round_index / 20)) / max(1, len(job.shots))), 3)
                self._save(job)
                self._report(job)
                seed = None if job.seed is None else job.seed + (round_index - 1) * 100 + n
                candidate = self._render_one(job, shot, round_index, seed, strategy=strategy, control_strength=control)
                produced = produced or candidate.status == "complete"
                self._save(job)
            if not produced:
                shot.note = "No candidate rendered this round"
                return True
            round_best = max((c.scores.composite for c in shot.candidates if c.status == "complete"), default=0.0)
            if round_best >= job.target_score:
                shot.reached = True
                shot.note = f"Target {job.target_score:.2f} reached at {round_best:.2f} with {strategy}"
                return True
            improved = round_best - best >= _PLATEAU
            best = max(best, round_best)
            flat = 0 if improved else flat + 1
            if strategy == "reference_video":
                # Converging rung: raise the pull toward the reference clip by
                # the gap left, and only give up at full strength.
                this_round = max((c.scores.composite for c in shot.candidates if c.round == round_index and c.status == "complete"), default=0.0)
                if strength >= 1.0:
                    if flat >= _CONTROL_PATIENCE:
                        shot.note = f"Plateau at {best:.2f} even at full reference-video strength"
                        return True
                else:
                    step = min(_CONTROL_MAX_STEP, max(_CONTROL_MIN_STEP, job.target_score - this_round))
                    strength = round(min(1.0, strength + step), 4)
                shot.note = f"reference_video at {control:.2f} gave {this_round:.2f}; next {strength:.2f}"
            elif flat >= _PLATEAU_ROUNDS:
                if rung + 1 >= len(ladder):
                    shot.note = (
                        f"Plateau at {best:.2f}: first + last frames and reference-video conditioning need WanGP (LTX-2)"
                        if not self._config.wangp_enabled else f"Plateau at {best:.2f}"
                    )
                    return True
                rung += 1
                flat = 0
                shot.note = f"Plateau at {best:.2f}; escalating to {ladder[rung]}"
            self._save(job)

    def _is_cancelled(self, analysis_id: str) -> bool:
        with self.lock:
            return analysis_id in self._cancelled

    def _report(self, job: VideoReproduceJob) -> None:
        if job.job_id and self._jobs is not None:
            self._jobs.progress(job.job_id, job.progress * 100, job.message)

    def _capture(self, job: VideoReproduceJob, source: Path, name: str) -> str:
        """Copy `source` into the film project's captures; project-relative path."""
        if not source.is_file():
            return ""
        captures = self._film.store.captures_dir(job.project_id)
        captures.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, captures / name)
        return f"captures/{name}"

    def _extract_end_frame(self, job: VideoReproduceJob, shot: ReproduceShot) -> str:
        """The shot's last frame, when the analysis depth only sampled start +
        middle. Analysis-relative, like the frames the analysis wrote."""
        analysis = self._analysis.load(job.analysis_id)
        if not analysis.source.path:
            return ""
        at = max(shot.start, shot.end - min(0.25, max(0.0, shot.end - shot.start) * 0.15))
        try:
            data = self._probe.extract_jpeg(analysis.source.path, at)
        except OSError as exc:
            logger.info("No end frame for %s: %s", shot.shot_id, exc)
            return ""
        name = f"end-{shot.shot_id}.jpg"
        (self._folder(job.analysis_id) / name).write_bytes(data)
        return f"{_FOLDER}/{name}"

    def _reference_clip(self, job: VideoReproduceJob, shot: ReproduceShot) -> Path | None:
        """This shot's own span of the source, at the render's fps and length,
        cut once per shot with the probe + stitcher the app already has."""
        folder = self._folder(job.analysis_id)
        if shot.reference_clip and (folder / shot.reference_clip).is_file():
            return folder / shot.reference_clip
        analysis = self._analysis.load(job.analysis_id)
        source = analysis.source.path
        if not source:
            return None
        frames_dir = folder / f"refclip-{shot.shot_id}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        count = max(2, int(round(shot.duration_seconds * job.fps)))
        span = max(0.05, min(shot.duration_seconds, (shot.end - shot.start) or shot.duration_seconds))
        frames: list[Path] = []
        # The last frames of a file often sit a few ms before the shot's
        # nominal end; never ask for a frame past the source.
        last = (analysis.source.duration_seconds - 1.0 / max(1, job.fps)) if analysis.source.duration_seconds > 0 else None
        for i in range(count):
            at = shot.start + span * i / count
            if last is not None:
                at = min(at, max(shot.start, last))
            try:
                data = self._probe.extract_jpeg(source, at, max_width=1280, quality=92)
            except OSError as exc:
                logger.info("Reference clip frame %.2fs unavailable: %s", at, exc)
                continue
            frame = frames_dir / f"f{i:05d}.jpg"
            frame.write_bytes(data)
            frames.append(frame)
        if not frames:
            return None
        name = f"reference-{shot.shot_id}.mp4"
        try:
            self._stitcher.encode_frames(frames, job.fps, folder / name)
        except StitchError as exc:
            logger.warning("Could not encode the reference clip for %s: %s", shot.shot_id, exc)
            return None
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)
        shot.reference_clip = name
        return folder / name

    def _render_one(
        self, job: VideoReproduceJob, shot: ReproduceShot, round_index: int, seed: int | None,
        *, strategy: str = "start_frame", control_strength: float | None = None,
    ) -> VideoCandidate:
        analysis_dir = self._dir(job.analysis_id)
        capture_rel = ""
        if shot.start_frame:
            source = analysis_dir / shot.start_frame
            capture_rel = self._capture(job, source, f"{shot.film_shot_id}-reproduce-start{source.suffix.lower() or '.jpg'}")
        end_rel = ""
        if strategy in ("start_end_frames", "reference_video") and not shot.end_frame:
            shot.end_frame = self._extract_end_frame(job, shot)
        if strategy in ("start_end_frames", "reference_video") and shot.end_frame:
            source = analysis_dir / shot.end_frame
            end_rel = self._capture(job, source, f"{shot.film_shot_id}-reproduce-end{source.suffix.lower() or '.jpg'}")
        control_rel = ""
        if strategy == "reference_video":
            clip = self._reference_clip(job, shot)
            if clip is not None:
                control_rel = self._capture(job, clip, f"{shot.film_shot_id}-reproduce-reference.mp4")

        candidate = VideoCandidate(
            id=f"vc-{uuid.uuid4().hex[:10]}",
            version_number=0,
            prompt=shot.prompt,
            negative_prompt=shot.negative_prompt,
            seed=seed,
            round=round_index,
            model=job.model,
            target=job.target,
            duration_seconds=shot.duration_seconds,
            strategy=strategy,
            control_strength=control_strength if control_rel else None,
        )
        shot.candidates.append(candidate)
        with self.lock:
            self._current_shot[job.analysis_id] = shot.film_shot_id

        # The film shot carries the prompt the queue will render; the human's
        # storyboard edits are preserved by locking only what we set.
        with self.lock:
            project = self._film.store.load(job.project_id)
            found = project.find_shot(shot.film_shot_id)
            if found is None:
                candidate.status = "failed"
                candidate.error = "Storyboard shot is gone"
                return candidate
            _, film_shot = found
            film_shot.visual_prompt = shot.prompt
            film_shot.negative_prompt = shot.negative_prompt
            film_shot.prompt_locked = True
            film_shot.generation.use_capture_as_reference = True
            self._film.store.save(project)

        request = GenerateShotRequest(
            kind=job.kind, duration_seconds=shot.duration_seconds, capture_path=capture_rel, seed=seed,
            end_capture_path=end_rel, control_video_path=control_rel,
            control_strength=control_strength if control_rel else None,
        )
        try:
            if self._jobs is not None and job.job_id:
                with self._jobs.parent(job.job_id):
                    queued = self._film_generation.queue_shot(job.project_id, shot.film_scene_id, shot.film_shot_id, request)
            else:
                queued = self._film_generation.queue_shot(job.project_id, shot.film_scene_id, shot.film_shot_id, request)
        except HTTPError as exc:
            candidate.status = "failed"
            candidate.error = str(exc.detail)
            return candidate
        candidate.version_number = queued.version_number
        candidate.status = "generating"
        self._save(job)

        version = self._wait(job, shot, queued.version_number)
        candidate.job_id = self._child_job_id(job, shot, version)
        if version.status == "complete" and version.output_path:
            candidate.status = "complete"
            candidate.path = version.output_path
            candidate.seed = version.seed if version.seed is not None else seed
            if version.peak_vram_gb is not None:
                job.peak_vram_mb = max(job.peak_vram_mb or 0, round(version.peak_vram_gb * 1024))
            self._score(job, shot, candidate)
        elif version.status == "cancelled":
            candidate.status = "cancelled"
            candidate.error = version.error or "Cancelled"
        else:
            candidate.status = "failed"
            candidate.error = version.error or "Generation failed"
        return candidate

    def _wait(self, job: VideoReproduceJob, shot: ReproduceShot, number: int) -> ShotVersion:
        orphaned_polls = 0
        while True:
            project = self._film.store.load(job.project_id)
            found = project.find_shot(shot.film_shot_id)
            version = found[1].version(number) if found is not None else None
            if version is None:
                return ShotVersion(number=number, kind=job.kind, status="failed", error="Version disappeared")
            if version.status in ("complete", "failed", "cancelled"):
                return version
            # The queue no longer holds this take but never finished it (its
            # thread died): waiting would be forever. A few polls of grace
            # cover the hand-off between queueing and the worker picking it up.
            orphaned_polls = 0 if self._film_generation.is_pending(shot.film_shot_id) else orphaned_polls + 1
            if orphaned_polls >= 8:
                return ShotVersion(number=number, kind=job.kind, status="failed", error="The render queue stopped without finishing this take")
            if self._is_cancelled(job.analysis_id):
                try:
                    self._film_generation.cancel_job(shot.film_shot_id)
                except HTTPError:
                    pass
            time.sleep(_POLL_SECONDS)

    def _child_job_id(self, job: VideoReproduceJob, shot: ReproduceShot, version: ShotVersion) -> str:
        if self._jobs is None or not job.job_id:
            return ""
        for child in self._jobs.children(job.job_id):
            if child.shot_id == shot.film_shot_id and child.params.get("version_number") == version.number:
                return child.id
        for child in self._jobs.children(job.job_id):
            if child.shot_id == shot.film_shot_id and any(o.path == version.output_path for o in child.outputs):
                return child.id
        return ""

    # ---- scoring -------------------------------------------------------------------

    def _score(self, job: VideoReproduceJob, shot: ReproduceShot, candidate: VideoCandidate) -> None:
        analysis = self._analysis.load(job.analysis_id)
        analysed = analysis.shot(shot.shot_id)
        if analysed is None or not candidate.path:
            return
        folder = self._folder(job.analysis_id)
        analysis_dir = self._dir(job.analysis_id)
        clip = Path(candidate.path)
        duration = max(0.2, candidate.duration_seconds or shot.duration_seconds)
        breakdowns: list[ScoreBreakdown] = []
        for role, at in zip(_FRAME_ROLES, (0.05, duration / 2, max(0.05, duration - 0.1))):
            reference = self._reference_frame(analysis_dir, analysed, role)
            try:
                data = self._probe.extract_jpeg(str(clip), at)
            except OSError as exc:
                logger.info("No %s frame from %s: %s", role, clip, exc)
                continue
            frame_name = f"{candidate.id}-{role}.jpg"
            (folder / frame_name).write_bytes(data)
            candidate.frames.append(frame_name)
            if reference is None:
                continue
            breakdowns.append(self._scorer.score(self._features(reference), self._features(folder / frame_name)))

        visual = _mean_breakdown(breakdowns)
        motion_match = self._motion_match(analysed, clip)
        candidate.motion_match = motion_match
        components = dict(visual.components)
        weights: dict[str, float] = {}
        composite = 0.0
        if visual.components:
            weights["visual"] = VISUAL_WEIGHT
            composite += VISUAL_WEIGHT * visual.composite
        if motion_match is not None:
            components["motion"] = round(motion_match, 4)
            weights["motion"] = MOTION_WEIGHT
            composite += MOTION_WEIGHT * motion_match
        total = sum(weights.values())
        missing = list(visual.missing) + ([] if motion_match is not None else ["motion"])
        candidate.scores = ScoreBreakdown(
            composite=round(composite / total, 4) if total else 0.0,
            components=components,
            weights_used={**{k: round(v * VISUAL_WEIGHT / total, 4) for k, v in visual.weights_used.items()}, **({"motion": round(MOTION_WEIGHT / total, 4)} if motion_match is not None and total else {})},
            missing=missing,
        )
        if candidate.job_id and self._jobs is not None:
            self._jobs.annotate(candidate.job_id, metrics={"scores": candidate.scores.model_dump(), "motion_match": motion_match})
        if self._knowledge is not None:
            self._knowledge.record_candidate(
                picked=False,
                model=job.model,
                provider="wangp" if self._config.wangp_enabled else "local",
                target=job.target,
                prompt=candidate.prompt,
                negative_prompt=candidate.negative_prompt,
                seed=candidate.seed,
                spec_keys=analysed.spec.attribute_keys(),
                metrics={"composite": candidate.scores.composite, **{k: float(v) for k, v in components.items()}},
                project_id=job.project_id,
                shot_id=shot.film_shot_id,
                task="video",
            )

    @staticmethod
    def _reference_frame(analysis_dir: Path, shot: AnalyzedShot, role: str) -> Path | None:
        for frame in shot.frames:
            if frame.role == role and (analysis_dir / frame.path).is_file():
                return analysis_dir / frame.path
        for frame in shot.frames:
            if (analysis_dir / frame.path).is_file():
                return analysis_dir / frame.path
        return None

    def _features(self, path: Path) -> ImageFeatures:
        features = ImageFeatures()
        try:
            with Image.open(path) as image:
                features.luma = luma_array(image)
        except (OSError, UnidentifiedImageError) as exc:
            logger.info("Frame %s unreadable for scoring: %s", path, exc)
            return features
        try:
            stats = measure_path(path)
            features.palette = [(e.hex, e.share) for e in stats.palette]
        except Exception as exc:  # noqa: BLE001 - a 1-px frame has no palette worth measuring
            logger.info("No palette for %s: %s", path, exc)
        if self._vision is not None:
            for kind in ("clip", "dino"):
                try:
                    vector = self._vision.embed(str(path), kind)
                    if vector:
                        setattr(features, kind, vector)
                except Exception as exc:  # noqa: BLE001 - a missing model drops the component
                    logger.info("%s embedding unavailable: %s", kind, exc)
        return features

    def _motion_match(self, analysed: AnalyzedShot, clip: Path) -> float | None:
        reference = analysed.motion
        if not reference.analyzed:
            return None
        try:
            measured: MotionSummary = self._motion.analyze(str(clip))
        except Exception as exc:  # noqa: BLE001 - scoring degrades, never fails the render
            logger.info("Motion analysis of %s failed: %s", clip, exc)
            return None
        if not measured.analyzed:
            return None
        scale = max(reference.magnitude, 0.01)
        magnitude = 1.0 - min(1.0, abs(measured.magnitude - reference.magnitude) / scale)
        rx, ry, cx, cy = reference.pan, reference.tilt, measured.pan, measured.tilt
        rn, cn = (rx * rx + ry * ry) ** 0.5, (cx * cx + cy * cy) ** 0.5
        if rn < 1e-4 and cn < 1e-4:
            direction = 1.0
        elif rn < 1e-4 or cn < 1e-4:
            direction = 0.5
        else:
            direction = max(0.0, (rx * cx + ry * cy) / (rn * cn))
        return round(0.6 * magnitude + 0.4 * direction, 4)

    # ---- choose / stitch ------------------------------------------------------------

    def _pick_bests(self, job: VideoReproduceJob) -> None:
        for shot in job.shots:
            done = [c for c in shot.candidates if c.status == "complete"]
            if not done:
                continue
            best = max(done, key=lambda c: c.scores.composite)
            shot.best_candidate_id = best.id
            if not shot.picked_candidate_id or shot.candidate(shot.picked_candidate_id) is None:
                shot.picked_candidate_id = best.id

    def pick(self, analysis_id: str, shot_id: str, candidate_id: str) -> VideoReproduceJob:
        job = self.get(analysis_id)
        shot = job.shot(shot_id)
        if shot is None:
            raise HTTPError(404, f"No shot {shot_id} in this reproduce job")
        candidate = shot.candidate(candidate_id)
        if candidate is None or candidate.status != "complete":
            raise HTTPError(404, "That candidate was not rendered")
        shot.picked_candidate_id = candidate_id
        self._save(job)
        # The pick is the storyboard's take too.
        try:
            self._film.promote_version(job.project_id, shot.film_scene_id, shot.film_shot_id, candidate.version_number)
        except HTTPError as exc:
            logger.info("Could not promote the picked take on the storyboard: %s", exc.detail)
        if self._knowledge is not None:
            self._knowledge.record_candidate(
                picked=True, model=candidate.model, provider="wangp" if self._config.wangp_enabled else "local",
                target=candidate.target, prompt=candidate.prompt, negative_prompt=candidate.negative_prompt,
                seed=candidate.seed, metrics={"composite": candidate.scores.composite}, project_id=job.project_id,
                shot_id=shot.film_shot_id, task="video",
            )
        return job

    def redo(self, analysis_id: str, shot_id: str) -> VideoReproduceJob:
        """One more candidate for a shot, in a new round, on the task runner."""
        job = self.get(analysis_id)
        shot = job.shot(shot_id)
        if shot is None:
            raise HTTPError(404, f"No shot {shot_id} in this reproduce job")
        with self.lock:
            if analysis_id in self._active:
                raise HTTPError(409, "This video is already being reproduced")
            self._active.add(analysis_id)
            self._cancelled.discard(analysis_id)
        job.status = "running"
        job.message = f"Shot {shot.index + 1}: one more candidate"
        job.error = ""
        self._save(job)
        round_index = max((c.round for c in shot.candidates), default=0) + 1
        seed = None if job.seed is None else job.seed + (round_index - 1) * 100

        def work() -> None:
            try:
                current = self._load(analysis_id) or job
                target = current.shot(shot_id)
                if target is None:
                    return
                self._render_one(current, target, round_index, seed)
                self._pick_bests(current)
                self._stitch(current)
                self._finish(current, "complete", self._summary_message(current))
            except HTTPError as exc:
                self._fail(analysis_id, str(exc.detail))
            finally:
                with self.lock:
                    self._active.discard(analysis_id)
                    self._current_shot.pop(analysis_id, None)

        self._tasks.run_background(work, task_name=f"video-reproduce-redo-{analysis_id}", on_error=lambda exc: self._fail(analysis_id, str(exc)))
        return self.get(analysis_id)

    def stitch(self, analysis_id: str) -> VideoReproduceJob:
        job = self.get(analysis_id)
        if job.status == "running":
            raise HTTPError(409, "Wait for the render to finish before stitching")
        self._stitch(job, strict=True)
        return self._save(job)

    def _stitch(self, job: VideoReproduceJob, *, strict: bool = False) -> None:
        picks = [shot.chosen() for shot in sorted(job.shots, key=lambda s: s.index)]
        clips = [Path(c.path) for c in picks if c is not None and c.status == "complete" and c.path]
        if not clips:
            if strict:
                raise HTTPError(400, "No rendered candidate to stitch")
            return
        name = f"stitched-{now_ms()}.mp4"
        try:
            self._stitcher.concat(clips, self._folder(job.analysis_id) / name)
        except StitchError as exc:
            if strict:
                raise HTTPError(500, str(exc)) from exc
            job.message = f"Stitch failed: {exc}"
            logger.warning("Stitch failed for %s: %s", job.analysis_id, exc)
            return
        job.stitched_path = name
        job.stitched_at = now_ms()

    def _finish(self, job: VideoReproduceJob, status: str, message: str) -> None:
        job.status = status  # type: ignore[assignment]
        job.progress = 1.0 if status == "complete" else job.progress
        job.message = message
        self._save(job)
        if not job.job_id or self._jobs is None:
            return
        outputs = [str(self._folder(job.analysis_id) / job.stitched_path)] if job.stitched_path else []
        outputs += [c.path for shot in job.shots for c in shot.candidates if c.status == "complete" and c.path]
        best_scores: dict[str, float | None] = {}
        for shot in job.shots:
            best = shot.candidate(shot.best_candidate_id)
            best_scores[shot.shot_id] = best.scores.composite if best is not None else None
        metrics: dict[str, Any] = {"best_scores": best_scores}
        if job.peak_vram_mb is not None:
            metrics["peak_vram_mb"] = job.peak_vram_mb
        if status == "complete":
            self._jobs.complete(job.job_id, outputs, metrics=metrics)
        elif status == "cancelled":
            self._jobs.mark_cancelled(job.job_id, reason=message)
        else:
            self._jobs.fail(job.job_id, message, metrics=metrics)

    @staticmethod
    def _summary_message(job: VideoReproduceJob) -> str:
        rendered = sum(1 for shot in job.shots for c in shot.candidates if c.status == "complete")
        failed = sum(1 for shot in job.shots for c in shot.candidates if c.status == "failed")
        note = f"{rendered} candidate{'' if rendered == 1 else 's'} across {len(job.shots)} shot{'' if len(job.shots) == 1 else 's'}"
        if failed:
            note += f", {failed} failed"
        reached = sum(1 for shot in job.shots if shot.reached)
        note += f" · {reached}/{len(job.shots)} at target {job.target_score:.2f}"
        if job.stitched_path:
            note += " · stitched"
        return note


def _walk(project: FilmProject):  # type: ignore[no-untyped-def]
    for scene in sorted(project.scenes, key=lambda s: s.order):
        for shot in sorted(scene.shots, key=lambda s: s.order):
            yield scene, shot


def _mean_breakdown(items: list[ScoreBreakdown]) -> ScoreBreakdown:
    if not items:
        return ScoreBreakdown()
    names = sorted({name for item in items for name in item.components})
    components = {name: round(sum(i.components.get(name, 0.0) for i in items if name in i.components) / max(1, sum(1 for i in items if name in i.components)), 4) for name in names}
    weights = items[0].weights_used
    return ScoreBreakdown(
        composite=round(sum(i.composite for i in items) / len(items), 4),
        components=components,
        weights_used=weights,
        missing=sorted(set(items[0].missing)),
    )
