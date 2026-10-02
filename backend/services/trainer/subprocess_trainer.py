"""Subprocess trainers: musubi-tuner and ai-toolkit in their own venvs.

Each wrapper writes the config the upstream expects, runs it, parses the
step / loss lines it prints, watches the sample folder, and returns the
LoRA safetensors path. Nothing here imports the upstream packages: they
live in `backend/.venv-trainer-*` (created by `scripts/ensure-trainer.*`).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from services.trainer.catalog import TrainerSpec, trainer_for
from services.trainer.trainer import (
    CancelledCallback,
    ProgressCallback,
    TrainerUnavailable,
    TrainingOutcome,
    TrainingProgress,
    TrainingRequest,
)

logger = logging.getLogger(__name__)

_STEP_PATTERNS = (
    re.compile(r"steps?:\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)/(\d+)\s*\[.*?\]"),
)
_LOSS_PATTERN = re.compile(r"(?:avr_)?loss[=:]\s*([0-9]*\.?[0-9]+(?:e[-+]?\d+)?)", re.IGNORECASE)
_ETA_PATTERN = re.compile(r"<\s*(\d+):(\d+)(?::(\d+))?")


def parse_progress_line(line: str) -> tuple[int, int, float | None, float | None] | None:
    """`(step, total, loss, eta_seconds)` from a tqdm/log line, or None."""
    step_total = None
    for pattern in _STEP_PATTERNS:
        match = pattern.search(line)
        if match:
            step_total = (int(match.group(1)), int(match.group(2)))
            break
    if step_total is None:
        return None
    loss_match = _LOSS_PATTERN.search(line)
    loss = float(loss_match.group(1)) if loss_match else None
    eta = None
    eta_match = _ETA_PATTERN.search(line)
    if eta_match:
        parts = [int(p) for p in eta_match.groups() if p is not None]
        eta = float(parts[0] * 60 + parts[1]) if len(parts) == 2 else float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return step_total[0], step_total[1], loss, eta


def training_step(line: str, total: int) -> tuple[int, int, float | None, float | None] | None:
    """The run's own progress: a bar counting to the run's step total. Other
    bars (loading shards, denoising a sample) also read "N/M [" - one froze
    Raven's run at 521 of 1100, since the step only goes up (2026-10-02)."""
    parsed = parse_progress_line(line)
    return parsed if parsed is not None and parsed[1] == total else None


def sample_images(work_dir: Path) -> list[Path]:
    """Sample renders: musubi writes them to `sample/`, ai-toolkit's config to `samples/`."""
    return sorted(p for folder in ("samples", "sample") for p in (work_dir / folder).glob("*.png"))


TRAINER_ROOT_ENV = "TFG_TRAINER_ROOT"


def resolve_trainer_root(*, backend_root: Path, app_data_dir: Path, environ: Mapping[str, str] | None = None) -> Path:
    """The folder that holds the trainers' clones and venvs.

    1. `TFG_TRAINER_ROOT`, when set.
    2. `<app data>/trainers`: survives reinstalls, unlike the installed app's
       own backend folder (the app looked only there, 2026-10-02).
    3. `backend/`, when a development checkout already has a trainer there.
    4. Otherwise `<app data>/trainers`, so "not installed" names where to put one.
    """
    env = os.environ if environ is None else environ
    explicit = env.get(TRAINER_ROOT_ENV, "").strip()
    if explicit:
        return Path(explicit)
    persistent = app_data_dir / "trainers"
    for root in (persistent, backend_root):
        if root.is_dir() and any(child.is_dir() for child in root.glob(".venv-trainer-*")):
            return root
    return persistent


class SubprocessTrainer:
    """Shared subprocess loop; subclasses build the command and config."""

    id = "subprocess"
    spec: TrainerSpec

    def __init__(self, backend_root: Path, trainer_id: str) -> None:
        spec = trainer_for(trainer_id)
        if spec is None:
            raise ValueError(f"Unknown trainer {trainer_id}")
        self.spec = spec
        self.id = spec.id
        self._backend_root = backend_root
        self._process: subprocess.Popen[str] | None = None

    # ---- environment ------------------------------------------------------------

    @property
    def env_dir(self) -> Path:
        return self._backend_root / self.spec.env_name

    @property
    def python(self) -> Path:
        if os.name == "nt":
            return self.env_dir / "Scripts" / "python.exe"
        return self.env_dir / "bin" / "python"

    @property
    def upstream_dir(self) -> Path:
        return self._backend_root / f".trainer-{self.spec.id}"

    def child_env(self) -> dict[str, str]:
        """The trainer's environment: unbuffered, and UTF-8 on the pipe - on
        Windows a piped child writes cp1252, and non-ASCII output (musubi's
        --help crashed with UnicodeEncodeError, 2026-10-02) would kill a run."""
        return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def available(self) -> tuple[bool, str]:
        if not self.spec.fits_12gb:
            return False, f"{self.spec.name} needs ~{self.spec.image_vram_mb // 1024} GB of VRAM; this machine has 12 GB. {self.spec.notes}"
        if not self.python.is_file():
            script = "scripts/ensure-trainer.ps1" if os.name == "nt" else "scripts/ensure-trainer.sh"
            return False, f'{self.spec.name} is not installed. Run `{script} {self.spec.id} "{self._backend_root}"` (creates {self.env_dir}).'
        return True, f"{self.spec.name} ready in {self.env_dir}"

    # ---- to override ---------------------------------------------------------------

    def build_command(self, request: TrainingRequest, work_dir: Path) -> list[list[str]]:
        raise NotImplementedError

    def lora_output(self, request: TrainingRequest) -> Path:
        return Path(request.output_dir) / f"{request.output_name}.safetensors"

    # ---- run -------------------------------------------------------------------------

    def missing_weights(self, target: str, weights: dict[str, str]) -> list[str]:
        """Model files the trainer lacks for `target`; a model name / repo id needs no file."""
        return []

    def train(self, request: TrainingRequest, on_progress: ProgressCallback, is_cancelled: CancelledCallback) -> TrainingOutcome:
        ok, reason = self.available()
        if not ok:
            raise TrainerUnavailable(reason)
        work_dir = Path(request.output_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        samples_dir = work_dir / "samples"
        samples_dir.mkdir(exist_ok=True)
        seen_samples: set[str] = set()
        tail: list[str] = []
        steps_done = 0
        last_loss: float | None = None
        commands = self.build_command(request, work_dir)
        for index, command in enumerate(commands):
            phase = "caching" if index < len(commands) - 1 else "training"
            on_progress(TrainingProgress(step=steps_done, total=request.steps, phase=phase))
            logger.info("[%s] %s", self.spec.id, " ".join(command[:6]) + (" …" if len(command) > 6 else ""))
            self._process = subprocess.Popen(  # noqa: S603 - command built from our own catalog + validated paths
                command,
                cwd=str(self.upstream_dir if self.upstream_dir.is_dir() else work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.child_env(),
            )
            assert self._process.stdout is not None
            for raw in self._process.stdout:
                line = raw.rstrip("\n")
                if line:
                    tail.append(line[:300])
                    tail = tail[-60:]
                if is_cancelled():
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                    return TrainingOutcome(status="cancelled", steps_done=steps_done, final_loss=last_loss, log_tail="\n".join(tail))
                if phase != "training":
                    continue
                parsed = training_step(line, request.steps)
                if parsed is None:
                    continue
                step, total, loss, eta = parsed
                steps_done = max(steps_done, step)
                if loss is not None:
                    last_loss = loss
                fresh = [p for p in sample_images(work_dir) if str(p) not in seen_samples]
                seen_samples.update(str(p) for p in fresh)
                on_progress(TrainingProgress(step=step, total=total or request.steps, loss=loss, eta_seconds=eta, phase="training", samples=[str(p) for p in fresh]))
            code = self._process.wait()
            self._process = None
            if code != 0:
                return TrainingOutcome(status="failed", steps_done=steps_done, final_loss=last_loss, log_tail="\n".join(tail))
        lora = self.find_lora(request)
        if lora is None:
            return TrainingOutcome(status="failed", steps_done=steps_done, final_loss=last_loss, log_tail="\n".join(tail) + "\nNo .safetensors was written.")
        convert = self.convert_command(lora, request)
        if convert is not None:
            on_progress(TrainingProgress(step=steps_done, total=request.steps, phase="converting"))
            done = subprocess.run(  # noqa: S603 - our own catalog command
                convert, cwd=str(self.upstream_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", env=self.child_env(),
            )
            converted = Path(convert[convert.index("--output") + 1])
            if done.returncode != 0 or not converted.is_file():
                log = "\n".join(tail + (done.stdout + done.stderr).splitlines()[-20:])
                return TrainingOutcome(status="failed", steps_done=steps_done, final_loss=last_loss, log_tail=log + "\nConverting the LoRA for the renderer failed.")
            lora = converted
        # A last sweep: musubi samples at the final step, after the last progress line.
        seen_samples.update(str(p) for p in sample_images(work_dir))
        return TrainingOutcome(status="complete", lora_path=str(lora), steps_done=max(steps_done, request.steps), final_loss=last_loss, samples=sorted(seen_samples), log_tail="\n".join(tail))

    def find_lora(self, request: TrainingRequest) -> Path | None:
        expected = self.lora_output(request)
        if expected.is_file():
            return expected
        # Never the latent cache, which also holds .safetensors (2026-10-02).
        root = Path(request.output_dir)
        candidates = sorted(
            (p for p in root.rglob("*.safetensors") if "cache" not in p.relative_to(root).parts),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        return candidates[0] if candidates else None

    def convert_command(self, lora: Path, request: TrainingRequest) -> list[str] | None:
        """The command that turns the trained file into one the renderer loads, or None."""
        return None


class MusubiTrainer(SubprocessTrainer):
    """kohya-ss/musubi-tuner: cache latents + text-encoder outputs, then train.

    Script and network-module names per the upstream docs (zimage.md,
    qwen_image.md, wan.md); the 12 GB preset uses `--fp8_base --fp8_scaled`,
    `--fp8_llm` / `--fp8_vl` / `--fp8_t5`, gradient checkpointing and
    `--blocks_to_swap`.
    """

    _SCRIPTS: dict[str, dict[str, str]] = {
        "z_image": {"cache_latents": "zimage_cache_latents.py", "cache_text": "zimage_cache_text_encoder_outputs.py", "train": "zimage_train_network.py", "network": "networks.lora_zimage", "te_flag": "--fp8_llm"},
        "qwen_image": {"cache_latents": "qwen_image_cache_latents.py", "cache_text": "qwen_image_cache_text_encoder_outputs.py", "train": "qwen_image_train_network.py", "network": "networks.lora_qwen_image", "te_flag": "--fp8_vl"},
        "flux": {"cache_latents": "flux_2_cache_latents.py", "cache_text": "flux_2_cache_text_encoder_outputs.py", "train": "flux_2_train_network.py", "network": "networks.lora_flux_2", "te_flag": "--fp8_llm"},
        "wan22": {"cache_latents": "wan_cache_latents.py", "cache_text": "wan_cache_text_encoder_outputs.py", "train": "wan_train_network.py", "network": "networks.lora_wan", "te_flag": "--fp8_t5"},
    }

    def __init__(self, backend_root: Path) -> None:
        super().__init__(backend_root, "musubi")

    def write_dataset_toml(self, request: TrainingRequest, work_dir: Path) -> Path:
        cache_dir = work_dir / "cache"
        cache_dir.mkdir(exist_ok=True)
        lines = [
            "[general]",
            f"resolution = [{request.resolution}, {request.resolution}]",
            'caption_extension = ".txt"',
            f"batch_size = {max(1, request.batch_size)}",
            "enable_bucket = true",
            "bucket_no_upscale = false",
            "",
            "[[datasets]]",
            f'image_directory = "{Path(request.dataset_dir).as_posix()}"',
            f'cache_directory = "{cache_dir.as_posix()}"',
            "num_repeats = 1",
            "",
        ]
        path = work_dir / "dataset.toml"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    #: Targets whose LoRA musubi writes in kohya layout (lora_unet_layers_0_...) while
    #: WanGP matches dotted module paths (layers.0.attention.to_q): converted with
    #: musubi's own convert_lora.py --target other (zimage.md). The raw file stays
    #: beside it, for resuming.
    _CONVERT_FOR_WANGP = ("z_image",)

    def convert_command(self, lora: Path, request: TrainingRequest) -> list[str] | None:
        if request.target not in self._CONVERT_FOR_WANGP:
            return None
        output = lora.with_name(f"{lora.stem}-wangp.safetensors")
        # src/musubi_tuner/convert_lora.py - zimage.md says networks/, which does not exist (MEASURED).
        script = self.upstream_dir / "src" / "musubi_tuner" / "convert_lora.py"
        return [str(self.python), str(script), "--input", str(lora), "--output", str(output), "--target", "other"]

    def missing_weights(self, target: str, weights: dict[str, str]) -> list[str]:
        """musubi needs the DiT, the VAE and the text encoder as files on disk."""
        if target not in self._SCRIPTS:
            return []
        return [key for key in ("dit", "vae", "text_encoder") if not weights.get(key) or not Path(weights[key]).exists()]

    def build_command(self, request: TrainingRequest, work_dir: Path) -> list[list[str]]:
        scripts = self._SCRIPTS.get(request.target)
        if scripts is None:
            raise TrainerUnavailable(f"musubi-tuner has no recipe for target {request.target}")
        if request.target == "wan22":
            raise TrainerUnavailable("Wan 2.2 video LoRA training needs 24 GB per musubi-tuner's documentation; train an image LoRA (Z-Image / Qwen-Image) on this card instead.")
        dit, vae, text_encoder = request.weights.get("dit", ""), request.weights.get("vae", ""), request.weights.get("text_encoder", "")
        missing = [name for name, value in (("dit", dit), ("vae", vae), ("text_encoder", text_encoder)) if not value or not Path(value).exists()]
        if missing:
            raise TrainerUnavailable(f"Weights missing for {request.target}: {', '.join(missing)}. Set them in Train → Trainer settings (docs/TRAINING.md).")
        toml = self.write_dataset_toml(request, work_dir)
        src = self.upstream_dir / "src" / "musubi_tuner"
        py = str(self.python)
        common = ["--dataset_config", str(toml), "--vae", vae]
        # Only the Wan latent cacher has --vae_cache_cpu; Z-Image's refused it (2026-10-02).
        cache_latents = [py, str(src / scripts["cache_latents"]), *common, *(["--vae_cache_cpu"] if request.target == "wan22" else [])]
        cache_text = [py, str(src / scripts["cache_text"]), "--dataset_config", str(toml), "--text_encoder", text_encoder, scripts["te_flag"], "--batch_size", "4"]
        train = [
            py, "-m", "accelerate.commands.launch", "--num_cpu_threads_per_process", "1", "--mixed_precision", "bf16",
            str(src / scripts["train"]),
            "--dit", dit, "--vae", vae, "--text_encoder", text_encoder,
            "--dataset_config", str(toml), "--sdpa", "--mixed_precision", "bf16",
            "--optimizer_type", "adamw8bit", "--learning_rate", str(request.learning_rate),
            "--gradient_checkpointing", "--max_data_loader_n_workers", "2", "--persistent_data_loader_workers",
            "--network_module", scripts["network"], "--network_dim", str(request.rank), "--network_alpha", str(max(1, request.rank // 2)),
            "--timestep_sampling", "shift", "--discrete_flow_shift", "3.0",
            "--max_train_steps", str(request.steps), "--save_every_n_steps", str(request.save_every),
            "--seed", str(request.seed), "--output_dir", str(work_dir), "--output_name", request.output_name,
        ]
        if request.fp8:
            train += ["--fp8_base", "--fp8_scaled", scripts["te_flag"]]
        if request.target in ("z_image", "qwen_image"):
            # Chunked attention: same numbers, ~9% faster and 700 MB less VRAM
            # (MEASURED 2026-10-02, Z-Image 512 px batch 2: 4.40 vs 4.84 s/step).
            train += ["--split_attn"]
        if request.blocks_to_swap > 0:
            train += ["--blocks_to_swap", str(request.blocks_to_swap)]
        if request.resume_from:
            train += ["--network_weights", request.resume_from]
        if request.sample_prompts and request.sample_every > 0:
            prompts = work_dir / "sample_prompts.txt"
            prompts.write_text("\n".join(request.sample_prompts) + "\n", encoding="utf-8")
            train += ["--sample_prompts", str(prompts), "--sample_every_n_steps", str(request.sample_every), "--sample_at_first"]
        return [cache_latents, cache_text, train]


class AiToolkitTrainer(SubprocessTrainer):
    """ostris/ai-toolkit: one YAML config, `python run.py config.yaml`.

    Keys per the upstream example configs (`network.type: lora`, `linear`,
    `train.steps`, `model.quantize` + `low_vram`, `trigger_word`,
    `datasets[].folder_path/resolution`, `save.save_every`, `sample.sample_every`).
    """

    _MODELS: dict[str, dict[str, Any]] = {
        "z_image": {"name_or_path": "Tongyi-MAI/Z-Image-Turbo", "arch": "zimage"},
        "flux": {"name_or_path": "black-forest-labs/FLUX.2-klein-base-4B", "arch": "flux2"},
        "qwen_image": {"name_or_path": "Qwen/Qwen-Image", "arch": "qwen_image"},
    }

    def __init__(self, backend_root: Path) -> None:
        super().__init__(backend_root, "ai-toolkit")

    def write_config(self, request: TrainingRequest, work_dir: Path) -> Path:
        model = self._MODELS.get(request.target)
        if model is None:
            raise TrainerUnavailable(f"ai-toolkit has no recipe for target {request.target}")
        name_or_path = request.weights.get("name_or_path") or str(model["name_or_path"])
        buckets = ", ".join(str(b) for b in (request.buckets or [request.resolution]))
        samples = "\n".join(f'          - "{p}"' for p in request.sample_prompts) or '          - "[trigger], a portrait, studio light"'
        text = f"""---
job: extension
config:
  name: "{request.output_name}"
  process:
    - type: 'sd_trainer'
      training_folder: "{work_dir.as_posix()}"
      device: cuda:0
      trigger_word: "{request.trigger}"
      network:
        type: "lora"
        linear: {request.rank}
        linear_alpha: {request.rank}
      save:
        dtype: float16
        save_every: {request.save_every}
        max_step_saves_to_keep: 4
      datasets:
        - folder_path: "{Path(request.dataset_dir).as_posix()}"
          caption_ext: "txt"
          caption_dropout_rate: 0.05
          shuffle_tokens: false
          cache_latents_to_disk: true
          resolution: [ {buckets} ]
      train:
        batch_size: {max(1, request.batch_size)}
        steps: {request.steps}
        gradient_accumulation_steps: 1
        train_unet: true
        train_text_encoder: false
        gradient_checkpointing: true
        noise_scheduler: "flowmatch"
        optimizer: "adamw8bit"
        lr: {request.learning_rate}
        dtype: bf16
      model:
        name_or_path: "{name_or_path}"
        arch: "{model["arch"]}"
        quantize: {"true" if request.fp8 else "false"}
        low_vram: true
      sample:
        sampler: "flowmatch"
        sample_every: {request.sample_every}
        width: {request.resolution}
        height: {request.resolution}
        prompts:
{samples}
        seed: {request.seed}
        walk_seed: true
        guidance_scale: 4
        sample_steps: 8
meta:
  name: "[name]"
  version: '1.0'
"""
        path = work_dir / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def lora_output(self, request: TrainingRequest) -> Path:
        return Path(request.output_dir) / request.output_name / f"{request.output_name}.safetensors"

    def build_command(self, request: TrainingRequest, work_dir: Path) -> list[list[str]]:
        config = self.write_config(request, work_dir)
        command = [str(self.python), str(self.upstream_dir / "run.py"), str(config)]
        if request.resume_from:
            command += ["--recover"]
        return [command]


def select_trainer(backend_root: Path, trainer_id: str) -> SubprocessTrainer:
    if trainer_id == "musubi":
        return MusubiTrainer(backend_root)
    if trainer_id == "ai-toolkit":
        return AiToolkitTrainer(backend_root)
    spec = trainer_for(trainer_id)
    if spec is not None:
        raise TrainerUnavailable(f"{spec.name} cannot run on this machine: {spec.notes}")
    raise TrainerUnavailable(f"Unknown trainer {trainer_id}")


def python_for_scripts() -> str:
    return sys.executable


def wait_briefly() -> None:
    time.sleep(0.01)
