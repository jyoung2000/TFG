"""Bridge LTX Desktop requests to WanGP's in-process session API."""

from __future__ import annotations

import importlib
import json
import logging
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, int | None, int | None], None]
CancelledCallback = Callable[[], bool]

_VIDEO_RESOLUTION_MAP: dict[str, dict[str, str]] = {
    "512p": {"16:9": "832x480", "9:16": "480x832"},
    "540p": {"16:9": "960x544", "9:16": "544x960"},
    "720p": {"16:9": "1280x704", "9:16": "704x1280"},
    "1080p": {"16:9": "1920x1088", "9:16": "1088x1920"},
    "1440p": {"16:9": "2560x1440", "9:16": "1440x2560"},
    "2160p": {"16:9": "3840x2176", "9:16": "2176x3840"},
}

_QWEN_IMAGE_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (1328, 1328),
    (1664, 928),
    (928, 1664),
    (1472, 1140),
    (1140, 1472),
)
#: ~1 MP sizes Qwen-Image-Edit renders as asked: LoRA dataset angles (1024x1024,
#: fitted to the photo's shape) and style-guide storyboard frames (16:9 / 9:16).
_QWEN_EDIT_EXACT: frozenset[tuple[int, int]] = frozenset({(1024, 1024), (1360, 768), (768, 1360)})
#: Wan 14B models (2.1 and 2.2) are 16 fps models; on the 12 GB card they render
#: at 720p at most (1080p would not fit their latents beside the weights).
_WAN_14B_PREFIXES: tuple[str, ...] = ("i2v", "t2v", "vace_14B")
#: Image models WanGP can run img2img with: FLUX.2's "Masked Denoising"
#: inpaint mode starts from the guide image's latents when
#: `denoising_strength` < 1 (models/flux/sampling.py:629-639). Z-Image has no
#: partial-denoise path, so it is absent on purpose.
IMG2IMG_MODEL_TYPES: tuple[str, ...] = ("flux2_klein_4b", "flux2_klein_9b", "flux2_dev")
#: Denoising strength is quantised to whole steps (first step =
#: int(steps * (1 - strength))), so the few-step default leaves low strengths
#: with no resolution at all.
IMG2IMG_MIN_STEPS = 24
#: Image models that compose from ordered reference images (`image_refs`):
#: FLUX.2 ("KI" = scene first, then people/objects; "I" = people/objects), and
#: Qwen-Image-Edit-2511 (same letters; WanGP models/qwen/qwen_handler.py) - last,
#: so the few-step FLUX.2 stays the fallback for general compositing. FLUX.1 USO Dev
#: (style transfer, film/style_transfer.py) is last: it only redraws in a style.
REFERENCE_IMAGE_MODEL_TYPES: tuple[str, ...] = ("flux2_klein_4b", "flux2_klein_9b", "flux2_dev", "qwen_image_edit_plus2_20B", "flux_dev_uso")
#: `video_prompt_type` letters of a reference render: "KI" scene then people (USO:
#: the content picture, then the style picture), "I" people only, "IJ" (USO) styles only.
REFERENCE_MODES: tuple[str, ...] = ("KI", "I", "IJ")
#: FLUX.1 Dev models (USO) are not few-step models: the app's default 4 steps is noise.
FLUX1_DEV_MIN_STEPS = 28
#: Qwen-Image-Edit is not a few-step model: the app's default of 4 steps is noise.
QWEN_EDIT_MIN_STEPS = 30
#: Qwen-Image-Edit with a Lightning LoRA: its distilled step count, CFG off.
QWEN_LIGHTNING_STEPS = 8
#: A VACE render with a guide video needs no CFG and few steps (see `_vace_settings`).
VACE_GUIDED_STEPS = 6

def pin_int8_kernels(config_path: Path) -> bool:
    """Use Triton when WanGP's INT8 math kernels are on "auto". WanGP's "auto"
    picks Comfy Kitchen after a 256x256 probe that never reaches Kitchen's
    cuBLASLt path; on this app's CUDA 12 torch the first real Qwen-Image
    text-encoder matmul then failed: "cuBLASLt 13.x library not found (requires
    CUDA 13+)" (2026-10-04). Triton worked and was faster on Z-Image (12.4 s vs
    14.0 s warm). A deliberate choice (disabled / kitchen / triton) is kept."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or cast(dict[str, object], data).get("int8_kernels", "auto") != "auto":
        return False
    config = cast(dict[str, object], data)
    config["int8_kernels"] = "triton"
    config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
    logger.info("WanGP INT8 kernels: auto -> triton (%s)", config_path)
    return True


def _with_default_attention(args: tuple[str, ...]) -> tuple[str, ...]:
    """`--attention auto` unless the caller chose one: WanGP's saved config can
    pin `sdpa` (it did on the installed app), and `auto` picks the fastest
    kernel actually installed (SageAttention ships with the app)."""
    if any(a == "--attention" or a.startswith("--attention=") for a in args):
        return args
    return (*args, "--attention", "auto")


_TQDM_PROGRESS_RE = re.compile(r"(?:(?P<label>.*?):\s+)?(?P<percent>\d{1,3})%\|[^|]*\|\s*(?P<current>\d+)/(?P<total>\d+)")


@dataclass(frozen=True)
class WanGPBridgeStatus:
    available: bool
    root: Path | None
    python_executable: str | None
    reason: str | None = None


class WanGPBridge:
    def __init__(
        self,
        *,
        enabled: bool,
        root: Path | None,
        python_executable: str | None,
        config_dir: Path,
        output_dir: Path,
        video_model_type: str,
        image_model_type: str,
        camera_motion_prompts: dict[str, str],
        extra_args: Iterable[str] = (),
    ) -> None:
        self._enabled = enabled
        self._root = root
        self._python = python_executable
        self._config_dir = config_dir
        self._output_dir = output_dir
        self._video_model_type = video_model_type
        self._image_model_type = image_model_type
        self._camera_motion_prompts = camera_motion_prompts
        self._extra_args = _with_default_attention(tuple(extra_args))
        self._session = None
        self._submitted_manifest_once = False
        self._session_lock = threading.Lock()

    def _resolve_session_config_path(self) -> Path:
        if self._root is not None:
            root_config = self._root / "wgp_config.json"
            if root_config.exists():
                return root_config
        return self._config_dir / "wgp_config.json"

    def get_status(self) -> WanGPBridgeStatus:
        if not self._enabled:
            return WanGPBridgeStatus(
                available=False,
                root=self._root,
                python_executable=self._python,
                reason="WanGP bridge is disabled",
            )

        if self._root is None:
            return WanGPBridgeStatus(
                available=False,
                root=None,
                python_executable=self._python,
                reason="WanGP root was not resolved",
            )

        wgp_path = self._root / "wgp.py"
        if not wgp_path.exists():
            return WanGPBridgeStatus(
                available=False,
                root=self._root,
                python_executable=self._python,
                reason=f"Missing {wgp_path}",
            )

        api_path = self._root / "shared" / "api.py"
        if not api_path.exists():
            return WanGPBridgeStatus(
                available=False,
                root=self._root,
                python_executable=self._python,
                reason=f"Missing {api_path}",
            )

        try:
            self._load_api_module()
        except Exception as exc:
            return WanGPBridgeStatus(
                available=False,
                root=self._root,
                python_executable=self._python,
                reason=f"Unable to import WanGP API: {exc}",
            )

        return WanGPBridgeStatus(
            available=True,
            root=self._root,
            python_executable=self._python,
        )

    def _checkpoint_roots(self) -> list[Path]:
        """Where WanGP finds weights: ``ckpts``, then the config's other
        ``checkpoints_paths`` (FLUX.1 USO lives on D: since 2026-10-05, C: is full)."""
        assert self._root is not None
        roots = [self._root / "ckpts"]
        listed: object = []
        try:
            config: object = json.loads(self._resolve_session_config_path().read_text(encoding="utf-8"))
            if isinstance(config, dict):
                listed = cast(dict[str, object], config).get("checkpoints_paths", [])
        except (OSError, ValueError):
            pass
        for entry in cast(list[object], listed) if isinstance(listed, list) else []:
            if isinstance(entry, str) and entry.strip() not in ("", "."):
                path = Path(entry.strip())
                path = path if path.is_absolute() else self._root / path
                if path.is_dir() and all(path.resolve() != r.resolve() for r in roots):
                    roots.append(path)
        return [r for r in roots if r.is_dir()]

    def list_model_definitions(self) -> list[dict[str, object]]:
        """Model definitions from the WanGP checkout (``defaults/*.json``) —
        the same files WanGP itself loads — plus whether their weights are
        already present under ``ckpts``. Never a hardcoded catalog."""
        if self._root is None:
            return []
        defaults = self._root / "defaults"
        if not defaults.is_dir():
            return []
        existing: set[str] = set()
        for ckpts in self._checkpoint_roots():
            try:
                existing |= {p.name for p in ckpts.rglob("*") if p.is_file()}
            except OSError:
                continue
        definitions: list[dict[str, object]] = []
        # A definition may name another model instead of listing files
        # (FastWan 5B: "URLs": "ti2v_2_2"); it uses that model's weights.
        own_urls: dict[str, list[str]] = {}
        for path in sorted(defaults.glob("*.json")):
            try:
                model = json.loads(path.read_text(encoding="utf-8")).get("model")
            except (OSError, ValueError, AttributeError):
                continue
            listed = cast(dict[str, object], model).get("URLs") if isinstance(model, dict) else None
            if isinstance(listed, list):
                own_urls[path.stem] = [str(u) for u in cast(list[object], listed) if isinstance(u, str)]
        for path in sorted(defaults.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            model = cast(dict[str, object], raw).get("model")
            if not isinstance(model, dict):
                continue
            model_dict = cast(dict[str, object], model)
            urls_raw = model_dict.get("URLs", [])
            urls: list[str] = []
            if isinstance(urls_raw, list):
                urls = [str(u) for u in cast(list[object], urls_raw) if isinstance(u, str)]
            elif isinstance(urls_raw, str):
                urls = own_urls.get(urls_raw, [urls_raw]) if not urls_raw.startswith("http") else [urls_raw]
            filenames = [u.rsplit("/", 1)[-1] for u in urls]
            installed = any(name in existing for name in filenames) if filenames else False
            architecture = str(model_dict.get("architecture", "") or "")
            definitions.append(
                {
                    "id": path.stem,
                    "name": str(model_dict.get("name", path.stem) or path.stem),
                    "architecture": architecture,
                    "description": str(model_dict.get("description", "") or ""),
                    "urls": urls,
                    "installed": installed,
                    "quantized_variants": sorted({"int8" if "int8" in n else "fp8" if "fp8" in n else "nvfp4" if "nvfp4" in n else "" for n in filenames} - {""}),
                    "default_resolution": str(cast(dict[str, object], raw).get("resolution", "") or ""),
                    "default_steps": cast(dict[str, object], raw).get("num_inference_steps"),
                }
            )
        return definitions

    def weights_installed(self, model_type: str) -> bool | None:
        """Whether the model's checkpoint files are present under ``ckpts``.

        ``None`` means "cannot tell" (no local checkout — the remote bridge —
        or an unknown model id) and callers must not refuse on it. ``False``
        is the state in which ``wgp.py`` would silently start a multi-GB
        checkpoint download the moment a render asks for the model; render
        handlers check this first and point at the Models tab instead, where
        the same download runs as an explicit job with progress and cancel."""
        if self._root is None:
            return None
        for definition in self.list_model_definitions():
            if str(definition.get("id", "")) == model_type:
                return bool(definition.get("installed", False))
        return None

    def generate_video(
        self,
        *,
        prompt: str,
        resolution_label: str,
        aspect_ratio: str,
        duration_seconds: int,
        fps: int,
        steps: int,
        seed: int | None,
        camera_motion: str,
        negative_prompt: str,
        image_path: str | None,
        audio_path: str | None,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
        control_video_path: str | None = None,
        depth_video_path: str | None = None,
        loras: Sequence[tuple[str, float]] = (),
        reference_images: Sequence[str] = (),
        end_frame_path: str | None = None,
        control_strength: float | None = None,
        model_type: str | None = None,
    ) -> str:
        chosen = (model_type or "").strip() or self._video_model_type
        wan_14b = chosen.startswith(_WAN_14B_PREFIXES)
        if wan_14b and resolution_label in ("1080p", "1440p", "2160p"):
            resolution_label = "720p"
        resolution = self._map_video_resolution(resolution_label, aspect_ratio)
        merged_prompt = prompt + self._camera_motion_prompts.get(camera_motion, "")
        if chosen.startswith("vace") or wan_14b:
            # A 16 fps model: at 24 fps a 10 s shot is 241 frames, at 16 it is 161.
            fps = 16
        video_length = self.compute_num_frames(duration_seconds, fps)

        settings: dict[str, object] = {
            "model_type": chosen,
            "prompt": merged_prompt,
            "resolution": resolution,
            "num_inference_steps": self._video_steps(chosen, steps),
            "video_length": video_length,
            "duration_seconds": duration_seconds,
            "force_fps": fps,
        }
        if chosen.startswith("ltx2_"):
            settings["sliding_window_size"] = video_length
        if negative_prompt.strip():
            settings["negative_prompt"] = negative_prompt.strip()
        if seed is not None:
            settings["seed"] = seed
        if image_path:
            settings["image_prompt_type"] = "S"
            settings["image_start"] = str(Path(image_path).resolve())
        if end_frame_path:
            # "E" = end frame (wgp.py image_end); combined with a start frame as "SE".
            settings["image_prompt_type"] = str(settings.get("image_prompt_type", "")) + "E"
            settings["image_end"] = str(Path(end_frame_path).resolve())
        self._apply_loras(settings, loras)
        if reference_images:
            settings["image_refs"] = [str(Path(p).resolve()) for p in reference_images]
            settings["video_prompt_type"] = str(settings.get("video_prompt_type", "")) + "I"
        if audio_path:
            settings["audio_prompt_type"] = "A"
            settings["audio_guide"] = str(Path(audio_path).resolve())
        # Control video (VACE / depth) from a Deliver export. `video_guide` +
        # `video_prompt_type` are WanGP's documented settings keys for a guide
        # video; the exact per-model semantics could not be verified in this
        # build (session-notes VF-011), so the depth pass is preferred when the
        # model type is a VACE/control variant and the clean pass otherwise.
        guide = depth_video_path if (depth_video_path and "vace" in self._video_model_type.lower()) else (control_video_path or depth_video_path)
        if guide:
            settings["video_prompt_type"] = str(settings.get("video_prompt_type", "")).replace("V", "") + "V"
            settings["video_guide"] = str(Path(guide).resolve())
            if control_strength is not None:
                # "G" makes the guide's strength count (wgp.py:1411-1415); for
                # LTX-2 "VG" is the raw control video and higher = closer to it.
                settings["video_prompt_type"] = str(settings["video_prompt_type"]).replace("G", "") + "G"
                settings["denoising_strength"] = round(min(1.0, max(0.0, control_strength)), 4)
        if chosen.startswith("vace"):
            self._vace_settings(settings, image_path, end_frame_path, video_length, aspect_ratio)

        outputs = self._run_manifest(
            manifest=[{"id": 1, "params": settings, "plugin_data": {}}],
            media_suffixes={".mp4", ".mov", ".mkv", ".avi", ".webm"},
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        if not outputs:
            raise RuntimeError("WanGP completed without producing a video")
        # A sliding-window render saves each window as it ends; the last file is the whole video.
        return outputs[-1]

    @staticmethod
    def _apply_loras(settings: dict[str, object], loras: Sequence[tuple[str, float]]) -> None:
        """`activated_loras` takes absolute paths (wgp.py `get_lora_URL` returns
        them unchanged) and `loras_multipliers` is the space-separated strengths."""
        chosen = [(path, mult) for path, mult in loras if path and Path(path).is_file()]
        if not chosen:
            return
        settings["activated_loras"] = [str(Path(path).resolve()) for path, _ in chosen]
        settings["loras_multipliers"] = " ".join(f"{mult:g}" for _, mult in chosen)

    def generate_images(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        num_steps: int,
        num_images: int,
        seed: int | None,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
        loras: Sequence[tuple[str, float]] = (),
        model_type: str | None = None,
        init_image: str | None = None,
        denoise_strength: float = 1.0,
        reference_images: Sequence[str] = (),
        reference_mode: str = "KI",
    ) -> list[str]:
        """Text-to-image, img2img from `init_image`, or a composition from
        ordered `reference_images` (FLUX.2: `reference_mode` "KI" puts the
        scene first, then the people; "I" is people/objects only)."""
        chosen = model_type or self._image_model_type
        if reference_images and chosen not in REFERENCE_IMAGE_MODEL_TYPES:
            raise RuntimeError(f"'{chosen}' cannot compose from reference images; that needs one of {', '.join(REFERENCE_IMAGE_MODEL_TYPES)}")
        if init_image and not self.supports_img2img(chosen):
            raise RuntimeError(f"'{chosen}' cannot render from a reference image; img2img needs one of {', '.join(IMG2IMG_MODEL_TYPES)}")
        mapped_width, mapped_height = self._map_image_resolution(width, height, chosen)
        normalized_steps = self._normalize_image_steps(num_steps, chosen)
        settings: dict[str, object] = {
            "model_type": chosen,
            "prompt": prompt,
            "resolution": f"{mapped_width}x{mapped_height}",
            "num_inference_steps": normalized_steps,
            "batch_size": max(1, num_images),
            "image_mode": 1,
        }
        if chosen.startswith("qwen_image"):
            # MEASURED 2026-10-04 (RTX 4070): SageAttention, which `--attention auto`
            # picks, turned Qwen-Image-Edit-2511 into NaN (all black); SDPA renders it.
            settings["override_attention"] = "sdpa"
        if seed is not None:
            settings["seed"] = seed
        if init_image:
            settings.update(self._img2img_settings(Path(init_image), denoise_strength, normalized_steps))
        elif reference_images:
            settings["video_prompt_type"] = reference_mode if reference_mode in REFERENCE_MODES else "KI"
            settings["image_refs"] = [str(Path(p).resolve()) for p in reference_images]

        self._apply_loras(settings, loras)
        if chosen.startswith("qwen_image_edit") and any("lightning" in Path(path).name.lower() for path, _ in loras):
            settings["num_inference_steps"] = QWEN_LIGHTNING_STEPS
            settings["guidance_scale"] = 1.0
        outputs = self._run_manifest(
            manifest=[{"id": 1, "params": settings, "plugin_data": {}}],
            media_suffixes={".png", ".jpg", ".jpeg", ".webp"},
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        if not outputs:
            raise RuntimeError("WanGP completed without producing any images")
        return outputs

    @staticmethod
    def supports_img2img(model_type: str) -> bool:
        return model_type in IMG2IMG_MODEL_TYPES

    def _img2img_settings(self, init_image: Path, strength: float, steps: int) -> dict[str, object]:
        """Masked Denoising over the whole frame: the reference is the guide,
        an all-white mask regenerates every pixel, and the strength decides
        how far from the reference the result may move."""
        from PIL import Image

        guide = init_image.resolve()
        with Image.open(guide) as image:
            size = image.size
        masks = self._output_dir / "img2img_masks"
        masks.mkdir(parents=True, exist_ok=True)
        mask = masks / f"white-{size[0]}x{size[1]}.png"
        if not mask.is_file():
            Image.new("L", size, 255).save(mask)
        return {
            "image_mode": 2,
            "video_prompt_type": "VAG",
            "model_mode": 0,
            "image_guide": str(guide),
            "image_mask": str(mask.resolve()),
            "denoising_strength": round(min(1.0, max(0.0, strength)), 4),
            "masking_strength": 1.0,
            "num_inference_steps": max(steps, IMG2IMG_MIN_STEPS),
        }

    @staticmethod
    def compute_num_frames(duration_seconds: int, fps: int) -> int:
        return max(((duration_seconds * fps) // 8) * 8 + 1, 9)

    def _map_video_resolution(self, resolution_label: str, aspect_ratio: str) -> str:
        per_aspect = _VIDEO_RESOLUTION_MAP.get(resolution_label)
        if per_aspect is None:
            raise RuntimeError(f"Unsupported WanGP video resolution: {resolution_label}")
        mapped = per_aspect.get(aspect_ratio)
        if mapped is None:
            raise RuntimeError(f"Unsupported WanGP aspect ratio: {aspect_ratio}")
        return mapped

    def _map_image_resolution(self, width: int, height: int, model_type: str | None = None) -> tuple[int, int]:
        """Qwen renders at its native presets; the model rendering decides, not
        the configured default (a Qwen angle render while Z-Image is the default)."""
        if "qwen_image" not in (model_type or self._image_model_type):
            return width, height
        if (width, height) in _QWEN_EDIT_EXACT and "qwen_image_edit" in (model_type or self._image_model_type):
            return width, height

        requested_ratio = width / max(height, 1)

        def score(candidate: tuple[int, int]) -> tuple[float, float]:
            candidate_ratio = candidate[0] / candidate[1]
            ratio_delta = abs(candidate_ratio - requested_ratio)
            area_delta = abs((candidate[0] * candidate[1]) - (width * height))
            return (ratio_delta, area_delta)

        mapped = min(_QWEN_IMAGE_RESOLUTIONS, key=score)
        if mapped != (width, height):
            logger.info(
                "Adjusted Qwen image resolution from %sx%s to native preset %sx%s",
                width,
                height,
                mapped[0],
                mapped[1],
            )
        return mapped

    def _normalize_image_steps(self, num_steps: int, model_type: str | None = None) -> int:
        normalized_steps = max(1, num_steps)
        chosen = model_type or self._image_model_type
        if chosen.startswith("qwen_image_edit"):
            return max(QWEN_EDIT_MIN_STEPS, normalized_steps)
        if chosen.startswith("flux_dev"):
            return max(FLUX1_DEV_MIN_STEPS, normalized_steps)
        if not chosen.startswith("z_image"):
            return normalized_steps

        adjusted_steps = max(8, normalized_steps)
        if adjusted_steps != normalized_steps:
            logger.info(
                "Adjusted %s inference steps from %s to %s",
                self._image_model_type,
                normalized_steps,
                adjusted_steps,
            )
        return adjusted_steps

    def _load_api_module(self):
        if self._root is None:
            raise RuntimeError("WanGP root is not configured")
        root_str = str(self._root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        module = importlib.import_module("shared.api")
        module_file = module.__file__
        if module_file is None:
            raise RuntimeError("shared.api has no __file__; cannot verify the WanGP checkout")
        module_path = Path(module_file).resolve()
        expected_path = (self._root / "shared" / "api.py").resolve()
        if module_path != expected_path:
            raise RuntimeError(f"shared.api resolved to {module_path}, expected {expected_path}")
        return module

    def warm_session(self) -> str:
        """Construct the WanGP session now — this imports ``wgp.py``, the
        heaviest module — so the first render does not pay for it inside its
        job thread (round-2 F-038 note (a)). Returns '' on success, else the
        reason renders will fail with."""
        try:
            self._get_session()
            return ""
        except Exception as exc:  # noqa: BLE001 - reported by the caller, renders re-raise it
            return str(exc)

    @staticmethod
    def _vace_settings(settings: dict[str, object], start: str | None, end: str | None, video_length: int, aspect_ratio: str) -> None:
        """VACE takes no start/end image: those frames are injected by
        position ("FI" + image_refs + frames_positions), a guide video is raw
        ("V", VACE has no guide strength), and it renders at its native 480p."""
        for key in ("image_prompt_type", "image_start", "image_end", "denoising_strength"):
            settings.pop(key, None)
        letters = "V" if settings.get("video_guide") else ""
        refs: list[str] = []
        positions: list[str] = []
        if start:
            refs.append(str(Path(start).resolve()))
            positions.append("1")
        if end:
            refs.append(str(Path(end).resolve()))
            positions.append(str(video_length))
        if refs:
            letters += "FI"
            settings["image_refs"] = refs
            settings["frames_positions"] = " ".join(positions)
        settings["video_prompt_type"] = letters
        settings["resolution"] = "480x832" if aspect_ratio == "9:16" else "832x480"
        # One window for the whole clip. With windows WanGP saves a file after
        # each one and the first (short) file came back as the take; smaller
        # windows were not faster either (MEASURED, r18: 4 x 49 frames ~ 1 x 161).
        settings["sliding_window_size"] = video_length
        if settings.get("video_guide"):
            # The guide carries the motion and layout: CFG's unconditional pass
            # doubled the cost and pulled the take off the source (MEASURED, r18,
            # 10 s shot vs source SSIM: CFG 5/8 steps 0.971 ~390 s; CFG 1/6 steps
            # 0.982 206 s; CFG 1/4 steps 0.981 166 s).
            settings["guidance_scale"] = 1.0
            steps = settings.get("num_inference_steps")
            settings["num_inference_steps"] = min(steps, VACE_GUIDED_STEPS) if isinstance(steps, int) else VACE_GUIDED_STEPS

    def _video_steps(self, model_type: str, requested: int) -> int:
        """An accelerated model (FastWan: 3 steps) renders with its own step
        count; the app's step setting is tuned for LTX-2."""
        if not model_type.startswith("ltx2_"):
            default = next((d.get("default_steps") for d in self.list_model_definitions() if d.get("id") == model_type), None)
            if isinstance(default, int) and 0 < default <= 8:
                return default
        return max(1, requested)

    def held_vram_mb(self) -> int:
        """VRAM held by this bridge's own WanGP process that a render may
        reuse. In-process WanGP shares the app's process: nothing to add."""
        return 0

    def release_models(self) -> bool:
        """Release whatever model WanGP holds (VRAM + pinned RAM). The next
        render reloads it. False when no session was ever started."""
        with self._session_lock:
            session = self._session
        if session is None:
            return False
        session.close()
        return True

    def _get_session(self):
        status = self.get_status()
        if not status.available or status.root is None:
            raise RuntimeError(status.reason or "WanGP bridge is unavailable")

        with self._session_lock:
            if self._session is None:
                api_module = self._load_api_module()
                config_path = self._resolve_session_config_path()
                pin_int8_kernels(config_path)
                self._session = api_module.WanGPSession(
                    root=status.root,
                    config_path=config_path,
                    output_dir=self._output_dir,
                    cli_args=self._extra_args,
                )
            return self._session

    def run_manifest(
        self,
        *,
        manifest: list[dict[str, object]],
        media_suffixes: set[str],
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> list[str]:
        """Run one already-built manifest (the remote WanGP server route calls this)."""
        return self._run_manifest(manifest=manifest, media_suffixes=media_suffixes, on_progress=on_progress, is_cancelled=is_cancelled)

    def _run_manifest(
        self,
        *,
        manifest: list[dict[str, object]],
        media_suffixes: set[str],
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> list[str]:
        session = self._get_session()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._config_dir.mkdir(parents=True, exist_ok=True)

        startup_phase = "starting_wangp" if not self._submitted_manifest_once else "validating_request"
        self._submitted_manifest_once = True
        on_progress(startup_phase, 2, None, None)
        job = session.submit_manifest(manifest)
        error_lines: deque[str] = deque(maxlen=40)
        cancel_requested = False
        console_progress: dict[str, object] = {"phase": "", "progress": -1, "logged_at": 0.0}

        while True:
            if is_cancelled() and not cancel_requested:
                cancel_requested = True
                job.cancel()

            event = job.events.get(timeout=0.2)
            if event is not None:
                self._handle_event(event, on_progress, error_lines, console_progress)

            if job.done and event is None:
                break

        result = job.result()

        if cancel_requested or is_cancelled():
            raise RuntimeError("Generation was cancelled")
        if not result.success:
            details = " | ".join(error_lines) if error_lines else "WanGP generation failed"
            raise RuntimeError(details)
        outputs = result.generated_files

        filtered_outputs = [
            str(Path(path).resolve())
            for path in outputs
            if Path(path).suffix.lower() in media_suffixes
        ]
        if not filtered_outputs:
            return []

        on_progress("complete", 100, None, None)
        return self._dedupe_preserve_order(filtered_outputs)

    def _handle_event(
        self,
        event: Any,
        on_progress: ProgressCallback,
        error_lines: deque[str],
        console_progress: dict[str, object],
    ) -> None:
        kind = getattr(event, "kind", "")
        data = getattr(event, "data", None)

        if kind == "stream":
            stream_name = getattr(data, "stream", "stdout")
            line = str(getattr(data, "text", "")).strip()
            if not line:
                return
            stream_phase = self._classify_stream_phase(line)
            parsed_progress = self._parse_tqdm_progress(line)
            if parsed_progress is None and stream_phase is not None:
                self._emit_console_progress(
                    console_progress,
                    stream_phase,
                    self._estimate_progress(stream_phase, None, None),
                    None,
                    None,
                    line,
                )
            if stream_phase is not None:
                on_progress(stream_phase, self._estimate_progress(stream_phase, None, None), None, None)
            if self._should_capture_error_line(stream_name, line):
                error_lines.append(line)
            return

        if kind == "progress":
            phase = str(getattr(data, "phase", "inference"))
            progress = int(getattr(data, "progress", 0))
            current_step = getattr(data, "current_step", None)
            total_steps = getattr(data, "total_steps", None)
            self._emit_console_progress(
                console_progress,
                phase,
                progress,
                current_step if isinstance(current_step, int) else None,
                total_steps if isinstance(total_steps, int) else None,
                str(getattr(data, "status", "")).strip(),
            )
            on_progress(phase, progress, current_step, total_steps)
            return

        if kind == "status":
            text = str(data or "").strip()
            if not text:
                return
            logger.info("[WanGP status] %s", text)
            phase = self._classify_phase(text)
            progress = self._estimate_progress(phase, None, None)
            self._emit_console_progress(console_progress, phase, progress, None, None, text, force=True)
            on_progress(phase, progress, None, None)
            return

        if kind == "info":
            text = str(data or "").strip()
            if text:
                logger.info("[WanGP info] %s", text)
            return

        if kind == "error":
            message = str(data)
            if message:
                error_lines.append(message)
                logger.error("[WanGP error] %s", message)
            return

        if kind == "completed":
            if bool(getattr(data, "success", False)):
                self._emit_console_progress(console_progress, "complete", 100, None, None, "Completed", force=True)
                on_progress("complete", 100, None, None)

    @staticmethod
    def _classify_phase(status_text: str) -> str:
        lowered = status_text.lower()
        if "denoising first pass" in lowered or "denoising 1st pass" in lowered:
            return "inference_stage_1"
        if "denoising second pass" in lowered or "denoising 2nd pass" in lowered:
            return "inference_stage_2"
        if "denoising third pass" in lowered or "denoising 3rd pass" in lowered:
            return "inference_stage_3"
        if "loading" in lowered:
            return "loading_model"
        if "enhancing prompt" in lowered or "encoding" in lowered:
            return "encoding_text"
        if "decoding" in lowered:
            return "decoding"
        if "saved" in lowered or "completed" in lowered or "output" in lowered:
            return "downloading_output"
        if "cancel" in lowered or "abort" in lowered:
            return "cancelled"
        return "inference"

    @staticmethod
    def _estimate_progress(phase: str, current_step: int | None, total_steps: int | None) -> int:
        if total_steps is None or total_steps <= 0 or current_step is None:
            if phase == "preparing_model":
                return 4
            if phase == "downloading_model":
                return 5
            if phase == "loading_model":
                return 10
            if phase == "encoding_text":
                return 18
            if phase == "inference_stage_1":
                return 25
            if phase == "inference_stage_2":
                return 70
            if phase == "inference_stage_3":
                return 80
            if phase == "decoding":
                return 90
            if phase == "downloading_output":
                return 95
            if phase == "cancelled":
                return 0
            return 15
        ratio = max(0.0, min(1.0, current_step / total_steps))
        if phase == "preparing_model":
            return min(6, 2 + int(ratio * 4))
        if phase == "downloading_model":
            return min(9, 3 + int(ratio * 6))
        if phase == "loading_model":
            return min(15, 5 + int(ratio * 10))
        if phase == "encoding_text":
            return min(22, 12 + int(ratio * 10))
        if phase == "inference_stage_1":
            return min(68, 20 + int(ratio * 48))
        if phase == "inference_stage_2":
            return min(88, 68 + int(ratio * 20))
        if phase == "inference_stage_3":
            return min(89, 80 + int(ratio * 9))
        if phase == "decoding":
            return min(95, 85 + int(ratio * 10))
        if phase == "downloading_output":
            return min(98, 92 + int(ratio * 6))
        if phase == "cancelled":
            return 0
        return min(90, 20 + int(ratio * 65))

    @staticmethod
    def _classify_stream_phase(line: str) -> str | None:
        lowered = line.lower()
        if "hf_xet" in lowered or "falling back to regular http download" in lowered:
            return "preparing_model"
        if lowered.startswith("downloading ") or "downloading model" in lowered or "snapshot_download" in lowered:
            return "downloading_model"
        return None

    @staticmethod
    def _parse_tqdm_progress(line: str) -> tuple[int, int | None, int | None, str | None] | None:
        match = _TQDM_PROGRESS_RE.search(line)
        if match is None:
            return None
        label = (match.group("label") or "").strip(" :")
        current_step = int(match.group("current"))
        total_steps = int(match.group("total"))
        return int(match.group("percent")), current_step, total_steps, label or None

    @staticmethod
    def _phase_label(phase: str) -> str:
        labels = {
            "starting_wangp": "Starting WanGP",
            "preparing_model": "Preparing model",
            "downloading_model": "Downloading model",
            "loading_model": "Loading model",
            "encoding_text": "Encoding text",
            "inference": "Generating",
            "inference_stage_1": "Generating pass 1",
            "inference_stage_2": "Generating pass 2",
            "inference_stage_3": "Generating pass 3",
            "decoding": "Decoding",
            "downloading_output": "Saving output",
            "complete": "Completed",
            "cancelled": "Cancelled",
        }
        return labels.get(phase, phase.replace("_", " ").title())

    def _emit_console_progress(
        self,
        tracker: dict[str, object],
        phase: str,
        progress: int,
        current_step: int | None,
        total_steps: int | None,
        status_text: str,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        progress = max(0, min(100, int(progress)))
        last_phase = str(tracker.get("phase", ""))
        last_progress_raw = tracker.get("progress", -1)
        last_progress = last_progress_raw if isinstance(last_progress_raw, int) else -1
        last_logged_at_raw = tracker.get("logged_at", 0.0)
        last_logged_at = last_logged_at_raw if isinstance(last_logged_at_raw, (int, float)) else 0.0
        if not force and phase == last_phase and progress == last_progress and now - last_logged_at < 1.0:
            return

        tracker["phase"] = phase
        tracker["progress"] = progress
        tracker["logged_at"] = now

        bar_width = 24
        filled = min(bar_width, max(0, round(progress * bar_width / 100)))
        bar = "#" * filled + "-" * (bar_width - filled)
        detail = f" {current_step}/{total_steps}" if current_step is not None and total_steps is not None else ""
        suffix = f" - {status_text}" if status_text else ""
        logger.info("[WanGP progress] [%s] %3d%% %s%s%s", bar, progress, self._phase_label(phase), detail, suffix)

    @staticmethod
    def _should_capture_error_line(stream_name: str, line: str) -> bool:
        lowered = line.lower()
        if line.startswith("Traceback") or line.startswith("File \"") or line.startswith("  File "):
            return True
        if stream_name != "stderr":
            return "[error]" in lowered or "exception" in lowered or "failed" in lowered
        if "%|" in line and "steps/" in lowered:
            return False
        if "| 0/" in line or "| 1/" in line or "| 2/" in line or "| 3/" in line or "| 4/" in line:
            return False
        return "[error]" in lowered or "traceback" in lowered or "exception" in lowered or "failed" in lowered

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
