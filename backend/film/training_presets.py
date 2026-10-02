"""12 GB-safe training presets per target (documented in docs/TRAINING.md).

Estimates come from the upstream docs recorded in session-notes: musubi
"12 GB or more for image training" with fp8 + block swap; ai-toolkit
quantize + low_vram. Anything above `MACHINE_VRAM_MB` is refused before a
subprocess starts, so no default can OOM the card.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    "z_image": _Base("musubi", 16, 600, 768, (512, 768), 8, 10500),
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


#: Block swap per target, from the model and musubi's docs: Z-Image's DiT is
#: 12.3 GB bf16 = ~6.2 GB fp8 over 30 blocks (~205 MB each); zimage.md says at
#: most 28 can be offloaded. Targets not listed keep their fixed estimate.
_SWAP: dict[str, _Swap] = {
    "z_image": _Swap(205, 28),
}

_PRESET_TWEAKS: dict[DatasetPreset, _Tweak] = {
    "character": _Tweak(0, 1.0, 1e-4),
    "style": _Tweak(8, 1.5, 8e-5),
    "object": _Tweak(-4, 0.8, 1.2e-4),
}


def default_config(target: str, preset: DatasetPreset, *, image_count: int = 12) -> TrainingConfig:
    base = _BASE.get(target, _BASE["z_image"])
    tweak = _PRESET_TWEAKS[preset]
    rank = max(4, base.rank + tweak.rank_delta)
    steps = int(base.steps * tweak.steps_scale)
    # More images need more steps to see each a sensible number of times.
    steps = max(200, min(3000, int(steps * max(0.6, min(2.0, image_count / 12)))))
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
    swap = _SWAP.get(config.target)
    if swap is None:
        return base.estimated_vram_mb
    blocks = min(max(config.blocks_to_swap, 0), swap.max_blocks)
    return base.estimated_vram_mb - (blocks - base.blocks_to_swap) * swap.per_block_mb


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
