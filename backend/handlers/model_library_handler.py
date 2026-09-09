"""The Model Library: one searchable catalog over every model this app can use.

Three kinds of entry live side by side so the same screen answers both "what
can I run offline?" and "what can I reach with a key?":

* **local weights** — the WanGP checkout's own model definitions (video/image)
  and the native LTX pipeline's files. These are the fully offline path, and
  the ones this handler can actually download.
* **local text** — whatever the configured OpenAI-compatible server (LM Studio,
  vLLM, Ollama) is serving. Ollama can also pull new models from here.
* **hosted** — the text and media models the configured providers offer.

Every source is optional and independent: one unreachable provider adds an
error line to ``sources`` and the rest of the library still lists.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import cast

from api_types import (
    LibraryDownloadStatus,
    LibraryModel,
    LibrarySourceStatus,
    LibraryTask,
    ModelSearchResponse,
)
from _routes._errors import HTTPError
from film.film_models import now_ms
from film.llm_providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    OpenRouterModel,
    XAIProvider,
    gemini_list_models,
    openrouter_list_models,
)
from film.media_providers import (
    HOSTED_PROVIDERS,
    PROVIDER_CATALOG_URLS,
    MediaModel,
    curated_models,
    media_provider,
)
from handlers.base import StateHandlerBase
from runtime_config.model_download_specs import MODEL_FILE_ORDER
from runtime_config.runtime_config import RuntimeConfig
from services.interfaces import GpuInfo, HTTPClient, HttpTimeoutError, ModelDownloader, TaskRunner
from services.wangp_bridge import WanGPBridge
from state.app_settings import AppSettings
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

# Weights referenced by a WanGP model definition. Anything served from the Hub
# can be fetched here; other hosts stay "managed by WanGP" (it downloads them
# itself on first use).
_HF_RESOLVE = re.compile(r"^https://huggingface\.co/(?P<repo>[^/]+/[^/]+)/resolve/(?P<rev>[^/]+)/(?P<path>.+)$")

_CACHE_TTL_MS = 10 * 60 * 1000

_SOURCE_LABELS: dict[str, str] = {
    "wangp": "Local · WanGP models",
    "native": "Local · LTX pipeline",
    "ollama": "Local · Ollama",
    "openai_compatible": "Local · OpenAI-compatible server",
    "openrouter": "OpenRouter",
    "anthropic": "Claude (Anthropic)",
    "xai": "Grok (xAI)",
    "gemini": "Gemini (Google)",
    "fal": "fal.ai",
    "wavespeed": "WaveSpeed AI",
    "replicate": "Replicate",
}

_TEXT_PROVIDER_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/models",
    "anthropic": "https://docs.anthropic.com/en/docs/about-claude/models",
    "xai": "https://docs.x.ai/docs/models",
    "gemini": "https://ai.google.dev/gemini-api/docs/models",
    "ollama": "https://ollama.com/library",
}


@dataclass
class _Download:
    provider: str
    model_id: str
    files_total: int = 0
    files_done: int = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    status: str = "running"
    error: str = ""
    message: str = ""
    cancel_requested: bool = False
    started_ms: int = field(default_factory=now_ms)


class ModelLibraryHandler(StateHandlerBase):
    """Search, download and remember models. Owns no generation state."""

    def __init__(
        self,
        state: AppState,
        lock: RLock,
        config: RuntimeConfig,
        wangp_bridge: WanGPBridge,
        http: HTTPClient,
        gpu_info: GpuInfo,
        task_runner: TaskRunner,
        model_downloader: ModelDownloader,
    ) -> None:
        super().__init__(state, lock)
        self._config = config
        self._wangp = wangp_bridge
        self._http = http
        self._gpu_info = gpu_info
        self._task_runner = task_runner
        self._downloader = model_downloader
        self._cache: dict[str, tuple[int, list[LibraryModel]]] = {}
        self._download: _Download | None = None

    # ---- helpers ---------------------------------------------------------

    def _settings(self) -> AppSettings:
        with self.lock:
            return self.state.app_settings.model_copy(deep=True)

    def _vram_gb(self) -> float | None:
        total = self._gpu_info.get_vram_total_gb()
        return float(total) if total is not None else None

    @staticmethod
    def _fits(vram_gb: float | None, minimum: float | None) -> bool | None:
        if vram_gb is None or minimum is None:
            return None
        return vram_gb >= minimum

    def _cached(self, key: str, refresh: bool) -> list[LibraryModel] | None:
        if refresh:
            return None
        entry = self._cache.get(key)
        if entry is None or now_ms() - entry[0] > _CACHE_TTL_MS:
            return None
        return entry[1]

    def _store(self, key: str, models: list[LibraryModel]) -> list[LibraryModel]:
        self._cache[key] = (now_ms(), models)
        return models

    @staticmethod
    def _ollama_root(base_url: str) -> str:
        """Ollama's native API sits next to its OpenAI-compatible /v1 shim."""
        trimmed = base_url.strip().rstrip("/")
        if trimmed.endswith("/v1"):
            trimmed = trimmed[: -len("/v1")]
        return trimmed

    # ---- local sources ---------------------------------------------------

    def _wangp_models(self, vram_gb: float | None) -> list[LibraryModel]:
        definitions = self._wangp.list_model_definitions()
        active = {self._config.wangp_video_model_type, self._config.wangp_image_model_type}
        models: list[LibraryModel] = []
        for definition in definitions:
            model_id = str(definition.get("id", ""))
            architecture = str(definition.get("architecture", "") or model_id)
            task = _wangp_task(architecture)
            if task is None:
                continue
            installed = bool(definition.get("installed", False))
            urls_raw = definition.get("urls", [])
            urls = [str(u) for u in cast(list[object], urls_raw)] if isinstance(urls_raw, list) else []
            downloadable = any(_HF_RESOLVE.match(url) for url in urls)
            minimum = 6.0 if task in ("video", "image") else None
            fits = self._fits(vram_gb, minimum)
            quant_raw = definition.get("quantized_variants", [])
            quant = ", ".join(str(q) for q in cast(list[object], quant_raw)) if isinstance(quant_raw, list) else ""
            is_active = model_id in active
            models.append(
                LibraryModel(
                    id=model_id,
                    name=str(definition.get("name", model_id) or model_id),
                    provider="wangp",
                    source="local",
                    task=task,
                    description=str(definition.get("description", ""))[:200],
                    state="active" if is_active else "installed" if installed else "incompatible" if fits is False else "available",
                    installed=installed,
                    downloadable=downloadable and not installed,
                    estimated_min_vram_gb=minimum,
                    fits_gpu=fits,
                    supports_image_input=task == "video",
                    family=architecture,
                    quantization=quant,
                )
            )
        return models

    def _native_models(self, vram_gb: float | None) -> list[LibraryModel]:
        """The bundled LTX pipeline's own files (checkpoint/upsampler/encoder)."""
        if self._config.wangp_enabled:
            return []
        with self.lock:
            available = dict(self.state.available_files)
        models: list[LibraryModel] = []
        for model_type in MODEL_FILE_ORDER:
            spec = self._config.spec_for(model_type)
            installed = available.get(model_type) is not None
            is_video = model_type in ("checkpoint", "upsampler", "text_encoder")
            minimum = 32.0 if is_video else None
            fits = self._fits(vram_gb, minimum)
            models.append(
                LibraryModel(
                    id=model_type,
                    name=spec.description,
                    provider="native",
                    source="local",
                    task="video" if is_video else "image",
                    description="Bundled LTX pipeline weights",
                    state="installed" if installed else "incompatible" if fits is False else "available",
                    installed=installed,
                    downloadable=not installed,
                    size_gb=round(spec.expected_size_bytes / 1_000_000_000, 1),
                    estimated_min_vram_gb=minimum,
                    fits_gpu=fits,
                    family="ltx",
                )
            )
        return models

    def _ollama_tags(self, root: str) -> list[LibraryModel] | None:
        """Locally pulled Ollama models, or None when this is not Ollama."""
        try:
            response = self._http.get(f"{root}/api/tags", timeout=8)
        except Exception:  # noqa: BLE001 - not Ollama, or not running
            return None
        if response.status_code != 200:
            return None
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        rows = cast(dict[str, object], payload).get("models", [])
        models: list[LibraryModel] = []
        for row in cast(list[object], rows if isinstance(rows, list) else []):
            if not isinstance(row, dict):
                continue
            entry = cast(dict[str, object], row)
            name = str(entry.get("name", "") or entry.get("model", "") or "")
            if not name:
                continue
            size = entry.get("size")
            details = entry.get("details")
            quant = ""
            if isinstance(details, dict):
                quant = str(cast(dict[str, object], details).get("quantization_level", "") or "")
            models.append(
                LibraryModel(
                    id=name,
                    name=name,
                    provider="ollama",
                    source="local",
                    task="text",
                    description="Pulled locally — runs with no network",
                    state="installed",
                    installed=True,
                    size_gb=round(float(cast(float, size)) / 1_000_000_000, 1) if isinstance(size, (int, float)) else None,
                    quantization=quant,
                )
            )
        return models

    def _local_text_models(self, settings: AppSettings, refresh: bool) -> tuple[str, list[LibraryModel], str]:
        """(source id, models, error) for the configured local text server."""
        base = settings.openai_compatible_base_url.strip()
        if not base:
            return "openai_compatible", [], ""
        cache_key = f"local-text:{base}"
        cached = self._cached(cache_key, refresh)
        root = self._ollama_root(base)
        if cached is not None:
            return ("ollama" if cached and cached[0].provider == "ollama" else "openai_compatible"), cached, ""
        pulled = self._ollama_tags(root)
        if pulled is not None:
            return "ollama", self._store(cache_key, pulled), ""
        try:
            provider = OpenAICompatibleProvider(self._http, settings.openai_compatible_api_key.strip(), "", base_url=base)
            served = provider.list_models()
        except HTTPError as exc:
            return "openai_compatible", [], str(exc.detail)
        models = [
            LibraryModel(
                id=model.id,
                name=model.name or model.id,
                provider="openai_compatible",
                source="local",
                task="text",
                description="Served by your local endpoint",
                state="installed",
                installed=True,
                context_length=model.context_length,
            )
            for model in served
        ]
        return "openai_compatible", self._store(cache_key, models), ""

    # ---- hosted sources --------------------------------------------------

    def _hosted_text(self, provider_id: str, settings: AppSettings, refresh: bool) -> tuple[list[LibraryModel], str]:
        key = {
            "openrouter": settings.resolved_openrouter_api_key(),
            "anthropic": settings.anthropic_api_key.strip(),
            "xai": settings.xai_api_key.strip(),
            "gemini": settings.gemini_api_key.strip(),
        }[provider_id]
        if not key:
            return [], ""
        cache_key = f"text:{provider_id}"
        cached = self._cached(cache_key, refresh)
        if cached is not None:
            return cached, ""
        try:
            listed: list[OpenRouterModel]
            if provider_id == "openrouter":
                listed = openrouter_list_models(self._http, key)
            elif provider_id == "anthropic":
                listed = AnthropicProvider(self._http, key).list_models()
            elif provider_id == "xai":
                listed = XAIProvider(self._http, key).list_models()
            else:
                listed = gemini_list_models(self._http, key)
        except HTTPError as exc:
            return [], str(exc.detail)
        models = [
            LibraryModel(
                id=model.id,
                name=model.name or model.id,
                provider=provider_id,
                source="hosted",
                task="text",
                description=(f"{model.prompt_price}/{model.completion_price} per token" if model.prompt_price else ""),
                state="available",
                context_length=model.context_length,
                supports_image_input=False,
                url=_TEXT_PROVIDER_URLS.get(provider_id, ""),
            )
            for model in listed
        ]
        return self._store(cache_key, models), ""

    def _hosted_media(self, provider_id: str, settings: AppSettings, refresh: bool) -> tuple[list[LibraryModel], str]:
        api_key = settings.media_api_key(provider_id)
        catalog_url = PROVIDER_CATALOG_URLS.get(provider_id, "")
        entries: list[MediaModel] = curated_models(provider_id)
        error = ""
        if api_key:
            cache_key = f"media:{provider_id}"
            cached_media = self._cached(cache_key, refresh)
            if cached_media is None:
                try:
                    discovered = media_provider(provider_id, self._http, api_key).discover()
                except HTTPError as exc:
                    discovered = []
                    error = str(exc.detail)
                known = {entry.id for entry in discovered}
                entries = discovered + [entry for entry in entries if entry.id not in known]
                self._store(
                    cache_key,
                    [self._media_row(entry, bool(api_key), catalog_url) for entry in entries],
                )
            else:
                return cached_media, ""
        return [self._media_row(entry, bool(api_key), catalog_url) for entry in entries], error

    @staticmethod
    def _media_row(entry: MediaModel, configured: bool, catalog_url: str) -> LibraryModel:
        return LibraryModel(
            id=entry.id,
            name=entry.name,
            provider=entry.provider,
            source="hosted",
            task=entry.task,
            description=entry.description,
            # Without a key the row cannot be used at all, whatever its origin;
            # with one, an example id still says so because it may be stale.
            state="needs_key" if not configured else "example" if entry.curated else "available",
            supports_image_input=entry.supports_image_input,
            curated=entry.curated,
            url=entry.url or catalog_url,
        )

    def _remembered(self, settings: AppSettings) -> list[LibraryModel]:
        """Model ids the user typed before, so they stay one click away."""
        rows: list[LibraryModel] = []
        for raw in settings.recent_model_ids[:40]:
            provider, _, model_id = raw.partition(":")
            if not model_id:
                continue
            task: LibraryTask = "text" if provider in ("openrouter", "anthropic", "xai", "gemini", "ollama", "openai_compatible") else "video"
            rows.append(
                LibraryModel(
                    id=model_id,
                    name=model_id,
                    provider=provider,
                    source="local" if provider in ("wangp", "native", "ollama", "openai_compatible") else "hosted",
                    task=task,
                    description="Used before in this app",
                    state="available",
                )
            )
        return rows

    # ---- search ----------------------------------------------------------

    def search(
        self,
        *,
        query: str = "",
        task: str = "all",
        source: str = "all",
        only_compatible: bool = False,
        refresh: bool = False,
        limit: int = 200,
    ) -> ModelSearchResponse:
        settings = self._settings()
        vram_gb = self._vram_gb()
        collected: list[LibraryModel] = []
        sources: list[LibrarySourceStatus] = []

        def add_source(source_id: str, kind: str, configured: bool, models: list[LibraryModel], error: str = "") -> None:
            collected.extend(models)
            sources.append(
                LibrarySourceStatus(
                    id=source_id,
                    label=_SOURCE_LABELS.get(source_id, source_id),
                    kind="local" if kind == "local" else "hosted",
                    configured=configured,
                    count=len(models),
                    error=error,
                    catalog_url=PROVIDER_CATALOG_URLS.get(source_id, _TEXT_PROVIDER_URLS.get(source_id, "")),
                )
            )

        wangp_models = self._wangp_models(vram_gb) if self._config.wangp_enabled else []
        add_source("wangp", "local", self._config.wangp_enabled and bool(wangp_models), wangp_models)
        native_models = self._native_models(vram_gb)
        if native_models:
            add_source("native", "local", True, native_models)
        text_source, local_text, local_text_error = self._local_text_models(settings, refresh)
        add_source(text_source, "local", bool(settings.openai_compatible_base_url.strip()), local_text, local_text_error)

        for provider_id in ("openrouter", "anthropic", "xai", "gemini"):
            models, error = self._hosted_text(provider_id, settings, refresh)
            configured = bool(
                {
                    "openrouter": settings.resolved_openrouter_api_key(),
                    "anthropic": settings.anthropic_api_key.strip(),
                    "xai": settings.xai_api_key.strip(),
                    "gemini": settings.gemini_api_key.strip(),
                }[provider_id]
            )
            add_source(provider_id, "hosted", configured, models, error)

        for provider_id in HOSTED_PROVIDERS:
            models, error = self._hosted_media(provider_id, settings, refresh)
            add_source(provider_id, "hosted", bool(settings.media_api_key(provider_id)), models, error)

        known = {(model.provider, model.id) for model in collected}
        collected.extend(row for row in self._remembered(settings) if (row.provider, row.id) not in known)

        needle = query.strip().lower()
        filtered = [
            model
            for model in collected
            if (task == "all" or model.task == task)
            and (source == "all" or model.source == source)
            and (not only_compatible or model.fits_gpu is not False)
            and (
                not needle
                or needle in model.id.lower()
                or needle in model.name.lower()
                or needle in model.provider.lower()
                or needle in model.family.lower()
                or needle in model.description.lower()
            )
        ]
        order = {"active": 0, "installed": 1, "available": 2, "example": 3, "needs_key": 4, "incompatible": 5}
        filtered.sort(key=lambda m: (0 if m.source == "local" else 1, order.get(m.state, 6), m.provider, m.id))

        has_local_media = any(m.source == "local" and m.task in ("video", "image") and m.installed for m in collected)
        has_local_text = any(m.source == "local" and m.task == "text" and m.installed for m in collected)
        if has_local_media and has_local_text:
            note = "Everything needed for an offline film is installed."
        elif has_local_media:
            note = "Local video is installed. Add a local text model (Ollama or LM Studio) for an offline AI Director."
        elif has_local_text:
            note = "A local text model is available. Download a local video model for offline generation."
        else:
            note = "No local models installed yet — download a video model and connect a local text server to work offline."

        return ModelSearchResponse(
            models=filtered[: max(1, limit)],
            total=len(filtered),
            sources=sources,
            gpu_name=self._gpu_info.get_device_name(),
            gpu_vram_gb=vram_gb,
            models_path=self._models_path(),
            offline_ready=has_local_media and has_local_text,
            offline_note=note,
        )

    def _models_path(self) -> str:
        if self._config.wangp_enabled and self._config.wangp_root is not None:
            return str(self._config.wangp_root / "ckpts")
        return str(self._config.models_dir)

    # ---- remembering user-typed ids --------------------------------------

    def remember(self, provider: str, model_id: str) -> None:
        entry = f"{provider}:{model_id}".strip()
        if not model_id.strip():
            return
        with self.lock:
            settings = self.state.app_settings
            remaining = [item for item in settings.recent_model_ids if item != entry]
            settings.recent_model_ids = [entry, *remaining][:40]

    # ---- downloads -------------------------------------------------------

    def download_status(self) -> LibraryDownloadStatus:
        with self.lock:
            current = self._download
            if current is None:
                return LibraryDownloadStatus()
            total = current.total_bytes
            progress = (current.downloaded_bytes / total) if total > 0 else 0.0
            if current.status == "complete":
                progress = 1.0
            return LibraryDownloadStatus(
                active=current.status == "running",
                provider=current.provider,
                model_id=current.model_id,
                status=current.status,
                files_total=current.files_total,
                files_done=current.files_done,
                downloaded_bytes=current.downloaded_bytes,
                total_bytes=total,
                progress=round(min(1.0, max(0.0, progress)), 4),
                error=current.error,
                message=current.message,
            )

    def cancel_download(self) -> LibraryDownloadStatus:
        with self.lock:
            if self._download is not None and self._download.status == "running":
                self._download.cancel_requested = True
                self._download.message = "Cancelling after the current file…"
        return self.download_status()

    def start_download(self, provider: str, model_id: str) -> LibraryDownloadStatus:
        """Fetch a model's weights. Only local sources can be downloaded: a
        hosted model has nothing to install."""
        with self.lock:
            if self._download is not None and self._download.status == "running":
                raise HTTPError(409, "A model download is already running")
        if provider == "wangp":
            return self._start_wangp_download(model_id)
        if provider == "ollama":
            return self._start_ollama_pull(model_id)
        if provider == "native":
            raise HTTPError(
                400,
                "The bundled LTX weights are downloaded together — use “Download missing models” in the Models tab.",
            )
        raise HTTPError(400, f"{provider} models run in the cloud — there is nothing to download. Add the API key instead.")

    def _start_wangp_download(self, model_id: str) -> LibraryDownloadStatus:
        root = self._config.wangp_root
        if not self._config.wangp_enabled or root is None:
            raise HTTPError(400, "WanGP is not configured, so local model weights cannot be downloaded")
        definition = next(
            (d for d in self._wangp.list_model_definitions() if str(d.get("id", "")) == model_id),
            None,
        )
        if definition is None:
            raise HTTPError(404, f"Unknown WanGP model: {model_id}")
        urls_raw = definition.get("urls", [])
        urls = [str(u) for u in cast(list[object], urls_raw)] if isinstance(urls_raw, list) else []
        targets = [(match.group("repo"), match.group("path")) for match in (_HF_RESOLVE.match(url) for url in urls) if match]
        if not targets:
            raise HTTPError(
                400,
                "This model's weights are not published on Hugging Face — WanGP downloads them itself the first time the model runs.",
            )
        # One quantisation is enough: prefer an int8/fp8 build when the catalog
        # offers one, since that is what a 12 GB card can actually load.
        quantised = [target for target in targets if any(tag in target[1] for tag in ("int8", "fp8", "nvfp4"))]
        chosen = quantised or targets
        destination = root / "ckpts"
        state = _Download(provider="wangp", model_id=model_id, files_total=len(chosen), message="Starting…")
        with self.lock:
            self._download = state
        self._task_runner.run_background(
            lambda: self._run_wangp_download(state, chosen, destination),
            task_name=f"library-download-{model_id}",
            on_error=lambda exc: self._fail_download(state, str(exc)),
        )
        return self.download_status()

    def _run_wangp_download(self, state: _Download, targets: list[tuple[str, str]], destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        base_bytes = 0
        for repo_id, filename in targets:
            with self.lock:
                if state.cancel_requested:
                    state.status = "cancelled"
                    state.message = "Cancelled"
                    return
                state.message = f"Downloading {filename}"

            def on_progress(downloaded: int, total: int, _base: int = base_bytes) -> None:
                with self.lock:
                    state.downloaded_bytes = _base + downloaded
                    state.total_bytes = max(state.total_bytes, _base + total)

            try:
                self._downloader.download_file(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(destination),
                    on_progress=on_progress,
                )
            except Exception as exc:  # noqa: BLE001 - report, never crash the worker
                self._fail_download(state, f"{filename}: {exc}")
                return
            with self.lock:
                state.files_done += 1
                base_bytes = state.downloaded_bytes
        with self.lock:
            state.status = "complete"
            state.message = f"{state.model_id} installed"
            state.total_bytes = max(state.total_bytes, state.downloaded_bytes)
        self._cache.pop("wangp", None)
        self.remember("wangp", state.model_id)

    def _start_ollama_pull(self, model_id: str) -> LibraryDownloadStatus:
        settings = self._settings()
        root = self._ollama_root(settings.openai_compatible_base_url)
        if not root:
            raise HTTPError(400, "Set the local endpoint base URL (for example http://127.0.0.1:11434/v1) first")
        state = _Download(provider="ollama", model_id=model_id, files_total=1, message=f"Pulling {model_id}…")
        with self.lock:
            self._download = state
        self._task_runner.run_background(
            lambda: self._run_ollama_pull(state, root, model_id),
            task_name=f"ollama-pull-{model_id}",
            on_error=lambda exc: self._fail_download(state, str(exc)),
        )
        return self.download_status()

    def _run_ollama_pull(self, state: _Download, root: str, model_id: str) -> None:
        try:
            response = self._http.post(
                f"{root}/api/pull",
                headers={"Content-Type": "application/json"},
                json_payload={"model": model_id, "stream": False},
                timeout=3600,
            )
        except HttpTimeoutError:
            self._fail_download(state, "The pull timed out — large models can take a while; check Ollama and retry.")
            return
        except Exception as exc:  # noqa: BLE001 - surface the reason, keep the worker alive
            self._fail_download(state, f"Ollama unreachable: {exc}")
            return
        if response.status_code != 200:
            self._fail_download(state, f"Ollama refused the pull ({response.status_code}): {response.text[:200]}")
            return
        with self.lock:
            state.status = "complete"
            state.files_done = 1
            state.message = f"{model_id} pulled"
        self._cache.clear()
        self.remember("ollama", model_id)

    def _fail_download(self, state: _Download, error: str) -> None:
        logger.warning("Model download failed: %s", error)
        with self.lock:
            state.status = "failed"
            state.error = error


def _wangp_task(architecture: str) -> LibraryTask | None:
    key = architecture.lower()
    if any(tag in key for tag in ("ace_step", "tts", "audio", "vocal")):
        return None
    if any(tag in key for tag in ("flux", "qwen_image", "z_image", "sd", "image")) and "t2v" not in key and "i2v" not in key:
        return "image"
    if any(tag in key for tag in ("llm", "text")):
        return None
    return "video"
