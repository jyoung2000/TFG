"""A trainer that pretends: steps on demand, a falling loss curve, sample
PNGs, checkpoints and a LoRA file — enough to test every handler path."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from services.trainer.trainer import (
    CancelledCallback,
    ProgressCallback,
    TrainerUnavailable,
    TrainingOutcome,
    TrainingProgress,
    TrainingRequest,
)


class FakeTrainer:
    id = "fake"

    def __init__(self) -> None:
        self.requests: list[TrainingRequest] = []
        self.installed = True
        self.fail_at_step: int | None = None
        self.cancel_after: int | None = None
        #: Steps reported per run (progress is reported every step).
        self.step_stride = 1

    def available(self) -> tuple[bool, str]:
        return (True, "fake trainer ready") if self.installed else (False, "fake trainer not installed: run scripts/ensure-trainer.sh fake")

    def train(self, request: TrainingRequest, on_progress: ProgressCallback, is_cancelled: CancelledCallback) -> TrainingOutcome:
        if not self.installed:
            raise TrainerUnavailable("fake trainer not installed")
        self.requests.append(request)
        out = Path(request.output_dir)
        (out / "samples").mkdir(parents=True, exist_ok=True)
        start = 0
        if request.resume_from and Path(request.resume_from).is_file():
            try:
                start = int(Path(request.resume_from).stem.rsplit("-", 1)[-1])
            except ValueError:
                start = 0
        samples: list[str] = []
        last_loss = None
        step = start
        while step < request.steps:
            step = min(request.steps, step + max(1, self.step_stride))
            loss = round(0.6 * (1.0 - step / request.steps) + 0.05, 4)
            last_loss = loss
            fresh: list[str] = []
            checkpoint = ""
            if request.sample_every and step % request.sample_every == 0:
                sample = out / "samples" / f"sample-{step:05d}.png"
                Image.new("RGB", (64, 64), (step % 255, 120, 200)).save(sample)
                fresh.append(str(sample))
                samples.append(str(sample))
            if request.save_every and step % request.save_every == 0 and step < request.steps:
                ckpt = out / f"{request.output_name}-{step:06d}.safetensors"
                ckpt.write_bytes(b"fake-lora-checkpoint")
                checkpoint = str(ckpt)
            on_progress(TrainingProgress(step=step, total=request.steps, loss=loss, eta_seconds=float(request.steps - step) * 0.5, phase="training", samples=fresh, checkpoint=checkpoint))
            if self.fail_at_step is not None and step >= self.fail_at_step:
                return TrainingOutcome(status="failed", steps_done=step, final_loss=loss, log_tail="CUDA out of memory (fake)")
            if is_cancelled() or (self.cancel_after is not None and step >= self.cancel_after):
                return TrainingOutcome(status="cancelled", steps_done=step, final_loss=loss, samples=samples)
        lora = out / f"{request.output_name}.safetensors"
        lora.write_bytes(b"fake-lora:" + request.output_name.encode())
        return TrainingOutcome(status="complete", lora_path=str(lora), steps_done=request.steps, final_loss=last_loss, samples=samples, log_tail="done")
