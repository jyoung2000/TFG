"""Zero123++ v1.2 (sudo-ai/zero123plus-v1.2; weights CC-BY-NC 4.0, code Apache-2.0) via diffusers.

Weights: `<model_dir>/` (diffusers layout) and the custom pipeline at
`<model_dir>/_pipeline/pipeline.py`. Torch and diffusers are imported lazily.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from threading import Lock
from typing import Any, cast

from PIL import Image

from services.multiview import ZERO123PP_VIEWS, MultiView, split_grid

CONDITION_SIZE = 320
OUTPUT_SIZE = 640
GREY = (127, 127, 127)


def _condition_image(image_path: str) -> Image.Image:
    """Pad to a square on neutral grey (honouring alpha), then resize to the condition size."""
    with Image.open(image_path) as src:
        rgba = src.convert("RGBA")
    side = max(rgba.size)
    canvas = Image.new("RGBA", (side, side), GREY + (255,))
    canvas.alpha_composite(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
    return canvas.convert("RGB").resize((CONDITION_SIZE, CONDITION_SIZE), Image.Resampling.LANCZOS)


class Zero123PlusGenerator:
    def __init__(self, model_dir: Path, output_dir: Path) -> None:
        self._model_dir = model_dir
        self._output_dir = output_dir
        self._lock = Lock()
        self._pipe: Any | None = None

    def available(self) -> bool:
        return (
            (self._model_dir / "model_index.json").is_file()
            and (self._model_dir / "unet" / "diffusion_pytorch_model.safetensors").is_file()
            and (self._model_dir / "_pipeline" / "pipeline.py").is_file()
        )

    def _load_pipeline(self) -> Any:
        """Load and cache the diffusers pipeline. Call under the lock."""
        if self._pipe is None:
            import torch
            diffusers = cast(Any, importlib.import_module("diffusers"))

            pipe = diffusers.DiffusionPipeline.from_pretrained(
                str(self._model_dir),
                custom_pipeline=str(self._model_dir / "_pipeline"),
                torch_dtype=torch.float16,
            )
            pipe.scheduler = diffusers.EulerAncestralDiscreteScheduler.from_config(
                pipe.scheduler.config, timestep_spacing="trailing"
            )
            pipe.to("cuda")
            self._pipe = pipe
        return self._pipe

    def generate(self, image_path: str, *, seed: int | None = None, steps: int = 75) -> list[MultiView]:
        condition = _condition_image(image_path)
        with self._lock:
            pipe = self._load_pipeline()
            kwargs: dict[str, Any] = {"num_inference_steps": steps}
            if seed is not None:
                import torch

                kwargs["generator"] = torch.Generator(device="cuda").manual_seed(seed)
            grid = cast(Image.Image, pipe(condition, **kwargs).images[0])

        self._output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(image_path).stem
        views: list[MultiView] = []
        for index, (tile, (azimuth, elevation, label)) in enumerate(zip(split_grid(grid), ZERO123PP_VIEWS)):
            out = self._output_dir / f"{stem}-z123-{index}.png"
            tile.convert("RGB").resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS).save(out)
            views.append(MultiView(path=str(out), azimuth=azimuth, elevation=elevation, label=label))
        return views

    def unload(self) -> None:
        with self._lock:
            self._pipe = None
        torch = sys.modules.get("torch")
        if torch is not None:
            cuda = cast(Any, torch).cuda
            if cuda.is_available():
                cuda.empty_cache()
