"""IC-LoRA model catalog/download service."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

from services.ic_lora_model_downloader.ic_lora_model_downloader import IcLoraDownloadPayload, IcLoraModelPayload

logger = logging.getLogger(__name__)


OFFICIAL_MODELS = {
    "canny": {
        "repo": "Lightricks/LTX-2-19b-IC-LoRA-Canny-Control",
        "file": "ltx-2-19b-ic-lora-canny-control.safetensors",
    },
    "depth": {
        "repo": "Lightricks/LTX-2-19b-IC-LoRA-Depth-Control",
        "file": "ltx-2-19b-ic-lora-depth-control.safetensors",
    },
    "pose": {
        "repo": "Lightricks/LTX-2-19b-IC-LoRA-Pose-Control",
        "file": "ltx-2-19b-ic-lora-pose-control.safetensors",
    },
    "detailer": {
        "repo": "Lightricks/LTX-2-19b-IC-LoRA-Detailer",
        "file": "ltx-2-19b-ic-lora-detailer.safetensors",
    },
}


class IcLoraModelDownloaderImpl:
    """Lists and downloads IC-LoRA model files."""

    def list_models(self, directory: Path) -> list[IcLoraModelPayload]:
        models: list[IcLoraModelPayload] = []
        if not directory.exists():
            return models

        for file_path in sorted(directory.iterdir()):
            if file_path.suffix != ".safetensors" or not file_path.is_file():
                continue

            metadata: dict[str, str] = {}
            try:
                from safetensors import safe_open

                with safe_open(str(file_path), framework="pt") as sf:
                    metadata = sf.metadata() or {}
            except Exception:
                logger.warning("Failed to read metadata for IC-LoRA model: %s", file_path, exc_info=True)

            models.append(
                {
                    "name": file_path.stem,
                    "path": str(file_path),
                    "conditioning_type": metadata.get("conditioning_type", "unknown"),
                    "reference_downscale_factor": int(metadata.get("reference_downscale_factor", 1)),
                }
            )

        return models

    def download_model(self, model_name: str, directory: Path) -> IcLoraDownloadPayload:
        if model_name not in OFFICIAL_MODELS:
            allowed = list(OFFICIAL_MODELS.keys())
            raise ValueError(f"Unknown model: {model_name}. Must be one of: {allowed}")

        info = OFFICIAL_MODELS[model_name]
        dest_path = directory / info["file"]
        if dest_path.exists() and dest_path.stat().st_size > 1_000_000:
            return {
                "status": "complete",
                "path": str(dest_path),
                "already_existed": True,
            }

        directory.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_suffix(".tmp")
        url = f"https://huggingface.co/{info['repo']}/resolve/main/{info['file']}"

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "LTX-Studio-App/1.0"})
            with urllib.request.urlopen(request) as response:
                with open(tmp_path, "wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)

            tmp_path.rename(dest_path)
            return {
                "status": "complete",
                "path": str(dest_path),
                "already_existed": False,
            }
        except Exception:
            logger.error("Failed to download IC-LoRA model '%s' from %s", model_name, url)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    logger.warning("Could not remove temporary IC-LoRA file: %s", tmp_path, exc_info=True)
            raise
