"""WanGP over HTTP: the desktop drives a WanGP that lives in the container.

The container runs this same backend with its own in-process `WanGPBridge`
and exposes it as `/api/wangp/*` (`handlers/wangp_server_handler.py`). This
bridge subclasses the local one, so every setting it builds — resolution
maps, LoRA keys, guide videos — is identical; only `_run_manifest` changes:
files the manifest references are uploaded, the manifest is submitted, the
job is polled for progress, and the outputs are downloaded into the local
outputs directory. Concept after Open-Generative-AI's "Wan2GP as a remote
server" (MIT): the desktop sends prompts and receives files; nothing heavy
runs on it. The transport here is our own API, not Wan2GP's Gradio one, so
it stays testable with the fake HTTP client.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from services.http_client import HTTPClient, HttpTimeoutError
from services.wangp_bridge import CancelledCallback, ProgressCallback, WanGPBridge, WanGPBridgeStatus

logger = logging.getLogger(__name__)

#: Manifest keys whose values are local file paths the container cannot see.
_FILE_KEYS = ("image_start", "image_end", "video_guide", "video_mask", "audio_guide", "image_guide", "image_mask")
_FILE_LIST_KEYS = ("image_refs", "activated_loras")
_POLL_SECONDS = 1.0


class RemoteWanGPError(RuntimeError):
    pass


class RemoteWanGPBridge(WanGPBridge):
    """Same contract as `WanGPBridge`; the work happens on `base_url`."""

    def __init__(
        self,
        *,
        http: HTTPClient,
        base_url: str,
        token: str,
        output_dir: Path,
        video_model_type: str,
        image_model_type: str,
        camera_motion_prompts: dict[str, str],
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        super().__init__(
            enabled=True,
            root=None,
            python_executable=None,
            config_dir=output_dir / "wangp_remote",
            output_dir=output_dir,
            video_model_type=video_model_type,
            image_model_type=image_model_type,
            camera_motion_prompts=camera_motion_prompts,
            extra_args=(),
        )
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._poll_seconds = poll_seconds

    # ---- contract ---------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    def get_status(self) -> WanGPBridgeStatus:
        try:
            payload = self._get_json("/api/wangp/status", timeout=10)
        except RemoteWanGPError as exc:
            return WanGPBridgeStatus(available=False, root=None, python_executable=None, reason=f"Remote WanGP at {self._base_url} unreachable: {exc}")
        available = bool(payload.get("available", False))
        reason = str(payload.get("reason", "") or "")
        return WanGPBridgeStatus(available=available, root=None, python_executable=None, reason=reason or ("" if available else "Remote WanGP is not available"))

    def list_model_definitions(self) -> list[dict[str, object]]:
        try:
            payload = self._get_json("/api/wangp/definitions", timeout=30)
        except RemoteWanGPError as exc:
            logger.warning("Remote WanGP definitions unavailable: %s", exc)
            return []
        raw = payload.get("definitions", [])
        if not isinstance(raw, list):
            return []
        return [cast(dict[str, object], item) for item in cast(list[object], raw) if isinstance(item, dict)]

    def _run_manifest(
        self,
        *,
        manifest: list[dict[str, object]],
        media_suffixes: set[str],
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> list[str]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        on_progress("uploading_inputs", 1, None, None)
        remote_manifest = [self._upload_referenced_files(entry) for entry in manifest]
        on_progress("starting_wangp", 3, None, None)
        submitted = self._post_json("/api/wangp/manifest", {"manifest": remote_manifest, "media_suffixes": sorted(media_suffixes)}, timeout=60)
        job_id = str(submitted.get("id", ""))
        if not job_id:
            raise RemoteWanGPError("The remote WanGP did not return a job id")
        cancel_requested = False
        last_phase = ""
        while True:
            if is_cancelled() and not cancel_requested:
                cancel_requested = True
                try:
                    self._post_json(f"/api/wangp/jobs/{job_id}/cancel", {}, timeout=10)
                except RemoteWanGPError as exc:
                    logger.info("Remote cancel failed: %s", exc)
            status = self._get_json(f"/api/wangp/jobs/{job_id}", timeout=15)
            phase = str(status.get("phase", "") or "")
            progress = status.get("progress")
            if phase and phase != last_phase or isinstance(progress, (int, float)):
                last_phase = phase
                on_progress(phase or "rendering", int(progress) if isinstance(progress, (int, float)) else 0, None, None)
            state = str(status.get("status", ""))
            if state in ("complete", "failed", "cancelled"):
                break
            time.sleep(self._poll_seconds)
        if cancel_requested or is_cancelled() or state == "cancelled":
            raise RuntimeError("Generation was cancelled")
        if state != "complete":
            raise RuntimeError(str(status.get("error", "") or "Remote WanGP generation failed"))
        outputs_raw = status.get("outputs", [])
        outputs = [str(p) for p in cast(list[object], outputs_raw)] if isinstance(outputs_raw, list) else []
        if not outputs:
            return []
        on_progress("downloading", 97, None, None)
        local: list[str] = []
        for remote_path in outputs:
            local.append(self._download(remote_path))
        on_progress("complete", 100, None, None)
        return local

    # ---- transport --------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_json(self, path: str, *, timeout: int) -> dict[str, Any]:
        try:
            response = self._http.get(f"{self._base_url}{path}", headers=self._headers(), timeout=timeout)
        except HttpTimeoutError as exc:
            raise RemoteWanGPError(f"timed out on {path}") from exc
        except Exception as exc:  # noqa: BLE001 - transport errors become one typed error
            raise RemoteWanGPError(str(exc)) from exc
        return self._payload(response.status_code, response.json(), path)

    def _post_json(self, path: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        try:
            response = self._http.post(f"{self._base_url}{path}", headers=self._headers(), json_payload=payload, timeout=timeout)
        except HttpTimeoutError as exc:
            raise RemoteWanGPError(f"timed out on {path}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RemoteWanGPError(str(exc)) from exc
        return self._payload(response.status_code, response.json(), path)

    @staticmethod
    def _payload(status_code: int, body: object, path: str) -> dict[str, Any]:
        if status_code >= 400:
            detail = ""
            if isinstance(body, dict):
                detail = str(cast(dict[str, object], body).get("error", "") or "")
            raise RemoteWanGPError(f"{path} → {status_code}{': ' + detail if detail else ''}")
        if not isinstance(body, dict):
            raise RemoteWanGPError(f"{path} returned a non-object body")
        return cast(dict[str, Any], body)

    def _upload_referenced_files(self, entry: dict[str, object]) -> dict[str, object]:
        params = entry.get("params")
        if not isinstance(params, dict):
            return entry
        settings = dict(cast(dict[str, object], params))
        for key in _FILE_KEYS:
            value = settings.get(key)
            if isinstance(value, str) and value:
                settings[key] = self._upload(value)
        for key in _FILE_LIST_KEYS:
            value = settings.get(key)
            if isinstance(value, list):
                settings[key] = [self._upload(str(item)) for item in cast(list[object], value)]
        return {**entry, "params": settings}

    def _upload(self, local_path: str) -> str:
        path = Path(local_path)
        if not path.is_file():
            raise RemoteWanGPError(f"Input file not found: {local_path}")
        payload = {"name": path.name, "data_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
        response = self._post_json("/api/wangp/upload", payload, timeout=600)
        remote = str(response.get("path", ""))
        if not remote:
            raise RemoteWanGPError(f"Upload of {path.name} returned no path")
        return remote

    def _download(self, remote_path: str) -> str:
        try:
            response = self._http.get(f"{self._base_url}/api/wangp/output?path={_quote(remote_path)}", headers=self._headers(), timeout=600)
        except HttpTimeoutError as exc:
            raise RemoteWanGPError("download timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise RemoteWanGPError(str(exc)) from exc
        if response.status_code != 200:
            raise RemoteWanGPError(f"download of {remote_path} failed ({response.status_code})")
        target = self._output_dir / f"remote-{int(time.time() * 1000)}-{Path(remote_path).name}"
        target.write_bytes(response.content)
        return str(target)


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def referenced_files(manifest: Iterable[dict[str, object]]) -> list[str]:
    """Every local file a manifest points at (what the remote bridge uploads)."""
    found: list[str] = []
    for entry in manifest:
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        settings = cast(dict[str, object], params)
        for key in _FILE_KEYS:
            value = settings.get(key)
            if isinstance(value, str) and value:
                found.append(value)
        for key in _FILE_LIST_KEYS:
            value = settings.get(key)
            if isinstance(value, list):
                found.extend(str(item) for item in cast(list[object], value))
    return found
