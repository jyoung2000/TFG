"""The real :class:`LoraFetcher`: Civitai's public API for resolution,
``requests`` streaming for the file. Network-only code — tests use
``FakeLoraFetcher``; this module is exercised on real hardware
(docs/RTX_4070_TEST_MATRIX.md)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import requests

from services.lora_fetcher.lora_fetcher import (
    CancelledCallback,
    LoraDownloadCancelled,
    LoraFetchError,
    LoraSource,
    ProgressCallback,
    ResolvedDownload,
    safe_lora_filename,
)

logger = logging.getLogger(__name__)

_CIVITAI_API = "https://civitai.com/api/v1"
_CHUNK = 1024 * 1024


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key.strip() else {}


class RequestsLoraFetcher:
    def resolve(self, source: LoraSource, api_key: str) -> ResolvedDownload:
        headers = _auth_headers(api_key)
        if source.kind in ("huggingface", "direct"):
            return ResolvedDownload(url=source.download_url, filename=source.filename, headers=headers)
        # Civitai: a direct download link keeps its URL; a model page needs the API.
        version_id = source.civitai_version_id
        if not version_id and source.civitai_model_id:
            model = self._get_json(f"{_CIVITAI_API}/models/{source.civitai_model_id}", headers)
            versions = cast(list[dict[str, Any]], model.get("modelVersions") or [])
            if not versions:
                raise LoraFetchError("Civitai lists no versions for that model")
            version_id = str(versions[0].get("id", ""))
            if not version_id:
                raise LoraFetchError("Civitai's response carried no version id")
        version = self._get_json(f"{_CIVITAI_API}/model-versions/{version_id}", headers)
        files = cast(list[dict[str, Any]], version.get("files") or [])
        chosen: dict[str, Any] | None = None
        for entry in files:
            name = str(entry.get("name", ""))
            if not name.lower().endswith(".safetensors"):
                continue
            if chosen is None or bool(entry.get("primary")):
                chosen = entry
            if bool(entry.get("primary")):
                break
        if chosen is None:
            raise LoraFetchError("That Civitai version has no .safetensors file")
        url = str(chosen.get("downloadUrl", "") or f"https://civitai.com/api/download/models/{version_id}")
        size_kb = chosen.get("sizeKB")
        size = int(float(size_kb) * 1024) if isinstance(size_kb, (int, float)) else None
        return ResolvedDownload(url=url, filename=safe_lora_filename(str(chosen.get("name", ""))), size_bytes=size, headers=headers)

    def download(
        self,
        resolved: ResolvedDownload,
        dest: Path,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> None:
        try:
            response = requests.get(resolved.url, headers=resolved.headers or None, stream=True, timeout=(15, 300), allow_redirects=True)
        except requests.exceptions.RequestException as exc:
            raise LoraFetchError(f"Download failed to start: {exc}") from exc
        with response:
            # Redirects are allowed (Civitai/HF hand off to CDNs) but must
            # stay on https — a hostile link must not bounce us to http.
            if not str(response.url).lower().startswith("https://"):
                raise LoraFetchError("The download redirected off https — refusing to fetch it")
            if response.status_code in (401, 403):
                raise LoraFetchError("The host refused the download (401/403) — this file likely needs an API key; paste one in the key field (it is used once, never saved)")
            if response.status_code >= 400:
                raise LoraFetchError(f"The host answered {response.status_code} for that link")
            total = resolved.size_bytes
            length = response.headers.get("content-length", "")
            if length.isdigit():
                total = int(length)
            done = 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                with dest.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=_CHUNK):
                        if is_cancelled():
                            raise LoraDownloadCancelled()
                        if not chunk:
                            continue
                        handle.write(chunk)
                        done += len(chunk)
                        on_progress(done, total)
            except LoraDownloadCancelled:
                dest.unlink(missing_ok=True)
                raise
            except OSError as exc:
                dest.unlink(missing_ok=True)
                raise LoraFetchError(f"Could not write the file: {exc}") from exc
            if done == 0:
                dest.unlink(missing_ok=True)
                raise LoraFetchError("The host returned an empty file")

    @staticmethod
    def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
        try:
            response = requests.get(url, headers=headers or None, timeout=30)
        except requests.exceptions.RequestException as exc:
            raise LoraFetchError(f"Civitai unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise LoraFetchError(f"Civitai answered {response.status_code} for {url.rsplit('/', 2)[-2]}/{url.rsplit('/', 1)[-1]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LoraFetchError("Civitai returned something that is not JSON") from exc
        if not isinstance(payload, dict):
            raise LoraFetchError("Civitai returned an unexpected response shape")
        return cast(dict[str, Any], payload)
