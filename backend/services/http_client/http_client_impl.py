"""HTTP client wrapper service."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path

import requests

from services.http_client.http_client import HttpTimeoutError
from services.services_utils import JSONValue, RequestData

logger = logging.getLogger(__name__)


class HTTPClientImpl:
    """Wraps requests.* for external API calls."""

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json_payload: Mapping[str, JSONValue] | None = None,
        data: RequestData = None,
        timeout: int = 30,
    ) -> requests.Response:
        try:
            return requests.post(url, headers=headers, json=json_payload, data=data, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            logger.error("HTTP POST timed out: %s", url, exc_info=True)
            raise HttpTimeoutError(str(exc)) from exc

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            logger.error("HTTP GET timed out: %s", url, exc_info=True)
            raise HttpTimeoutError(str(exc)) from exc

    def download_to(
        self,
        url: str,
        path: Path,
        on_chunk: Callable[[int, int], None],
        headers: dict[str, str] | None = None,
        timeout: int = 60,
        chunk_bytes: int = 1024 * 1024,
    ) -> int:
        """Stream to disk: a multi-GB model never sits in memory whole."""
        try:
            with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Download failed: HTTP {response.status_code}")
                total = int(response.headers.get("Content-Length", "0") or 0)
                written = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=chunk_bytes):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                        on_chunk(written, total)
                return written
        except requests.exceptions.Timeout as exc:
            logger.error("HTTP download timed out: %s", url, exc_info=True)
            raise HttpTimeoutError(str(exc)) from exc

    def put(
        self,
        url: str,
        data: RequestData = None,
        headers: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> requests.Response:
        try:
            return requests.put(url, data=data, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            logger.error("HTTP PUT timed out: %s", url, exc_info=True)
            raise HttpTimeoutError(str(exc)) from exc
