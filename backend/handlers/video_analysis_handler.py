"""Analysing an existing video into an editable TFG project.

The reverse of the filmmaking flow. Four stages, each resumable and each
persisted before the next begins, so a crash or a cancel never leaves a job
that claims to be running:

    probe -> detect -> extract frames -> analyse

Only the last stage needs a model. Everything before it is deterministic and
works with no provider, no key and no network — which is what makes "import a
video and see its shots" an offline capability rather than a hosted one.

Analysed content is untrusted input: a caption extracted from someone's video
is data, never an instruction, and never reaches a tool-calling loop.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal, cast

from _routes._errors import HTTPError
from film.film_models import (
    CameraAngle,
    CameraMove,
    FilmAsset,
    FilmProject,
    FilmScene,
    FilmScript,
    FilmShot,
    ShotCharacter,
    ShotSize,
    ShotSourceRef,
    new_id,
    now_ms,
)
from film.llm_providers import LLMMessage, LLMProvider
from film.shot_detection import (
    DetectionSettings,
    ShotBoundary,
    detect_shots,
    merge_shots,
    set_boundary,
    split_shot,
)
from film.video_analysis_api_types import PromptEditRequest, VideoRecreationRequest, VideoRecreationResponse
from film.shot_spec_fusion import apply_flow, apply_vlm, spec_from_vision
from film.video_analysis_models import (
    MotionAnalysis,
    AnalysisDepth,
    AnalysisStage,
    AnalyzedShot,
    AudioAnalysis,
    CinematographyAnalysis,
    EditorialAnalysis,
    FrameEvidence,
    NarrativeAnalysis,
    PromptLensAnalysis,
    ReversePrompts,
    TextAnalysis,
    VideoAnalysis,
    VideoSourceInfo,
    VisualAnalysis,
)
from film.film_store import FilmStore
from film.prompt_brief import brief_from_analysis
from film.prompt_compiler import compile_for
from film.video_analysis_store import VideoAnalysisStore, VideoAnalysisStoreError
from handlers.base import StateHandlerBase
from handlers.jobs_handler import JobsHandler
from handlers.vision_handler import VisionHandler
from server_utils.path_policy import PathPolicyError, require_absolute_file
from services.media_probe.media_probe import MediaProbe
from services.interfaces import TaskRunner
from services.motion.motion_analyzer import MotionAnalyzer, MotionSummary, describe_motion
from state.app_state_types import AppState

if TYPE_CHECKING:
    from handlers.video_reproduce_handler import VideoReproduceHandler

logger = logging.getLogger(__name__)

#: The local host always renders with LTX. Which quality profile it picks
#: ("fast" or "pro") varies per render, but the family — and so the prompt
#: convention — does not, which is all the compiler needs.
_LOCAL_VIDEO_MODEL = "ltx-2"

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")

#: How many stills to keep per shot, by depth. More frames cost decode time and
#: tokens, and past three the marginal read on a single shot is small.
_FRAMES_BY_DEPTH: dict[str, int] = {"fast": 1, "standard": 1, "detailed": 3}
#: Frame sampling rate for detection. Detailed spends more to place cuts better.
_SAMPLE_FPS_BY_DEPTH: dict[str, float] = {"fast": 2.0, "standard": 4.0, "detailed": 8.0}


class VideoAnalysisHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        root: Path,
        probe: MediaProbe,
        task_runner: TaskRunner,
        film_store: FilmStore,
        jobs: JobsHandler | None = None,
        vision: VisionHandler | None = None,
        motion: MotionAnalyzer | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._jobs = jobs
        self._vision = vision
        self._motion = motion
        self._reproduce: VideoReproduceHandler | None = None
        self._analysis_jobs: dict[str, str] = {}
        self._grounding: dict[str, str] = {}
        self._store = VideoAnalysisStore(root)
        self._probe = probe
        self._tasks = task_runner
        self._film_store = film_store
        #: Ids whose job the user asked to stop. Checked between decode steps.
        self._cancelled: set[str] = set()

    @property
    def store(self) -> VideoAnalysisStore:
        return self._store

    # ---- loading ---------------------------------------------------------

    def _load(self, analysis_id: str) -> VideoAnalysis:
        try:
            return self._store.load(analysis_id)
        except VideoAnalysisStoreError as exc:
            raise HTTPError(404, str(exc)) from exc

    def load(self, analysis_id: str) -> VideoAnalysis:
        """An analysis by id, 404 when unknown (used by Video Reproduce)."""
        return self._load(analysis_id)

    def attach_reproduce(self, reproduce: VideoReproduceHandler) -> None:
        self._reproduce = reproduce

    def _save(self, analysis: VideoAnalysis) -> VideoAnalysis:
        analysis.updated_at = now_ms()
        self._store.save(analysis)
        return analysis

    def get(self, analysis_id: str) -> VideoAnalysis:
        return self._load(analysis_id)

    def list_analyses(self) -> list[VideoAnalysis]:
        analyses: list[VideoAnalysis] = []
        for analysis_id in self._store.list_ids():
            try:
                analyses.append(self._store.load(analysis_id))
            except VideoAnalysisStoreError:
                logger.warning("Skipping unreadable analysis %s", analysis_id)
        return sorted(analyses, key=lambda item: item.created_at, reverse=True)

    def delete(self, analysis_id: str) -> None:
        self._cancelled.discard(analysis_id)
        self._store.delete(analysis_id)

    # ---- stage 1: import + probe ----------------------------------------

    def import_video(
        self,
        path: str,
        *,
        title: str = "",
        depth: AnalysisDepth = "standard",
        sensitivity: float = 0.5,
        min_shot_seconds: float = 0.6,
        max_shots: int = 400,
        detect_fades: bool = True,
        analyze_audio: bool = False,
        analyze_text: bool = False,
        provider: str = "",
        model: str = "",
    ) -> VideoAnalysis:
        """Register a video and read its metadata. No decoding of content yet."""
        try:
            resolved = require_absolute_file(path, what="video", allowed_suffixes=VIDEO_SUFFIXES)
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc

        try:
            metadata = self._probe.probe(str(resolved))
        except OSError as exc:
            raise HTTPError(400, f"Could not read that video: {exc}") from exc
        if metadata["duration_seconds"] <= 0:
            raise HTTPError(400, "That file has no readable duration — it may be corrupt or not a video.")

        analysis = VideoAnalysis(
            id=f"va-{uuid.uuid4().hex[:12]}",
            title=title.strip() or resolved.stem,
            source=VideoSourceInfo(
                path=str(resolved),
                file_name=resolved.name,
                size_bytes=resolved.stat().st_size if resolved.is_file() else 0,
                duration_seconds=round(metadata["duration_seconds"], 3),
                fps=round(metadata["fps"], 3),
                width=metadata["width"],
                height=metadata["height"],
                aspect_ratio=_aspect_ratio(metadata["width"], metadata["height"]),
                codec=metadata["codec"],
                bit_rate=metadata["bit_rate"],
                frame_count=metadata["frame_count"],
                has_audio=metadata["has_audio"],
                audio_codec=metadata["audio_codec"],
                audio_channels=metadata["audio_channels"],
                audio_sample_rate=metadata["audio_sample_rate"],
                rotation=metadata["rotation"],
                pixel_format=metadata["pixel_format"],
            ),
            depth=depth,
            sensitivity=max(0.0, min(1.0, sensitivity)),
            min_shot_seconds=max(0.1, min_shot_seconds),
            max_shots=max(1, max_shots),
            detect_fades=detect_fades,
            # Asking for audio analysis on a silent file would promise nothing.
            analyze_audio=analyze_audio and metadata["has_audio"],
            analyze_text=analyze_text,
            provider=provider,
            model=model,
            stage="probing",
            progress=1.0,
            message="Ready to detect shots",
        )
        analysis.stage = "idle"
        return self._save(analysis)

    # ---- stage 2: detect shots ------------------------------------------

    def _open_job(self, analysis: VideoAnalysis, phase: str) -> None:
        if self._jobs is None:
            return
        job = self._jobs.start(
            "analysis",
            title=f"{phase.capitalize()}: {analysis.title}",
            model=analysis.model,
            inputs={"analysis_id": analysis.id, "video_path": analysis.source.path},
            params={"depth": analysis.depth, "sensitivity": analysis.sensitivity, "phase": phase},
        )
        self._analysis_jobs[analysis.id] = job.id

    def _close_job(self, analysis: VideoAnalysis) -> None:
        job_id = self._analysis_jobs.pop(analysis.id, "")
        if not job_id or self._jobs is None:
            return
        if analysis.stage == "cancelled":
            self._jobs.mark_cancelled(job_id)
        elif analysis.stage == "failed":
            self._jobs.fail(job_id, analysis.error or analysis.message)
        else:
            root = self._store.directory(analysis.id)
            frames = [str(root / shot.frames[0].path) for shot in analysis.shots if shot.frames]
            self._jobs.annotate(job_id, model=analysis.model, inputs={"shots": len(analysis.shots)})
            self._jobs.complete(job_id, frames[:12])

    def detect(self, analysis_id: str) -> VideoAnalysis:
        """Find shot boundaries and extract a still for each. Deterministic."""
        analysis = self._load(analysis_id)
        self._cancelled.discard(analysis_id)
        analysis.stage = "detecting"
        analysis.progress = 0.0
        analysis.error = ""
        analysis.message = "Reading the video"
        self._save(analysis)
        self._open_job(analysis, "detect")
        try:
            return self._detect(analysis)
        finally:
            self._close_job(analysis)

    def _detect(self, analysis: VideoAnalysis) -> VideoAnalysis:
        analysis_id = analysis.id

        try:
            signatures = self._probe.sample_signatures(
                analysis.source.path,
                sample_fps=_SAMPLE_FPS_BY_DEPTH.get(analysis.depth, 4.0),
                on_progress=lambda fraction: self._report(analysis, "detecting", fraction * 0.7, "Reading the video"),
                is_cancelled=lambda: analysis_id in self._cancelled,
            )
        except OSError as exc:
            return self._fail(analysis, f"Could not decode the video: {exc}")

        if analysis_id in self._cancelled:
            return self._cancel(analysis)

        boundaries = detect_shots(
            signatures,
            analysis.source.duration_seconds,
            DetectionSettings(
                sensitivity=analysis.sensitivity,
                min_shot_seconds=analysis.min_shot_seconds,
                max_shots=analysis.max_shots,
                detect_fades=analysis.detect_fades,
            ),
        )

        # A boundary a person moved outranks anything the detector finds.
        pinned = [shot for shot in analysis.shots if shot.boundary_edited]
        analysis.shots = [self._shot_from_boundary(boundary) for boundary in boundaries]

        analysis.stage = "extracting"
        analysis.progress = 0.7
        self._save(analysis)

        self._extract_frames(analysis)
        if analysis_id in self._cancelled:
            return self._cancel(analysis)

        analysis.stage = "idle"
        analysis.progress = 1.0
        note = f"{len(analysis.shots)} shot{'' if len(analysis.shots) == 1 else 's'} detected"
        if pinned:
            # Say so rather than quietly discarding a person's work.
            note += f" — {len(pinned)} edited boundar{'y' if len(pinned) == 1 else 'ies'} were replaced"
        analysis.message = note
        return self._save(analysis)

    def _shot_from_boundary(self, boundary: ShotBoundary) -> AnalyzedShot:
        return AnalyzedShot(
            id=f"vs-{uuid.uuid4().hex[:10]}",
            index=boundary.index,
            start=boundary.start,
            end=boundary.end,
            duration=round(boundary.duration, 3),
            detection_confidence=boundary.confidence,
            detection_method=boundary.method,
        )

    def _extract_frames(self, analysis: VideoAnalysis) -> None:
        """Pull stills for every shot that has none yet. Safe to re-run."""
        frames_dir = self._store.frames_directory(analysis.id)
        frames_dir.mkdir(parents=True, exist_ok=True)
        wanted = _FRAMES_BY_DEPTH.get(analysis.depth, 1)
        total = max(1, len(analysis.shots))

        for position, shot in enumerate(analysis.shots):
            if analysis.id in self._cancelled:
                return
            if shot.frames:
                continue
            for role, timestamp in _frame_times(shot.start, shot.end, wanted):
                name = f"{shot.id}-{role}.jpg"
                try:
                    data = self._probe.extract_jpeg(analysis.source.path, timestamp)
                except OSError as exc:
                    logger.warning("No frame at %.2fs for %s: %s", timestamp, shot.id, exc)
                    continue
                (frames_dir / name).write_bytes(data)
                shot.frames.append(
                    FrameEvidence(path=f"frames/{name}", timestamp=round(timestamp, 3), role=role)
                )
            self._report(analysis, "extracting", 0.7 + 0.3 * (position + 1) / total, "Extracting frames")
        self._save(analysis)

    # ---- stage 3: analyse -------------------------------------------------

    def analyze(self, analysis_id: str, provider: LLMProvider | None) -> VideoAnalysis:
        """Describe every shot.

        With a multimodal provider each shot's stills are sent for a structured
        reading. Without one, a deterministic pass still fills the measurable
        fields — duration, pacing, cut type, an editorial role — so the
        reconstructed storyboard is usable offline and the UI never shows an
        empty analysis it cannot explain.
        """
        analysis = self._load(analysis_id)
        if not analysis.shots:
            raise HTTPError(400, "Detect shots before analysing them.")
        self._cancelled.discard(analysis_id)
        analysis.stage = "analyzing"
        analysis.progress = 0.0
        analysis.error = ""
        self._save(analysis)
        self._open_job(analysis, "analyze")
        try:
            return self._analyze(analysis, provider)
        finally:
            self._close_job(analysis)

    def _analyze(self, analysis: VideoAnalysis, provider: LLMProvider | None) -> VideoAnalysis:
        analysis_id = analysis.id
        total = len(analysis.shots)
        used_model = ""
        for position, shot in enumerate(analysis.shots):
            if analysis_id in self._cancelled:
                return self._cancel(analysis)

            self._describe_deterministically(analysis, shot, position, total)
            if provider is not None:
                last_error: str = ""
                for attempt in range(2):  # one retry: local models occasionally OOM/queue-stall
                    try:
                        used_model = self._describe_with_model(analysis, shot, provider) or used_model
                        last_error = ""
                        break
                    except HTTPError as exc:
                        last_error = exc.detail
                        logger.warning("Shot %s analysis attempt %s failed: %s", shot.id, attempt + 1, exc.detail)
                if last_error:
                    # One shot failing must not lose the shots already done.
                    shot.evidence_note = f"Model call failed: {last_error}"

            shot.prompts = self._compose_prompts(analysis, shot)
            shot.analyzed_at = now_ms()
            self._report(analysis, "analyzing", (position + 1) / total, f"Analysed shot {position + 1} of {total}")

        self._summarise(analysis)
        analysis.stage = "complete"
        analysis.progress = 1.0
        analysis.model = used_model or analysis.model
        analysis.message = (
            f"Analysed {total} shot{'' if total == 1 else 's'}"
            if provider is not None
            else f"Described {total} shot{'' if total == 1 else 's'} without a model — connect one for a richer read"
        )
        return self._save(analysis)

    def _describe_deterministically(self, analysis: VideoAnalysis, shot: AnalyzedShot, position: int, total: int) -> None:
        """Fill what can be known from measurement alone, with no model.

        Everything set here is derived from timing and the detector, so it is
        marked `measured` — the model pass upgrades the provenance only for the
        fields it actually replaces.
        """
        duration = shot.duration
        shot.editorial = EditorialAnalysis(
            transition_in="fade" if shot.detection_method == "fade" else "cut",
            transition_out="",
            cut_type=shot.detection_method,
            rhythm="fast" if duration < 1.5 else "measured" if duration < 5 else "slow",
            approximate_beat=f"{duration:.1f}s",
            montage_role="montage beat" if duration < 1.5 else "",
            broll_role="",
            confidence=0.9 if shot.detection_method in ("cut", "fade") else 0.2,
        )
        shot.narrative = NarrativeAnalysis(
            what_happens="",
            narrative_purpose="opening" if position == 0 else "closing" if position == total - 1 else "",
            pacing=shot.editorial.rhythm,
            transition_role="establishing" if position == 0 else "",
            confidence=0.3,
        )
        shot.audio = AudioAnalysis(analyzed=False)
        shot.text = TextAnalysis(analyzed=False)
        shot.analysis_provider = shot.analysis_provider or "deterministic"
        shot.provenance = "measured"
        vision_result = self._ground_with_vision(analysis, shot)
        self._build_spec(analysis, shot, vision_result)
        self._measure_motion(analysis, shot)

    def _build_spec(self, analysis: VideoAnalysis, shot: AnalyzedShot, vision_result: Any) -> None:
        """The shot's ShotSpec from what was measured; locked/user sections survive."""
        base = shot.spec if shot.spec.provenance else None
        if vision_result is not None:
            try:
                shot.spec = spec_from_vision(vision_result, kind="video_shot", base=base)
            except Exception as exc:  # noqa: BLE001 - a spec is a bonus, never a blocker
                logger.info("Spec fusion failed for %s: %s", shot.id, exc)
        shot.spec.source.kind = "video_shot"
        shot.spec.source.path = shot.spec.source.path or analysis.source.path
        shot.spec.source.start = shot.start
        shot.spec.source.end = shot.end
        shot.spec.source.fps = analysis.source.fps or None
        if not shot.spec.source.aspect:
            shot.spec.source.aspect = analysis.source.aspect_ratio
        if not shot.spec.narrative.what_happens and shot.visual.description and not shot.spec.is_locked("narrative"):
            shot.spec.narrative.what_happens = shot.visual.description

    def _measure_motion(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> None:
        """Optical flow over the shot's span: camera move words with *measured*
        provenance, `shot.motion`, and `spec.motion` / `spec.camera.move`."""
        if self._motion is None or not analysis.source.path:
            return
        try:
            summary: MotionSummary = self._motion.analyze(analysis.source.path, start=shot.start, end=shot.end)
        except Exception as exc:  # noqa: BLE001 - the deterministic pass must never fail on flow
            shot.evidence_note = (shot.evidence_note + " " if shot.evidence_note else "") + f"Motion analysis unavailable: {exc}"
            return
        if not summary.analyzed:
            return
        shot.motion = MotionAnalysis(**summary.model_dump())
        movement, types, is_static = describe_motion(summary)
        shot.cinematography.camera_movement = movement
        shot.cinematography.movement_types = types
        shot.cinematography.is_static = is_static
        shot.cinematography.confidence = max(shot.cinematography.confidence, summary.confidence)
        try:
            apply_flow(
                shot.spec,
                pan=summary.pan, tilt=summary.tilt, zoom=summary.zoom, roll=summary.roll,
                magnitude=summary.magnitude, subject_motion=summary.subject_motion,
                handheld=summary.handheld, pacing=summary.pacing, fps=analysis.source.fps or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("apply_flow failed for %s: %s", shot.id, exc)
        grounded = self._grounding.get(shot.id, "")
        line = f"Measured camera motion (optical flow): {movement}; magnitude {summary.magnitude:.4f}, subject motion {summary.subject_motion:.4f}, pacing {summary.pacing}."
        self._grounding[shot.id] = f"{grounded}\n{line}" if grounded else line

    def _ground_with_vision(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> Any:
        """Florence-2 + CLIP + stats on the shot's representative still: fills
        subjects, a caption and a palette with *measured* provenance, and
        keeps the text as grounded context for the model pass."""
        self._grounding.pop(shot.id, "")
        if self._vision is None or not shot.frames:
            return None
        frame = self._store.directory(analysis.id) / shot.frames[len(shot.frames) // 2].path
        if not frame.is_file():
            return None
        try:
            result = self._vision.analyze(str(frame), want_depth=False)
        except Exception as exc:  # noqa: BLE001 - the deterministic pass must never fail on vision
            shot.evidence_note = f"Local vision unavailable: {exc}"
            return None
        counts: dict[str, int] = {}
        for region in result.regions:
            counts[region.label] = counts.get(region.label, 0) + 1
        subjects = [f"{n} {label}" if n > 1 else label for label, n in counts.items()]
        if subjects and not shot.visual.subjects:
            shot.visual.subjects = subjects
        if result.caption and not shot.visual.description:
            shot.visual.description = result.caption.text
        if result.measured.palette and not shot.visual.palette:
            shot.visual.palette = [entry.hex for entry in result.measured.palette[:4]]
        if result.tags and not shot.visual.visual_style:
            shot.visual.visual_style = ", ".join(t.term for t in result.tags.tags[:5])
        if subjects or result.caption:
            shot.visual.confidence = max(shot.visual.confidence, 0.5)
        lines: list[str] = []
        if result.caption:
            lines.append(f"Detected caption: {result.caption.text}")
        if subjects:
            lines.append("Detected subjects (object detection): " + ", ".join(subjects) + ".")
        if result.measured.palette:
            lines.append("Measured palette: " + ", ".join(e.hex for e in result.measured.palette[:4]) + f"; luminance {result.measured.luminance:.2f}, contrast {result.measured.contrast:.2f}.")
        if result.tags:
            lines.append("Style tags (CLIP): " + ", ".join(t.term for t in result.tags.tags[:8]) + ".")
        self._grounding[shot.id] = "\n".join(lines)
        return result

    def _describe_with_model(self, analysis: VideoAnalysis, shot: AnalyzedShot, provider: LLMProvider) -> str:
        """Ask a multimodal model to read the shot's stills, one section per call.

        Small local VLMs drop fields and break JSON when asked for forty keys
        at once; four focused calls with a repair round each keep what they
        can answer and lose only the section that failed.
        """
        images = self._frame_data_urls(analysis, shot)
        if not images:
            return ""
        context = (
            f"Shot {shot.index + 1} of {len(analysis.shots)}. "
            f"Runs {shot.start:.2f}s to {shot.end:.2f}s ({shot.duration:.2f}s) "
            f"of a {analysis.source.duration_seconds:.0f}s video at {analysis.source.aspect_ratio or 'unknown ratio'}."
        )
        grounded = self._grounding.get(shot.id, "")
        if grounded:
            context = f"{context}\n\nGround truth from a local measurement pass (do not contradict):\n{grounded}"

        answered: list[str] = []
        failed: list[str] = []
        raw_notes: list[str] = []
        for section, model_type, shape, guidance in _VLM_SECTIONS:
            parsed, raw = self._ask_section(provider, section, shape, guidance, context, images)
            if raw:
                raw_notes.append(f"[{section}] {raw[:600]}")
            if parsed is None:
                failed.append(section)
                continue
            payload = _clean(parsed, model_type)
            if not payload:
                failed.append(section)
                continue
            self._apply_section(shot, section, payload)
            answered.append(section)

        if answered:
            shot.analysis_provider = provider.name
            shot.analysis_model = provider.model
            shot.provenance = "inferred"
            self._apply_vlm_to_spec(shot)
        note = "\n".join(raw_notes)[:2000]
        if failed:
            note = f"Sections without a usable answer: {', '.join(failed)}.\n{note}"
        shot.evidence_note = note or "The model did not return usable JSON for this shot."
        return provider.model

    def _ask_section(
        self,
        provider: LLMProvider,
        section: str,
        shape: str,
        guidance: str,
        context: str,
        images: list[str],
    ) -> tuple[dict[str, object] | None, str]:
        instruction = (
            "You are a cinematographer describing ONE shot from a film. "
            f"Reply with JSON only, exactly this shape:\n{shape}\n{guidance} "
            "Every confidence is 0..1 and must reflect how much the frames actually show. "
            "Describe only what is visible; leave a field empty rather than invent."
        )
        messages = [
            LLMMessage(role="system", content=instruction),
            LLMMessage(role="user", content=context, images=images),
        ]
        reply = provider.chat(messages, json_mode=True, timeout=120)
        parsed = _json_object(reply.text)
        if parsed is not None and _has_expected_keys(parsed, shape):
            return parsed, reply.text
        # One repair round: show the model what it sent and the shape it owed.
        repair = LLMMessage(
            role="user",
            content=(
                "Your previous reply was not valid JSON of the required shape. "
                f"Send only the JSON object, no prose, matching exactly:\n{shape}\n\nPrevious reply:\n{reply.text[:1500]}"
            ),
        )
        try:
            fixed = provider.chat([*messages, LLMMessage(role="assistant", content=reply.text[:1500]), repair], json_mode=True, timeout=120)
        except HTTPError as exc:
            logger.info("Repair call for %s failed: %s", section, exc.detail)
            return None, reply.text
        parsed = _json_object(fixed.text)
        if parsed is not None and _has_expected_keys(parsed, shape):
            return parsed, fixed.text
        return None, fixed.text or reply.text

    @staticmethod
    def _apply_section(shot: AnalyzedShot, section: str, payload: dict[str, object]) -> None:
        if section == "visual":
            merged = shot.visual.model_dump()
            merged.update(payload)
            shot.visual = VisualAnalysis.model_validate(merged)
        elif section == "cinematography":
            merged = shot.cinematography.model_dump()
            measured_move = shot.motion.analyzed
            for key, value in payload.items():
                # Optical flow measured the move; the model may only add what flow cannot see.
                if measured_move and key in ("camera_movement", "movement_types", "is_static"):
                    continue
                merged[key] = value
            shot.cinematography = CinematographyAnalysis.model_validate(merged)
        elif section == "narrative":
            merged = shot.narrative.model_dump()
            merged.update(payload)
            merged["pacing"] = shot.narrative.pacing  # timed, not guessed
            shot.narrative = NarrativeAnalysis.model_validate(merged)
        elif section == "prompt_lens":
            shot.prompt_lens = PromptLensAnalysis.model_validate(_clean(payload, PromptLensAnalysis))

    @staticmethod
    def _apply_vlm_to_spec(shot: AnalyzedShot) -> None:
        visual, narrative = shot.visual, shot.narrative
        fields: dict[str, Any] = {
            "location": visual.location,
            "environment": visual.environment,
            "time_of_day": "",
            "fg": visual.foreground,
            "mg": visual.midground,
            "bg": visual.background,
            "shot_size": visual.shot_size,
            "angle": visual.angle,
            "height": visual.camera_height,
            "lens_estimate": visual.lens_estimate,
            "dof": visual.depth_of_field,
            "focus": visual.focus,
            "lighting": visual.lighting,
            "what_happens": narrative.what_happens,
            "purpose": narrative.narrative_purpose,
            "beat": narrative.story_beat,
            "style": visual.visual_style,
        }
        try:
            apply_vlm(shot.spec, fields, confidence=max(visual.confidence, 0.3))
        except Exception as exc:  # noqa: BLE001
            logger.info("apply_vlm failed for %s: %s", shot.id, exc)

    def _frame_data_urls(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> list[str]:
        directory = self._store.directory(analysis.id)
        urls: list[str] = []
        for frame in shot.frames:
            path = directory / frame.path
            if not path.is_file():
                continue
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            urls.append(f"data:image/jpeg;base64,{encoded}")
        return urls

    def _summarise(self, analysis: VideoAnalysis) -> None:
        """Roll shot-level reads up into project-level facts, without inventing."""
        characters: list[str] = []
        locations: list[str] = []
        styles: list[str] = []
        for shot in analysis.shots:
            for name in shot.visual.subjects + shot.visual.character_estimates:
                if name and name not in characters:
                    characters.append(name)
            if shot.visual.location and shot.visual.location not in locations:
                locations.append(shot.visual.location)
            if shot.visual.visual_style and shot.visual.visual_style not in styles:
                styles.append(shot.visual.visual_style)
        analysis.characters = characters[:24]
        analysis.locations = locations[:24]
        analysis.visual_style = "; ".join(styles[:3])
        described = [s.visual.description for s in analysis.shots if s.visual.description]
        analysis.synopsis = " ".join(described[:6])[:1200]

    # ---- stage 4: reverse prompts ----------------------------------------

    def compose_prompts(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> ReversePrompts:
        """Recompose a shot's prompts from its current analysis (used after spec edits)."""
        return self._compose_prompts(analysis, shot)

    def _compose_prompts(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> ReversePrompts:
        """Turn the analysis into prompts. Never overwrites a human's edit."""
        if shot.prompts.edited:
            return shot.prompts

        visual, camera = shot.visual, shot.cinematography
        subject = ", ".join(visual.subjects[:3])
        environment = " ".join(part for part in (visual.location, visual.environment) if part).strip()
        palette = ", ".join(visual.palette[:3])
        look = ", ".join(part for part in (visual.lighting, palette, visual.visual_style) if part)
        motion = camera.camera_movement or ("static camera" if camera.is_static else "")
        if shot.motion.analyzed and shot.motion.pacing and shot.motion.pacing != "still":
            motion = ", ".join(part for part in (motion, f"{shot.motion.pacing} pacing") if part)

        framing = " ".join(part for part in (visual.shot_size, visual.angle) if part)
        storyboard = ", ".join(part for part in (framing, subject, environment) if part) or shot.visual.description
        video = ", ".join(
            part
            for part in (visual.description or storyboard, motion, look, visual.depth_of_field)
            if part
        )

        return ReversePrompts(
            storyboard=storyboard,
            video=video,
            cinematography=", ".join(part for part in (framing, camera.camera_position, motion, visual.lens_estimate) if part),
            environment=", ".join(part for part in (environment, visual.production_design, visual.lighting) if part),
            character=", ".join(part for part in (subject, visual.wardrobe) if part),
            motion=motion,
            negative="text, watermark, logo, distorted hands, extra limbs",
            model_specific=self._model_specific(analysis, shot),
        )

    def _model_specific(self, analysis: VideoAnalysis, shot: AnalyzedShot) -> dict[str, str]:
        """Compile the shot for the models this user would actually render with.

        Only the configured ones, not every model in the catalog: a document
        carrying a prompt for forty models would be mostly noise, and the
        compile endpoint covers anything else on demand.
        """
        with self.lock:
            settings = self.state.app_settings
            candidates = [settings.default_video_model, settings.default_image_model]
        # The local host is always a possibility, so it is always compiled for.
        models = [model.strip() for model in (*candidates, _LOCAL_VIDEO_MODEL) if model.strip()]
        brief = brief_from_analysis(analysis, shot)
        return {model: result.prompt for model, result in compile_for(brief, models).items()}

    # ---- boundary editing ------------------------------------------------

    def split(self, analysis_id: str, shot_id: str, at: float) -> VideoAnalysis:
        analysis = self._load(analysis_id)
        index = self._index_of(analysis, shot_id)
        return self._apply_boundaries(analysis, split_shot(self._boundaries(analysis), index, at), edited_from=index)

    def merge(self, analysis_id: str, shot_id: str) -> VideoAnalysis:
        analysis = self._load(analysis_id)
        index = self._index_of(analysis, shot_id)
        return self._apply_boundaries(analysis, merge_shots(self._boundaries(analysis), index), edited_from=index)

    def move_boundary(self, analysis_id: str, shot_id: str, *, start: float | None, end: float | None) -> VideoAnalysis:
        analysis = self._load(analysis_id)
        index = self._index_of(analysis, shot_id)
        return self._apply_boundaries(
            analysis, set_boundary(self._boundaries(analysis), index, start=start, end=end), edited_from=index
        )

    def _index_of(self, analysis: VideoAnalysis, shot_id: str) -> int:
        for index, shot in enumerate(analysis.shots):
            if shot.id == shot_id:
                return index
        raise HTTPError(404, f"No shot {shot_id} in this analysis")

    @staticmethod
    def _boundaries(analysis: VideoAnalysis) -> list[ShotBoundary]:
        return [
            ShotBoundary(shot.index, shot.start, shot.end, shot.detection_confidence, shot.detection_method)
            for shot in analysis.shots
        ]

    def _apply_boundaries(
        self, analysis: VideoAnalysis, boundaries: list[ShotBoundary], *, edited_from: int
    ) -> VideoAnalysis:
        """Rebuild the shot list, keeping analysis for shots whose span is intact.

        Re-analysing a shot the edit did not touch would throw away work and
        cost tokens, so a shot is only reset when its span actually moved.
        """
        previous = {(round(s.start, 3), round(s.end, 3)): s for s in analysis.shots}
        rebuilt: list[AnalyzedShot] = []
        for boundary in boundaries:
            key = (round(boundary.start, 3), round(boundary.end, 3))
            existing = previous.get(key)
            if existing is not None:
                existing.index = boundary.index
                rebuilt.append(existing)
                continue
            shot = self._shot_from_boundary(boundary)
            shot.boundary_edited = True
            rebuilt.append(shot)
        analysis.shots = rebuilt
        # Mark the touched region so a re-detect will not silently undo the edit.
        for shot in analysis.shots[max(0, edited_from - 1) : edited_from + 2]:
            shot.boundary_edited = True
        self._save(analysis)
        self._extract_frames(analysis)
        return self._save(analysis)

    def edit_prompts(self, analysis_id: str, shot_id: str, request: PromptEditRequest) -> VideoAnalysis:
        """Apply a person's prompt edits and pin them against regeneration."""
        analysis = self._load(analysis_id)
        shot = analysis.shot(shot_id)
        if shot is None:
            raise HTTPError(404, f"No shot {shot_id} in this analysis")
        changes = request.model_dump(exclude_none=True)
        for field, value in changes.items():
            if hasattr(shot.prompts, field):
                setattr(shot.prompts, field, value)
        if changes:
            shot.prompts.edited = True
            shot.provenance = "user"
        return self._save(analysis)

    # ---- stage 5: reconstruct an editable project -------------------------

    def reconstruct(self, analysis_id: str, *, project_id: str = "", name: str = "") -> FilmProject:
        """Turn an analysis into a normal film project.

        The result is not a special kind of project: it is the same
        `FilmProject` the storyboard authors, so every existing tool — the
        composer, the queue, continuity, versions, export — works on it without
        knowing it came from a video. Lineage back to the source is kept on the
        shots so evidence stays reachable.
        """
        analysis = self._load(analysis_id)
        if not analysis.shots:
            raise HTTPError(400, "Detect shots before building a project.")

        project = FilmProject(
            id=project_id.strip() or f"film-{uuid.uuid4().hex[:12]}",
            name=name.strip() or analysis.title or "Reconstructed film",
        )
        project.settings.style_prompt = analysis.visual_style
        project.script = FilmScript(content=_script_from(analysis), updated_at=now_ms())

        # Characters and locations the analysis actually named become assets, so
        # continuity has something real to check against.
        asset_by_name: dict[str, str] = {}
        for person in analysis.characters[:12]:
            asset = FilmAsset(id=new_id("asset"), kind="character", name=person, description="Seen in the source video")
            project.assets.append(asset)
            asset_by_name[person.lower()] = asset.id
        for place in analysis.locations[:12]:
            asset = FilmAsset(id=new_id("asset"), kind="location", name=place, environment=place)
            project.assets.append(asset)
            asset_by_name[place.lower()] = asset.id

        for scene_index, group in enumerate(_group_into_scenes(analysis.shots)):
            location_name = next((s.visual.location for s in group if s.visual.location), "")
            scene = FilmScene(
                id=new_id("scene"),
                order=scene_index + 1,
                title=location_name or f"Sequence {scene_index + 1}",
                description=group[0].narrative.what_happens,
                location_id=asset_by_name.get(location_name.lower()),
                mood=group[0].narrative.emotional_purpose,
                lighting=group[0].visual.lighting,
            )
            for shot_index, analysed in enumerate(group):
                scene.shots.append(self._film_shot_from(analysis, analysed, shot_index + 1, asset_by_name))
            project.scenes.append(scene)

        self._film_store.save(project)
        analysis.reconstructed_project_id = project.id
        self._save(analysis)
        return project

    # ---- stage 6: video recreation ---------------------------------------
    
    def recreate_video(self, analysis_id: str, req: VideoRecreationRequest) -> VideoRecreationResponse:
        """Reproduce the analysed shots: one film-queue job per shot, scored,
        stitched. The work lives in `VideoReproduceHandler`; this stays the
        entry point the route and History call."""
        if self._reproduce is None:
            raise HTTPError(503, "Video reproduce is not wired in this build")
        return self._reproduce.start(analysis_id, req)

    def _film_shot_from(
        self, analysis: VideoAnalysis, analysed: AnalyzedShot, order: int, asset_by_name: dict[str, str]
    ) -> FilmShot:
        shot = FilmShot(
            id=new_id("shot"),
            order=order,
            title=analysed.visual.description[:60] or f"Shot {analysed.index + 1}",
            description=analysed.visual.description,
            duration_seconds=max(0.5, round(analysed.duration, 2)),
            action=analysed.narrative.what_happens,
            emotion=analysed.narrative.emotional_purpose,
            visual_prompt=analysed.prompts.video,
            negative_prompt=analysed.prompts.negative,
            # The prompt came from evidence; regenerating it from the structured
            # fields would lose that, so it stays locked until the user edits.
            prompt_locked=bool(analysed.prompts.video),
            status="draft",
        )
        shot.framing.shot_size = _shot_size(analysed.visual.shot_size)
        shot.framing.camera_angle = _camera_angle(analysed.visual.angle)
        shot.camera_move = _camera_move(analysed.cinematography)
        location_id = asset_by_name.get(analysed.visual.location.lower())
        if location_id:
            shot.location_id = location_id
        for name in analysed.visual.subjects[:3]:
            asset_id = asset_by_name.get(name.lower())
            if asset_id:
                shot.characters.append(ShotCharacter(asset_id=asset_id, emotion=analysed.narrative.emotional_purpose))
        # Lineage: which analysis, which shot, and where in the source.
        shot.source_ref = ShotSourceRef(
            kind="video_analysis",
            analysis_id=analysis.id,
            analysis_shot_id=analysed.id,
            source_path=analysis.source.path,
            start=analysed.start,
            end=analysed.end,
        )
        return shot

    # ---- cancellation / progress ----------------------------------------

    def cancel(self, analysis_id: str) -> VideoAnalysis:
        self._cancelled.add(analysis_id)
        analysis = self._load(analysis_id)
        if analysis.stage in ("detecting", "extracting", "analyzing"):
            return self._cancel(analysis)
        return analysis

    def _cancel(self, analysis: VideoAnalysis) -> VideoAnalysis:
        analysis.stage = "cancelled"
        analysis.message = "Cancelled"
        return self._save(analysis)

    def _fail(self, analysis: VideoAnalysis, message: str) -> VideoAnalysis:
        analysis.stage = "failed"
        analysis.error = message
        analysis.message = message
        return self._save(analysis)

    def _report(self, analysis: VideoAnalysis, stage: AnalysisStage, progress: float, message: str) -> None:
        """Persist progress on the live analysis.

        Takes the object rather than an id on purpose: reloading here would
        write back a copy from before the current stage's work and silently
        discard it.
        """
        analysis.stage = stage
        analysis.progress = round(max(0.0, min(1.0, progress)), 3)
        analysis.message = message
        self._save(analysis)
        job_id = self._analysis_jobs.get(analysis.id, "")
        if job_id and self._jobs is not None:
            self._jobs.progress(job_id, analysis.progress * 100, message)

    def recover_interrupted(self) -> int:
        """Turn jobs left running by a dead process into failures, at startup."""
        recovered = 0
        for analysis_id in self._store.list_ids():
            try:
                analysis = self._store.load(analysis_id)
            except VideoAnalysisStoreError:
                continue
            if analysis.stage in ("probing", "detecting", "extracting", "analyzing"):
                analysis.stage = "failed"
                analysis.error = "Interrupted: the app restarted while this analysis was running."
                analysis.message = analysis.error
                self._store.save(analysis)
                recovered += 1
        return recovered


def _aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return ""
    from math import gcd

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


FrameRole = Literal["start", "middle", "end", "representative"]


def _frame_times(start: float, end: float, wanted: int) -> list[tuple[FrameRole, float]]:
    """Timestamps to sample inside a shot, biased away from the cut itself."""
    span = max(0.0, end - start)
    middle = start + span / 2
    if wanted <= 1 or span < 0.5:
        return [("representative", middle)]
    inset = min(0.25, span * 0.15)
    ordered: list[tuple[FrameRole, float]] = [
        ("start", start + inset),
        ("middle", middle),
        ("end", max(start + inset, end - inset)),
    ]
    return ordered[:wanted]


#: (section, model, JSON shape, extra guidance) — one focused call each.
_VLM_SECTIONS: tuple[tuple[str, type[object], str, str], ...] = (
    (
        "visual",
        VisualAnalysis,
        '{"description":"","subjects":[],"objects":[],"location":"","environment":"","foreground":"","midground":"",'
        '"background":"","composition":"","framing":"","shot_size":"","angle":"","camera_height":"","perspective":"",'
        '"lens_estimate":"","depth_of_field":"","focus":"","lighting":"","palette":[],"contrast":"","visual_style":"",'
        '"production_design":"","wardrobe":"","props":[],"confidence":0.0}',
        "shot_size must be one of: xwide, wide, full, medium, mcu, closeup, xcu.",
    ),
    (
        "cinematography",
        CinematographyAnalysis,
        '{"camera_position":"","camera_movement":"","movement_types":[],"is_static":true,"screen_direction":"",'
        '"eyeline":"","ots_relationship":"","blocking":"","composition_rules":[],"confidence":0.0}',
        "If the ground truth names a measured camera motion, repeat it rather than guessing from stills.",
    ),
    (
        "narrative",
        NarrativeAnalysis,
        '{"what_happens":"","who_acts":[],"narrative_purpose":"","emotional_purpose":"","story_beat":"",'
        '"setup_or_payoff":"","continuity_implications":[],"confidence":0.0}',
        "Do not invent a story; describe the action the frames show.",
    ),
    (
        "prompt_lens",
        PromptLensAnalysis,
        '{"core_prompt":"","deep_description":"","subject":"","environment":"","camera":"","lighting":"","style":"",'
        '"mood":"","confidence":0.0}',
        "core_prompt is ONE concise sentence usable as an AI video prompt that reproduces this exact shot; "
        "deep_description is a vivid 150-200 word paragraph of the whole frame.",
    ),
)


def _has_expected_keys(parsed: dict[str, object], shape: str) -> bool:
    """At least one of the shape's keys came back — the model answered this
    section rather than something else (an error object, another section)."""
    try:
        expected = set(cast(dict[str, object], json.loads(shape)).keys())
    except json.JSONDecodeError:
        return True
    if not expected:
        return True
    return bool(expected & set(parsed.keys()))


def _json_object(raw: str) -> dict[str, object] | None:
    """Parse a model reply that should be a JSON object, tolerating fencing."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else None


def _clean(payload: dict[str, object], model: type[object]) -> dict[str, object]:
    """Keep only keys the model declares, so an extra field cannot break parsing.

    Also drops placeholder junk ("None", "Unknown", "N/A") that small local
    models emit for fields they could not read — leaving it in would leak
    straight into composed prompts.
    """
    fields = getattr(model, "model_fields", {})
    return {key: _strip_placeholders(value) for key, value in payload.items() if key in fields}


_PLACEHOLDER_WORDS = {"none", "unknown", "n/a", "na", "null", "not visible", "unclear", "unspecified"}


def _strip_placeholders(value: object) -> object:
    """Map a model's 'I don't know' words to empty so `or` fallbacks work."""
    if isinstance(value, str):
        return "" if value.strip().lower().strip(".,") in _PLACEHOLDER_WORDS else value
    if isinstance(value, list):
        cleaned: list[object] = [_strip_placeholders(item) for item in cast(list[object], value)]
        return cleaned
    return value


def _script_from(analysis: VideoAnalysis) -> str:
    """A readable screenplay-ish rendering of what the analysis observed."""
    lines: list[str] = []
    for shot in analysis.shots:
        heading = (shot.visual.location or "UNKNOWN").upper()
        lines.append(f"{heading} - {shot.visual.lighting or 'CONTINUOUS'}")
        lines.append("")
        body = shot.narrative.what_happens or shot.visual.description
        if body:
            lines.append(body)
            lines.append("")
    return "\n".join(lines).strip()


def _group_into_scenes(shots: list[AnalyzedShot]) -> list[list[AnalyzedShot]]:
    """Group consecutive shots into scenes where the location holds steady.

    With no location read (an offline analysis), everything lands in one scene
    rather than inventing a structure the evidence does not support.
    """
    groups: list[list[AnalyzedShot]] = []
    current: list[AnalyzedShot] = []
    previous_location = None
    for shot in shots:
        location = shot.visual.location or None
        if current and location is not None and previous_location is not None and location != previous_location:
            groups.append(current)
            current = []
        current.append(shot)
        if location is not None:
            previous_location = location
    if current:
        groups.append(current)
    return groups or [[]]


_SHOT_SIZE_WORDS: dict[str, str] = {
    "xwide": "xwide", "extreme wide": "xwide", "establishing": "xwide", "ews": "xwide",
    "wide": "wide", "ws": "wide", "long": "wide",
    "full": "full", "fs": "full",
    "medium": "medium", "ms": "medium", "mid": "medium",
    "mcu": "mcu", "medium close": "mcu",
    "closeup": "closeup", "close-up": "closeup", "close up": "closeup", "cu": "closeup",
    "xcu": "xcu", "extreme close": "xcu", "ecu": "xcu",
}

_ANGLE_WORDS: dict[str, str] = {
    "front": "front", "frontal": "front",
    "three quarter left": "threeQuarterLeft", "3/4 left": "threeQuarterLeft",
    "three quarter right": "threeQuarterRight", "3/4 right": "threeQuarterRight",
    "profile": "profile", "side": "profile",
    "back": "back", "behind": "back", "rear": "back",
    "ots": "ots", "over the shoulder": "ots", "over-the-shoulder": "ots",
    "pov": "pov", "point of view": "pov",
    "dutch": "dutch", "canted": "dutch",
}


def _shot_size(raw: str) -> ShotSize:
    """Map a model's words onto the app's vocabulary, defaulting to medium."""
    text = raw.strip().lower()
    for phrase, value in _SHOT_SIZE_WORDS.items():
        if phrase in text:
            return cast(ShotSize, value)
    return "medium"


def _camera_angle(raw: str) -> CameraAngle:
    text = raw.strip().lower()
    for phrase, value in _ANGLE_WORDS.items():
        if phrase in text:
            return cast(CameraAngle, value)
    return "front"


def _camera_move(camera: CinematographyAnalysis) -> CameraMove:
    text = " ".join([camera.camera_movement, *camera.movement_types]).lower()
    for phrase, value in (
        ("push", "push_in"), ("dolly in", "push_in"), ("zoom in", "push_in"),
        ("pull", "pull_out"), ("dolly out", "pull_out"), ("zoom out", "pull_out"),
        ("pan left", "pan_left"), ("pan right", "pan_right"),
        ("tilt up", "tilt_up"), ("tilt down", "tilt_down"),
        ("truck left", "dolly_left"), ("truck right", "dolly_right"),
        ("orbit", "orbit"), ("arc", "orbit"),
        ("follow", "follow"), ("tracking", "follow"),
    ):
        if phrase in text:
            return cast(CameraMove, value)
    return "static"
