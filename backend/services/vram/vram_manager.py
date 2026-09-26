"""VRAM arbitration for a 12 GB card.

The problem it solves: a vision language model kept warm by Ollama (~6 GB
for five minutes), CLIP, DINO and Florence all loaded from the last analysis,
and then a WanGP render that needs 9–10 GB. Without arbitration that is an
OOM trace; with it, the render asks the manager for headroom first, the
manager unloads what it owns (lowest priority first) and tells Ollama to drop
its model, and if that is still not enough it raises an *actionable* error
("Free 2.1 GB: qwen2.5vl:3b is loaded") instead of letting CUDA fail.

Nothing here imports torch. The GPU is read through `NvmlProbe`; tests use
`FakeNvml`. Ollama is reached through the app's `HTTPClient` so tests can
fake that too.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Protocol

from services.http_client.http_client import HTTPClient

logger = logging.getLogger(__name__)

VRAM_CLASS_MB: dict[str, int] = {"S": 1536, "M": 3072, "L": 8192}

#: What a render needs free, by model type, at the default 4070 profiles.
#: Overridden per model by the `vram_render_needs_mb` setting (AppHandler
#: applies it via `set_overrides` on load and on every settings save).
#:
#: The 12 GB-class video figures are chosen to be ATTAINABLE on a 12 GB card
#: after arbitration (a Windows desktop leaves ~8.9 GB free at best — a
#: higher bar refuses every render the hardware could attempt) and lean on
#: WanGP's block offloading rather than measured peaks. Replace them with
#: measured numbers via the setting once a real run reports its peak.
#: `ltx2_22B` (non-distilled) genuinely does not fit 12 GB and stays refused.
RENDER_NEEDS_MB: dict[str, int] = {
    "ltx2_22B_distilled": 8000,
    "ltx2_22B": 11000,
    "wan2_2_ti2v_5B": 8000,
    "z_image": 7500,
    "qwen_image_edit": 8000,
    "flux": 8000,
    "ltx2-fast": 8000,
    "default": 8000,
}
#: Keep this much free beyond the model's need for activations and the desktop compositor.
SAFETY_MARGIN_MB = 512


class NvmlProbe(Protocol):
    def memory_mb(self) -> tuple[int, int] | None:
        """(used, total) in MB, or None when there is no NVIDIA GPU to ask."""
        ...


class PynvmlProbe:
    """Real probe. pynvml is imported lazily and every failure means 'unknown'."""

    def __init__(self, index: int = 0) -> None:
        self._index = index

    def memory_mb(self) -> tuple[int, int] | None:
        try:
            import pynvml  # type: ignore[reportMissingModuleSource]

            pynvml.nvmlInit()
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(self._index)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                return int(info.used) // (1024 * 1024), int(info.total) // (1024 * 1024)
            finally:
                pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001 - no NVML, no GPU, or a driver mismatch
            return None


class FakeNvml:
    """Test probe: `used_mb` is what the fake GPU reports; unloading a registered
    model (see `VramManager.register`) subtracts its estimate so tests can
    watch the number move."""

    def __init__(self, total_mb: int = 12288, used_mb: int = 1024) -> None:
        self.total_mb = total_mb
        self.used_mb = used_mb
        self.available = True

    def memory_mb(self) -> tuple[int, int] | None:
        if not self.available:
            return None
        return self.used_mb, self.total_mb


@dataclass
class LoadedModel:
    name: str
    vram_class: str
    estimated_mb: int
    unload: Callable[[], None]
    #: Lower unloads first. VLM/CLIP/DINO are cheap to reload; Florence is kept when it fits.
    priority: int = 50


@dataclass
class VramPlan:
    model_type: str
    needed_mb: int
    free_before_mb: int | None
    free_after_mb: int | None
    unloaded: list[str] = field(default_factory=list[str])
    ollama_released: str = ""
    note: str = ""


class VramError(RuntimeError):
    """Raised before a render that cannot fit. `str()` is user-facing and actionable."""

    def __init__(self, needed_mb: int, free_mb: int, still_loaded: list[str], external_hint: str = "") -> None:
        self.needed_mb = needed_mb
        self.free_mb = free_mb
        self.still_loaded = still_loaded
        gap_gb = max(0.1, (needed_mb - free_mb) / 1024)
        loaded = ", ".join(still_loaded) if still_loaded else "nothing this app owns"
        hint = f" {external_hint}" if external_hint else ""
        super().__init__(
            f"Free {gap_gb:.1f} GB of VRAM before rendering: {free_mb / 1024:.1f} GB free, "
            f"{needed_mb / 1024:.1f} GB needed. Loaded: {loaded}.{hint}"
        )


@dataclass
class RenderScope:
    model_type: str
    plan: VramPlan
    peak_mb: int | None = None
    seconds: float = 0.0


class VramManager:
    def __init__(
        self,
        probe: NvmlProbe,
        *,
        http: HTTPClient | None = None,
        render_needs_mb: dict[str, int] | None = None,
        sample_interval_s: float = 0.5,
    ) -> None:
        self._probe = probe
        self._http = http
        self._base_needs = dict(RENDER_NEEDS_MB)
        if render_needs_mb:
            self._base_needs.update(render_needs_mb)
        self._needs = dict(self._base_needs)
        self._lock = threading.RLock()
        self._models: dict[str, LoadedModel] = {}
        self._ollama_root = ""
        self._ollama_model = ""
        self._sample_interval = sample_interval_s

    def set_overrides(self, overrides: dict[str, int]) -> None:
        """Apply the `vram_render_needs_mb` setting on top of the defaults.
        Called on settings load and on every save; passing `{}` restores the
        defaults, so a removed override does not linger."""
        with self._lock:
            self._needs = dict(self._base_needs)
            for model_type, value in overrides.items():
                if value > 0:
                    self._needs[model_type] = int(value)

    # ---- registry -----------------------------------------------------------

    def register(self, name: str, vram_class: str, estimated_mb: int, unload: Callable[[], None], *, priority: int = 50) -> None:
        with self._lock:
            self._models[name] = LoadedModel(name, vram_class, estimated_mb, unload, priority)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._models.pop(name, None)

    def loaded(self) -> list[LoadedModel]:
        with self._lock:
            return sorted(self._models.values(), key=lambda m: m.priority)

    def set_ollama(self, root: str, model: str) -> None:
        """Where the VLM lives, so `prepare_for_render` can ask Ollama to drop it."""
        self._ollama_root = root.rstrip("/")
        self._ollama_model = model.strip()

    # ---- measurements -------------------------------------------------------

    def memory_mb(self) -> tuple[int, int] | None:
        return self._probe.memory_mb()

    def free_mb(self) -> int | None:
        memory = self.memory_mb()
        if memory is None:
            return None
        used, total = memory
        return max(0, total - used)

    def needed_mb(self, model_type: str) -> int:
        base = self._needs.get(model_type)
        if base is None:
            for key, value in self._needs.items():
                if key != "default" and model_type.startswith(key):
                    base = value
                    break
        return (base if base is not None else self._needs["default"]) + SAFETY_MARGIN_MB

    def fits(self, vram_class: str) -> bool | None:
        free = self.free_mb()
        if free is None:
            return None
        return free >= VRAM_CLASS_MB.get(vram_class, VRAM_CLASS_MB["L"])

    # ---- arbitration --------------------------------------------------------

    def release_ollama(self) -> str:
        """`keep_alive: 0` on the configured VLM. Returns the model name released ("" if none)."""
        if not self._ollama_root or not self._ollama_model or self._http is None:
            return ""
        try:
            self._http.post(
                f"{self._ollama_root}/api/generate",
                headers={"Content-Type": "application/json"},
                json_payload={"model": self._ollama_model, "keep_alive": 0},
                timeout=10,
            )
            return self._ollama_model
        except Exception as exc:  # noqa: BLE001 - Ollama down is not a render failure
            logger.info("Could not release Ollama model %s: %s", self._ollama_model, exc)
            return ""

    def prepare_for_render(self, model_type: str, *, needed_mb: int | None = None) -> VramPlan:
        """Make room for a render. Unloads, in priority order, only what is
        needed; Florence (priority 80) survives when the headroom allows it.
        Raises `VramError` when the card still cannot fit the render."""
        needed = needed_mb if needed_mb is not None else self.needed_mb(model_type)
        free_before = self.free_mb()
        plan = VramPlan(model_type=model_type, needed_mb=needed, free_before_mb=free_before, free_after_mb=free_before)
        with self._lock:
            candidates = sorted(self._models.values(), key=lambda m: m.priority)

        def enough() -> bool:
            free = self.free_mb()
            plan.free_after_mb = free
            return free is None or free >= needed

        if free_before is not None and free_before < needed:
            plan.ollama_released = self.release_ollama()
            if plan.ollama_released:
                # Ollama frees asynchronously; give it a moment before re-reading.
                for _ in range(10):
                    if enough():
                        break
                    time.sleep(0.2)
        elif self._ollama_model:
            # No pressure, but a warm VLM next to a render is the classic OOM: drop it anyway.
            plan.ollama_released = self.release_ollama()
        for model in candidates:
            if enough():
                break
            try:
                model.unload()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unloading %s failed: %s", model.name, exc)
            with self._lock:
                self._models.pop(model.name, None)
            plan.unloaded.append(model.name)
            if isinstance(self._probe, FakeNvml):
                self._probe.used_mb = max(0, self._probe.used_mb - model.estimated_mb)
        if not enough():
            free = plan.free_after_mb or 0
            still = [m.name for m in self.loaded()]
            hint = ""
            if self._ollama_model and not plan.ollama_released:
                hint = f"Ollama model {self._ollama_model} may still be resident; check `ollama ps`."
            raise VramError(needed, free, still, hint)
        if plan.unloaded or plan.ollama_released:
            plan.note = "Unloaded " + ", ".join([*plan.unloaded, *([f"ollama:{plan.ollama_released}"] if plan.ollama_released else [])])
        return plan

    def after_render(self) -> None:
        """Nothing to reload eagerly: every vision model loads lazily on next use."""
        return None

    # ---- peak sampling ------------------------------------------------------

    @contextmanager
    def render_scope(self, model_type: str, *, needed_mb: int | None = None) -> Iterator[RenderScope]:
        """`prepare_for_render` then sample used VRAM until the block ends;
        `scope.peak_mb` holds the peak (None without a GPU)."""
        plan = self.prepare_for_render(model_type, needed_mb=needed_mb)
        scope = RenderScope(model_type=model_type, plan=plan)
        stop = threading.Event()
        peak: list[int] = []

        def sample() -> None:
            while not stop.is_set():
                memory = self.memory_mb()
                if memory is not None:
                    peak.append(memory[0])
                stop.wait(self._sample_interval)

        started = time.perf_counter()
        thread: threading.Thread | None = None
        if self.memory_mb() is not None:
            thread = threading.Thread(target=sample, name="vram-sampler", daemon=True)
            thread.start()
        try:
            yield scope
        finally:
            stop.set()
            if thread is not None:
                thread.join(timeout=2.0)
            memory = self.memory_mb()
            if memory is not None:
                peak.append(memory[0])
            scope.peak_mb = max(peak) if peak else None
            scope.seconds = round(time.perf_counter() - started, 2)
            self.after_render()
