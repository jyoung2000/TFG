"""The app-wide style library (user, 2026-10-05: "Add a new option on the home menu to
save style from image and in the playground, image and video generator add a tab for
style to let the user set the style for the image / video").

A saved style is its pictures plus the words a vision model read from them
(film/style_extraction.py), kept in ``outputs/styles``. An image generated with a style
is drawn from the style's pictures by FLUX.1 USO Dev ("KIJ": style pictures only) in
one pass, or rendered then redrawn by FLUX.2 Klein; a video starts on such a frame
(its own first image redrawn in the style, or one drawn from its prompt).
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import threading
from pathlib import Path
from typing import cast

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from _routes._errors import HTTPError
from api_types import GenerateImageRequest, GenerateImageResponse, GenerateVideoRequest
from film.film_models import FilmAsset, FilmAssetStyleGuide, new_id, now_ms
from film.llm_providers import LLMProvider
from film.style_extraction import StyleReadError, read_style, style_prompt_of
from api_types import LoraUse
from film.style_transfer import QWEN_RESTYLER, STYLE_TRANSFER_MODELS, USO_MODEL, USO_STEPS, pick_style_images, restyle_model, style_slots, style_text, transfer_mode, transfer_prompt
from handlers.image_generation_handler import ImageGenerationHandler
from handlers.taste_handler import TasteHandler

#: Pictures a style keeps; the vision model reads the first three.
MAX_STYLE_IMAGES = 6


class SavedStyle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("style"))
    name: str
    style_prompt: str = ""
    style_guide: FilmAssetStyleGuide | None = None
    #: File names in the library folder.
    images: list[str] = Field(default_factory=list[str])
    created_at: int = Field(default_factory=now_ms)


class StyleLibraryHandler:
    def __init__(self, *, root: Path, image_generation: ImageGenerationHandler, taste: TasteHandler | None = None) -> None:
        self._root = root
        self._images = image_generation
        self._taste = taste
        #: Qwen-Edit-2511's Lightning LoRA (wired in app_handler): without it the
        #: identity-keeping restyler is unaffordable (30 steps) and USO is used.
        self._lightning: Path | None = None
        self._lock = threading.Lock()

    def attach_lightning(self, lora: Path) -> None:
        self._lightning = lora

    # ---- store ---------------------------------------------------------------

    def _index(self) -> Path:
        return self._root / "styles.json"

    def _read(self) -> list[SavedStyle]:
        try:
            raw: object = json.loads(self._index().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = cast(list[object], raw) if isinstance(raw, list) else []
        return [SavedStyle.model_validate(item) for item in items if isinstance(item, dict)]

    def _write(self, styles: list[SavedStyle]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temp = self._index().with_suffix(".tmp")
        temp.write_text(json.dumps([s.model_dump() for s in styles], indent=1), encoding="utf-8")
        temp.replace(self._index())

    def list(self) -> list[SavedStyle]:
        with self._lock:
            return sorted(self._read(), key=lambda s: s.created_at, reverse=True)

    def get(self, style_id: str) -> SavedStyle:
        style = next((s for s in self.list() if s.id == style_id), None)
        if style is None:
            raise HTTPError(404, f"Style not found: {style_id}")
        return style

    def image_file(self, style_id: str, index: int) -> Path:
        style = self.get(style_id)
        if not 0 <= index < len(style.images):
            raise HTTPError(404, "No such style picture")
        return self._root / style.images[index]

    def create(self, name: str, images_base64: list[str], provider: LLMProvider | None) -> SavedStyle:
        """A style from its pictures, read by the vision model when one is set up
        (without one it is still usable: the pictures carry the style)."""
        if not name.strip():
            raise HTTPError(400, "Name the style")
        if not images_base64:
            raise HTTPError(400, "Add at least one picture of the style")
        style = SavedStyle(name=name.strip())
        self._root.mkdir(parents=True, exist_ok=True)
        data_urls: list[str] = []
        for i, encoded in enumerate(images_base64[:MAX_STYLE_IMAGES]):
            payload = encoded.split(",", 1)[1] if encoded.startswith("data:") else encoded
            try:
                with Image.open(io.BytesIO(base64.b64decode(payload, validate=True))) as opened:
                    picture = opened.convert("RGB")
            except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as exc:
                raise HTTPError(400, f"Picture {i + 1} is not an image") from exc
            picture.thumbnail((1536, 1536))
            file = f"{style.id}-{i}.png"
            picture.save(self._root / file)
            style.images.append(file)
            if len(data_urls) < 3:
                buffer = io.BytesIO()
                picture.save(buffer, format="PNG")
                data_urls.append("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"))
        if provider is not None:
            try:
                style.style_guide = read_style(provider, data_urls)
            except StyleReadError as exc:
                raise HTTPError(502, str(exc)) from exc
            style.style_prompt = style_prompt_of(style.style_guide)
        with self._lock:
            self._write([*self._read(), style])
        return style

    def delete(self, style_id: str) -> None:
        with self._lock:
            styles = self._read()
            style = next((s for s in styles if s.id == style_id), None)
            if style is None:
                raise HTTPError(404, f"Style not found: {style_id}")
            self._write([s for s in styles if s.id != style_id])
        for file in style.images:
            (self._root / file).unlink(missing_ok=True)

    # ---- generation -------------------------------------------------------------

    @staticmethod
    def _asset(style: SavedStyle) -> FilmAsset:
        return FilmAsset(kind="style", name=style.name, style_prompt=style.style_prompt, style_guide=style.style_guide)

    def _pictures(self, style: SavedStyle, count: int) -> list[str]:
        taste = self._taste
        return pick_style_images(
            [str(self._root / f) for f in style.images if (self._root / f).is_file()], count=count,
            rejected=taste.rejected if taste is not None else (lambda _: False),
            liked=taste.liked if taste is not None else (lambda _: False),
        )

    def _transfer_model(self) -> str | None:
        return next((m for m in STYLE_TRANSFER_MODELS if self._images.model_installed(m)), None)

    def _restyle_model(self) -> tuple[str, list[LoraUse]] | None:
        """The installed model that redraws a picture keeping its subject, with its LoRAs."""
        fast = self._lightning is not None and self._lightning.is_file()
        model = restyle_model(self._images.model_installed, fast_qwen=fast)
        if model is None:
            return None
        loras = [LoraUse(name=str(self._lightning), multiplier=1.0)] if model == QWEN_RESTYLER and self._lightning else []
        return model, loras

    def generate_image(self, req: GenerateImageRequest) -> GenerateImageResponse:
        """`req` drawn in its saved style: USO from the style's pictures in one pass,
        else the request's own model, each image then redrawn by Klein."""
        style = self.get(req.styleId)
        look = style_text(self._asset(style))
        styled = req.model_copy(update={"prompt": f"{req.prompt.strip().rstrip('.')}. Art style: {look}", "styleId": ""})
        model = self._transfer_model()
        if model == USO_MODEL and (pictures := self._pictures(style, style_slots(USO_MODEL, has_content=False))):
            return self._images.generate(
                styled.model_copy(update={"model": USO_MODEL, "numSteps": max(req.numSteps, USO_STEPS), "faceLock": False}),
                reference_images=pictures, reference_mode=transfer_mode(USO_MODEL, has_content=False),
            )
        response = self._images.generate(styled)
        if model is None or response.status != "complete" or not response.image_paths:
            return response
        response.image_paths = [str(self.restyle(style, Path(p), subject=req.prompt)) for p in response.image_paths]
        return response

    def restyle(self, style: SavedStyle, source: Path, *, model: str | None = None, subject: str = "") -> Path:
        """`source` redrawn in `style` (the picture first, then the style's), by the
        model that keeps the subject (film/style_transfer.py RESTYLE_MODELS)."""
        loras: list[LoraUse] = []
        if model is None:
            chosen = self._restyle_model()
            if chosen is not None:
                model, loras = chosen
        if model is None:
            raise HTTPError(400, "No style-transfer model is installed: download FLUX.1 USO Dev or FLUX.2 Klein in the Models tab")
        pictures = self._pictures(style, style_slots(model))
        if not pictures:
            raise HTTPError(400, f"The style {style.name} has no pictures")
        with Image.open(source) as opened:
            width, height = opened.size
        scale = min(1.0, 1360 / max(width, height))
        response = self._images.generate(
            GenerateImageRequest(
                prompt=transfer_prompt(model, style_text(self._asset(style)), subject=subject, styles=len(pictures)),
                width=max(256, int(width * scale) // 16 * 16), height=max(256, int(height * scale) // 16 * 16),
                numImages=1, model=model, numSteps=USO_STEPS if model == USO_MODEL else 4, faceLock=False, outfitLock=False,
                loras=loras,
            ),
            reference_images=[str(source), *pictures], reference_mode=transfer_mode(model, has_content=True),
        )
        if response.status != "complete" or not response.image_paths:
            raise HTTPError(502, "The image model did not return the restyled picture")
        return Path(response.image_paths[0])

    def styled_video(self, req: GenerateVideoRequest) -> GenerateVideoRequest:
        """`req` in its saved style: the style in the prompt, and a first frame in it
        (the video's own image redrawn, or one drawn from the prompt) when a
        style-transfer model is installed; the video takes its look from that frame."""
        style = self.get(req.styleId)
        look = style_text(self._asset(style))
        update: dict[str, object] = {"prompt": f"{req.prompt.strip().rstrip('.')}. Art style: {look}", "styleId": ""}
        if self._transfer_model() is not None:
            if req.imagePath:
                update["imagePath"] = str(self.restyle(style, Path(req.imagePath), subject=req.prompt))
            else:
                width, height = (1024, 576) if req.aspectRatio == "16:9" else (576, 1024)
                frame = self.generate_image(GenerateImageRequest(prompt=req.prompt, width=width, height=height, numImages=1, styleId=style.id))
                if frame.status == "complete" and frame.image_paths:
                    update["imagePath"] = frame.image_paths[0]
        return req.model_copy(update=update)
