"""Vision facade: settings-aware access to the local vision stack, the
optional VLM slot (independent of the AI Director — fixes the text-only
Director breaking image analysis), a content-hash cache, and VRAM
arbitration for every render path.

Analyzers call `analyze()`; render handlers call `render_scope()`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from _routes._errors import HTTPError
from film.llm_providers import LLMProvider, OpenAICompatibleProvider
from handlers.base import StateHandlerBase
from services.http_client.http_client import HTTPClient
from services.vision.depth import depth_median_in_box, read_depth_png
from services.vision.protocol import (
    CaptionResult,
    DepthResult,
    MeasuredStats,
    TagResult,
    VisionRegion,
    VisionService,
    VisionStatus,
)
from services.vram.vram_manager import RenderScope, VramError, VramManager
from state.app_settings import AppSettings, VisionSettings

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1
_OLLAMA_DEFAULT_VLMS = ("qwen3-vl:4b", "qwen2.5vl:3b")


class VisionAnalysis(BaseModel):
    """Everything the local stack could measure or read from one image."""

    image_path: str
    content_hash: str
    measured: MeasuredStats
    caption: CaptionResult | None = None
    regions: list[VisionRegion] = Field(default_factory=list[VisionRegion])
    tags: TagResult | None = None
    depth: DepthResult | None = None
    #: Component name → why it produced nothing (disabled, failed, unavailable).
    notes: dict[str, str] = Field(default_factory=dict[str, str])

    @property
    def subject_labels(self) -> list[str]:
        return [r.label for r in self.regions if r.label]


class VramStatus(BaseModel):
    free_mb: int | None
    total_mb: int | None
    loaded: list[str]
    ollama_model: str


class VisionHandler(StateHandlerBase):
    def __init__(
        self,
        *,
        state: Any,
        lock: Any,
        vision: VisionService,
        vram: VramManager,
        http: HTTPClient,
        cache_dir: Path,
        outputs_dir: Path,
    ) -> None:
        super().__init__(state, lock)
        self.vision = vision
        self.vram = vram
        self._http = http
        self._cache_dir = cache_dir
        self._outputs_dir = outputs_dir
        self.apply_settings()

    # ---- settings -----------------------------------------------------------

    def settings(self) -> VisionSettings:
        with self.lock:
            return self.state.app_settings.vision.model_copy(deep=True)

    def apply_settings(self, settings: AppSettings | None = None) -> None:
        """Push the current settings into the service and the VRAM manager.
        Called at startup and after every settings change."""
        current = settings.vision if settings is not None else self.settings()
        configure = getattr(self.vision, "configure", None)
        if callable(configure):
            from services.vision.local_vision import VisionConfig

            configure(
                VisionConfig(
                    florence_enabled=current.enabled and current.florence_enabled,
                    florence_model=current.florence_model,
                    clip_enabled=current.enabled and current.clip_enabled,
                    clip_model=current.clip_model,
                    depth_enabled=current.enabled and current.depth_enabled,
                    depth_model=current.depth_model,
                    dino_enabled=current.enabled and current.dino_enabled,
                    dino_model=current.dino_model,
                    cache_dir=Path(current.cache_dir) if current.cache_dir else self._cache_dir / "models",
                )
            )
        root, model = self._ollama_target(current)
        self.vram.set_ollama(root, model)

    def _ollama_target(self, current: VisionSettings) -> tuple[str, str]:
        if current.vlm_provider != "ollama":
            return "", ""
        root = current.vlm_base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        return root, current.vlm_model or self._default_ollama_model(root)

    def _default_ollama_model(self, root: str) -> str:
        """qwen3-vl:4b if Ollama has it, else qwen2.5vl:3b (the 12 GB-safe picks)."""
        try:
            response = self._http.get(f"{root}/api/tags", timeout=3)
            if response.status_code == 200:
                payload = cast(dict[str, Any], response.json())
                names = {str(cast(dict[str, Any], m).get("name", "")) for m in cast(list[Any], payload.get("models", []))}
                for candidate in _OLLAMA_DEFAULT_VLMS:
                    if candidate in names:
                        return candidate
        except Exception:  # noqa: BLE001 - Ollama not running is fine
            pass
        return _OLLAMA_DEFAULT_VLMS[1]

    # ---- VLM slot (D9) ------------------------------------------------------

    def optional_vlm(self, director_fallback: LLMProvider | None = None) -> LLMProvider | None:
        """The vision-language model for analysis, or None. Independent of the
        AI Director unless the user explicitly picks `director`."""
        current = self.settings()
        if not current.enabled or current.vlm_provider == "off":
            return None
        if current.vlm_provider == "director":
            return director_fallback
        with self.lock:
            app = self.state.app_settings
        if current.vlm_provider == "ollama":
            root, model = self._ollama_target(current)
            if not root or not model:
                return None
            return OpenAICompatibleProvider(self._http, "ollama", model, base_url=f"{root}/v1", name="ollama")
        base_url = current.vlm_base_url.rstrip("/") or app.openai_compatible_base_url.rstrip("/")
        model = current.vlm_model or app.openai_compatible_model
        if not base_url or not model:
            return None
        return OpenAICompatibleProvider(self._http, app.openai_compatible_api_key or "local", model, base_url=base_url, name="openai_compatible")

    # ---- analysis -----------------------------------------------------------

    @staticmethod
    def content_hash(image_path: str) -> str:
        digest = hashlib.sha256()
        with open(image_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()[:24]

    def _cache_file(self, content_hash: str) -> Path:
        return self._cache_dir / f"{content_hash}.v{_CACHE_VERSION}.json"

    def analyze(
        self,
        image_path: str,
        *,
        want_caption: bool = True,
        want_regions: bool = True,
        want_tags: bool = True,
        want_depth: bool = True,
        depth_dir: Path | None = None,
        use_cache: bool = True,
    ) -> VisionAnalysis:
        """Run the offline stack on one image. Each component that fails or is
        disabled leaves a note instead of failing the whole analysis; the
        measured stats always succeed. Results are cached by content hash."""
        path = Path(image_path)
        if not path.is_file():
            raise HTTPError(400, f"Image not found: {image_path}")
        content_hash = self.content_hash(image_path)
        cache_file = self._cache_file(content_hash)
        if use_cache and cache_file.is_file():
            try:
                cached = VisionAnalysis.model_validate_json(cache_file.read_text(encoding="utf-8"))
                if self._cache_satisfies(cached, want_caption, want_regions, want_tags, want_depth):
                    return cached
            except Exception as exc:  # noqa: BLE001 - a bad cache entry is recomputed
                logger.info("Ignoring unreadable vision cache %s: %s", cache_file, exc)

        current = self.settings()
        result = VisionAnalysis(image_path=str(path), content_hash=content_hash, measured=self.vision.stats(str(path)))
        if not current.enabled:
            result.notes["vision"] = "disabled"
            return result
        if want_caption:
            try:
                result.caption = self.vision.caption(str(path), "more_detailed_caption")
            except Exception as exc:  # noqa: BLE001
                result.notes["caption"] = str(exc)
        if want_regions:
            try:
                result.regions = self.vision.detect(str(path), "od").regions
            except Exception as exc:  # noqa: BLE001
                result.notes["regions"] = str(exc)
        if want_tags:
            try:
                result.tags = self.vision.tags(str(path), 12)
            except Exception as exc:  # noqa: BLE001
                result.notes["tags"] = str(exc)
        if want_depth:
            target_dir = depth_dir or (self._cache_dir / "depth")
            target = target_dir / f"{content_hash}.png"
            try:
                result.depth = self.vision.depth(str(path), str(target))
                if result.regions:
                    depth01 = read_depth_png(target)
                    for region in result.regions:
                        region.depth_median = depth_median_in_box(depth01, region.bbox)
            except Exception as exc:  # noqa: BLE001
                result.notes["depth"] = str(exc)
        if use_cache:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(result.model_dump_json(), encoding="utf-8")
            except OSError as exc:
                logger.info("Could not write vision cache: %s", exc)
        return result

    @staticmethod
    def _cache_satisfies(cached: VisionAnalysis, caption: bool, regions: bool, tags: bool, depth: bool) -> bool:
        if caption and cached.caption is None and "caption" not in cached.notes:
            return False
        if regions and not cached.regions and "regions" not in cached.notes:
            return False
        if tags and cached.tags is None and "tags" not in cached.notes:
            return False
        if depth and (cached.depth is None or not Path(cached.depth.depth_png).is_file()) and "depth" not in cached.notes:
            return False
        return True

    def embed(self, image_path: str, kind: str = "clip") -> list[float]:
        return self.vision.embed(image_path, "dino" if kind == "dino" else "clip").vector

    # ---- status / control ---------------------------------------------------

    def status(self) -> VisionStatus:
        return self.vision.status()

    def vram_status(self) -> VramStatus:
        memory = self.vram.memory_mb()
        used, total = memory if memory is not None else (None, None)
        return VramStatus(
            free_mb=(total - used) if used is not None and total is not None else None,
            total_mb=total,
            loaded=[m.name for m in self.vram.loaded()],
            ollama_model=self.vram._ollama_model,  # pyright: ignore[reportPrivateUsage]
        )

    def unload(self) -> list[str]:
        return self.vision.unload()

    # ---- render arbitration -------------------------------------------------

    def prepare_for_render(self, model_type: str) -> None:
        """Raise an actionable HTTPError instead of letting CUDA OOM."""
        try:
            self.vram.prepare_for_render(model_type)
        except VramError as exc:
            raise HTTPError(507, str(exc)) from exc

    @contextmanager
    def render_scope(self, model_type: str) -> Iterator[RenderScope]:
        try:
            with self.vram.render_scope(model_type) as scope:
                yield scope
        except VramError as exc:
            raise HTTPError(507, str(exc)) from exc

    def cache_summary(self) -> dict[str, int]:
        files = list(self._cache_dir.glob("*.json")) if self._cache_dir.is_dir() else []
        return {"entries": len(files), "bytes": sum(f.stat().st_size for f in files)}

    def clear_cache(self) -> int:
        removed = 0
        if self._cache_dir.is_dir():
            for file in self._cache_dir.glob("*.json"):
                file.unlink(missing_ok=True)
                removed += 1
        return removed

    @staticmethod
    def to_json(analysis: VisionAnalysis) -> dict[str, Any]:
        return json.loads(analysis.model_dump_json())
