"""Monocular depth (Depth-Anything-V2 via transformers) and DINOv2 embeddings.

Both are tiny (class S) and load lazily; nothing here imports torch at module
level. Depth maps are written as 16-bit PNGs (0 = far, 65535 = near) so the
composer underlay and the control-video path can read them without numpy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from services.vision.protocol import DepthResult, EmbeddingResult, VramClass

logger = logging.getLogger(__name__)

DEPTH_MODELS: dict[str, tuple[str, VramClass, int]] = {
    "depth-anything-v2-small": ("depth-anything/Depth-Anything-V2-Small-hf", "S", 200),
    "depth-anything-v2-base": ("depth-anything/Depth-Anything-V2-Base-hf", "S", 500),
}
DEFAULT_DEPTH_MODEL = "depth-anything-v2-small"
DINO_MODELS: dict[str, tuple[str, VramClass, int]] = {
    "dinov2-small": ("facebook/dinov2-small", "S", 150),
    "dinov2-base": ("facebook/dinov2-base", "S", 400),
}
DEFAULT_DINO_MODEL = "dinov2-small"


def _pick_device(device: str) -> str:
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _empty_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def write_depth_png(depth: NDArray[np.float32], output_png: Path) -> tuple[float, float, float]:
    """Normalise to 16-bit (near = bright) and save. Returns (near, far, mean) of the raw map."""
    near, far, mean = float(depth.max()), float(depth.min()), float(depth.mean())
    span = (near - far) or 1.0
    normalised = ((depth - far) / span * 65535.0).astype(np.uint16)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(normalised).save(output_png)
    return near, far, mean


def read_depth_png(path: Path) -> NDArray[np.float32]:
    with Image.open(path) as image:
        return np.asarray(image, dtype=np.float32) / 65535.0


def depth_median_in_box(depth01: NDArray[np.float32], bbox: list[float]) -> float | None:
    if len(bbox) != 4:
        return None
    h, w = depth01.shape[:2]
    x, y, bw, bh = bbox
    x1, y1 = max(0, int(x * w)), max(0, int(y * h))
    x2, y2 = min(w, int((x + bw) * w)), min(h, int((y + bh) * h))
    if x2 <= x1 or y2 <= y1:
        return None
    return round(float(np.median(depth01[y1:y2, x1:x2])), 4)


class DepthEstimator:
    name = "depth"

    def __init__(self, model_id: str = DEFAULT_DEPTH_MODEL, *, cache_dir: Path | None = None, device: str = "auto") -> None:
        self.model_id = model_id if model_id in DEPTH_MODELS else DEFAULT_DEPTH_MODEL
        repo_id, vram_class, estimated_mb = DEPTH_MODELS[self.model_id]
        self.repo_id: str = repo_id
        self.vram_class: VramClass = vram_class
        self.estimated_mb: int = estimated_mb
        self._cache_dir = cache_dir
        self._device = device
        self._model: Any = None
        self._processor: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoImageProcessor, DepthAnythingForDepthEstimation  # pyright: ignore[reportUnknownVariableType]

        device = _pick_device(self._device)
        kwargs: dict[str, Any] = {"cache_dir": str(self._cache_dir / "hf")} if self._cache_dir else {}
        logger.info("Loading %s on %s", self.repo_id, device)
        self._processor = AutoImageProcessor.from_pretrained(self.repo_id, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._model = DepthAnythingForDepthEstimation.from_pretrained(self.repo_id, **kwargs).to(device).eval()  # pyright: ignore[reportUnknownMemberType]
        self._device = device

    def unload(self) -> None:
        self._model = None
        self._processor = None
        _empty_cache()

    def predict(self, image: Image.Image) -> NDArray[np.float32]:
        import torch

        self.load()
        rgb = image.convert("RGB")
        inputs = self._processor(images=rgb, return_tensors="pt").to(self._device)
        with torch.inference_mode():
            outputs = self._model(**inputs)
        predicted: Any = outputs.predicted_depth
        resized = torch.nn.functional.interpolate(predicted.unsqueeze(1), size=rgb.size[::-1], mode="bicubic", align_corners=False)
        return cast(NDArray[np.float32], resized[0, 0].float().cpu().numpy())

    def depth(self, image: Image.Image, output_png: Path) -> DepthResult:
        raw = self.predict(image)
        near, far, mean = write_depth_png(raw, output_png)
        return DepthResult(model=self.model_id, depth_png=str(output_png), width=image.width, height=image.height, near=near, far=far, mean=mean)


class DinoEmbedder:
    name = "dino"

    def __init__(self, model_id: str = DEFAULT_DINO_MODEL, *, cache_dir: Path | None = None, device: str = "auto") -> None:
        self.model_id = model_id if model_id in DINO_MODELS else DEFAULT_DINO_MODEL
        repo_id, vram_class, estimated_mb = DINO_MODELS[self.model_id]
        self.repo_id: str = repo_id
        self.vram_class: VramClass = vram_class
        self.estimated_mb: int = estimated_mb
        self._cache_dir = cache_dir
        self._device = device
        self._model: Any = None
        self._processor: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoImageProcessor, Dinov2Model  # pyright: ignore[reportUnknownVariableType]

        device = _pick_device(self._device)
        kwargs: dict[str, Any] = {"cache_dir": str(self._cache_dir / "hf")} if self._cache_dir else {}
        logger.info("Loading %s on %s", self.repo_id, device)
        self._processor = AutoImageProcessor.from_pretrained(self.repo_id, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._model = Dinov2Model.from_pretrained(self.repo_id, **kwargs).to(device).eval()  # pyright: ignore[reportUnknownMemberType]
        self._device = device

    def unload(self) -> None:
        self._model = None
        self._processor = None
        _empty_cache()

    def embed(self, image: Image.Image) -> EmbeddingResult:
        import torch

        self.load()
        inputs = self._processor(images=image.convert("RGB"), return_tensors="pt").to(self._device)
        with torch.inference_mode():
            outputs = self._model(**inputs)
        pooled: Any = outputs.pooler_output[0]
        pooled = pooled / pooled.norm()
        return EmbeddingResult(kind="dino", model=self.model_id, vector=[float(v) for v in pooled.float().cpu().numpy()])
