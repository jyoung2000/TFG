from __future__ import annotations

from pathlib import Path

from services.wangp_bridge import WanGPBridge


def _make_bridge(*, image_model_type: str = "z_image") -> WanGPBridge:
    return WanGPBridge(
        enabled=True,
        root=Path(r"E:\ML\w20"),
        python_executable=None,
        config_dir=Path(r"E:\tmp\wangp_bridge"),
        output_dir=Path(r"E:\tmp\wangp_outputs"),
        video_model_type="ltx2_22B_distilled",
        image_model_type=image_model_type,
        camera_motion_prompts={},
        extra_args=(),
    )


def test_qwen_image_resolution_uses_native_16_9_preset() -> None:
    bridge = _make_bridge(image_model_type="qwen_image_20B")

    assert bridge._map_image_resolution(1920, 1072) == (1664, 928)


def test_qwen_image_resolution_falls_back_to_nearest_supported_aspect() -> None:
    bridge = _make_bridge(image_model_type="qwen_image_20B")

    assert bridge._map_image_resolution(2520, 1080) == (1664, 928)


def test_non_qwen_image_resolution_is_left_unchanged() -> None:
    bridge = _make_bridge(image_model_type="z_image")

    assert bridge._map_image_resolution(1920, 1072) == (1920, 1072)


def test_z_image_uses_eight_step_floor() -> None:
    bridge = _make_bridge(image_model_type="z_image")

    assert bridge._normalize_image_steps(4) == 8
    assert bridge._normalize_image_steps(8) == 8
    assert bridge._normalize_image_steps(12) == 12


def test_ltx2_video_uses_full_video_length_as_sliding_window_size() -> None:
    bridge = _make_bridge()
    captured: dict[str, object] = {}

    def fake_run_manifest(*, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[no-untyped-def]
        captured["settings"] = manifest[0]["params"]
        return ["E:/tmp/out.mp4"]

    bridge._run_manifest = fake_run_manifest  # type: ignore[method-assign]

    output = bridge.generate_video(
        prompt="A person walking in the rain",
        resolution_label="1080p",
        aspect_ratio="16:9",
        duration_seconds=6,
        fps=24,
        steps=8,
        seed=123,
        camera_motion="none",
        negative_prompt="",
        image_path=None,
        audio_path=None,
        on_progress=lambda *_args: None,
        is_cancelled=lambda: False,
    )

    assert output == "E:/tmp/out.mp4"
    assert captured["settings"]["video_length"] == 145
    assert captured["settings"]["sliding_window_size"] == 145


def test_bridge_prefers_root_wgp_config_when_present(tmp_path: Path) -> None:
    root = tmp_path / "wangp-root"
    root.mkdir()
    root_config = root / "wgp_config.json"
    root_config.write_text("{}", encoding="utf-8")

    bridge = WanGPBridge(
        enabled=True,
        root=root,
        python_executable=None,
        config_dir=tmp_path / "wangp_bridge",
        output_dir=tmp_path / "wangp_outputs",
        video_model_type="ltx2_22B_distilled",
        image_model_type="z_image",
        camera_motion_prompts={},
        extra_args=(),
    )

    assert bridge._resolve_session_config_path() == root_config


def test_bridge_falls_back_to_bridge_config_when_root_config_missing(tmp_path: Path) -> None:
    root = tmp_path / "wangp-root"
    root.mkdir()
    config_dir = tmp_path / "wangp_bridge"

    bridge = WanGPBridge(
        enabled=True,
        root=root,
        python_executable=None,
        config_dir=config_dir,
        output_dir=tmp_path / "wangp_outputs",
        video_model_type="ltx2_22B_distilled",
        image_model_type="z_image",
        camera_motion_prompts={},
        extra_args=(),
    )

    assert bridge._resolve_session_config_path() == config_dir / "wgp_config.json"


class TestImg2ImgFromAReference:
    """The reproduce loop's converging rung: start from the reference's pixels.

    Text-to-image cannot converge on one specific photograph - four local
    models measured 0.70-0.83 on the round-6 references and plateaued there.
    WanGP's FLUX.2 does img2img through its "Masked Denoising" inpaint mode:
    `image_mode` 2, `video_prompt_type` "VAG" (control image + mask +
    guide-denoising), the reference as `image_guide`, an all-white
    `image_mask`, and `denoising_strength` < 1 (wgp.py:1391-1415,
    models/flux/sampling.py:629-639). Z-Image has no such path.
    """

    def _bridge(self, tmp_path: Path):
        from tests.fakes.fake_wangp_bridge import FakeWanGPBridge

        return FakeWanGPBridge(tmp_path / "out")

    def test_flux2_img2img_settings(self, tmp_path: Path) -> None:
        from PIL import Image

        reference = tmp_path / "reference.png"
        Image.new("RGB", (96, 48), (10, 20, 30)).save(reference)
        bridge = self._bridge(tmp_path)
        bridge.generate_images(
            prompt="p", width=96, height=48, num_steps=4, num_images=1, seed=3,
            on_progress=lambda *a: None, is_cancelled=lambda: False,
            model_type="flux2_klein_4b", init_image=str(reference), denoise_strength=0.3,
        )
        params = bridge.manifests[-1][0]["params"]
        assert isinstance(params, dict)
        assert params["image_mode"] == 2
        assert params["video_prompt_type"] == "VAG"
        assert params["model_mode"] == 0
        assert params["image_guide"] == str(reference.resolve())
        assert params["denoising_strength"] == 0.3
        assert params["masking_strength"] == 1.0
        with Image.open(str(params["image_mask"])) as mask:
            assert mask.size == (96, 48)
            assert mask.convert("L").getextrema() == (255, 255), "the whole frame is regenerated"
        # Denoising strength only has resolution with enough steps: 4 steps
        # at 0.3 would start at step int(4*0.7)=2 - one step of change.
        assert params["num_inference_steps"] >= 20

    def test_a_model_without_img2img_is_refused_by_name(self, tmp_path: Path) -> None:
        import pytest
        from PIL import Image

        reference = tmp_path / "reference.png"
        Image.new("RGB", (32, 32)).save(reference)
        bridge = self._bridge(tmp_path)
        assert bridge.supports_img2img("flux2_klein_4b") and not bridge.supports_img2img("z_image")
        with pytest.raises(RuntimeError, match="z_image"):
            bridge.generate_images(
                prompt="p", width=32, height=32, num_steps=8, num_images=1, seed=1,
                on_progress=lambda *a: None, is_cancelled=lambda: False,
                model_type="z_image", init_image=str(reference), denoise_strength=0.5,
            )
        assert bridge.manifests == [], "nothing reached WanGP"
