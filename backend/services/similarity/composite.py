"""Composite candidate score.

    composite = 0.35·CLIP-I + 0.25·DINOv2 + 0.15·SSIM(luma) + 0.15·palette(ΔE2000) + 0.10·layout(Florence count/IoU)

Why these weights: CLIP-I tracks semantic sameness (what is in the picture),
DINOv2 tracks structure (where things are and how they are drawn), SSIM on
luma catches composition/contrast, the palette term catches colour drift the
embeddings forgive, and the layout term catches "two people instead of one".
Weights are stored with every score so they can be tuned later without
making old numbers unreadable. When a component is unavailable (a model
disabled in Settings) the remaining weights are renormalised and the
breakdown says which were used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from services.similarity.metrics import FloatArray, cosine_similarity, layout_similarity, palette_similarity, ssim

COMPOSITE_WEIGHTS: dict[str, float] = {"clip": 0.35, "dino": 0.25, "ssim": 0.15, "palette": 0.15, "layout": 0.10}


@dataclass
class ImageFeatures:
    """Everything the scorer needs about one image, computed once."""

    luma: FloatArray | None = None
    clip: list[float] = field(default_factory=list[float])
    dino: list[float] = field(default_factory=list[float])
    palette: list[tuple[str, float]] = field(default_factory=list[tuple[str, float]])
    regions: list[tuple[str, list[float]]] = field(default_factory=list[tuple[str, list[float]]])
    sharpness: float = 0.0
    edge_density: float = 0.0


class ScoreBreakdown(BaseModel):
    composite: float = 0.0
    components: dict[str, float] = Field(default_factory=dict[str, float])
    weights_used: dict[str, float] = Field(default_factory=dict[str, float])
    missing: list[str] = Field(default_factory=list[str])


class CompositeScorer:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights or COMPOSITE_WEIGHTS)

    def score(self, reference: ImageFeatures, candidate: ImageFeatures) -> ScoreBreakdown:
        components: dict[str, float] = {}
        if reference.clip and candidate.clip:
            components["clip"] = round(cosine_similarity(reference.clip, candidate.clip), 4)
        if reference.dino and candidate.dino:
            components["dino"] = round(cosine_similarity(reference.dino, candidate.dino), 4)
        if reference.luma is not None and candidate.luma is not None:
            components["ssim"] = round(ssim(reference.luma, candidate.luma), 4)
        if reference.palette and candidate.palette:
            components["palette"] = palette_similarity(reference.palette, candidate.palette)
        if reference.regions or candidate.regions:
            components["layout"] = layout_similarity(reference.regions, candidate.regions)
        used = {name: weight for name, weight in self.weights.items() if name in components}
        total = sum(used.values())
        composite = sum(components[name] * weight for name, weight in used.items()) / total if total else 0.0
        return ScoreBreakdown(
            composite=round(composite, 4),
            components=components,
            weights_used={name: round(weight / total, 4) for name, weight in used.items()} if total else {},
            missing=[name for name in self.weights if name not in components],
        )
