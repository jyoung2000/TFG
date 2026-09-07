"""IC-LoRA model downloader protocol definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypedDict


class IcLoraModelPayload(TypedDict):
    name: str
    path: str
    conditioning_type: str
    reference_downscale_factor: int


class IcLoraDownloadPayload(TypedDict):
    status: str
    path: str
    already_existed: bool


class IcLoraModelDownloader(Protocol):
    def list_models(self, directory: Path) -> list[IcLoraModelPayload]:
        ...

    def download_model(self, model_name: str, directory: Path) -> IcLoraDownloadPayload:
        ...
