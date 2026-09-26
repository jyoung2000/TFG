"""The vision service contract.

Everything the analyzers need from local vision models, behind one Protocol
so the backend never imports torch/transformers at module import time and
tests swap in `FakeVision`. Two real implementations exist: `LocalVision`
(models in this process) and `RemoteVision` (HTTP to the sidecar worker,
`backend/vision_worker.py`). Both compose the same model wrappers.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

#: S ≤ 1.5 GB · M ≤ 3 GB · L > 3 GB, as loaded in fp16 with activations for one image.
VramClass = Literal["S", "M", "L"]
CaptionLevel = Literal["caption", "detailed_caption", "more_detailed_caption", "prompt_gen_tags", "prompt_gen_mixed_caption_plus"]
DetectTask = Literal["od", "dense_region_caption", "caption_to_phrase_grounding", "region_proposal"]
EmbeddingKind = Literal["clip", "dino"]


class VisionRegion(BaseModel):
    label: str
    #: Normalised [x, y, w, h] in 0..1 of the source image.
    bbox: list[float] = Field(default_factory=list[float])
    score: float = 1.0
    #: Median depth (0 = far, 1 = near) inside the box when a depth map was available.
    depth_median: float | None = None


class CaptionResult(BaseModel):
    text: str
    level: str
    model: str


class DetectResult(BaseModel):
    task: str
    model: str
    regions: list[VisionRegion] = Field(default_factory=list[VisionRegion])


class TagScore(BaseModel):
    term: str
    score: float
    #: Which list the term came from: medium | movement | artist | flavor | negative.
    category: str = "flavor"


class TagResult(BaseModel):
    model: str
    tags: list[TagScore] = Field(default_factory=list[TagScore])
    negatives: list[TagScore] = Field(default_factory=list[TagScore])


class DepthResult(BaseModel):
    model: str
    #: 16-bit PNG, 0 = far … 65535 = near, same size as the analysed image.
    depth_png: str
    width: int
    height: int
    near: float
    far: float
    mean: float


class EmbeddingResult(BaseModel):
    kind: str
    model: str
    vector: list[float] = Field(default_factory=list[float])


class PaletteEntry(BaseModel):
    hex: str
    share: float


class MeasuredStats(BaseModel):
    """Deterministic, model-free measurements. Always available, always local."""

    width: int
    height: int
    aspect: str
    palette: list[PaletteEntry] = Field(default_factory=list[PaletteEntry])
    luminance: float
    contrast: float
    saturation: float
    edge_density: float
    sharpness: float
    #: Background colour estimate from the border, or "" when no clear background.
    background_hex: str = ""
    #: 0..1, how flat/vector-like the image is (few colours, hard edges).
    vector_likeness: float = 0.0
    exif: dict[str, str] = Field(default_factory=dict[str, str])


class ComponentStatus(BaseModel):
    name: str
    enabled: bool
    available: bool
    loaded: bool
    model: str = ""
    vram_class: VramClass = "S"
    estimated_mb: int = 0
    note: str = ""


class VisionStatus(BaseModel):
    mode: Literal["local", "sidecar", "fake"]
    device: str = "cpu"
    components: list[ComponentStatus] = Field(default_factory=list[ComponentStatus])


class VisionService(Protocol):
    def status(self) -> VisionStatus: ...

    def stats(self, image_path: str) -> MeasuredStats: ...

    def caption(self, image_path: str, level: CaptionLevel = "more_detailed_caption") -> CaptionResult: ...

    def detect(self, image_path: str, task: DetectTask = "od", text: str = "") -> DetectResult: ...

    def tags(self, image_path: str, top_k: int = 12) -> TagResult: ...

    def depth(self, image_path: str, output_png: str) -> DepthResult: ...

    def embed(self, image_path: str, kind: EmbeddingKind = "clip") -> EmbeddingResult: ...

    def unload(self, keep: tuple[str, ...] = ()) -> list[str]:
        """Free model memory; returns the component names that were unloaded."""
        ...
