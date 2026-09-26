"""A fetcher that pretends: resolves to a configurable filename/size and
"downloads" by writing bytes with progress — enough to test every handler
path including failure and cancellation."""

from __future__ import annotations

from pathlib import Path

from services.lora_fetcher.lora_fetcher import (
    CancelledCallback,
    LoraDownloadCancelled,
    LoraFetchError,
    LoraSource,
    ProgressCallback,
    ResolvedDownload,
)


class FakeLoraFetcher:
    def __init__(self) -> None:
        self.resolves: list[tuple[LoraSource, str]] = []
        self.downloads: list[ResolvedDownload] = []
        #: Filename handed back for sources that do not name one (Civitai).
        self.civitai_filename = "civitai-lora.safetensors"
        self.size_bytes: int | None = 3 * 1024 * 1024
        self.content = b"fake-lora-from-url"
        self.fail_resolve = ""
        self.fail_download = ""
        #: Simulate a cancel arriving after the first chunk.
        self.cancel_mid_download = False
        #: Resolve to a non-safetensors name (a host serving the wrong file).
        self.resolve_to: str = ""

    def resolve(self, source: LoraSource, api_key: str) -> ResolvedDownload:
        self.resolves.append((source, api_key))
        if self.fail_resolve:
            raise LoraFetchError(self.fail_resolve)
        filename = self.resolve_to or source.filename or self.civitai_filename
        url = source.download_url or f"https://civitai.com/api/download/models/{source.civitai_version_id or '1'}"
        return ResolvedDownload(url=url, filename=filename, size_bytes=self.size_bytes, headers={"Authorization": f"Bearer {api_key}"} if api_key else {})

    def download(
        self,
        resolved: ResolvedDownload,
        dest: Path,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> None:
        self.downloads.append(resolved)
        if self.fail_download:
            raise LoraFetchError(self.fail_download)
        dest.parent.mkdir(parents=True, exist_ok=True)
        half = max(1, len(self.content) // 2)
        with dest.open("wb") as handle:
            handle.write(self.content[:half])
            on_progress(half, self.size_bytes)
            if self.cancel_mid_download or is_cancelled():
                dest.unlink(missing_ok=True)
                raise LoraDownloadCancelled()
            handle.write(self.content[half:])
            on_progress(len(self.content), self.size_bytes)
