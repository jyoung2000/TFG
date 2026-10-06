"""F-08x: adding models from HuggingFace and Ollama, and telling them apart.

The Models tab can list models but cannot add any, and the analyse-model picker
has nothing to list because an Ollama model entry never says whether it can
read images. WanGP already ships a HuggingFace installer and Ollama already
exposes `POST /api/pull`; neither is reachable from the backend.

The contract here:
- `download_wangp_model` runs the checkout's own downloader, and rejects a
  non-HuggingFace URL *before* the worker is touched (the downloader executes
  fetched configs, so the filter is a security boundary, not cosmetics).
- `pull_ollama_model` proxies Ollama's own pull endpoint.
- Ollama entries carry their `capabilities`, so vision models can drive
  "Analyse with" and text-only ones are visibly not image-capable.
- The Models tab lists the checkout's whole inventory, not the one definition
  the handshake happens to keep.

ServiceBundle fakes, no mocking libraries.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from _routes._errors import HTTPError
from state.app_state_types import AppState, StartupReady
from state.app_settings import AppSettings
from runtime_config.runtime_config import RuntimeConfig
from runtime_config.model_download_specs import DEFAULT_MODEL_DOWNLOAD_SPECS, DEFAULT_REQUIRED_MODEL_TYPES


class FakeTaskRunner:
    """Records background tasks without running them."""

    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []

    def run_background(self, fn, *, task_name: str = "", on_error=None) -> None:
        self.tasks.append({"name": task_name, "fn": fn, "on_error": on_error})


class FakeGpuInfo:
    """Always reports a 12 GB card."""

    def get_vram_total_gb(self) -> float | None:
        return 12.0

    def get_device_name(self) -> str | None:
        return "NVIDIA GeForce RTX 4070"


class FakeModelDownloader:
    """Records download calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def download_file(self, *, repo_id: str, filename: str, local_dir: str, on_progress=None) -> None:
        self.calls.append({"kind": "file", "repo_id": repo_id, "filename": filename, "local_dir": local_dir})

    def download_snapshot(self, *, repo_id: str, local_dir: str, on_progress=None) -> None:
        self.calls.append({"kind": "snapshot", "repo_id": repo_id, "local_dir": local_dir})


class FakeHTTPClient:
    """Ollama, as it actually answers: /api/tags by GET, /api/show by POST."""

    def __init__(self, *, show_fails: bool = False) -> None:
        self.show_fails = show_fails
        self.pulls: list[str] = []
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30):
        self.get_calls.append({"url": url, "timeout": timeout})
        class R:
            status_code = 200
            def json(self):
                return {
                    "models": [
                        {"name": "qwen2.5vl:7b", "size": 6_000_000_000, "details": {"family": "qwen25vl"}},
                        {"name": "qwen2.5:3b", "size": 2_000_000_000, "details": {"family": "qwen2"}},
                    ]
                }
        return R()

    def post(self, url: str, *, headers: dict[str, str] | None = None, json_payload: dict[str, Any] | None = None, timeout: int = 30):
        self.post_calls.append({"url": url, "json_payload": json_payload, "timeout": timeout})
        if url.endswith("/api/show"):
            assert isinstance(json_payload, dict) and json_payload.get("model"), "/api/show takes a JSON body"
            if self.show_fails:
                raise RuntimeError("probe failed")
            class Show:
                status_code = 200
                def json(self):
                    vision = "vl" in str(json_payload.get("model", "")) if json_payload else False
                    return {"capabilities": ["completion", "vision"] if vision else ["completion"]}
            return Show()

        name = str((json_payload or {}).get("name", "") or (json_payload or {}).get("model", ""))
        self.pulls.append(name)
        class Pull:
            status_code = 200
        return Pull()


class FakeWanGPBridge:
    """Records the URLs the worker is asked to install."""

    def __init__(self, *, raise_on: Exception | None = None) -> None:
        self.urls: list[str] = []
        self.raise_on = raise_on

    def download_model(self, url: str, progress=None) -> dict:
        self.urls.append(url)
        if self.raise_on is not None:
            raise self.raise_on
        return {"ok": True, "url": url, "model_id": "ZImageTurbo"}

    def list_model_definitions(self) -> list[dict]:
        """One model — the one the handshake keeps."""
        return [{"id": "ltx2_22B_distilled", "name": "LTX-2 22B Distilled", "architecture": "ltx2_22B_distilled",
                 "urls": [], "installed": True, "description": ""}]

    def list_all_model_definitions(self) -> list[dict]:
        """All models in the checkout."""
        return [
            {"id": "ltx2_22B_distilled", "name": "LTX-2 22B Distilled", "architecture": "ltx2_22B_distilled",
             "urls": [], "installed": True, "description": ""},
            {"id": "ZImageTurbo", "name": "Z-Image Turbo", "architecture": "z_image",
             "urls": [], "installed": True, "description": ""},
            {"id": "flux_1_dev", "name": "FLUX.1 dev", "architecture": "flux",
             "urls": [], "installed": False, "description": ""},
        ]


def _make_handler(http=None, wangp=None):
    """Construct a ModelLibraryHandler with minimal fakes for unit testing."""
    from handlers.model_library_handler import ModelLibraryHandler

    state = AppState(
        available_files={},
        downloading_session={},
        gpu_slot=None,
        api_generation=None,
        cpu_slot=None,
        text_encoder=None,
        startup=StartupReady(),
        app_settings=AppSettings(openai_compatible_base_url="http://127.0.0.1:11434/v1"),
    )

    config = RuntimeConfig(
        device="cpu",
        models_dir=Path("."),
        model_download_specs=DEFAULT_MODEL_DOWNLOAD_SPECS,
        required_model_types=DEFAULT_REQUIRED_MODEL_TYPES,
        outputs_dir=Path("."),
        ic_lora_dir=Path("."),
        settings_file=Path("."),
        ltx_api_base_url="https://api.example.com",
        force_api_generations=False,
        use_sage_attention=False,
        camera_motion_prompts={},
        default_negative_prompt="",
        wangp_enabled=wangp is not None,
        wangp_root=Path(".") if wangp is not None else None,
        wangp_python=None,
        wangp_config_dir=Path("."),
        wangp_video_model_type="ltx2_22B_distilled",
        wangp_image_model_type="ZImageTurbo",
        wangp_extra_args=(),
    )

    return ModelLibraryHandler(
        state=state,
        lock=threading.RLock(),
        config=config,
        wangp_bridge=wangp,
        http=http or FakeHTTPClient(),
        gpu_info=FakeGpuInfo(),
        task_runner=FakeTaskRunner(),
        model_downloader=FakeModelDownloader(),
    )


# ---- HuggingFace ----------------------------------------------------------------------------


def test_huggingface_download_rejects_a_foreign_url_before_the_worker_sees_it() -> None:
    bridge = FakeWanGPBridge()
    handler = _make_handler(wangp=bridge)

    for url in (
        "https://evil.example.com/owner/repo/model.safetensors",
        "https://huggingface.co.evil.test/owner/repo/model.safetensors",
        "http://huggingface.co/owner/repo/model.safetensors",
        "https://huggingface.co/owner",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "   ",
    ):
        with pytest.raises(HTTPError) as exc:
            handler.download_wangp_model(url)
        assert exc.value.status_code == 400, url

    assert bridge.urls == [], "the downloader must never see a URL that is not huggingface.co"


def test_huggingface_download_hands_a_valid_url_to_the_checkout_downloader() -> None:
    bridge = FakeWanGPBridge()
    handler = _make_handler(wangp=bridge)
    url = "https://huggingface.co/DeepBeepMeep/Z-Image/resolve/main/ZImageTurbo_quanto_bf16_int8.safetensors"

    result = handler.download_wangp_model(url)

    assert bridge.urls == [url]
    assert result["ok"] is True


def test_huggingface_download_reports_the_worker_failure_verbatim() -> None:
    handler = _make_handler(wangp=FakeWanGPBridge(raise_on=HTTPError(502, "WanGP worker: 404 repo not found")))

    with pytest.raises(HTTPError) as exc:
        handler.download_wangp_model("https://huggingface.co/owner/Nothing/resolve/main/x.safetensors")
    assert exc.value.status_code == 502
    assert "404" in str(exc.value.detail)


def test_huggingface_download_without_a_worker_is_a_503_not_a_silent_no_op() -> None:
    handler = _make_handler(wangp=None)
    with pytest.raises(HTTPError) as exc:
        handler.download_wangp_model("https://huggingface.co/owner/repo/resolve/main/x.safetensors")
    assert exc.value.status_code == 503


# ---- Ollama ---------------------------------------------------------------------------------


def test_ollama_models_say_whether_they_can_read_images() -> None:
    handler = _make_handler(http=FakeHTTPClient())

    by_id = {m.id: m for m in handler.list_models("ollama")}

    assert "vision" in by_id["qwen2.5vl:7b"].capabilities
    assert "vision" not in by_id["qwen2.5:3b"].capabilities


def test_a_failed_capability_probe_still_lists_the_model() -> None:
    # A broken probe must not hide a model the user can still see and diagnose.
    handler = _make_handler(http=FakeHTTPClient(show_fails=True))

    models = handler.list_models("ollama")

    assert [m.id for m in models] == ["qwen2.5vl:7b", "qwen2.5:3b"]
    assert all(m.capabilities == [] for m in models)


def test_ollama_pull_proxies_the_ollama_server() -> None:
    http = FakeHTTPClient()
    handler = _make_handler(http=http)

    result = handler.pull_ollama_model("qwen2.5vl:7b")

    assert http.pulls == ["qwen2.5vl:7b"]
    assert result == {"ok": True, "status": "success", "model": "qwen2.5vl:7b"}


def test_ollama_pull_needs_a_model_name() -> None:
    with pytest.raises(HTTPError) as exc:
        _make_handler(http=FakeHTTPClient()).pull_ollama_model("   ")
    assert exc.value.status_code == 400


# ---- inventory ------------------------------------------------------------------------------


def test_the_models_tab_lists_the_whole_checkout_not_just_the_handshaken_model() -> None:
    # The worker handshake keeps one definition for mode selection; the Models
    # tab has to ask for all of them or the other 147 are invisible.
    handler = _make_handler(wangp=FakeWanGPBridge())

    models = handler.list_models("wangp")

    assert [m.id for m in models] == ["ltx2_22B_distilled", "ZImageTurbo", "flux_1_dev"]
    assert [m.installed for m in models] == [True, True, False]
    assert [m.task for m in models] == ["video", "image", "image"]


def test_a_stopped_worker_degrades_to_the_cached_definitions() -> None:
    class DownWorker(FakeWanGPBridge):
        def list_all_model_definitions(self) -> list[dict]:
            raise HTTPError(503, "WANGP_UNAVAILABLE: no WanGP worker is running")

    models = _make_handler(wangp=DownWorker()).list_models("wangp")

    assert [m.id for m in models] == ["ltx2_22B_distilled"]