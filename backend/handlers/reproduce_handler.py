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
from typing import Any, cast

from PIL import Image, UnidentifiedImageError

from _routes._errors import HTTPError
from api_types import GenerateImageRequest
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
from film.shot_spec_fusion import apply_user, apply_vlm, spec_from_vision
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
from services.vision.deterministic import measure_path
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

_NAMED_COLOURS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("black", (20, 20, 20)), ("white", (240, 240, 240)), ("grey", (128, 128, 128)), ("red", (200, 40, 40)),
    ("orange", (230, 130, 40)), ("amber", (240, 180, 60)), ("yellow", (230, 220, 60)), ("green", (60, 160, 70)),
    ("teal", (40, 150, 150)), ("blue", (50, 90, 200)), ("navy", (25, 35, 90)), ("purple", (120, 60, 160)),
    ("magenta", (200, 60, 160)), ("brown", (110, 70, 40)), ("beige", (220, 200, 160)), ("pink", (240, 160, 190)),
)
_PLATEAU = 0.01


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
            temporary.replace(folder / "analysis.json")
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

    def analyze(self, job_id: str, provider: LLMProvider | None) -> ReproduceJob:
        """Offline stack → spec; VLM (optional) fills scene/lighting/narrative."""
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "The job is busy")
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
        if provider is not None:
            self._describe_with_vlm(job, analysis, provider)
        compiled = self._compile(job)
        job.prompt = job.prompt_override or compiled.prompt
        job.negative_prompt = compiled.negative_prompt
        job.status = "idle"
        job.message = "Analysed"
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
        instruction = (
            "You describe ONE image for a cinematographer. Reply with JSON only with string fields: location, environment, "
            "time_of_day, weather, foreground, midground, background, lighting_quality, light_direction, color_temp, mood, "
            "shot_size (xwide|wide|full|medium|mcu|closeup|xcu), angle, camera_height, lens_estimate, depth_of_field "
            "(shallow|medium|deep), focus, what_happens, purpose, style, medium (vector|photo|3d-render|painting|pixel-art|"
            "line-art|anime), negatives (list) and confidence (0-1). Measured facts below are ground truth; do not contradict them."
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
        apply_vlm(job.spec, fields, float(confidence) if isinstance(confidence, (int, float)) else 0.5)
        job.vision_model = f"{provider.name}:{provider.model}"
        job.why["vlm"] = f"{provider.name}:{provider.model} filled scene, lighting and narrative"

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

    def start(self, job_id: str, budget: ReproduceBudget | None, *, seed: int | None, provider: LLMProvider | None) -> ReproduceJob:
        job = self.get(job_id)
        if job.is_busy:
            raise HTTPError(409, "A reproduce run is already in progress")
        if not job.prompt.strip() and not job.prompt_override.strip():
            raise HTTPError(400, "Analyse the reference first, or enter a prompt")
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
            params={"candidates_per_round": job.budget.candidates_per_round, "max_rounds": job.budget.max_rounds, "target_score": job.budget.target_score, "target": job.target, "seed": seed},
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
        reference = self._features(self._reference_path(job))
        extra_phrases: list[str] = []
        previous_best = _best_score(job)
        start_round = len(job.rounds)
        for round_offset in range(job.budget.max_rounds):
            index = start_round + round_offset + 1
            if job.id in self._cancelled:
                return self._finish(job, "cancelled", "Cancelled")
            compiled = self._compile(job, extra_phrases=extra_phrases, seed=seed0)
            prompt = job.prompt_override or compiled.prompt
            negative = compiled.negative_prompt
            job.prompt, job.negative_prompt = prompt, negative
            current = ReproduceRound(index=index, prompt=prompt, negative_prompt=negative, target=job.target, style=str(compiled.style), hints_applied=list(compiled.hints_applied))
            job.rounds.append(current)
            job.status = "rendering"
            job.message = f"Round {index}: rendering {job.budget.candidates_per_round} candidates"
            self._save(job)
            for n in range(job.budget.candidates_per_round):
                if job.id in self._cancelled:
                    current.finished_at = _now()
                    return self._finish(job, "cancelled", "Cancelled")
                seed = (seed0 + (index - 1) * 100 + n) % 2147483647
                current.seeds.append(seed)
                progress = ((round_offset + n / job.budget.candidates_per_round) / job.budget.max_rounds) * 100
                job.progress = round(progress, 1)
                job.message = f"Round {index}: candidate {n + 1} of {job.budget.candidates_per_round}"
                self._save(job)
                self._jobs.progress(job.job_id, progress, job.message)
                candidate = self._render_one(job, prompt, negative, compiled, seed, index)
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
            if best_now >= job.budget.target_score:
                current.note = f"Target score {job.budget.target_score:.2f} reached"
                self._save(job)
                break
            if round_offset == job.budget.max_rounds - 1:
                break
            improvement = best_now - previous_best
            previous_best = best_now
            best = job.best()
            if best is None:
                current.note = "No candidate was produced"
                self._save(job)
                break
            patches = self._metric_patches(job, best.scores, self._dir(job.id) / best.path)
            if improvement < _PLATEAU and provider is not None:
                patches.extend(self._vlm_patches(job, best, provider))
            current.patches = patches
            extra_phrases = list(dict.fromkeys([*extra_phrases, *(p.phrase for p in patches if p.phrase)]))
            if not patches:
                current.note = "No measurable mismatch left to patch"
            self._save(job)
        self._finish(job, "complete", f"Best composite {_best_score(job):.2f}" if job.best() is not None else "No candidate was produced")

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

    def _render_one(self, job: ReproduceJob, prompt: str, negative: str, compiled: SpecCompileResult, seed: int, round_index: int) -> ReproduceCandidate | None:
        params = compiled.params
        width = params.width or job.width
        height = params.height or job.height
        request = GenerateImageRequest(prompt=prompt, width=width, height=height, numSteps=params.steps, numImages=1)
        try:
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
            params={"steps": params.steps, "guidance": params.guidance, "width": width, "height": height},
            round=round_index,
            model=job.image_model,
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
            parts = [f"exactly {s.count} {s.label}{'s' if s.count > 1 else ''} {_position_word(s.bbox)}".strip() for s in job.spec.subjects]
            patches.append(ReproducePatch(reason="subject count or placement differs", phrase=", ".join(parts), metric="layout", value=layout))
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
