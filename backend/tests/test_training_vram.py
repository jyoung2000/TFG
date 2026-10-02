"""Training VRAM follows block swap.

Found 2026-10-02 (training a character LoRA on a 12 GB card with a browser,
Discord and Steam open): Start refused - "9.8 GB free, 10.3 GB needed" - and
nothing the user could set changed that. The estimate was a fixed number per
target, though Block swap (musubi's --blocks_to_swap) is exactly how a small
card fits: each swapped block's fp8 weights leave the GPU. Z-Image: 12.3 GB of
bf16 DiT = ~6.2 GB fp8 over 30 blocks = ~205 MB each; musubi swaps at most 28.
"""

from __future__ import annotations

from pathlib import Path

from film.training_presets import default_config, estimate_vram_mb, fits_machine
from handlers.training_handler import _config_problem


def test_more_block_swap_needs_less_vram() -> None:
    base = default_config("z_image", "character")
    more = base.model_copy(update={"blocks_to_swap": 20})
    assert estimate_vram_mb(more) < estimate_vram_mb(base) - 2000
    assert estimate_vram_mb(base) == base.estimated_vram_mb


def test_less_swap_than_the_preset_never_lowers_the_estimate() -> None:
    base = default_config("z_image", "character")
    assert estimate_vram_mb(base.model_copy(update={"blocks_to_swap": 0})) >= estimate_vram_mb(base)


def test_a_client_number_cannot_understate_it() -> None:
    config = default_config("z_image", "character").model_copy(update={"estimated_vram_mb": 1})
    assert estimate_vram_mb(config) == default_config("z_image", "character").estimated_vram_mb


def test_video_targets_are_unchanged_by_block_swap() -> None:
    wan = default_config("wan22", "character")
    assert not fits_machine(wan.model_copy(update={"blocks_to_swap": 40}))[0]


def test_swapping_more_blocks_than_the_model_has_is_refused() -> None:
    config = default_config("z_image", "character").model_copy(update={"blocks_to_swap": 29})
    assert "28" in _config_problem(config)


def test_a_refused_start_says_to_raise_block_swap(client, tmp_path: Path, fake_services) -> None:
    from tests.test_training import _dataset

    fake_services.trainer.required_weights = ()
    dataset = _dataset(client, tmp_path, count=4)
    fake_services.nvml.used_mb = fake_services.nvml.total_mb - 4000  # 4 GB free
    config = default_config("z_image", "character").model_dump()
    run = client.post("/api/training/runs", json={"dataset_id": dataset["id"], "config": config}).json()
    detail = client.get(f"/api/training/runs/{run['id']}").json()
    assert detail["status"] == "failed" and "Block swap" in detail["error"], detail


def test_a_character_lora_trains_at_512_in_about_half_an_hour() -> None:
    """MEASURED 2026-10-02 (RTX 4070, musubi Z-Image, fp8, gradient checkpointing):
    4.9 s/step at 768 px (Raven's 1100-step run took 108 min), 2.3 s/step at 512 px.
    Block swap barely moved the speed (4.7 s at 4 blocks, 4.9 at 16)."""
    config = default_config("z_image", "character", image_count=26)
    assert config.resolution == 512 and config.buckets == [512]
    assert config.steps <= 840, config.steps


def test_the_estimate_matches_what_training_used() -> None:
    """MEASURED: ~7.2 GB at 768 px, 8 swapped blocks; 4 -> 16 blocks freed ~2.0 GB.
    The old 10.5 GB figure refused runs that fit beside a browser."""
    base = default_config("z_image", "character")
    assert 8000 <= estimate_vram_mb(base) <= 9000
