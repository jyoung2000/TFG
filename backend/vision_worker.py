"""Vision sidecar.

The same model wrappers the backend can run in-process, served over HTTP on
the loopback interface so they can live in their **own** environment
(`backend/vision-requirements.txt`). Use it when the WanGP checkout pins a
`transformers` that cannot load Florence-2 natively, or in the compose stack
where vision runs as its own service. See docs/adr/0001-local-vision-stack.md.

    uv venv .venv-vision --python 3.12
    uv pip install --python .venv-vision/bin/python -r vision-requirements.txt
    .venv-vision/bin/python vision_worker.py --port 8765
    TFG_VISION_URL=http://127.0.0.1:8765 <start the backend>

Endpoints mirror `services/vision/protocol.py::VisionService`; image paths
are absolute paths on this machine.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.vision.local_vision import LocalVision, VisionConfig
from services.vision.protocol import CaptionLevel, DetectTask, EmbeddingKind
from services.vram.vram_manager import PynvmlProbe, VramManager

logger = logging.getLogger("vision_worker")


class CaptionRequest(BaseModel):
    image_path: str
    level: CaptionLevel = "more_detailed_caption"


class DetectRequest(BaseModel):
    image_path: str
    task: DetectTask = "od"
    text: str = ""


class TagsRequest(BaseModel):
    image_path: str
    top_k: int = 12


class DepthRequest(BaseModel):
    image_path: str
    output_png: str


class EmbedRequest(BaseModel):
    image_path: str
    kind: EmbeddingKind = "clip"


class UnloadRequest(BaseModel):
    keep: list[str] = []


class ConfigureRequest(BaseModel):
    florence_enabled: bool = True
    florence_model: str = "florence-2-large"
    clip_enabled: bool = True
    clip_model: str = "openai/clip-vit-large-patch14"
    depth_enabled: bool = True
    depth_model: str = "depth-anything-v2-small"
    dino_enabled: bool = True
    dino_model: str = "dinov2-small"
    cache_dir: str = ""


def create_worker(cache_dir: Path) -> FastAPI:
    vram = VramManager(PynvmlProbe())
    vision = LocalVision(VisionConfig(cache_dir=cache_dir), vram)
    app = FastAPI(title="TFG vision worker")

    def _check(path: str) -> None:
        if not Path(path).is_file():
            raise HTTPException(400, f"Image not found: {path}")

    @app.get("/health")
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/status")
    def status():  # pyright: ignore[reportUnusedFunction]
        return vision.status()

    @app.post("/configure")
    def configure(req: ConfigureRequest):  # pyright: ignore[reportUnusedFunction]
        vision.configure(
            VisionConfig(
                florence_enabled=req.florence_enabled,
                florence_model=req.florence_model,
                clip_enabled=req.clip_enabled,
                clip_model=req.clip_model,
                depth_enabled=req.depth_enabled,
                depth_model=req.depth_model,
                dino_enabled=req.dino_enabled,
                dino_model=req.dino_model,
                cache_dir=Path(req.cache_dir) if req.cache_dir else cache_dir,
            )
        )
        return vision.status()

    @app.post("/caption")
    def caption(req: CaptionRequest):  # pyright: ignore[reportUnusedFunction]
        _check(req.image_path)
        return vision.caption(req.image_path, req.level)

    @app.post("/detect")
    def detect(req: DetectRequest):  # pyright: ignore[reportUnusedFunction]
        _check(req.image_path)
        return vision.detect(req.image_path, req.task, req.text)

    @app.post("/tags")
    def tags(req: TagsRequest):  # pyright: ignore[reportUnusedFunction]
        _check(req.image_path)
        return vision.tags(req.image_path, req.top_k)

    @app.post("/depth")
    def depth(req: DepthRequest):  # pyright: ignore[reportUnusedFunction]
        _check(req.image_path)
        return vision.depth(req.image_path, req.output_png)

    @app.post("/embed")
    def embed(req: EmbedRequest):  # pyright: ignore[reportUnusedFunction]
        _check(req.image_path)
        return vision.embed(req.image_path, req.kind)

    @app.post("/unload")
    def unload(req: UnloadRequest):  # pyright: ignore[reportUnusedFunction]
        return {"unloaded": vision.unload(tuple(req.keep))}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="TFG vision worker (loopback only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("TFG_VISION_PORT", "8765")))
    parser.add_argument("--cache-dir", default=os.environ.get("TFG_VISION_CACHE", ""))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path(os.environ.get("LTX_APP_DATA_DIR", ".")) / "vision-cache" / "models"
    import uvicorn

    uvicorn.run(create_worker(cache_dir), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
