"""HTTP client service protocol definitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from services.services_utils import JSONValue, RequestData


class HttpTimeoutError(Exception):
    """Raised by HTTP service implementations when a request times out."""


class HttpResponseLike(Protocol):
    @property
    def status_code(self) -> int:
        ...

    @property
    def text(self) -> str:
        ...

    @property
    def headers(self) -> Mapping[str, str]:
        ...

    @property
    def content(self) -> bytes:
        ...

    def json(self) -> object:
        ...


class HTTPClient(Protocol):
    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json_payload: Mapping[str, JSONValue] | None = None,
        data: RequestData = None,
        timeout: int = 30,
    ) -> HttpResponseLike:
        ...

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> HttpResponseLike:
        ...

    def put(
        self,
        url: str,
        data: RequestData = None,
        headers: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> HttpResponseLike:
        ...


class StreamingHTTPClient(Protocol):
    """An HTTP client that can stream a large download straight to disk."""

    def download_to(
        self,
        url: str,
        path: Path,
        on_chunk: Callable[[int, int], None],
        headers: dict[str, str] | None = None,
        timeout: int = 60,
        chunk_bytes: int = 1024 * 1024,
    ) -> int:
        """Stream a GET body to `path` in chunks, calling `on_chunk(written, total)`
        after each (total 0 when unknown; raising from it stops the download).
        Raises RuntimeError on a non-200 status. Returns the bytes written."""
        ...
