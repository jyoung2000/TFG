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


def _vace_settings_for(*, control_video_path: str | None, end_frame_path: str | None) -> dict[str, object]:
    bridge = _make_bridge()
    captured: dict[str, object] = {}

    def fake_run_manifest(*, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[no-untyped-def]
        captured["settings"] = manifest[0]["params"]
        return ["E:/tmp/out.mp4"]

    bridge._run_manifest = fake_run_manifest  # type: ignore[method-assign]
    bridge.generate_video(
        prompt="two people kissing", resolution_label="540p", aspect_ratio="16:9", duration_seconds=10, fps=24, steps=8, seed=7,
        camera_motion="none", negative_prompt="", image_path="E:/tmp/first.png", audio_path=None, on_progress=lambda *_a: None,
        is_cancelled=lambda: False, control_video_path=control_video_path, end_frame_path=end_frame_path, control_strength=1.0,
        model_type="vace_1.3B",
    )
    return captured["settings"]  # type: ignore[return-value]


def test_a_vace_render_with_a_guide_video_skips_cfg_and_takes_six_steps() -> None:
    """MEASURED (RTX 4070, the reference clip's 10 s shot, SSIM against the
    source): CFG 5 / 8 steps 0.971 in ~390 s; CFG 1 / 6 steps 0.982 in 206 s;
    CFG 1 / 4 steps 0.981 in 166 s. With a guide video the unconditional
    pass doubled the cost and pulled the take away from the source."""
    settings = _vace_settings_for(control_video_path="E:/tmp/guide.mp4", end_frame_path="E:/tmp/last.png")
    assert settings["guidance_scale"] == 1.0
    assert settings["num_inference_steps"] == 6


def test_a_vace_render_without_a_guide_video_keeps_cfg() -> None:
    settings = _vace_settings_for(control_video_path=None, end_frame_path="E:/tmp/last.png")
    assert "guidance_scale" not in settings
    assert settings["num_inference_steps"] == 8


def _image_settings(**kwargs: object) -> dict[str, object]:
    bridge = _make_bridge(image_model_type="flux2_klein_4b")
    captured: dict[str, object] = {}

    def fake_run_manifest(*, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[no-untyped-def]
        captured["settings"] = manifest[0]["params"]
        return ["E:/tmp/out.png"]

    bridge._run_manifest = fake_run_manifest  # type: ignore[method-assign]
    bridge.generate_images(prompt="the woman, seen in profile", width=768, height=1024, num_steps=4, num_images=1, seed=7,
                           on_progress=lambda *_a: None, is_cancelled=lambda: False, **kwargs)  # type: ignore[arg-type]
    return captured["settings"]  # type: ignore[return-value]


def test_reference_images_go_to_flux2_klein_as_ordered_image_refs() -> None:
    """Asked 2026-10-01: multi-angle shots good enough to train a LoRA. FLUX.2
    Klein (installed) composes from ordered reference images: "KI" = the first
    image is the scene (the composer's posed mannequin at an angle), the next
    ones the people (the character's reference)."""
    settings = _image_settings(reference_images=["E:/tmp/guide.png", "E:/tmp/hero.png"], reference_mode="KI")
    assert settings["video_prompt_type"] == "KI"
    assert [Path(p).name for p in settings["image_refs"]] == ["guide.png", "hero.png"]  # type: ignore[union-attr]
    assert settings["image_mode"] == 1


def test_a_model_without_reference_images_refuses_them() -> None:
    bridge = _make_bridge(image_model_type="z_image")
    bridge._run_manifest = lambda **_k: ["E:/tmp/out.png"]  # type: ignore[method-assign]
    import pytest

    with pytest.raises(RuntimeError, match="reference images"):
        bridge.generate_images(prompt="x", width=512, height=512, num_steps=8, num_images=1, seed=1, on_progress=lambda *_a: None,
                               is_cancelled=lambda: False, reference_images=["E:/tmp/hero.png"])


def test_qwen_edit_2511_renders_the_angles_with_its_own_steps_and_sizes() -> None:
    """User, 2026-10-04: Qwen-Image-Edit-2511 with the Multiple-Angles LoRA as the
    default for multiple angles. It composes from reference images like FLUX.2,
    but it is not a few-step model: the app's default of 4 steps would be noise,
    and its resolution presets apply to the model rendering, not to the app's
    configured default image model (z_image here)."""
    bridge = _make_bridge(image_model_type="z_image")
    captured: dict[str, object] = {}

    def fake_run_manifest(*, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[no-untyped-def]
        captured["settings"] = manifest[0]["params"]
        return ["E:/tmp/out.png"]

    bridge._run_manifest = fake_run_manifest  # type: ignore[method-assign]
    bridge.generate_images(prompt="<sks> left side view eye-level shot wide shot", width=768, height=1024, num_steps=4, num_images=1, seed=7,
                           on_progress=lambda *_a: None, is_cancelled=lambda: False,
                           model_type="qwen_image_edit_plus2_20B", reference_images=["E:/tmp/hero.png"], reference_mode="KI")  # type: ignore[arg-type]
    settings = captured["settings"]
    assert isinstance(settings, dict)
    assert settings["model_type"] == "qwen_image_edit_plus2_20B"
    assert settings["video_prompt_type"] == "KI" and [Path(p).name for p in settings["image_refs"]] == ["hero.png"]
    assert settings["num_inference_steps"] >= 20
    assert settings["resolution"] != "768x1024", "a Qwen native preset of the same shape"
    width, height = (int(v) for v in str(settings["resolution"]).split("x"))
    assert abs(width / height - 768 / 1024) < 0.05


def test_int8_kernels_on_auto_are_pinned_to_triton(tmp_path: Path) -> None:
    """Live QA 2026-10-04: WanGP's "auto" INT8 kernels chose Comfy Kitchen after a
    256x256 probe that never reaches its cuBLASLt path, and the first real Qwen-Image
    text-encoder matmul failed ("cuBLASLt 13.x library not found (requires CUDA
    13+)"). Triton works and measured 12.4 s vs 14.0 s warm on Z-Image."""
    import json

    from services.wangp_bridge import pin_int8_kernels

    config = tmp_path / "wgp_config.json"
    config.write_text(json.dumps({"int8_kernels": "auto", "profile": 4}), encoding="utf-8")
    assert pin_int8_kernels(config) is True
    assert json.loads(config.read_text(encoding="utf-8")) == {"int8_kernels": "triton", "profile": 4}
    for chosen in ("disabled", "kitchen", "triton"):
        config.write_text(json.dumps({"int8_kernels": chosen}), encoding="utf-8")
        assert pin_int8_kernels(config) is False and json.loads(config.read_text(encoding="utf-8"))["int8_kernels"] == chosen, "a deliberate choice is kept"
    assert pin_int8_kernels(tmp_path / "missing.json") is False
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert pin_int8_kernels(tmp_path / "broken.json") is False



def test_qwen_edit_with_the_lightning_lora_renders_in_8_steps_without_cfg() -> None:
    """MEASURED 2026-10-04 on the RTX 4070: Qwen-Image-Edit-2511 int8 at 30 steps and
    CFG 4 came back solid black (NaN, every pixel 0) after ~10 minutes; with the
    Lightning 8-step LoRA at CFG 1 the same angle rendered cleanly in 148 s."""
    bridge = _make_bridge(image_model_type="z_image")
    captured: dict[str, object] = {}

    def fake_run_manifest(*, manifest, media_suffixes, on_progress, is_cancelled):  # type: ignore[no-untyped-def]
        captured["settings"] = manifest[0]["params"]
        return ["E:/tmp/out.png"]

    bridge._run_manifest = fake_run_manifest  # type: ignore[method-assign]
    loras = [("E:/loras/qwen_image_edit/angles.safetensors", 0.9),
             ("E:/loras/qwen_image_edit/Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", 1.0)]
    bridge.generate_images(prompt="<sks> back view eye-level shot wide shot", width=768, height=1024, num_steps=4, num_images=1, seed=7,
                           on_progress=lambda *_a: None, is_cancelled=lambda: False, loras=loras,
                           model_type="qwen_image_edit_plus2_20B", reference_images=["E:/tmp/hero.png"], reference_mode="KI")  # type: ignore[arg-type]
    settings = captured["settings"]
    assert isinstance(settings, dict)
    assert settings["num_inference_steps"] == 8 and settings["guidance_scale"] == 1.0
