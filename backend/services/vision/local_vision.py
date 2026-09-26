"""In-process vision service: the model wrappers composed behind the Protocol,
registered with the VRAM manager as they load."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from services.vision.clip_tagger import CLIP_ESTIMATED_MB, CLIP_VRAM_CLASS, DEFAULT_CLIP_MODEL, ClipTagger
from services.vision.depth import DEFAULT_DEPTH_MODEL, DEFAULT_DINO_MODEL, DepthEstimator, DinoEmbedder
from services.vision.deterministic import measure_image
from services.vision.florence2 import DEFAULT_FLORENCE_MODEL, FLORENCE_MODELS, Florence2
from services.vision.protocol import (
    CaptionLevel,
    CaptionResult,
    ComponentStatus,
    DepthResult,
    DetectResult,
    DetectTask,
    EmbeddingKind,
    EmbeddingResult,
    MeasuredStats,
    TagResult,
    VisionStatus,
)
from services.vram.vram_manager import VramManager

logger = logging.getLogger(__name__)

#: Longest edge fed to the models; the originals stay untouched on disk.
ANALYSIS_EDGE = 1024


@dataclass
class VisionConfig:
    florence_enabled: bool = True
    florence_model: str = DEFAULT_FLORENCE_MODEL
    clip_enabled: bool = True
    clip_model: str = DEFAULT_CLIP_MODEL
    depth_enabled: bool = True
    depth_model: str = DEFAULT_DEPTH_MODEL
    dino_enabled: bool = True
    dino_model: str = DEFAULT_DINO_MODEL
    cache_dir: Path | None = None
    device: str = "auto"


def open_for_analysis(image_path: str) -> Image.Image:
    with Image.open(image_path) as raw:
        image = ImageOps.exif_transpose(raw) or raw
        image = image.convert("RGB")
        image.thumbnail((ANALYSIS_EDGE, ANALYSIS_EDGE))
        return image.copy()


class LocalVision:
    def __init__(self, config: VisionConfig, vram: VramManager) -> None:
        self._config = config
        self._vram = vram
        self._florence = Florence2(config.florence_model, cache_dir=config.cache_dir, device=config.device)
        self._clip = ClipTagger(config.clip_model, cache_dir=config.cache_dir, device=config.device)
        self._depth = DepthEstimator(config.depth_model, cache_dir=config.cache_dir, device=config.device)
        self._dino = DinoEmbedder(config.dino_model, cache_dir=config.cache_dir, device=config.device)

    def configure(self, config: VisionConfig) -> None:
        """Apply new settings; models whose id changed are dropped and reload lazily."""
        if config.florence_model != self._config.florence_model:
            self._florence.unload()
            self._florence = Florence2(config.florence_model, cache_dir=config.cache_dir, device=config.device)
        if config.clip_model != self._config.clip_model:
            self._clip.unload()
            self._clip = ClipTagger(config.clip_model, cache_dir=config.cache_dir, device=config.device)
        if config.depth_model != self._config.depth_model:
            self._depth.unload()
            self._depth = DepthEstimator(config.depth_model, cache_dir=config.cache_dir, device=config.device)
        if config.dino_model != self._config.dino_model:
            self._dino.unload()
            self._dino = DinoEmbedder(config.dino_model, cache_dir=config.cache_dir, device=config.device)
        self._config = config

    # ---- registry glue ------------------------------------------------------

    def _register(self, name: str, vram_class: str, estimated_mb: int, unload: object, priority: int) -> None:
        def _do_unload() -> None:
            getattr(unload, "unload")()

        self._vram.register(name, vram_class, estimated_mb, _do_unload, priority=priority)

    def _ensure_florence(self) -> Florence2:
        if not self._config.florence_enabled:
            raise RuntimeError("Florence-2 is disabled in Settings → Vision")
        if not self._florence.loaded:
            self._florence.load()
            self._register("florence", self._florence.spec.vram_class, self._florence.spec.estimated_mb, self._florence, 80)
        return self._florence

    def _ensure_clip(self) -> ClipTagger:
        if not self._config.clip_enabled:
            raise RuntimeError("CLIP is disabled in Settings → Vision")
        if not self._clip.loaded:
            self._clip.load()
            self._register("clip", CLIP_VRAM_CLASS, CLIP_ESTIMATED_MB, self._clip, 40)
        return self._clip

    def _ensure_depth(self) -> DepthEstimator:
        if not self._config.depth_enabled:
            raise RuntimeError("Depth estimation is disabled in Settings → Vision")
        if not self._depth.loaded:
            self._depth.load()
            self._register("depth", self._depth.vram_class, self._depth.estimated_mb, self._depth, 30)
        return self._depth

    def _ensure_dino(self) -> DinoEmbedder:
        if not self._config.dino_enabled:
            raise RuntimeError("DINOv2 is disabled in Settings → Vision")
        if not self._dino.loaded:
            self._dino.load()
            self._register("dino", self._dino.vram_class, self._dino.estimated_mb, self._dino, 20)
        return self._dino

    # ---- Protocol -----------------------------------------------------------

    def status(self) -> VisionStatus:
        spec = FLORENCE_MODELS.get(self._config.florence_model, FLORENCE_MODELS[DEFAULT_FLORENCE_MODEL])
        return VisionStatus(
            mode="local",
            device=self._config.device,
            components=[
                ComponentStatus(name="stats", enabled=True, available=True, loaded=True, model="deterministic", vram_class="S", estimated_mb=0),
                ComponentStatus(name="florence", enabled=self._config.florence_enabled, available=True, loaded=self._florence.loaded, model=spec.id, vram_class=spec.vram_class, estimated_mb=spec.estimated_mb),
                ComponentStatus(name="clip", enabled=self._config.clip_enabled, available=True, loaded=self._clip.loaded, model=self._clip.model_id, vram_class=CLIP_VRAM_CLASS, estimated_mb=CLIP_ESTIMATED_MB),
                ComponentStatus(name="depth", enabled=self._config.depth_enabled, available=True, loaded=self._depth.loaded, model=self._depth.model_id, vram_class=self._depth.vram_class, estimated_mb=self._depth.estimated_mb),
                ComponentStatus(name="dino", enabled=self._config.dino_enabled, available=True, loaded=self._dino.loaded, model=self._dino.model_id, vram_class=self._dino.vram_class, estimated_mb=self._dino.estimated_mb),
            ],
        )

    def stats(self, image_path: str) -> MeasuredStats:
        with Image.open(image_path) as image:
            return measure_image(image)

    def caption(self, image_path: str, level: CaptionLevel = "more_detailed_caption") -> CaptionResult:
        return self._ensure_florence().caption(open_for_analysis(image_path), level)

    def detect(self, image_path: str, task: DetectTask = "od", text: str = "") -> DetectResult:
        return self._ensure_florence().detect(open_for_analysis(image_path), task, text)

    def tags(self, image_path: str, top_k: int = 12) -> TagResult:
        image = open_for_analysis(image_path)
        seed = ""
        if self._config.florence_enabled:
            try:
                seed = self._ensure_florence().caption(image, "caption").text
            except Exception as exc:  # noqa: BLE001 - tags still work without a seed
                logger.info("Caption seed unavailable for tagging: %s", exc)
        return self._ensure_clip().tags(image, top_k, caption_seed=seed)

    def depth(self, image_path: str, output_png: str) -> DepthResult:
        return self._ensure_depth().depth(open_for_analysis(image_path), Path(output_png))

    def embed(self, image_path: str, kind: EmbeddingKind = "clip") -> EmbeddingResult:
        image = open_for_analysis(image_path)
        if kind == "dino":
            return self._ensure_dino().embed(image)
        return self._ensure_clip().image_embedding(image)

    def unload(self, keep: tuple[str, ...] = ()) -> list[str]:
        unloaded: list[str] = []
        for name, component in (("florence", self._florence), ("clip", self._clip), ("depth", self._depth), ("dino", self._dino)):
            if name in keep or not component.loaded:
                continue
            component.unload()
            self._vram.unregister(name)
            unloaded.append(name)
        return unloaded
