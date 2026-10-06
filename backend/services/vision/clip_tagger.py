"""CLIP term ranking.

A port of pharmapsychotic/clip-interrogator (MIT): `LabelTable` (chunked
text embedding with an on-disk cache), `rank_top`, `chain` and the
classic/negative orderings, rewritten on `transformers`' CLIP so no extra
package is installed. The term lists in `clip_data/` are vendored unchanged.
No BLIP: Florence captions seed `chain()` instead.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from services.vision.protocol import EmbeddingResult, TagResult, TagScore, VramClass

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "clip_data"
DEFAULT_CLIP_MODEL = "openai/clip-vit-large-patch14"
CLIP_VRAM_CLASS: VramClass = "M"
CLIP_ESTIMATED_MB = 1000
_CHUNK = 1024
FloatArray = NDArray[np.float32]


def load_terms(name: str) -> list[str]:
    path = DATA_DIR / f"{name}.txt"
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def _cache_key(model_id: str, name: str, terms: list[str]) -> str:
    digest = hashlib.sha256((model_id + "\n" + "\n".join(terms)).encode("utf-8")).hexdigest()[:16]
    return f"{name}-{digest}.npy"


class LabelTable:
    """Text embeddings for one term list, computed in chunks and cached on disk
    (clip-interrogator's LabelTable, safetensors swapped for .npy)."""

    def __init__(self, terms: list[str], name: str, embed_texts: Any, model_id: str, cache_dir: Path | None) -> None:
        self.terms = terms
        self.name = name
        self.embeddings: FloatArray = np.zeros((0, 0), dtype=np.float32)
        cache_path = cache_dir / _cache_key(model_id, name, terms) if cache_dir else None
        if cache_path is not None and cache_path.is_file():
            self.embeddings = cast(FloatArray, np.load(cache_path))
            return
        chunks: list[FloatArray] = []
        for start in range(0, len(terms), _CHUNK):
            chunks.append(embed_texts(terms[start : start + _CHUNK]))
        if chunks:
            self.embeddings = np.concatenate(chunks, axis=0).astype(np.float32)
        if cache_path is not None and self.embeddings.size:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache_path, self.embeddings)

    def rank(self, image_features: FloatArray, top_count: int = 1) -> list[tuple[str, float]]:
        """clip-interrogator `_rank`: cosine similarity, best first."""
        if not self.embeddings.size:
            return []
        sims = self.embeddings @ image_features
        top = np.argsort(-sims)[:top_count]
        return [(self.terms[int(i)], float(sims[int(i)])) for i in top]

    def rank_top(self, image_features: FloatArray) -> tuple[str, float]:
        ranked = self.rank(image_features, 1)
        return ranked[0] if ranked else ("", 0.0)


class ClipTagger:
    name = "clip"

    def __init__(self, model_id: str = DEFAULT_CLIP_MODEL, *, cache_dir: Path | None = None, device: str = "auto", flavor_count: int = 2048) -> None:
        self.model_id = model_id
        self._cache_dir = cache_dir
        self._device = device
        self._model: Any = None
        self._processor: Any = None
        self._tables: dict[str, LabelTable] = {}
        #: Low-VRAM knob (clip-interrogator `flavor_intermediate_count`): rank a
        #: subset of the 100k flavors so the tables fit in memory quickly.
        self._flavor_count = flavor_count

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import CLIPModel, CLIPProcessor  # pyright: ignore[reportUnknownVariableType]

        device = self._device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        kwargs: dict[str, Any] = {}
        if self._cache_dir is not None:
            kwargs["cache_dir"] = str(self._cache_dir / "hf")
        logger.info("Loading CLIP %s on %s", self.model_id, device)
        self._processor = CLIPProcessor.from_pretrained(self.model_id, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._model = CLIPModel.from_pretrained(self.model_id, **kwargs).to(device).eval()  # pyright: ignore[reportUnknownMemberType]
        self._device = device

    def unload(self) -> None:
        self._model = None
        self._processor = None
        self._tables.clear()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def _embed_texts(self, texts: list[str]) -> FloatArray:
        import torch

        self.load()
        inputs = self._processor(text=texts, return_tensors="pt", padding=True, truncation=True).to(self._device)
        with torch.inference_mode():
            features = self._model.get_text_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        return cast(FloatArray, features.float().cpu().numpy())

    def image_features(self, image: Image.Image) -> FloatArray:
        import torch

        self.load()
        inputs = self._processor(images=image, return_tensors="pt").to(self._device)
        with torch.inference_mode():
            features = self._model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        return cast(FloatArray, features[0].float().cpu().numpy())

    def image_embedding(self, image: Image.Image) -> EmbeddingResult:
        return EmbeddingResult(kind="clip", model=self.model_id, vector=[float(v) for v in self.image_features(image)])

    def _table(self, name: str) -> LabelTable:
        table = self._tables.get(name)
        if table is None:
            terms = load_terms(name)
            if name == "flavors" and self._flavor_count and len(terms) > self._flavor_count:
                terms = terms[: self._flavor_count]
            table = LabelTable(terms, name, self._embed_texts, self.model_id, self._cache_dir / "clip-tables" if self._cache_dir else None)
            self._tables[name] = table
        return table

    def chain(self, image_features: FloatArray, seed: str, candidates: list[str], max_count: int = 8) -> list[str]:
        """clip-interrogator `chain`: greedily append the term that most
        improves similarity of the whole phrase to the image."""
        chosen: list[str] = []
        best_sim = self._phrase_similarity(image_features, seed)
        pool = list(candidates)
        for _ in range(max_count):
            if not pool:
                break
            phrases = [", ".join(filter(None, [seed, *chosen, term])) for term in pool]
            sims = self._embed_texts(phrases) @ image_features
            index = int(np.argmax(sims))
            if float(sims[index]) <= best_sim:
                break
            best_sim = float(sims[index])
            chosen.append(pool.pop(index))
        return chosen

    def _phrase_similarity(self, image_features: FloatArray, phrase: str) -> float:
        if not phrase:
            return -1.0
        return float(self._embed_texts([phrase])[0] @ image_features)

    def tags(self, image: Image.Image, top_k: int = 12, *, caption_seed: str = "") -> TagResult:
        """Classic ordering: medium, artist, movement, then chained flavors;
        negatives are the best-matching negative terms (so a compiler can
        put them in the negative prompt)."""
        features = self.image_features(image)
        medium = self._table("mediums").rank_top(features)
        movement = self._table("movements").rank_top(features)
        artists = self._table("artists").rank(features, 3)
        flavors = self._table("flavors").rank(features, max(32, top_k * 3))
        negatives = self._table("negative").rank(features, 5)
        scored: list[TagScore] = []
        if medium[0]:
            scored.append(TagScore(term=medium[0], score=round(medium[1], 4), category="medium"))
        if movement[0]:
            scored.append(TagScore(term=movement[0], score=round(movement[1], 4), category="movement"))
        scored.extend(TagScore(term=t, score=round(s, 4), category="artist") for t, s in artists[:2])
        chained = self.chain(features, caption_seed or medium[0], [t for t, _ in flavors], max_count=max(4, top_k - len(scored)))
        flavor_scores = dict(flavors)
        scored.extend(TagScore(term=t, score=round(flavor_scores.get(t, 0.0), 4), category="flavor") for t in chained)
        remaining = [t for t, _ in flavors if t not in chained]
        for term in remaining:
            if len(scored) >= top_k:
                break
            scored.append(TagScore(term=term, score=round(flavor_scores[term], 4), category="flavor"))
        return TagResult(
            model=self.model_id,
            tags=scored[:top_k],
            negatives=[TagScore(term=t, score=round(s, 4), category="negative") for t, s in negatives],
        )
