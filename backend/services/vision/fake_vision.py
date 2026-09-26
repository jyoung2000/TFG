"""Deterministic vision for tests and the UI mock path.

Outputs derive from the image itself (size, mean colour, file name), so a
test can assert on them without a model and a broken wiring still fails.
Depth maps are real 16-bit PNGs so downstream code reads real files.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from services.vision.depth import write_depth_png
from services.vision.deterministic import measure_image
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
    TagScore,
    VisionRegion,
    VisionStatus,
)


class FakeVision:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.loaded: set[str] = set()
        #: Components a test switches off to simulate a disabled/missing model.
        self.disabled: set[str] = set()
        #: Regions returned by `detect` when set; otherwise derived from the image.
        self.regions_override: list[VisionRegion] | None = None
        self.caption_override: str = ""

    def _use(self, component: str, image_path: str) -> None:
        if component in self.disabled:
            raise RuntimeError(f"{component} is disabled in Settings → Vision")
        self.loaded.add(component)
        self.calls.append((component, image_path))

    def status(self) -> VisionStatus:
        names = ("florence", "clip", "depth", "dino")
        return VisionStatus(
            mode="fake",
            components=[ComponentStatus(name="stats", enabled=True, available=True, loaded=True, model="deterministic")]
            + [ComponentStatus(name=n, enabled=n not in self.disabled, available=True, loaded=n in self.loaded, model=f"fake-{n}") for n in names],
        )

    def stats(self, image_path: str) -> MeasuredStats:
        self.calls.append(("stats", image_path))
        with Image.open(image_path) as image:
            return measure_image(image)

    def caption(self, image_path: str, level: CaptionLevel = "more_detailed_caption") -> CaptionResult:
        self._use("florence", image_path)
        if self.caption_override:
            return CaptionResult(text=self.caption_override, level=level, model="fake-florence")
        with Image.open(image_path) as image:
            width, height = image.size
            mean = np.asarray(image.convert("RGB").resize((8, 8)), dtype=np.float64).reshape(-1, 3).mean(axis=0)
        dominant = ["red", "green", "blue"][int(np.argmax(mean))]
        stem = Path(image_path).stem.replace("-", " ").replace("_", " ")
        return CaptionResult(text=f"A {dominant}-toned {width}x{height} frame of {stem}.", level=level, model="fake-florence")

    def detect(self, image_path: str, task: DetectTask = "od", text: str = "") -> DetectResult:
        self._use("florence", image_path)
        if self.regions_override is not None:
            return DetectResult(task=task, model="fake-florence", regions=list(self.regions_override))
        regions = [VisionRegion(label="person" if task != "caption_to_phrase_grounding" else (text or "subject"), bbox=[0.3, 0.2, 0.4, 0.7], score=0.9)]
        return DetectResult(task=task, model="fake-florence", regions=regions)

    def tags(self, image_path: str, top_k: int = 12) -> TagResult:
        self._use("clip", image_path)
        stats = self.stats(image_path)
        base = ["cinematic", "film still", "natural light", "shallow depth of field", "35mm", "moody"]
        tags = [TagScore(term="photograph", score=0.31, category="medium"), TagScore(term="cinematic realism", score=0.28, category="movement")]
        tags.extend(TagScore(term=t, score=round(0.27 - i * 0.01, 4), category="flavor") for i, t in enumerate(base))
        if stats.saturation < 0.15:
            tags.append(TagScore(term="black and white", score=0.25, category="flavor"))
        return TagResult(model="fake-clip", tags=tags[:top_k], negatives=[TagScore(term="blurry", score=0.2, category="negative")])

    def depth(self, image_path: str, output_png: str) -> DepthResult:
        self._use("depth", image_path)
        with Image.open(image_path) as image:
            width, height = image.size
        yy = np.linspace(0.0, 1.0, num=max(2, height), dtype=np.float32)[:, None]
        raw = np.repeat(yy, max(2, width), axis=1)  # near at the bottom, far at the top
        near, far, mean = write_depth_png(raw, Path(output_png))
        return DepthResult(model="fake-depth", depth_png=output_png, width=width, height=height, near=near, far=far, mean=mean)

    def embed(self, image_path: str, kind: EmbeddingKind = "clip") -> EmbeddingResult:
        self._use("clip" if kind == "clip" else "dino", image_path)
        # A content-derived unit vector: identical images embed identically,
        # different colours land far apart — enough for similarity tests.
        try:
            with Image.open(image_path) as image:
                small = np.asarray(image.convert("RGB").resize((4, 4)), dtype=np.float64).reshape(-1) / 255.0
        except (OSError, UnidentifiedImageError):
            # Frames the fake video processor produces are not real images;
            # hash their bytes so the vector is still content-derived.
            digest = hashlib.sha1(Path(image_path).read_bytes()).digest()
            small = np.asarray(list(digest[:48]), dtype=np.float64) / 255.0
        seed = int(hashlib.sha1(small.tobytes()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        vector = np.concatenate([small, rng.normal(size=16)])
        vector /= math.sqrt(float((vector**2).sum())) or 1.0
        return EmbeddingResult(kind=kind, model=f"fake-{kind}", vector=[float(v) for v in vector])

    def unload(self, keep: tuple[str, ...] = ()) -> list[str]:
        unloaded = sorted(name for name in self.loaded if name not in keep)
        self.loaded -= set(unloaded)
        return unloaded
