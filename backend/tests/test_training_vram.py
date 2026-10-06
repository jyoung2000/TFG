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


def test_the_fast_preset_trains_a_character_in_about_ten_minutes() -> None:
    """User, 2026-10-02: "generate an accurate Lora in around 10 minutes with
    similar quality". MEASURED on Raven's face-matched set (same 6 prompts and
    seeds, SFace vs. her photo): 840 steps at batch 1, LR 1e-4 -> 0.421 in 35
    min; 200 steps at batch 1, LR 3e-4 -> 0.259; 200 steps at batch 2, LR 3e-4
    -> 0.380; 150 steps at batch 2, LR 4e-4 -> 0.436 in 9.9 min. The batch lets
    the learning rate rise; the rate alone does not."""
    fast = default_config("z_image", "character", image_count=23, speed="fast")
    standard = default_config("z_image", "character", image_count=23)
    assert fast.batch_size == 2 and fast.steps == 150 and fast.learning_rate == 4e-4
    assert fast.resolution == 512
    assert standard.batch_size == 1 and standard.steps > fast.steps
    assert default_config("z_image", "character", image_count=23, speed="standard") == standard


def test_the_balanced_preset_is_the_fast_recipe_with_twice_the_steps() -> None:
    """MEASURED 2026-10-02 (same 6 prompts and seeds, SFace vs. the photo): at 150
    steps / batch 2 / LR 4e-4 the face score swung 0.33-0.44 between runs and the
    outfit sometimes drifted; the learning curve never plateaus, so the dependable
    lever is steps. Balanced doubles them for about twenty minutes."""
    fast = default_config("z_image", "character", speed="fast")
    balanced = default_config("z_image", "character", speed="balanced")
    assert balanced.batch_size == fast.batch_size and balanced.learning_rate == fast.learning_rate
    assert balanced.steps == 2 * fast.steps == 300


def test_the_balanced_preset_trains_at_384_px() -> None:
    """User, 2026-10-03: a consistent face and body "while only taking 0-15
    minutes". MEASURED (same 6 prompts and seeds, SFace vs. the photo), with face
    close-ups in the dataset and the full-body views twice per epoch: 300 steps
    at 384 px = 0.499 in 11.4 min of training (2.29 s/step) against 0.452 in
    18.7 min at 512 px without them. The close-ups are ~360-490 px crops, so
    512 px only upscaled them."""
    balanced = default_config("z_image", "character", speed="balanced")
    assert balanced.resolution == 384 and balanced.buckets == [384]
    assert balanced.steps == 300 and balanced.batch_size == 2
    assert default_config("z_image", "character", speed="fast").resolution == 512
    assert default_config("z_image", "character").resolution == 512


def test_the_estimate_counts_the_batch() -> None:
    """MEASURED: batch 1 peaked at 7.7 GB of GPU use, batch 2 at 9.3 GB."""
    one = default_config("z_image", "character")
    two = one.model_copy(update={"batch_size": 2})
    assert 1200 <= estimate_vram_mb(two) - estimate_vram_mb(one) <= 2000
    assert fits_machine(two)[0]


def test_suggest_offers_the_fast_preset(client, tmp_path: Path, fake_services) -> None:
    from tests.test_training import _dataset

    dataset = _dataset(client, tmp_path, count=4)
    fast = client.post("/api/training/suggest", json={"dataset_id": dataset["id"], "target": "z_image", "speed": "fast"}).json()
    standard = client.post("/api/training/suggest", json={"dataset_id": dataset["id"], "target": "z_image"}).json()
    assert fast["batch_size"] >= 2 and fast["steps"] < standard["steps"]
