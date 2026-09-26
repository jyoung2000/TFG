"""Local vision: Florence-2, CLIP tagging, depth, DINOv2 and model-free stats
behind one Protocol (`VisionService`)."""

from services.vision.protocol import (
    CaptionResult,
    ComponentStatus,
    DepthResult,
    DetectResult,
    EmbeddingResult,
    MeasuredStats,
    PaletteEntry,
    TagResult,
    TagScore,
    VisionRegion,
    VisionService,
    VisionStatus,
)

__all__ = [
    "CaptionResult",
    "ComponentStatus",
    "DepthResult",
    "DetectResult",
    "EmbeddingResult",
    "MeasuredStats",
    "PaletteEntry",
    "TagResult",
    "TagScore",
    "VisionRegion",
    "VisionService",
    "VisionStatus",
]
