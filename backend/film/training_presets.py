"""12 GB-safe training presets per target (documented in docs/TRAINING.md).

Estimates come from the upstream docs recorded in session-notes: musubi
"12 GB or more for image training" with fp8 + block swap; ai-toolkit
quantize + low_vram. Anything above `MACHINE_VRAM_MB` is refused before a
subprocess starts, so no default can OOM the card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from film.training_models import DatasetPreset, TrainingConfig
from services.trainer.catalog import MACHINE_VRAM_MB, trainers_for_target


@dataclass(frozen=True)
class _Base:
    trainer: str
    rank: int
    steps: int
    resolution: int
    buckets: tuple[int, ...]
    blocks_to_swap: int
    estimated_vram_mb: int


@dataclass(frozen=True)
class _Tweak:
    rank_delta: int
    steps_scale: float
    learning_rate: float


_BASE: dict[str, _Base] = {
    # MEASURED 2026-10-02 (RTX 4070, fp8, gradient checkpointing): 4.9 s/step at
    # 768 px, 2.3 s/step at 512 px; ~7.2 GB in use at 768 px with 8 blocks swapped
    # (8.6 GB here leaves a margin; the old 10.5 GB refused runs that fit).
    "z_image": _Base("musubi", 16, 600, 512, (512,), 8, 8600),
    "qwen_image": _Base("musubi", 16, 800, 768, (512, 768), 20, 11200),
    "flux": _Base("ai-toolkit", 16, 1000, 768, (512, 768, 1024), 0, 11500),
    "wan22": _Base("musubi", 16, 800, 512, (384, 512), 30, 24000),
    "ltx2": _Base("ltx-trainer", 32, 1000, 512, (512,), 0, 32768),
}

@dataclass(frozen=True)
class _Swap:
    #: VRAM one swapped block frees (its fp8 weights) and how many musubi can swap.
    per_block_mb: int
    max_blocks: int


#: Block swap per target: Z-Image swapping 4 -> 16 blocks freed ~2.0 GB
#: (MEASURED 2026-10-02, ~170 MB a block; 12.3 GB bf16 DiT / 30 blocks in fp8
#: predicts ~205); zimage.md says at most 28 can be offloaded. Swap barely
#: changes the speed (4.7 s/step at 4 blocks, 4.9 at 16). Targets not listed
#: keep their fixed estimate.
_SWAP: dict[str, _Swap] = {
    "z_image": _Swap(170, 28),
}

TrainingSpeed = Literal["standard", "balanced", "fast"]

#: The fast character run (user, 2026-10-02: "an accurate LoRA in around 10
#: minutes"). MEASURED on Raven's face-matched set, same 6 prompts and seeds,
#: SFace vs. her photo: 840 steps / batch 1 / LR 1e-4 -> 0.421 in 35 min;
#: 200 steps / batch 1 / LR 3e-4 -> 0.259; 200 steps / batch 2 / LR 3e-4 ->
#: 0.380; 150 steps / batch 2 / LR 3e-4 -> 0.355 in 10.0 min; 150 steps /
#: batch 2 / LR 4e-4 -> 0.436 in 9.9 min. A bigger batch lets the learning
#: rate rise; the rate alone does not (batch 1 at 3e-4 gave 0.259). Only
#: Z-Image is measured; other targets train at standard speed.
_FAST: dict[str, tuple[int, int, float]] = {
    # target: (batch_size, steps, learning_rate)
    "z_image": (2, 150, 4e-4),
}
#: Balanced: the same recipe with twice the steps. At 150 steps the face score
#: swung 0.33-0.44 between runs and the outfit sometimes drifted (bodysuits
#: from the trigger alone); the learning curve never plateaued, so steps are
#: the dependable lever. MEASURED: see test_training_vram.
_BALANCED: dict[str, tuple[int, int, float]] = {
    "z_image": (2, 300, 4e-4),
}

#: VRAM each extra image in a batch costs (MEASURED: batch 1 peaked at 7.7 GB,
#: batch 2 at 9.3 GB of GPU use at 512 px).
_PER_EXTRA_BATCH_MB: dict[str, int] = {"z_image": 1650}

_PRESET_TWEAKS: dict[DatasetPreset, _Tweak] = {
    "character": _Tweak(0, 1.0, 1e-4),
    "style": _Tweak(8, 1.5, 8e-5),
    "object": _Tweak(-4, 0.8, 1.2e-4),
}


def default_config(target: str, preset: DatasetPreset, *, image_count: int = 12, speed: TrainingSpeed = "standard") -> TrainingConfig:
    base = _BASE.get(target, _BASE["z_image"])
    tweak = _PRESET_TWEAKS[preset]
    rank = max(4, base.rank + tweak.rank_delta)
    fast = _FAST.get(target) if speed == "fast" else _BALANCED.get(target) if speed == "balanced" else None
    if fast is not None:
        batch_size, fast_steps, learning_rate = fast
        config = TrainingConfig(
            target=target, trainer=base.trainer, rank=rank, steps=fast_steps, learning_rate=learning_rate, batch_size=batch_size,
            resolution=base.resolution, buckets=list(base.buckets), blocks_to_swap=base.blocks_to_swap, fp8=True,
            save_every=max(50, fast_steps // 2), sample_every=max(50, fast_steps // 2), estimated_vram_mb=base.estimated_vram_mb,
        )
        return config.model_copy(update={"estimated_vram_mb": estimate_vram_mb(config)})
    steps = int(base.steps * tweak.steps_scale)
    # More images need more steps to see each a sensible number of times.
    # A character's look is learned in a few hundred steps once the captions leave it
    # to the trigger; up to 2x for 24+ images made Raven's run 1100 steps (108 min).
    cap = 1.4 if preset == "character" else 2.0
    steps = max(200, min(3000, int(steps * max(0.6, min(cap, image_count / 12)))))
    buckets = list(base.buckets)
    return TrainingConfig(
        target=target,
        trainer=base.trainer,
        rank=rank,
        steps=steps,
        learning_rate=tweak.learning_rate,
        resolution=base.resolution,
        buckets=buckets,
        blocks_to_swap=base.blocks_to_swap,
        fp8=True,
        save_every=max(50, steps // 6),
        sample_every=max(50, steps // 6),
        estimated_vram_mb=base.estimated_vram_mb,
    )


def estimate_vram_mb(config: TrainingConfig) -> int:
    """The VRAM this config costs according to *our* table, not the caller's.

    `TrainingConfig.estimated_vram_mb` travels in the request body, so a hand-written
    config (an MCP tool call, a curl, a stale UI payload) can put any number there;
    it is never read. The estimate moves only with what really changes the cost:
    each block swapped beyond the preset frees its weights, each one fewer adds them
    back (QA 2026-10-02: Block swap changed nothing, so a 12 GB card with a browser
    open could never start a Z-Image run).
    """
    base = _BASE.get(config.target, _BASE["z_image"])
    extra_batch = max(0, config.batch_size - 1) * _PER_EXTRA_BATCH_MB.get(config.target, 0)
    swap = _SWAP.get(config.target)
    if swap is None:
        return base.estimated_vram_mb + extra_batch
    blocks = min(max(config.blocks_to_swap, 0), swap.max_blocks)
    return base.estimated_vram_mb - (blocks - base.blocks_to_swap) * swap.per_block_mb + extra_batch


def max_blocks_to_swap(target: str) -> int | None:
    swap = _SWAP.get(target)
    return swap.max_blocks if swap else None


def fits_machine(config: TrainingConfig, total_mb: int | None = None) -> tuple[bool, str]:
    limit = total_mb or MACHINE_VRAM_MB
    needed = estimate_vram_mb(config)
    if needed > limit:
        names = ", ".join(t.name for t in trainers_for_target(config.target)) or "no trainer"
        return False, f"{config.target} LoRA training is estimated at {needed / 1024:.1f} GB ({names}); this machine has {limit / 1024:.0f} GB. Pick an image target (Z-Image, Qwen-Image, FLUX) or train elsewhere."
    return True, ""
