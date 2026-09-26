"""Vision over HTTP: the same Protocol served by `backend/vision_worker.py`
(a sidecar with its own environment). Image paths are passed, not bytes, so
the worker must see the same filesystem — true on one machine and in the
compose stack, where the outputs volume is shared."""

from __future__ import annotations

from typing import Any, cast

from services.http_client.http_client import HTTPClient, JSONValue
from services.vision.deterministic import measure_path
from services.vision.protocol import (
    CaptionLevel,
    CaptionResult,
    DepthResult,
    DetectResult,
    DetectTask,
    EmbeddingKind,
    EmbeddingResult,
    MeasuredStats,
    TagResult,
    VisionStatus,
)


class RemoteVisionError(RuntimeError):
    pass


class RemoteVision:
    def __init__(self, http: HTTPClient, base_url: str, *, timeout: int = 300) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base

    def _post(self, path: str, payload: dict[str, JSONValue]) -> dict[str, Any]:
        try:
            response = self._http.post(f"{self._base}{path}", headers={"Content-Type": "application/json"}, json_payload=payload, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            raise RemoteVisionError(f"Vision worker unreachable at {self._base}: {exc}") from exc
        if response.status_code != 200:
            raise RemoteVisionError(f"Vision worker {path} failed ({response.status_code}): {response.text[:300]}")
        body = cast(Any, response.json())
        if not isinstance(body, dict):
            raise RemoteVisionError(f"Vision worker {path} returned a non-object")
        return cast(dict[str, Any], body)

    def reachable(self) -> bool:
        try:
            response = self._http.get(f"{self._base}/health", timeout=3)
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> VisionStatus:
        try:
            response = self._http.get(f"{self._base}/status", timeout=10)
            status = VisionStatus.model_validate(response.json())
            status.mode = "sidecar"
            return status
        except Exception as exc:  # noqa: BLE001
            raise RemoteVisionError(f"Vision worker unreachable at {self._base}: {exc}") from exc

    def stats(self, image_path: str) -> MeasuredStats:
        # Pure PIL/numpy: no reason to cross a process boundary for it.
        return measure_path(image_path)

    def caption(self, image_path: str, level: CaptionLevel = "more_detailed_caption") -> CaptionResult:
        return CaptionResult.model_validate(self._post("/caption", {"image_path": image_path, "level": level}))

    def detect(self, image_path: str, task: DetectTask = "od", text: str = "") -> DetectResult:
        return DetectResult.model_validate(self._post("/detect", {"image_path": image_path, "task": task, "text": text}))

    def tags(self, image_path: str, top_k: int = 12) -> TagResult:
        return TagResult.model_validate(self._post("/tags", {"image_path": image_path, "top_k": top_k}))

    def depth(self, image_path: str, output_png: str) -> DepthResult:
        return DepthResult.model_validate(self._post("/depth", {"image_path": image_path, "output_png": output_png}))

    def embed(self, image_path: str, kind: EmbeddingKind = "clip") -> EmbeddingResult:
        return EmbeddingResult.model_validate(self._post("/embed", {"image_path": image_path, "kind": kind}))

    def unload(self, keep: tuple[str, ...] = ()) -> list[str]:
        body = self._post("/unload", {"keep": list(keep)})
        return [str(name) for name in cast(list[Any], body.get("unloaded", []))]
