"""Datasets, training runs and the LoRA registry (phase 7).

Storage: `<app-data>/training/datasets/<id>/{dataset.json, <images>, <captions>.txt}`,
`<app-data>/training/runs/<id>/{run.json, samples/, checkpoints}`, and the
registry `<app-data>/loras/<folder>/<name>.safetensors` + `registry.json`.
A run is one `training` job in History (progress, ETA, loss history and
samples in its metrics, the LoRA as its output). Training happens on the
task runner through the `LoraTrainer` service; the VRAM manager unloads the
vision models first and refuses configs that cannot fit the card.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path
from threading import RLock
from typing import Any, cast

from PIL import Image, UnidentifiedImageError

from _routes._errors import HTTPError
from film.training_api_types import (
    ImportDatasetItemsRequest,
    StartTrainingRequest,
    TrainerStatus,
    TrainingStatusResponse,
)
from film.training_models import LORA_TARGETS, Dataset, DatasetItem, DatasetPreset, ItemSource, LoraEntry, TrainingConfig, TrainingRun, TrainingSample, now_ms
from film.training_presets import default_config, fits_machine
from handlers.base import StateHandlerBase
from handlers.jobs_handler import Job, JobsHandler
from handlers.vision_handler import VisionHandler
from server_utils.path_policy import PathPolicyError, is_within, require_absolute_file
from services.interfaces import TaskRunner
from services.lora_fetcher import (
    LoraDownloadCancelled,
    LoraFetchError,
    LoraFetcher,
    LoraSource,
    parse_lora_url,
    safe_lora_filename,
)
from services.media_probe.media_probe import MediaProbe
from services.trainer.catalog import MACHINE_VRAM_MB, TRAINERS
from services.trainer.trainer import LoraTrainer, TrainerUnavailable, TrainingProgress, TrainingRequest
from services.vram.vram_manager import VramError, VramManager
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MAX_ITEMS = 500
#: Weight files each subprocess trainer wants per target (musubi needs all three).
WEIGHT_KEYS: dict[str, tuple[str, ...]] = {
    "z_image": ("dit", "vae", "text_encoder"),
    "qwen_image": ("dit", "vae", "text_encoder"),
    "flux": ("name_or_path",),
    "wan22": ("dit", "vae", "text_encoder"),
    "ltx2": ("name_or_path",),
}


class TrainingHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        app_data: Path,
        trainers: dict[str, LoraTrainer],
        lora_fetcher: LoraFetcher,
        task_runner: TaskRunner,
        probe: MediaProbe,
        vram: VramManager,
        jobs: JobsHandler | None = None,
        vision: VisionHandler | None = None,
        reproduce_root: Path | None = None,
        analysis_root: Path | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._root = app_data / "training"
        self._lora_root = app_data / "loras"
        self._trainers = trainers
        self._fetcher = lora_fetcher
        self._tasks = task_runner
        self._probe = probe
        self._vram = vram
        self._jobs = jobs
        self._vision = vision
        self._reproduce_root = reproduce_root
        self._analysis_root = analysis_root
        self._active: str = ""
        self._cancelled: set[str] = set()
        #: LoRA URL downloads in flight, job id → cancel flag.
        self._lora_downloads: dict[str, bool] = {}
        self._io = threading.RLock()

    # ---- storage --------------------------------------------------------------------

    def _dataset_dir(self, dataset_id: str) -> Path:
        return self._root / "datasets" / dataset_id

    def _run_dir(self, run_id: str) -> Path:
        return self._root / "runs" / run_id

    def _load_dataset(self, dataset_id: str) -> Dataset:
        path = self._dataset_dir(dataset_id) / "dataset.json"
        if not path.is_file():
            raise HTTPError(404, "Dataset not found")
        return Dataset.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_dataset(self, dataset: Dataset) -> Dataset:
        dataset.updated_at = now_ms()
        folder = self._dataset_dir(dataset.id)
        folder.mkdir(parents=True, exist_ok=True)
        dataset.folder = str(folder)
        (folder / "dataset.json").write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        # Captions live beside the images the way every trainer expects.
        for item in dataset.items:
            caption = (item.caption.strip() or dataset.trigger).strip()
            (folder / (Path(item.file).stem + ".txt")).write_text(caption + "\n", encoding="utf-8")
        return dataset

    def _load_run(self, run_id: str) -> TrainingRun:
        path = self._run_dir(run_id) / "run.json"
        if not path.is_file():
            raise HTTPError(404, "Training run not found")
        return TrainingRun.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_run(self, run: TrainingRun) -> TrainingRun:
        with self._io:
            run.updated_at = now_ms()
            folder = self._run_dir(run.id)
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / "run.json.tmp"
            tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(folder / "run.json")
        return run

    def _registry_path(self) -> Path:
        return self._lora_root / "registry.json"

    def _load_registry(self) -> list[LoraEntry]:
        path = self._registry_path()
        if not path.is_file():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(raw, list):
            return []
        items = cast(list[object], raw)
        entries = [LoraEntry.model_validate(e) for e in items if isinstance(e, dict)]
        return [e for e in entries if Path(e.file).is_file()]

    def _save_registry(self, entries: list[LoraEntry]) -> None:
        self._lora_root.mkdir(parents=True, exist_ok=True)
        self._registry_path().write_text(json.dumps([e.model_dump() for e in entries], indent=2), encoding="utf-8")

    def _weights_path(self) -> Path:
        return self._root / "trainer-weights.json"

    def weights(self) -> dict[str, dict[str, str]]:
        path = self._weights_path()
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        out: dict[str, dict[str, str]] = {}
        if isinstance(raw, dict):
            for target, values in cast(dict[str, object], raw).items():
                if isinstance(values, dict):
                    out[target] = {str(k): str(v) for k, v in cast(dict[str, object], values).items()}
        return out

    def set_weights(self, target: str, values: dict[str, str]) -> dict[str, dict[str, str]]:
        if target not in LORA_TARGETS:
            raise HTTPError(400, f"Unknown target {target}")
        current = self.weights()
        current[target] = {k: v.strip() for k, v in values.items() if k in WEIGHT_KEYS.get(target, ())}
        self._root.mkdir(parents=True, exist_ok=True)
        self._weights_path().write_text(json.dumps(current, indent=2), encoding="utf-8")
        return current

    # ---- status ----------------------------------------------------------------------

    def status(self) -> TrainingStatusResponse:
        trainers: list[TrainerStatus] = []
        for spec in TRAINERS:
            trainer = self._trainers.get(spec.id)
            installed, reason = trainer.available() if trainer is not None else (False, f"{spec.name} is not wired in this build")
            trainers.append(TrainerStatus(id=spec.id, name=spec.name, upstream=spec.upstream, license=spec.license, targets=list(spec.targets), installed=installed and spec.fits_12gb, fits_12gb=spec.fits_12gb, reason=reason, notes=spec.notes))
        weights: dict[str, dict[str, str]] = {}
        configured = self.weights()
        for target, keys in WEIGHT_KEYS.items():
            row: dict[str, str] = {}
            for key in keys:
                value = configured.get(target, {}).get(key, "")
                row[key] = value if value and (key == "name_or_path" or Path(value).exists()) else ("" if not value else f"missing: {value}")
            weights[target] = row
        memory = self._vram.memory_mb()
        with self.lock:
            active = self._active
        return TrainingStatusResponse(trainers=trainers, weights=weights, machine_vram_mb=memory[1] if memory else MACHINE_VRAM_MB, active_run_id=active)

    # ---- datasets ----------------------------------------------------------------------

    def list_datasets(self) -> list[Dataset]:
        root = self._root / "datasets"
        if not root.is_dir():
            return []
        out: list[Dataset] = []
        for folder in sorted(root.iterdir()):
            if (folder / "dataset.json").is_file():
                try:
                    out.append(Dataset.model_validate_json((folder / "dataset.json").read_text(encoding="utf-8")))
                except ValueError:
                    continue
        return sorted(out, key=lambda d: -d.updated_at)

    def get_dataset(self, dataset_id: str) -> Dataset:
        return self._load_dataset(dataset_id)

    def create_dataset(self, *, name: str, preset: DatasetPreset, trigger: str) -> Dataset:
        dataset = Dataset(name=name.strip() or "Untitled dataset", preset=preset, trigger=trigger.strip())
        return self._save_dataset(dataset)

    def update_dataset(self, dataset_id: str, *, name: str | None, preset: DatasetPreset | None, trigger: str | None) -> Dataset:
        dataset = self._load_dataset(dataset_id)
        if name is not None:
            dataset.name = name.strip() or dataset.name
        if preset is not None:
            dataset.preset = preset
        if trigger is not None:
            dataset.trigger = trigger.strip()
        return self._save_dataset(dataset)

    def delete_dataset(self, dataset_id: str) -> None:
        folder = self._dataset_dir(dataset_id)
        if not (folder / "dataset.json").is_file():
            raise HTTPError(404, "Dataset not found")
        shutil.rmtree(folder, ignore_errors=True)

    def _add_image(self, dataset: Dataset, source_path: Path, *, source: ItemSource, origin: str) -> DatasetItem | None:
        if len(dataset.items) >= MAX_ITEMS:
            raise HTTPError(400, f"A dataset holds at most {MAX_ITEMS} images")
        try:
            with Image.open(source_path) as image:
                width, height = image.size
        except (OSError, UnidentifiedImageError):
            return None
        folder = self._dataset_dir(dataset.id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{len(dataset.items) + 1:04d}-{source_path.stem[:40]}{source_path.suffix.lower()}"
        shutil.copyfile(source_path, folder / name)
        item = DatasetItem(file=name, source=source, origin=str(source_path if not origin else origin), width=width, height=height)
        dataset.items.append(item)
        return item

    def import_items(self, dataset_id: str, req: ImportDatasetItemsRequest) -> Dataset:
        dataset = self._load_dataset(dataset_id)
        added = 0
        if req.folder:
            folder = Path(req.folder)
            if not folder.is_absolute() or not folder.is_dir():
                raise HTTPError(400, "Folder must be an absolute path to an existing directory")
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in IMAGE_SUFFIXES and self._add_image(dataset, path, source="folder", origin=""):
                    added += 1
        for raw in req.image_paths:
            try:
                path = require_absolute_file(raw, what="image")
            except PathPolicyError as exc:
                raise HTTPError(400, str(exc)) from exc
            if path.suffix.lower() in IMAGE_SUFFIXES and self._add_image(dataset, path, source="folder", origin=""):
                added += 1
        if req.video_path:
            try:
                video = require_absolute_file(req.video_path, what="video")
            except PathPolicyError as exc:
                raise HTTPError(400, str(exc)) from exc
            info = self._probe.probe(str(video))
            duration = float(info["duration_seconds"])
            step = 1.0 / max(0.05, req.video_fps)
            count = 0
            t = 0.0
            frames_dir = self._dataset_dir(dataset.id) / ".frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            while t < duration and count < max(1, req.video_max_frames):
                try:
                    data = self._probe.extract_jpeg(str(video), t, max_width=1280, quality=92)
                except OSError:
                    break
                frame = frames_dir / f"{video.stem}-{t:07.2f}.jpg"
                frame.write_bytes(data)
                if self._add_image(dataset, frame, source="video", origin=f"{video}@{t:.2f}s"):
                    added += 1
                count += 1
                t += step
            shutil.rmtree(frames_dir, ignore_errors=True)
        for job_id in req.job_ids:
            if self._jobs is None:
                break
            job = self._jobs.get(job_id)
            for output in job.outputs:
                path = Path(output.path)
                if output.kind == "image" and path.is_file() and self._add_image(dataset, path, source="history", origin=job_id):
                    added += 1
        if req.analysis_id and self._analysis_root is not None:
            frames = self._analysis_root / req.analysis_id / "frames"
            if not frames.is_dir():
                raise HTTPError(404, "Video analysis not found")
            for path in sorted(frames.glob("*.jpg")):
                if self._add_image(dataset, path, source="analysis", origin=req.analysis_id):
                    added += 1
        if req.reproduce_id and self._reproduce_root is not None:
            folder = self._reproduce_root / req.reproduce_id
            if not (folder / "analysis.json").is_file():
                raise HTTPError(404, "Reproduce job not found")
            for path in sorted(folder.rglob("*.png")) + sorted(folder.rglob("*.jpg")):
                if path.name.startswith("depth") or "/fixes/" in path.as_posix():
                    continue
                if self._add_image(dataset, path, source="candidate", origin=req.reproduce_id):
                    added += 1
        if added == 0:
            raise HTTPError(400, "Nothing importable was found (PNG, JPG or WebP images, or a readable video).")
        return self._save_dataset(dataset)

    def remove_item(self, dataset_id: str, item_id: str) -> Dataset:
        dataset = self._load_dataset(dataset_id)
        item = dataset.item(item_id)
        if item is None:
            raise HTTPError(404, "Item not found")
        folder = self._dataset_dir(dataset.id)
        (folder / item.file).unlink(missing_ok=True)
        (folder / (Path(item.file).stem + ".txt")).unlink(missing_ok=True)
        dataset.items = [i for i in dataset.items if i.id != item_id]
        return self._save_dataset(dataset)

    def update_item(self, dataset_id: str, item_id: str, caption: str) -> Dataset:
        dataset = self._load_dataset(dataset_id)
        item = dataset.item(item_id)
        if item is None:
            raise HTTPError(404, "Item not found")
        item.caption = caption.strip()
        item.edited = True
        return self._save_dataset(dataset)

    def caption_dataset(self, dataset_id: str, *, overwrite_edited: bool = False) -> Dataset:
        """Florence captions + the trigger word, through the vision stack."""
        dataset = self._load_dataset(dataset_id)
        if self._vision is None:
            raise HTTPError(503, "The vision stack is not available; captions can be typed by hand.")
        folder = self._dataset_dir(dataset.id)
        model = ""
        attempted = 0
        captioned = 0
        first_failure = ""
        for item in dataset.items:
            if item.edited and not overwrite_edited:
                continue
            path = folder / item.file
            if not path.is_file():
                continue
            attempted += 1
            try:
                analysis = self._vision.analyze(str(path), want_regions=False, want_tags=False, want_depth=False)
            except Exception as exc:  # noqa: BLE001 - one bad image must not stop the pass
                logger.info("Caption failed for %s: %s", path, exc)
                first_failure = first_failure or str(exc)
                continue
            if analysis.caption is None:
                # Florence failed; the reason is in the analysis notes. Keep
                # whatever caption the item had — never fabricate a
                # trigger-only caption from a failure.
                first_failure = first_failure or analysis.notes.get("caption", "Florence-2 returned no caption")
                continue
            captioned += 1
            model = analysis.caption.model
            item.caption = _with_trigger(analysis.caption.text.strip(), dataset.trigger, dataset.preset)
            item.edited = False
        if attempted and not captioned:
            # Silence here is how a broken vision stack masquerades as a
            # captioned dataset. Say what actually happened, actionably.
            raise HTTPError(
                502,
                f"Florence-2 could not caption any of the {attempted} image(s): {first_failure or 'unknown error'}. "
                "Check Settings → Vision (Florence-2 enabled and downloadable) or type captions by hand.",
            )
        dataset.caption_model = model
        return self._save_dataset(dataset)

    def media_path(self, dataset_id: str, file: str) -> Path:
        dataset = self._load_dataset(dataset_id)
        if not any(i.file == file for i in dataset.items):
            raise HTTPError(400, "File is not part of this dataset")
        path = (self._dataset_dir(dataset.id) / file).resolve()
        if not is_within(self._dataset_dir(dataset.id), path) or not path.is_file():
            raise HTTPError(404, "File not found")
        return path

    def run_media_path(self, run_id: str, file: str) -> Path:
        """A sample image or checkpoint strictly from inside the run folder."""
        run_dir = self._run_dir(run_id)
        if not (run_dir / "run.json").is_file():
            raise HTTPError(404, "Training run not found")
        path = (run_dir / file).resolve() if not Path(file).is_absolute() else Path(file).resolve()
        if not is_within(run_dir, path) or not path.is_file():
            raise HTTPError(404, "File not found")
        return path

    # ---- training runs -------------------------------------------------------------------

    def suggest_config(self, dataset_id: str, target: str) -> TrainingConfig:
        dataset = self._load_dataset(dataset_id)
        if target not in LORA_TARGETS:
            raise HTTPError(400, f"Unknown target {target}")
        return default_config(target, dataset.preset, image_count=max(1, len(dataset.items)))

    def list_runs(self) -> list[TrainingRun]:
        root = self._root / "runs"
        if not root.is_dir():
            return []
        out: list[TrainingRun] = []
        for folder in root.iterdir():
            if (folder / "run.json").is_file():
                try:
                    out.append(TrainingRun.model_validate_json((folder / "run.json").read_text(encoding="utf-8")))
                except ValueError:
                    continue
        return sorted(out, key=lambda r: -r.created_at)

    def get_run(self, run_id: str) -> TrainingRun:
        return self._load_run(run_id)

    def start(self, req: StartTrainingRequest) -> TrainingRun:
        dataset = self._load_dataset(req.dataset_id)
        if len(dataset.items) < 4:
            raise HTTPError(400, "A LoRA needs at least 4 captioned images (12 or more is the sweet spot).")
        resume_from = ""
        if req.resume_run_id:
            previous = self._load_run(req.resume_run_id)
            if previous.is_active:
                raise HTTPError(409, "That run is still active")
            if not previous.checkpoints:
                raise HTTPError(400, "That run left no checkpoint to resume from")
            resume_from = previous.checkpoints[-1]
            config = previous.config.model_copy()
        else:
            config = req.config or default_config("z_image", dataset.preset, image_count=len(dataset.items))
        if config.target not in LORA_TARGETS:
            raise HTTPError(400, f"Unknown target {config.target}")
        memory = self._vram.memory_mb()
        ok, why = fits_machine(config, memory[1] if memory else None)
        if not ok:
            raise HTTPError(400, why)
        trainer = self._trainers.get(config.trainer)
        if trainer is None:
            raise HTTPError(400, f"No trainer named {config.trainer}")
        installed, reason = trainer.available()
        if not installed:
            raise HTTPError(400, reason)
        with self.lock:
            if self._active:
                raise HTTPError(409, "A training run is already in progress")
            run = TrainingRun(
                name=req.name.strip() or f"{dataset.name} · {config.target}",
                dataset_id=dataset.id,
                preset=dataset.preset,
                trigger=dataset.trigger,
                config=config,
                status="queued",
                total_steps=config.steps,
            )
            self._active = run.id
            self._cancelled.discard(run.id)
        if self._jobs is not None:
            job = self._jobs.start(
                "training",
                title=run.name,
                model=config.target,
                provider=config.trainer,
                seed=config.seed,
                prompt=dataset.trigger,
                params=config.model_dump(),
                inputs={"dataset_id": dataset.id, "images": len(dataset.items), "resume_from": resume_from, "run_id": run.id},
                status="queued",
            )
            run.job_id = job.id
        self._save_run(run)
        self._tasks.run_background(
            lambda: self._train(run.id, resume_from),
            task_name=f"training-{run.id}",
            on_error=lambda exc: self._fail(run.id, str(exc)),
        )
        return self._load_run(run.id)

    def cancel(self, run_id: str) -> TrainingRun:
        run = self._load_run(run_id)
        with self.lock:
            self._cancelled.add(run_id)
            active = self._active == run_id
        if not active and run.is_active:
            run.status = "cancelled"
            run.error = "Cancelled"
            self._save_run(run)
        return self._load_run(run_id)

    def delete_run(self, run_id: str) -> None:
        run = self._load_run(run_id)
        if run.is_active:
            raise HTTPError(409, "Cancel the run before deleting it")
        shutil.rmtree(self._run_dir(run_id), ignore_errors=True)

    def _is_cancelled(self, run_id: str) -> bool:
        with self.lock:
            return run_id in self._cancelled

    def _fail(self, run_id: str, message: str) -> None:
        with self.lock:
            if self._active == run_id:
                self._active = ""
        try:
            run = self._load_run(run_id)
        except HTTPError:
            return
        run.status = "failed"
        run.error = message
        run.finished_at = now_ms()
        self._save_run(run)
        if run.job_id and self._jobs is not None:
            self._jobs.fail(run.job_id, message, metrics=self._metrics(run))

    @staticmethod
    def _metrics(run: TrainingRun) -> dict[str, Any]:
        metrics: dict[str, Any] = {"steps": run.step, "total_steps": run.total_steps, "loss_history": run.loss_history[-200:]}
        if run.loss_history:
            metrics["final_loss"] = run.loss_history[-1]
        if run.eta_seconds is not None:
            metrics["eta_seconds"] = round(run.eta_seconds)
        if run.peak_vram_mb is not None:
            metrics["peak_vram_mb"] = run.peak_vram_mb
        if run.samples:
            metrics["samples"] = [s.path for s in run.samples[-8:]]
        return metrics

    def _train(self, run_id: str, resume_from: str) -> None:
        run = self._load_run(run_id)
        dataset = self._load_dataset(run.dataset_id)
        trainer = self._trainers[run.config.trainer]
        run.status = "running"
        run.phase = "preparing"
        run.started_at = now_ms()
        self._save_run(run)
        if run.job_id and self._jobs is not None:
            self._jobs.mark_running(run.job_id)
        # Make room: unload every vision model the trainer's estimate needs.
        try:
            self._vram.prepare_for_render("training", needed_mb=run.config.estimated_vram_mb)
        except VramError as exc:
            self._fail(run_id, str(exc))
            return
        out_dir = self._run_dir(run.id)
        request = TrainingRequest(
            run_id=run.id,
            trainer_id=run.config.trainer,
            target=run.config.target,
            dataset_dir=str(self._dataset_dir(dataset.id)),
            output_dir=str(out_dir),
            output_name=_safe_name(run.name),
            trigger=dataset.trigger,
            steps=run.config.steps,
            rank=run.config.rank,
            learning_rate=run.config.learning_rate,
            batch_size=run.config.batch_size,
            resolution=run.config.resolution,
            buckets=run.config.buckets,
            blocks_to_swap=run.config.blocks_to_swap,
            fp8=run.config.fp8,
            save_every=run.config.save_every,
            sample_every=run.config.sample_every,
            sample_prompts=[_sample_prompt(dataset)],
            seed=run.config.seed,
            resume_from=resume_from,
            weights=self.weights().get(run.config.target, {}),
        )
        last_report = 0.0

        def on_progress(progress: TrainingProgress) -> None:
            nonlocal last_report
            current = self._load_run(run_id)
            current.phase = progress.phase
            current.step = max(current.step, progress.step)
            current.total_steps = progress.total or current.total_steps
            if progress.loss is not None:
                current.loss_history.append(round(progress.loss, 5))
            current.eta_seconds = progress.eta_seconds
            for sample in progress.samples:
                current.samples.append(TrainingSample(step=progress.step, path=sample))
            if progress.checkpoint:
                current.checkpoints.append(progress.checkpoint)
            memory = self._vram.memory_mb()
            if memory is not None:
                current.peak_vram_mb = max(current.peak_vram_mb or 0, memory[0])
            self._save_run(current)
            if current.job_id and self._jobs is not None:
                pct = 100.0 * current.step / max(1, current.total_steps)
                self._jobs.progress(current.job_id, pct, f"{progress.phase} · step {current.step}/{current.total_steps}")
                import time as _time

                if _time.monotonic() - last_report > 2.0:
                    last_report = _time.monotonic()
                    self._jobs.annotate(current.job_id, metrics=self._metrics(current))

        try:
            outcome = trainer.train(request, on_progress, lambda: self._is_cancelled(run_id))
        except TrainerUnavailable as exc:
            self._fail(run_id, str(exc))
            return
        finally:
            with self.lock:
                if self._active == run_id:
                    self._active = ""
        run = self._load_run(run_id)
        run.log_tail = outcome.log_tail[-4000:]
        run.finished_at = now_ms()
        run.step = max(run.step, outcome.steps_done)
        if outcome.status == "complete" and outcome.lora_path:
            entry = self._register_lora(run, dataset, Path(outcome.lora_path))
            run.lora_id = entry.id
            run.lora_path = entry.file
            run.status = "complete"
            run.phase = "complete"
            self._save_run(run)
            if run.job_id and self._jobs is not None:
                self._jobs.complete(run.job_id, [entry.file, *[s.path for s in run.samples[-4:]]], metrics=self._metrics(run))
        elif outcome.status == "cancelled":
            run.status = "cancelled"
            run.phase = "cancelled"
            run.error = "Cancelled"
            self._save_run(run)
            if run.job_id and self._jobs is not None:
                self._jobs.mark_cancelled(run.job_id, reason="Cancelled")
        else:
            run.status = "failed"
            run.phase = "failed"
            run.error = (outcome.log_tail.strip().splitlines() or ["Training failed"])[-1][:400]
            self._save_run(run)
            if run.job_id and self._jobs is not None:
                self._jobs.fail(run.job_id, run.error, metrics=self._metrics(run))

    # ---- registry ------------------------------------------------------------------------

    def _register_lora(self, run: TrainingRun, dataset: Dataset, source: Path) -> LoraEntry:
        folder = self._lora_root / LORA_TARGETS.get(run.config.target, run.config.target)
        folder.mkdir(parents=True, exist_ok=True)
        name = _safe_name(run.name)
        destination = folder / f"{name}.safetensors"
        counter = 2
        while destination.exists():
            destination = folder / f"{name}-{counter}.safetensors"
            counter += 1
        shutil.copyfile(source, destination)
        entry = LoraEntry(
            name=run.name,
            file=str(destination),
            target=run.config.target,
            base_model=run.config.target,
            trigger=dataset.trigger,
            dataset_id=dataset.id,
            run_id=run.id,
            job_id=run.job_id,
            preset=dataset.preset,
            size_bytes=destination.stat().st_size,
        )
        entries = self._load_registry()
        entries.append(entry)
        self._save_registry(entries)
        return entry

    def list_loras(self, target: str = "") -> list[LoraEntry]:
        entries = self._load_registry()
        if target:
            entries = [e for e in entries if e.target == target]
        return sorted(entries, key=lambda e: -e.created_at)

    def get_lora(self, lora_id: str) -> LoraEntry:
        entry = next((e for e in self._load_registry() if e.id == lora_id), None)
        if entry is None:
            raise HTTPError(404, "LoRA not found")
        return entry

    def import_lora(self, *, path: str, name: str, target: str, trigger: str) -> LoraEntry:
        try:
            source = require_absolute_file(path, what="LoRA")
        except PathPolicyError as exc:
            raise HTTPError(400, str(exc)) from exc
        if source.suffix.lower() != ".safetensors":
            raise HTTPError(400, "A LoRA is a .safetensors file")
        if target not in LORA_TARGETS:
            raise HTTPError(400, f"Unknown target {target}")
        folder = self._lora_root / LORA_TARGETS[target]
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / source.name
        if destination.resolve() != source.resolve():
            shutil.copyfile(source, destination)
        entry = LoraEntry(name=name.strip() or source.stem, file=str(destination), target=target, base_model=target, trigger=trigger.strip(), imported=True, size_bytes=destination.stat().st_size)
        entries = [e for e in self._load_registry() if e.file != entry.file]
        entries.append(entry)
        self._save_registry(entries)
        return entry

    def update_lora(self, lora_id: str, *, name: str | None, trigger: str | None, default_multiplier: float | None) -> LoraEntry:
        entries = self._load_registry()
        entry = next((e for e in entries if e.id == lora_id), None)
        if entry is None:
            raise HTTPError(404, "LoRA not found")
        if name is not None and name.strip():
            entry.name = name.strip()
        if trigger is not None:
            entry.trigger = trigger.strip()
        if default_multiplier is not None:
            entry.default_multiplier = max(0.0, min(2.0, default_multiplier))
        self._save_registry(entries)
        return entry

    def delete_lora(self, lora_id: str) -> None:
        entries = self._load_registry()
        entry = next((e for e in entries if e.id == lora_id), None)
        if entry is None:
            raise HTTPError(404, "LoRA not found")
        Path(entry.file).unlink(missing_ok=True)
        self._save_registry([e for e in entries if e.id != lora_id])

    # ---- LoRA downloads (Hugging Face / Civitai / direct URL) ----------------------------

    def download_lora(self, *, url: str, target: str, name: str = "", trigger: str = "", api_key: str = "") -> Job:
        """Fetch a LoRA from a pasted link into the registry, as a History
        `download` job. The optional API key is used for this one request and
        never stored (not in the job, not in settings, not in logs)."""
        if target not in LORA_TARGETS:
            raise HTTPError(400, f"Unknown target {target}")
        try:
            source = parse_lora_url(url)
        except ValueError as exc:
            raise HTTPError(400, str(exc)) from exc
        if self._jobs is None:  # pragma: no cover - wired in AppHandler
            raise HTTPError(500, "The job store is not available in this build")
        title = source.filename or (f"Civitai model {source.civitai_model_id or source.civitai_version_id}" if source.kind == "civitai" else url)
        job = self._jobs.start(
            "download",
            title=f"LoRA · {title}",
            model=target,
            provider=source.kind,
            params={"target": target, "name": name, "trigger": trigger},
            inputs={"lora_url": url},
            status="queued",
        )
        with self._io:
            self._lora_downloads[job.id] = False
        key = api_key.strip()
        self._tasks.run_background(
            lambda: self._download_lora(job.id, source, target=target, name=name, trigger=trigger, api_key=key),
            task_name=f"lora-download-{job.id}",
            on_error=lambda exc: self._lora_download_failed(job.id, str(exc)),
        )
        return job

    def cancel_lora_download(self, job_id: str) -> bool:
        with self._io:
            if job_id not in self._lora_downloads:
                return False
            self._lora_downloads[job_id] = True
            return True

    def _lora_download_cancelled(self, job_id: str) -> bool:
        with self._io:
            return self._lora_downloads.get(job_id, False)

    def _lora_download_failed(self, job_id: str, message: str) -> None:
        with self._io:
            self._lora_downloads.pop(job_id, None)
        if self._jobs is not None:
            self._jobs.fail(job_id, message)

    def _download_lora(self, job_id: str, source: LoraSource, *, target: str, name: str, trigger: str, api_key: str) -> None:
        assert self._jobs is not None
        jobs = self._jobs
        jobs.mark_running(job_id, phase="resolving")
        folder = self._lora_root / LORA_TARGETS[target]
        staging = folder / ".downloading"
        try:
            resolved = self._fetcher.resolve(source, api_key)
            filename = safe_lora_filename(resolved.filename)
            if not filename:
                raise LoraFetchError(f"The link resolved to '{resolved.filename or 'no file'}', not a .safetensors LoRA")
            jobs.annotate(job_id, title=f"LoRA · {filename}")
            tmp = staging / f"{job_id}-{filename}"

            def on_progress(done: int, total: int | None) -> None:
                if total:
                    jobs.progress(job_id, min(99.0, 100.0 * done / total), f"downloading · {done // 1_048_576} / {total // 1_048_576} MB")
                else:
                    jobs.progress(job_id, 0.0, f"downloading · {done // 1_048_576} MB")

            self._fetcher.download(resolved, tmp, on_progress, lambda: self._lora_download_cancelled(job_id))
            folder.mkdir(parents=True, exist_ok=True)
            final = folder / filename
            shutil.move(str(tmp), final)
            entry = LoraEntry(
                name=name.strip() or final.stem,
                file=str(final),
                target=target,
                base_model=target,
                trigger=trigger.strip(),
                imported=True,
                size_bytes=final.stat().st_size,
            )
            with self._io:
                entries = [e for e in self._load_registry() if e.file != entry.file]
                entries.append(entry)
                self._save_registry(entries)
            jobs.annotate(job_id, metrics={"size_mb": round(entry.size_bytes / 1_048_576, 1)})
            jobs.complete(job_id, [entry.file])
        except LoraDownloadCancelled:
            jobs.mark_cancelled(job_id, reason="Cancelled")
        except LoraFetchError as exc:
            jobs.fail(job_id, str(exc))
        finally:
            with self._io:
                self._lora_downloads.pop(job_id, None)
            shutil.rmtree(staging, ignore_errors=True)

    def compatible(self, model_id: str) -> list[LoraEntry]:
        """LoRAs whose target matches a model id (for pickers)."""
        needle = model_id.lower()
        target = next((t for t in ("qwen_image", "z_image", "wan22", "flux", "ltx2") if t.replace("_", "") in needle.replace("_", "").replace("-", "")), "")
        if not target and "wan" in needle:
            target = "wan22"
        if not target and "ltx" in needle:
            target = "ltx2"
        return self.list_loras(target) if target else []


def _with_trigger(caption: str, trigger: str, preset: DatasetPreset) -> str:
    trigger = trigger.strip()
    caption = caption.strip().rstrip(".")
    if not trigger:
        return caption
    if trigger.lower() in caption.lower():
        return caption
    if preset == "style":
        return f"{caption}, in the style of {trigger}" if caption else trigger
    return f"{trigger}, {caption}" if caption else trigger


def _sample_prompt(dataset: Dataset) -> str:
    trigger = dataset.trigger or "the subject"
    if dataset.preset == "style":
        return f"a quiet street at dusk, in the style of {trigger}"
    if dataset.preset == "object":
        return f"{trigger} on a wooden table, soft window light"
    return f"{trigger}, portrait, three-quarter view, soft studio light"


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip()).strip("-")
    return (cleaned or "lora")[:60]
