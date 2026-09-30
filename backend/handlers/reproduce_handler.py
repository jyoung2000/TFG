"""Image Reproduce v2.

analyse → ShotSpec → compile → N candidates (History jobs, through the
image handler) → composite score → metric-guided refinement → repeat until
the target score or the budget. Every candidate is a scored knowledge
event; the user's pick is another. Storage keeps v1's directory layout.

Locking: the loop runs on the task runner; the app lock is held only to
read settings. The document is saved after every step so the UI can poll.
"""

from __future__ import annotations

import base64
import logging
import shutil
import threading
import uuid
from pathlib import Path
from threading import RLock
from collections.abc import Sequence
from typing import Any, cast

from PIL import Image, UnidentifiedImageError

from _routes._errors import HTTPError
from api_types import GenerateImageRequest, LoraUse
from film.image_recreation import MAX_BYTES, MAX_PIXELS, SUPPORTED, describe_differences, image_data_url, read_json
from film.llm_providers import LLMMessage, LLMProvider
from film.prompt_compiler import PromptHints, PromptStyle, SpecCompileResult, compile_from_spec, resolve_target
from film.reproduce_models import (
    ReproduceBudget,
    ReproduceCandidate,
    ReproduceJob,
    ReproducePatch,
    ReproduceRound,
    migrate_document,
)
from film.shot_spec import ShotSpec
from film.shot_spec_fusion import FILLABLE_FIELDS, apply_user, apply_vlm, apply_vlm_subjects, empty_fields, fill_empty_fields, spec_from_vision, subjects_are_derived
from handlers.base import StateHandlerBase
from handlers.image_generation_handler import ImageGenerationHandler
from handlers.jobs_handler import JobsHandler
from handlers.knowledge_handler import KnowledgeHandler
from handlers.vision_handler import VisionAnalysis, VisionHandler
from server_utils.path_policy import PathPolicyError, is_within, require_absolute_file
from services import image_ops
from services.interfaces import TaskRunner
from services.similarity.composite import CompositeScorer, ImageFeatures, ScoreBreakdown
from services.similarity.metrics import luma_array
from services.wangp_bridge import IMG2IMG_MIN_STEPS
from services.vision.deterministic import measure_path
from state.app_state_types import AppState
from server_utils.atomic_file import replace_with_retry

logger = logging.getLogger(__name__)

#: The blocks the vision model is asked for: the fields to request and the reply
#: keys that show the block was answered (a missing block gets one follow-up).
VLM_BLOCKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "scene": ("location, environment, time_of_day, weather, foreground, midground, background", ("location", "environment", "foreground", "midground", "background")),
    "lighting": ("lighting_quality, light_direction, color_temp, mood", ("lighting_quality", "light_direction", "color_temp", "mood")),
    "camera": (
        "shot_size (xwide|wide|full|medium|mcu|closeup|xcu), angle, camera_height, lens_estimate, depth_of_field (shallow|medium|deep), focus",
        ("shot_size", "angle", "camera_height", "lens_estimate", "depth_of_field", "focus"),
    ),
    "narrative": ("what_happens, purpose, beat", ("what_happens", "purpose", "beat")),
}

#: The focused follow-up used when the main read names no subjects. Live on the
#: round-5 reference, qwen2.5vl:7b answered this with "woman" and seven visible
#: details where the full instruction produced no subjects at all.
SUBJECTS_INSTRUCTION = (
    "You describe ONE image for a cinematographer. Reply with JSON only. `subjects` is a list with one object per person, "
    'animal or key object: {"label": a short specific noun such as "woman", "man", "dog" (never just "person" when the image '
    'shows more), "count": integer, "attributes": list of visible details: clothing and materials, hair, pose, expression, '
    "held objects}."
)

_NAMED_COLOURS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("black", (20, 20, 20)), ("white", (240, 240, 240)), ("grey", (128, 128, 128)), ("red", (200, 40, 40)),
    ("orange", (230, 130, 40)), ("amber", (240, 180, 60)), ("yellow", (230, 220, 60)), ("green", (60, 160, 70)),
    ("teal", (40, 150, 150)), ("blue", (50, 90, 200)), ("navy", (25, 35, 90)), ("purple", (120, 60, 160)),
    ("magenta", (200, 60, 160)), ("brown", (110, 70, 40)), ("beige", (220, 200, 160)), ("pink", (240, 160, 190)),
)
_PLATEAU = 0.01
#: Escalation ladder, tried in order when the score plateaus. The last rung is
#: img2img from the reference: as its strength falls the render converges on
#: the reference, so it is the only rung that can reach a 0.95 target and the
#: loop stays on it until the target, a cancel, or max_rounds.
_STRATEGIES = ("prompt_refinement", "seed_search", "same_resolution", "reference_conditioning")
#: FLUX.2 Klein also reads the guide as reference conditioning, so strength
#: 1.0 is already a full re-render close to the reference (MEASURED on the
#: 4070, round-6 reference at 688x384: SSIM 0.943, MAE 12.5/255) and at <= 0.8
#: the output is a near-copy (SSIM 0.998, MAE 1-2/255). Start at 1.0 and step
#: down gently so the target is met by the most re-rendered result, not a copy.
_IMG2IMG_START = 1.0
#: The largest single cut; the smallest is one sampler step (1/IMG2IMG_MIN_STEPS).
_IMG2IMG_MAX_CUT = 0.1
_IMG2IMG_FLOOR = 0.02
#: Rounds at the floor strength without improvement before the loop admits it.
_IMG2IMG_FLOOR_PATIENCE = 3
#: Longest side for reference-sized renders: a 2730 px portrait does not fit a
#: 12 GB card, and the scorer compares at a fixed size anyway.
_REFERENCE_RENDER_MAX_SIDE = 1536


def colour_name(hex_value: str) -> str:
    value = hex_value.lstrip("#")
    if len(value) != 6:
        return ""
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return min(_NAMED_COLOURS, key=lambda item: (item[1][0] - r) ** 2 + (item[1][1] - g) ** 2 + (item[1][2] - b) ** 2)[0]


def _position_word(bbox: list[float]) -> str:
    if len(bbox) != 4:
        return ""
    cx = bbox[0] + bbox[2] / 2
    return "on the left" if cx < 0.36 else "on the right" if cx > 0.64 else "centred"


class ReproduceHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        *,
        root: Path,
        image_generation: ImageGenerationHandler,
        vision: VisionHandler,
        jobs: JobsHandler,
        knowledge: KnowledgeHandler,
        task_runner: TaskRunner,
        image_model: str,
        wangp_enabled: bool,
    ) -> None:
        super().__init__(state, lock)
        self.root = root
        self._image_generation = image_generation
        self._vision = vision
        self._jobs = jobs
        self._knowledge = knowledge
        self._tasks = task_runner
        self._image_model = image_model
        self._wangp_enabled = wangp_enabled
        self._scorer = CompositeScorer()
        self._cancelled: set[str] = set()
        self._running: set[str] = set()
        self._doc_lock = threading.RLock()
        # The storyboard + 3D composer (built after this handler in AppHandler).
        self._film: Any = None
        self._scene: Any = None

    # ---- storage --------------------------------------------------------------

    def _dir(self, job_id: str) -> Path:
        if not job_id.startswith("ia-") or len(job_id) > 64 or not all(c.isalnum() or c == "-" for c in job_id):
            raise HTTPError(400, "Invalid reproduce id")
        return self.root / job_id

    def _save(self, job: ReproduceJob) -> ReproduceJob:
        from film.film_models import now_ms

        job.updated_at = now_ms()
        folder = self._dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        with self._doc_lock:
            temporary = folder / "analysis.json.tmp"
            temporary.write_text(job.model_dump_json(indent=1), encoding="utf-8")
            replace_with_retry(temporary, folder / "analysis.json")
        return job

    def get(self, job_id: str) -> ReproduceJob:
        doc = self._dir(job_id) / "analysis.json"
        if not doc.is_file():
            raise HTTPError(404, "Reproduce job not found")
        try:
            with self._doc_lock:
                payload = read_json(doc.read_text(encoding="utf-8"))
            if not payload:
                raise ValueError("empty document")
            job = migrate_document(payload)
        except (ValueError, OSError) as exc:
            raise HTTPError(500, "Reproduce job could not be read") from exc
        if job.is_busy and job.id not in self._running:
            job.status = "failed"
            job.error = job.error or "Interrupted: the app was restarted while this job was running"
        return job

    def list(self) -> list[ReproduceJob]:
        if not self.root.is_dir():
            return []
        jobs: list[ReproduceJob] = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if folder.is_dir() and folder.name.startswith("ia-"):
                try:
                    jobs.append(self.get(folder.name))
                except HTTPError:
                    continue
        return jobs

    def delete(self, job_id: str) -> None:
        self.get(job_id)
        self._cancelled.add(job_id)
        shutil.rmtree(self._dir(job_id))

    def media_path(self, job_id: str, relative: str) -> Path:
        job = self.get(job_id)
        allowed = {job.source_path, job.depth_path, *(c.path for c in job.candidates)}
        allowed.discard("")
        if relative not in allowed:
            raise HTTPError(400, "File is not part of this reproduce job")
        path = (self._dir(job_id) / relative).resolve()
        if not is_within(self._dir(job_id), path) or not path.is_file():
            raise HTTPError(404, "File not found")
        return path

    # ---- import / analyse -------------------------------------------------------

    def import_image(self, raw_path: str) -> ReproduceJob:
        try:
            path = require_absolute_file(raw_path, what="reference image", allowed_suffixes=SUPPORTED)
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        if path.stat().st_size > MAX_BYTES:
            raise HTTPError(400, "Reference exceeds the 20 MB limit")
        try:
            with Image.open(path) as image:
                if image.format != SUPPORTED[path.suffix.lower()]:
                    raise HTTPError(400, "Image contents do not match its extension")
                width, height = image.size
                if width * height > MAX_PIXELS or width < 16 or height < 16:
                    raise HTTPError(400, "Image dimensions must be at least 16px and under 32 megapixels")
                image.load()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPError(400, "Reference image cannot be decoded") from exc
        job = ReproduceJob(
            id="ia-" + uuid.uuid4().hex[:12],
            title=path.stem,
            source_path="reference" + path.suffix.lower(),
            width=width,
            height=height,
            image_model=self._image_model,
            target=self._default_target(),
        )
        job.spec.source.width, job.spec.source.height = width, height
        folder = self._dir(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, folder / job.source_path)
        return self._save(job)

    def _default_target(self) -> str:
        return resolve_target(self._image_model)[0].id if self._image_model else "z_image"

    def analyze(self, job_id: str, provider: LLMProvider | None, *, vlm_note: str = "") -> ReproduceJob:
        """Offline stack → spec; VLM (optional) fills scene/lighting/narrative.

        Registers the job as running for the whole analysis. `get()` treats a
        busy job that is not in `_running` as one whose process died and marks
        it failed, so without this the first read after the analysis was asked
        for — which is what the UI does continuously while it waits — failed
        the run it was watching. `start()`/`_run()` never had this problem
        because they do register.
        """
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
        self._running.add(job.id)
        try:
            return self._analyze(job, provider, vlm_note=vlm_note)
        finally:
            self._running.discard(job_id)

    def _analyze(self, job: ReproduceJob, provider: LLMProvider | None, *, vlm_note: str = "") -> ReproduceJob:
        job.status = "analyzing"
        job.message = "Reading the reference"
        self._save(job)
        source = self._dir(job.id) / job.source_path
        try:
            analysis = self._vision.analyze(str(source), depth_dir=self._dir(job.id))
        except HTTPError:
            job.status = "failed"
            self._save(job)
            raise
        base = job.spec if job.spec.locks else None
        job.spec = spec_from_vision(analysis, kind="image", base=base)
        job.spec.source.path = str(source)
        job.depth_path = Path(analysis.depth.depth_png).name if analysis.depth and Path(analysis.depth.depth_png).parent == self._dir(job.id) else job.depth_path
        job.why = self._why(analysis, job.spec)
        job.vision_model = "local-stack"
        # Degradation is stated, never silent (round-2 F-015): why the VLM was
        # skipped, and that a missing caption leaves a CLIP-tag-grade spec.
        if provider is None and vlm_note:
            job.why["vlm"] = f"VLM skipped: {vlm_note}"
        degraded = analysis.caption is None
        if degraded:
            reason = analysis.notes.get("caption", "Florence-2 produced no caption")
            job.why["caption_degraded"] = f"CLIP tags only — captioning unavailable: {reason}"
        if provider is not None:
            self._describe_with_vlm(job, analysis, provider)
        compiled = self._compile(job)
        job.prompt = job.prompt_override or compiled.prompt
        job.negative_prompt = compiled.negative_prompt
        job.status = "idle"
        job.message = "Analysed (captioning unavailable — CLIP tags only)" if degraded and provider is None else "Analysed"
        return self._save(job)

    def _describe_with_vlm(self, job: ReproduceJob, analysis: VisionAnalysis, provider: LLMProvider) -> None:
        with Image.open(self._dir(job.id) / job.source_path) as image:
            url = image_data_url(image)
        grounding = "\n".join(
            part
            for part in (
                f"Measured: {analysis.measured.width}x{analysis.measured.height} ({analysis.measured.aspect}); palette "
                + ", ".join(e.hex for e in analysis.measured.palette[:4]),
                f"Detected caption: {analysis.caption.text}" if analysis.caption else "",
                "Detected subjects: " + ", ".join(job.spec.subject_labels()) if job.spec.subjects else "",
            )
            if part
        )
        # Fields first, subjects last: asked subjects-first, qwen2.5vl:7b sometimes
        # answered only the subjects (live, round 5).
        instruction = (
            "You describe ONE image for a cinematographer. Reply with JSON only with string fields: "
            + ", ".join(spec for spec, _ in VLM_BLOCKS.values())
            + ", style, medium (vector|photo|3d-render|painting|pixel-art|line-art|anime), negatives (list), confidence (0-1), and "
            'subjects (list of {"label": a short specific noun, "count", "attributes": list of visible details}, one per person, '
            "animal or key object). Measured facts below are ground truth; do not contradict them."
        )
        try:
            reply = provider.chat(
                [LLMMessage(role="system", content=instruction), LLMMessage(role="user", content=f"Describe this image.\n\n{grounding}", images=[url])],
                json_mode=True,
                timeout=180,
            )
            fields = read_json(reply.text)
            if not fields:
                raise RuntimeError("no JSON returned")
        except Exception as exc:  # noqa: BLE001 - the offline spec stands on its own
            job.why["vlm"] = f"{provider.name}:{provider.model} failed: {exc}"
            return
        confidence = fields.get("confidence", 0.5)
        conf = float(confidence) if isinstance(confidence, (int, float)) else 0.5
        apply_vlm(job.spec, fields, conf)
        job.vision_model = f"{provider.name}:{provider.model}"
        still_empty = empty_fields(job.spec)
        if still_empty:
            # One follow-up for everything the main read left empty, field by
            # field (a block the read filled partly used to keep its holes:
            # time of day, focal length, aperture, background, ...). Merged
            # without overwriting; flat keys are accepted too.
            try:
                reply = provider.chat(
                    [
                        LLMMessage(role="system", content=(
                            "You describe ONE image for a cinematographer. Reply with JSON only, one key per field below, "
                            "each a short best estimate (never 'unknown'):\n"
                            + "\n".join(f'"{name}": {FILLABLE_FIELDS[name]}' for name in still_empty)
                        )),
                        LLMMessage(role="user", content=f"Fill every field for this image.\n\n{grounding}", images=[url]),
                    ],
                    json_mode=True,
                    timeout=120,
                )
                answers = read_json(reply.text) or {}
                apply_vlm(job.spec, answers, conf)
                filled_fields = fill_empty_fields(job.spec, answers, conf)
                job.why["fields_vlm"] = f"{provider.name}:{provider.model} filled {len(filled_fields)} of {len(still_empty)} empty fields"
            except Exception as exc:  # noqa: BLE001 - the reads above stand
                job.why["fields_vlm"] = f"{provider.name}:{provider.model} field follow-up failed: {exc}"
        if not job.spec.is_locked("subjects") and (not job.spec.subjects or subjects_are_derived(job.spec)):
            # A long instruction dilutes the subjects request; ask once, briefly.
            try:
                reply = provider.chat(
                    [LLMMessage(role="system", content=SUBJECTS_INSTRUCTION), LLMMessage(role="user", content="List the subjects in this image.", images=[url])],
                    json_mode=True,
                    timeout=120,
                )
                apply_vlm_subjects(job.spec, read_json(reply.text) or {}, 0.6)
            except Exception as exc:  # noqa: BLE001 - the main read stands
                job.why["subjects_vlm"] = f"{provider.name}:{provider.model} subjects follow-up failed: {exc}"
        filled = [block for block in ("subjects", "scene", "camera", "lighting", "style", "narrative") if job.spec.provenance.get(block) == "vlm"]
        job.why["vlm"] = f"{provider.name}:{provider.model} filled " + (", ".join(filled) if filled else "nothing the other readers had not")
        if not job.spec.subjects:
            job.why["subjects_empty"] = f"No subjects: object detection found none and {provider.model} named none"

    @staticmethod
    def _why(analysis: VisionAnalysis, spec: ShotSpec) -> dict[str, Any]:
        measured = analysis.measured
        why: dict[str, Any] = {
            "measured": {
                "source": "deterministic stats",
                "aspect": measured.aspect,
                "palette": [e.model_dump() for e in measured.palette[:6]],
                "luminance": measured.luminance,
                "contrast": measured.contrast,
                "saturation": measured.saturation,
                "edge_density": measured.edge_density,
                "sharpness": measured.sharpness,
            },
            "subjects": {"source": "Florence-2 object detection", "regions": [r.model_dump() for r in analysis.regions]} if analysis.regions else {"source": "none detected"},
            "caption": {"source": f"Florence-2 ({analysis.caption.model})", "text": analysis.caption.text} if analysis.caption else {"source": "no caption"},
            "style": {"source": f"CLIP ({analysis.tags.model})", "tags": [t.model_dump() for t in analysis.tags.tags], "negatives": [t.term for t in analysis.tags.negatives]} if analysis.tags else {"source": "no tags"},
            "depth": {"source": analysis.depth.model, "near": analysis.depth.near, "far": analysis.depth.far, "mean": analysis.depth.mean} if analysis.depth else {"source": "no depth"},
            "provenance": dict(spec.provenance),
            "confidence": dict(spec.confidence),
        }
        if analysis.notes:
            why["notes"] = dict(analysis.notes)
        return why

    # ---- spec / prompt editing ----------------------------------------------------

    def update_spec(self, job_id: str, patch: dict[str, Any], *, locks: dict[str, bool] | None = None) -> ReproduceJob:
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
        apply_user(job.spec, patch)
        if locks is not None:
            for section, locked in locks.items():
                job.spec.locks[section] = bool(locked)
        compiled = self._compile(job)
        if not job.prompt_override:
            job.prompt = compiled.prompt
            job.negative_prompt = compiled.negative_prompt
        return self._save(job)

    def set_prompt(self, job_id: str, prompt: str, *, target: str | None = None, style: PromptStyle | None = None) -> ReproduceJob:
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
        job.prompt_override = prompt.strip()
        if target:
            job.target = resolve_target(target)[0].id
        if style is not None:
            job.style = style
        compiled = self._compile(job)
        job.prompt = job.prompt_override or compiled.prompt
        job.negative_prompt = compiled.negative_prompt
        return self._save(job)

    def _hints(self, job: ReproduceJob) -> PromptHints | None:
        try:
            hints = self._knowledge.hints_for(job.spec.attribute_keys(), job.target, model=job.image_model)
        except Exception as exc:  # noqa: BLE001 - advice must never block a render
            logger.info("Knowledge hints unavailable: %s", exc)
            return None
        return hints if hints.phrases or hints.params else None

    def _compile(self, job: ReproduceJob, *, extra_phrases: list[str] | None = None, seed: int | None = None) -> SpecCompileResult:
        hints = self._hints(job)
        if extra_phrases:
            merged = PromptHints(phrases=[*(hints.phrases if hints else []), *extra_phrases], params=dict(hints.params) if hints else {}, sample=hints.sample if hints else 0)
            hints = merged
        return compile_from_spec(job.spec, job.target, job.style, hints, seed=seed)

    # ---- the loop -----------------------------------------------------------------

    def start(
        self,
        job_id: str,
        budget: ReproduceBudget | None,
        *,
        seed: int | None,
        provider: LLMProvider | None,
        loras: Sequence[LoraUse] = (),
        target: str | None = None,
        style: PromptStyle | None = None,
        render_model: str | None = None,
    ) -> ReproduceJob:
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "A reproduce run is already in progress")
        if target or style is not None:
            # What the target tab shows is what the loop renders.
            if target:
                job.target = resolve_target(target)[0].id
            if style is not None:
                job.style = style
            compiled = self._compile(job)
            job.prompt = job.prompt_override or compiled.prompt
            job.negative_prompt = compiled.negative_prompt
        if not job.prompt.strip() and not job.prompt_override.strip():
            raise HTTPError(400, "Analyse the reference first, or enter a prompt")
        job.loras = [l for l in loras if Path(l.name).is_file()]
        if render_model is not None:
            job.render_model = render_model.strip()
        if budget is not None:
            job.budget = budget
        job.status = "rendering"
        job.progress = 0.0
        job.error = ""
        job.message = "Starting"
        self._cancelled.discard(job.id)
        self._running.add(job.id)
        history = self._jobs.start(
            "image_reproduce",
            title=f"Reproduce: {job.title}",
            model=job.image_model,
            provider="wangp" if self._wangp_enabled else "local",
            prompt=job.prompt,
            negative_prompt=job.negative_prompt,
            params={"candidates_per_round": job.budget.candidates_per_round, "max_rounds": job.budget.max_rounds, "target_score": job.budget.target_score, "target": job.target, "seed": seed, "render_model": job.render_model or job.image_model},
            inputs={"analysis_id": job.id, "reference": str(self._dir(job.id) / job.source_path)},
            spec=job.spec.to_json(),
        )
        job.job_id = history.id
        self._save(job)
        self._tasks.run_background(
            lambda: self._run(job.id, seed, provider),
            task_name=f"reproduce-{job.id}",
            on_error=lambda exc: self._fail(job.id, str(exc)),
        )
        return self.get(job_id)

    def cancel(self, job_id: str) -> ReproduceJob:
        job = self.get(job_id)
        if job.is_busy:
            self._cancelled.add(job_id)
            self._image_generation.cancel_current()
        return job

    def _fail(self, job_id: str, error: str) -> None:
        try:
            job = self.get(job_id)
        except HTTPError:
            return
        job.status = "failed"
        job.error = error
        job.message = error
        self._running.discard(job_id)
        self._save(job)
        if job.job_id:
            self._jobs.fail(job.job_id, error)

    def _run(self, job_id: str, base_seed: int | None, provider: LLMProvider | None) -> None:
        job = self.get(job_id)
        try:
            with self._jobs.parent(job.job_id):
                self._loop(job, base_seed, provider)
        except HTTPError as exc:
            self._fail(job_id, str(exc.detail))
            return
        except Exception as exc:  # noqa: BLE001 - the document must end in a state
            self._fail(job_id, str(exc))
            return
        finally:
            self._running.discard(job_id)

    def _loop(self, job: ReproduceJob, base_seed: int | None, provider: LLMProvider | None) -> None:
        import time

        seed0 = base_seed if base_seed is not None else int(time.time()) % 2147483647
        reference_path = self._reference_path(job)
        reference = self._features(reference_path)
        extra_phrases: list[str] = []
        previous_best = _best_score(job)
        start_round = len(job.rounds)
        target = job.budget.target_score

        strategy_idx = 0
        plateau_rounds = 0
        round_count = 0
        img2img_model: str | None = None
        strength = _IMG2IMG_START
        floor_rounds = 0

        while True:
            if job.id in self._cancelled:
                return self._finish(job, "cancelled", "Cancelled")

            active_max = job.budget.max_rounds
            if active_max is not None and round_count >= active_max:
                job.message = f"Max rounds ({active_max}) reached"
                self._save(job)
                break

            strategy = _STRATEGIES[strategy_idx]
            index = start_round + round_count + 1
            size = self._reference_render_size(job) if strategy in ("same_resolution", "reference_conditioning") else None
            init = (reference_path, strength, img2img_model) if strategy == "reference_conditioning" and img2img_model else None

            compiled = self._compile(job, extra_phrases=extra_phrases, seed=seed0)
            prompt = job.prompt_override or compiled.prompt
            negative = compiled.negative_prompt
            job.prompt, job.negative_prompt = prompt, negative
            current = ReproduceRound(
                index=index, prompt=prompt, negative_prompt=negative,
                target=job.target, style=str(compiled.style),
                hints_applied=list(compiled.hints_applied), strategy=strategy,
            )
            job.rounds.append(current)
            label = f"{strategy} @ strength {strength:.2f}" if init else strategy
            job.status = "rendering"
            job.message = f"Round {index} [{label}]: rendering {job.budget.candidates_per_round} candidates"
            self._save(job)

            for n in range(job.budget.candidates_per_round):
                if job.id in self._cancelled:
                    current.finished_at = _now()
                    return self._finish(job, "cancelled", "Cancelled")
                seed = (seed0 + index * 100 + n) % 2147483647
                current.seeds.append(seed)
                denom = active_max if active_max is not None else 50
                progress = ((round_count + n / job.budget.candidates_per_round) / denom) * 100
                job.progress = min(round(progress, 1), 99.9)
                job.message = f"Round {index} [{label}]: candidate {n + 1}"
                self._save(job)
                self._jobs.progress(job.job_id, progress, job.message)
                candidate = self._render_one(job, prompt, negative, compiled, seed, index, size=size, init=init)
                if candidate is None:
                    continue
                job.status = "scoring"
                candidate.scores = self._score(reference, self._dir(job.id) / candidate.path)
                job.candidates.append(candidate)
                self._record(job, candidate, picked=False)
                if job.best() is None or candidate.scores.composite > _best_score(job):
                    job.best_candidate_id = candidate.id
                if candidate.scores.composite > current.best_score:
                    current.best_score, current.best_candidate_id = candidate.scores.composite, candidate.id
                job.status = "rendering"
                self._save(job)

            current.finished_at = _now()
            best_now = _best_score(job)

            if best_now >= target:
                current.note = f"Target {target:.2f} reached with {label}"
                self._save(job)
                return self._finish(job, "complete", f"Target {target:.2f} reached at {best_now:.2f}")

            best = job.best()
            if best is None:
                current.note = "No candidate was produced"
                self._save(job)
                break

            improvement = best_now - previous_best
            if improvement >= _PLATEAU:
                plateau_rounds = 0
                previous_best = best_now
            else:
                plateau_rounds += 1

            if init is not None:
                # Converging rung: never escalate, never give up while the
                # strength can still fall. Step down by the gap left - one
                # sampler step when close, _IMG2IMG_MAX_CUT when far - so the
                # first strength that meets the target is about the highest one.
                round_best = current.best_score
                cut = min(_IMG2IMG_MAX_CUT, max(1.0 / IMG2IMG_MIN_STEPS, target - round_best))
                next_strength = max(_IMG2IMG_FLOOR, round(strength - cut, 4))
                if strength <= _IMG2IMG_FLOOR:
                    floor_rounds = 0 if improvement >= _PLATEAU else floor_rounds + 1
                    if floor_rounds >= _IMG2IMG_FLOOR_PATIENCE:
                        current.note = f"Best {best_now:.2f} at the lowest strength {strength:.2f}"
                        self._save(job)
                        return self._finish(
                            job, "plateau",
                            f"Target not reached: best {best_now:.2f} even at img2img strength {strength:.2f} with {img2img_model}",
                        )
                current.note = f"img2img strength {strength:.2f} gave {round_best:.3f}; next {next_strength:.2f}"
                strength = next_strength
            elif plateau_rounds >= 2:
                strategy_idx += 1
                plateau_rounds = 0
                if _STRATEGIES[strategy_idx] == "reference_conditioning":
                    img2img_model = self._image_generation.img2img_model(job.render_model or job.image_model)
                    if img2img_model is None:
                        current.note = f"Plateau at {best_now:.2f}; no img2img model installed"
                        self._save(job)
                        return self._finish(
                            job, "plateau",
                            f"Target not reached: best {best_now:.2f}. Text-to-image stops here; converging on the "
                            "reference needs img2img, which needs FLUX.2 Klein installed (Models tab)",
                        )
                current.note = f"Plateau at {best_now:.2f}; escalating to {_STRATEGIES[strategy_idx]}"
                if img2img_model:
                    current.note += f" with {img2img_model}"

            if strategy == "prompt_refinement":
                patches = self._metric_patches(job, best.scores, self._dir(job.id) / best.path)
                if improvement < _PLATEAU and provider is not None:
                    patches.extend(self._vlm_patches(job, best, provider))
                current.patches = patches
                extra_phrases = list(dict.fromkeys([*extra_phrases, *(p.phrase for p in patches if p.phrase)]))

            round_count += 1
            self._save(job)

        best_final = _best_score(job)
        msg = "No candidate was produced" if not job.candidates else f"Best {best_final:.2f} (target was {target:.2f})"
        return self._finish(job, "complete", msg)

    @staticmethod
    def _reference_render_size(job: ReproduceJob) -> tuple[int, int]:
        """The reference's own size, capped for the card and snapped to 16."""
        width, height = max(job.width, 1), max(job.height, 1)
        scale = min(1.0, _REFERENCE_RENDER_MAX_SIDE / max(width, height))
        return max(64, int(width * scale) // 16 * 16), max(64, int(height * scale) // 16 * 16)

    def _finish(self, job: ReproduceJob, status: str, message: str) -> None:
        job.status = status  # type: ignore[assignment]
        job.message = message
        job.progress = 100.0 if status == "complete" else job.progress
        self._save(job)
        best = job.best()
        outputs = [str(self._dir(job.id) / best.path)] if best else []
        metrics = {"candidates": len(job.candidates), "rounds": len(job.rounds), "best_score": best.scores.composite if best else 0.0}
        if status == "complete":
            self._jobs.complete(job.job_id, outputs, metrics=metrics)
        elif status == "cancelled":
            self._jobs.mark_cancelled(job.job_id)
        else:
            self._jobs.fail(job.job_id, message, metrics=metrics)

    def _reference_path(self, job: ReproduceJob) -> Path:
        pinned = job.candidate(job.reference_candidate_id) if job.reference_candidate_id else None
        return self._dir(job.id) / (pinned.path if pinned else job.source_path)

    def _render_one(
        self, job: ReproduceJob, prompt: str, negative: str, compiled: SpecCompileResult, seed: int, round_index: int,
        *, size: tuple[int, int] | None = None, init: tuple[Path, float, str] | None = None,
    ) -> ReproduceCandidate | None:
        """One candidate. `size` overrides the compiled resolution; `init`
        (image, strength, model) renders img2img from that image."""
        params = compiled.params
        width, height = size or (params.width or job.width, params.height or job.height)
        model = init[2] if init else job.render_model
        request = GenerateImageRequest(
            prompt=prompt, width=width, height=height,
            numSteps=params.steps, numImages=1,
            loras=list(job.loras), model=model,
        )
        try:
            if init:
                result = self._image_generation.generate(request, seed=seed, init_image=init[0], denoise_strength=init[1])
            else:
                result = self._image_generation.generate(request, seed=seed)
        except HTTPError as exc:
            if exc.status_code == 507:
                raise
            logger.warning("Candidate render failed: %s", exc.detail)
            return None
        if result.status == "cancelled":
            self._cancelled.add(job.id)
            return None
        if result.status != "complete" or not result.image_paths:
            return None
        generated = Path(result.image_paths[0]).resolve()
        if not is_within(self._image_generation._outputs_dir, generated) or not generated.is_file():  # pyright: ignore[reportPrivateUsage]
            raise HTTPError(502, "Image generator returned an unreadable image")
        name = "candidate-" + uuid.uuid4().hex[:12] + generated.suffix.lower()
        shutil.copyfile(generated, self._dir(job.id) / name)
        child = self._jobs.list(kind="image_gen", limit=1)[0]
        return ReproduceCandidate(
            id=name.rsplit(".", 1)[0],
            path=name,
            prompt=prompt,
            negative_prompt=negative,
            seed=seed,
            params={"steps": params.steps, "guidance": params.guidance, "width": width, "height": height, **({"denoise_strength": init[1]} if init else {})},
            round=round_index,
            # The model that actually rendered this candidate, so History and
            # the per-model comparison read the truth rather than the default.
            model=model or job.image_model,
            target=job.target,
            job_id=child[0].id if child and child[0].parent_job_id == job.job_id else "",
        )

    # ---- scoring ------------------------------------------------------------------

    def _features(self, path: Path) -> ImageFeatures:
        features = ImageFeatures()
        with Image.open(path) as image:
            features.luma = luma_array(image)
        stats = measure_path(path)
        features.palette = [(e.hex, e.share) for e in stats.palette]
        features.sharpness = stats.sharpness
        features.edge_density = stats.edge_density
        try:
            features.clip = self._vision.embed(str(path), "clip")
        except Exception as exc:  # noqa: BLE001 - a missing model drops the component
            logger.info("CLIP embedding unavailable: %s", exc)
        try:
            features.dino = self._vision.embed(str(path), "dino")
        except Exception as exc:  # noqa: BLE001
            logger.info("DINO embedding unavailable: %s", exc)
        try:
            regions = self._vision.vision.detect(str(path), "od").regions
            features.regions = [(r.label.lower(), list(r.bbox)) for r in regions]
        except Exception as exc:  # noqa: BLE001
            logger.info("Detection unavailable for scoring: %s", exc)
        return features

    def _score(self, reference: ImageFeatures, candidate_path: Path) -> ScoreBreakdown:
        return self._scorer.score(reference, self._features(candidate_path))

    def _metric_patches(self, job: ReproduceJob, scores: ScoreBreakdown, best_path: Path) -> list[ReproducePatch]:
        """Turn the weakest components into concrete prompt language."""
        patches: list[ReproducePatch] = []
        components = scores.components
        palette = components.get("palette")
        if palette is not None and palette < 0.6 and job.spec.measured.palette:
            names = [colour_name(e.hex) for e in job.spec.measured.palette[:3]]
            phrase = "dominant colours " + ", ".join(dict.fromkeys(n for n in names if n)) + " (" + ", ".join(e.hex for e in job.spec.measured.palette[:3]) + ")"
            patches.append(ReproducePatch(reason="palette drifted from the reference", phrase=phrase, metric="palette", value=palette))
        layout = components.get("layout")
        if layout is not None and layout < 0.6 and job.spec.subjects:
            # Placement, never population. A detector's count is advisory:
            # Florence-2 returns two `human face` boxes for a single person, and
            # phrased as an order ("exactly 2 human faces centred") that made the
            # next round render a second face on a single-subject reference,
            # driving the very component this patch exists to fix further down.
            # Measured on the RTX 4070 (round-6 reference): the old phrase
            # produced round-1 best 0.7024 with layout 0.054.
            parts = [f"the {s.label} {_position_word(s.bbox)}".strip() for s in job.spec.subjects]
            phrase = ", ".join(p for p in parts if p)
            if phrase:
                patches.append(ReproducePatch(reason="subject placement differs", phrase=phrase, metric="layout", value=layout))
        ssim_value = components.get("ssim")
        if ssim_value is not None and ssim_value < 0.45:
            try:
                candidate_stats = measure_path(best_path)
                if candidate_stats.sharpness > job.spec.measured.sharpness * 1.5 and job.spec.measured.sharpness > 0:
                    patches.append(ReproducePatch(reason="candidate is sharper than the reference", phrase="soft focus, gentle film grain, no oversharpening", metric="ssim", value=ssim_value))
                elif candidate_stats.sharpness * 1.5 < job.spec.measured.sharpness:
                    patches.append(ReproducePatch(reason="candidate is softer than the reference", phrase="crisp detail, sharp edges, high clarity", metric="ssim", value=ssim_value))
                if candidate_stats.contrast + 0.08 < job.spec.measured.contrast:
                    patches.append(ReproducePatch(reason="contrast is lower than the reference", phrase="high contrast lighting", metric="ssim", value=ssim_value))
                elif candidate_stats.contrast > job.spec.measured.contrast + 0.08:
                    patches.append(ReproducePatch(reason="contrast is higher than the reference", phrase="low contrast, soft even light", metric="ssim", value=ssim_value))
            except Exception as exc:  # noqa: BLE001
                logger.info("Could not measure the candidate for patches: %s", exc)
        clip = components.get("clip")
        if clip is not None and clip < 0.6 and job.spec.narrative.what_happens:
            patches.append(ReproducePatch(reason="semantic content differs", phrase=job.spec.narrative.what_happens, metric="clip", value=clip))
        return patches

    def _vlm_patches(self, job: ReproduceJob, best: ReproduceCandidate, provider: LLMProvider) -> list[ReproducePatch]:
        try:
            with Image.open(self._dir(job.id) / job.source_path) as ref, Image.open(self._dir(job.id) / best.path) as gen:
                images = [image_data_url(ref), image_data_url(gen)]
            instruction = (
                "Compare two images: image 1 is the reference and image 2 is a generated candidate. Return JSON ONLY: "
                "differences (specific mismatches in object count/position, colours, lighting, style, text) and "
                "corrections (a list of short prompt phrases that would fix them). Do not claim exact matching is guaranteed."
            )
            reply = provider.chat(
                [LLMMessage(role="system", content=instruction), LLMMessage(role="user", content="Describe visible differences and give corrections.", images=images)],
                json_mode=True,
                timeout=180,
            )
            fields = read_json(reply.text)
        except Exception as exc:  # noqa: BLE001
            logger.info("VLM comparison unavailable: %s", exc)
            return []
        differences = describe_differences(fields.get("differences"))
        raw = fields.get("corrections")
        phrases = [str(p).strip() for p in cast(list[object], raw) if str(p).strip()] if isinstance(raw, list) else ([str(raw).strip()] if isinstance(raw, str) and raw.strip() else [])
        return [ReproducePatch(reason=differences or "VLM comparison", phrase=phrase, metric="vlm") for phrase in phrases[:4]]

    def _record(self, job: ReproduceJob, candidate: ReproduceCandidate, *, picked: bool) -> None:
        metrics = dict(candidate.scores.components)
        metrics["composite"] = candidate.scores.composite
        metrics["steps"] = float(candidate.params.get("steps", 0) or 0)
        metrics["guidance"] = float(candidate.params.get("guidance", 0) or 0)
        self._knowledge.record_candidate(
            picked=picked,
            model=job.image_model,
            provider="wangp" if self._wangp_enabled else "local",
            target=job.target,
            prompt=candidate.prompt,
            negative_prompt=candidate.negative_prompt,
            seed=candidate.seed,
            spec_keys=job.spec.attribute_keys(),
            metrics=metrics,
            note=f"{job.id}/{candidate.id}",
        )

    # ---- user actions -------------------------------------------------------------

    def pin(self, job_id: str, candidate_id: str) -> ReproduceJob:
        job = self.get(job_id)
        if candidate_id and job.candidate(candidate_id) is None:
            raise HTTPError(404, "Unknown candidate")
        job.reference_candidate_id = candidate_id
        return self._save(job)

    def pick(self, job_id: str, candidate_id: str) -> ReproduceJob:
        job = self.get(job_id)
        candidate = job.candidate(candidate_id)
        if candidate is None:
            raise HTTPError(404, "Unknown candidate")
        job.picked_candidate_id = candidate_id
        job.best_candidate_id = candidate_id
        self._record(job, candidate, picked=True)
        return self._save(job)

    def commit_fix(
        self,
        job_id: str,
        candidate_id: str,
        *,
        adjustments: image_ops.Adjustments,
        mask_png_base64: str = "",
        patch_from_reference: bool = False,
        inpaint_prompt: str = "",
    ) -> ReproduceJob:
        """Apply FixCanvas changes server-side and score the result as a new candidate."""
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
        candidate = job.candidate(candidate_id)
        if candidate is None:
            raise HTTPError(404, "Unknown candidate")
        folder = self._dir(job.id)
        with Image.open(folder / candidate.path) as image:
            working = image_ops.apply_adjustments(image, adjustments)
        mask = image_ops.decode_mask(mask_png_base64, working.size) if mask_png_base64 else None
        source: str = "fix"
        note = ""
        if mask is not None and inpaint_prompt.strip():
            working, note = self._inpaint(job, working, mask, inpaint_prompt.strip())
            source = "inpaint"
        elif mask is not None and patch_from_reference:
            with Image.open(folder / job.source_path) as reference:
                working = image_ops.patch_from_reference(working, reference, mask)
            source = "patch"
        name = "candidate-" + uuid.uuid4().hex[:12] + ".png"
        working.save(folder / name, format="PNG")
        fixed = ReproduceCandidate(
            id=name.rsplit(".", 1)[0],
            path=name,
            prompt=candidate.prompt,
            negative_prompt=candidate.negative_prompt,
            seed=candidate.seed,
            params={**candidate.params, "adjustments": adjustments.__dict__, "note": note},
            round=candidate.round,
            model=candidate.model,
            target=candidate.target,
            source=source,  # type: ignore[arg-type]
            parent_id=candidate.id,
        )
        fixed.scores = self._score(self._features(self._reference_path(job)), folder / name)
        job.candidates.append(fixed)
        if job.best() is None or fixed.scores.composite > _best_score(job):
            job.best_candidate_id = fixed.id
        return self._save(job)

    def _inpaint(self, job: ReproduceJob, base: Image.Image, mask: Any, prompt: str) -> tuple[Image.Image, str]:
        """Inpaint the masked area with the edit-capable image model; composited back inside the mask."""
        if not self._wangp_enabled:
            raise HTTPError(400, "Inpainting needs the WanGP edit model (Qwen-Image-Edit); it is not configured. Use 'patch from reference' instead.")
        bbox = image_ops.mask_bbox(mask)
        if bbox is None:
            raise HTTPError(400, "Select an area to inpaint first")
        request = GenerateImageRequest(prompt=prompt, width=base.width, height=base.height, numSteps=20, numImages=1)
        result = self._image_generation.edit(request, reference=base, mask_png=image_ops.encode_png(Image.fromarray((mask * 255).astype("uint8"), mode="L")))
        if result.status != "complete" or not result.image_paths:
            raise HTTPError(502, f"Inpaint ended with status {result.status}")
        with Image.open(result.image_paths[0]) as painted:
            merged = image_ops.composite_with_mask(base, painted.convert("RGB").resize(base.size), mask)
        return merged, f"inpainted with {job.image_model}"

    # ---- storyboard / composer / assets ------------------------------------------------

    #: Whole-person labels; detector parts ("human face", "jacket") are not cast.
    _PERSON_LABELS = frozenset({"person", "woman", "man", "girl", "boy", "child", "lady", "gentleman", "people"})

    def attach_storyboard(self, film: Any, scene: Any) -> None:
        self._film = film
        self._scene = scene

    def send_to_storyboard(self, job_id: str, *, project_id: str = "") -> dict[str, str]:
        """The job as a storyboard shot: the picked (else best, else source)
        image as its capture, the job's prompt locked on it, character assets
        (with a reference crop) for the people in it, and a composer scene +
        blockout seeded from the job's 3D layout. Sending again updates the
        same shot."""
        from film.film_models import FilmProject, FilmScene, FilmShot, ShotCharacter, new_id

        if self._film is None or self._scene is None:
            raise HTTPError(503, "The storyboard is not wired in this build")
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
        store = self._film.store
        chosen = job.candidate(job.picked_candidate_id) or job.best()
        image_path = self._dir(job.id) / (chosen.path if chosen else job.source_path)
        with self.lock:
            wanted = project_id.strip() or job.storyboard_project_id
            project = store.load(wanted) if wanted and store.exists(wanted) else FilmProject(id=wanted or new_id("film"), name=f"Reproduce: {job.title}")
            found = project.find_shot(job.storyboard_shot_id) if job.storyboard_shot_id else None
            if found is None:
                scene = next((s for s in project.scenes if s.title == "Reproduced images"), None)
                if scene is None:
                    scene = FilmScene(id=new_id("scene"), order=len(project.scenes) + 1, title="Reproduced images")
                    project.scenes.append(scene)
                shot = FilmShot(id=new_id("shot"), order=len(scene.shots) + 1, title=job.title[:60] or "Reproduced image", duration_seconds=4.0)
                scene.shots.append(shot)
            else:
                scene, shot = found
            shot.description = job.spec.narrative.what_happens
            shot.visual_prompt, shot.negative_prompt, shot.prompt_locked = job.prompt, job.negative_prompt, True
            captures = store.captures_dir(project.id)
            captures.mkdir(parents=True, exist_ok=True)
            name = f"{shot.id}-reproduce{image_path.suffix.lower() or '.png'}"
            shutil.copyfile(image_path, captures / name)
            shot.capture_path = f"captures/{name}"
            shot.generation.use_capture_as_reference = True
            if not shot.characters:
                for asset in self._cast_from_subjects(job, project.id):
                    project.assets.append(asset)
                    shot.characters.append(ShotCharacter(asset_id=asset.id))
            self._scene.seed_shot(project, shot, job.spec, shot.duration_seconds)
            store.save(project)
        job.storyboard_project_id, job.storyboard_shot_id = project.id, shot.id
        self._save(job)
        return {"project_id": project.id, "scene_id": scene.id, "shot_id": shot.id}

    def _cast_from_subjects(self, job: ReproduceJob, project_id: str) -> list[Any]:
        """A character asset per person in the image, its reference image the
        person's crop (the whole frame when there is no box)."""
        import io

        from film.film_models import FilmAsset, new_id

        with Image.open(self._dir(job.id) / job.source_path) as source:
            reference = source.convert("RGB")
        assets: list[Any] = []
        seen: set[str] = set()
        for subject in job.spec.subjects:
            label = subject.label.strip().lower()
            if label not in self._PERSON_LABELS or label in seen:
                continue
            seen.add(label)
            crop = reference
            if len(subject.bbox) == 4:
                x, y, w, h = subject.bbox
                width, height = reference.size
                box = (int(x * width), int(y * height), int((x + w) * width), int((y + h) * height))
                if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                    crop = reference.crop(box)
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG")
            details = ", ".join(subject.attributes)[:300]
            asset = FilmAsset(id=new_id("asset"), kind="character", name=subject.label.title(), description=details, appearance=details)
            asset.reference_images.append(self._film.store.save_reference_image(project_id, f"{asset.name}-{job.id}", buffer.getvalue()))
            assets.append(asset)
            if len(assets) >= 4:
                break
        return assets

    # ---- legacy compatibility ---------------------------------------------------------

    def encode_depth(self, job_id: str) -> str:
        job = self.get(job_id)
        if not job.depth_path:
            return ""
        return base64.b64encode((self._dir(job_id) / job.depth_path).read_bytes()).decode("ascii")


def _best_score(job: ReproduceJob) -> float:
    best = job.best()
    return best.scores.composite if best is not None else 0.0


def _now() -> int:
    from film.film_models import now_ms

    return now_ms()
