"""Server-side image operations behind FixCanvas.

The canvas previews adjustments client-side; the *saved* file is produced
here with the same maths so what the user saw is what gets scored and
reused. PIL + numpy only.

Concepts (layers, masks, adjustment layers, patch-from-reference) follow the
robbietilton/Compositor design; no Swift source was used.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Adjustments:
    """All neutral by default. Ranges mirror the sliders in FixCanvas."""

    exposure: float = 0.0  # stops, -3..3
    contrast: float = 0.0  # -1..1
    saturation: float = 0.0  # -1..1
    hue: float = 0.0  # degrees, -180..180
    black_point: float = 0.0  # 0..1 input levels
    white_point: float = 1.0  # 0..1 input levels
    gamma: float = 1.0  # 0.2..5
    temperature: float = 0.0  # -1 (cool) .. 1 (warm)

    def is_neutral(self) -> bool:
        return self == Adjustments()


def decode_mask(mask_png_base64: str, size: tuple[int, int]) -> FloatArray | None:
    """A grayscale PNG (white = selected) → float mask 0..1 at `size`."""
    if not mask_png_base64:
        return None
    raw = base64.b64decode(mask_png_base64.split(",", 1)[-1])
    with Image.open(io.BytesIO(raw)) as mask:
        gray = mask.convert("L").resize(size, Image.Resampling.BILINEAR)
        return np.asarray(gray, dtype=np.float64) / 255.0


def feather(mask: FloatArray, radius: int) -> FloatArray:
    if radius <= 0:
        return mask
    image = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), mode="L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(image, dtype=np.float64) / 255.0


def apply_adjustments(image: Image.Image, adjustments: Adjustments) -> Image.Image:
    """Levels → gamma → exposure → contrast → temperature → hue/saturation, in
    the order a colourist would stack them."""
    if adjustments.is_neutral():
        return image.convert("RGB")
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    black, white = adjustments.black_point, max(adjustments.white_point, adjustments.black_point + 1e-3)
    rgb = np.clip((rgb - black) / (white - black), 0.0, 1.0)
    if adjustments.gamma != 1.0:
        rgb = np.power(rgb, 1.0 / max(0.05, adjustments.gamma))
    if adjustments.exposure:
        rgb = np.clip(rgb * (2.0**adjustments.exposure), 0.0, 1.0)
    if adjustments.contrast:
        factor = 1.0 + adjustments.contrast
        rgb = np.clip((rgb - 0.5) * factor + 0.5, 0.0, 1.0)
    if adjustments.temperature:
        shift = adjustments.temperature * 0.08
        rgb[:, :, 0] = np.clip(rgb[:, :, 0] + shift, 0.0, 1.0)
        rgb[:, :, 2] = np.clip(rgb[:, :, 2] - shift, 0.0, 1.0)
    if adjustments.hue or adjustments.saturation:
        hsv = np.asarray(Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB").convert("HSV"), dtype=np.float64)
        if adjustments.hue:
            hsv[:, :, 0] = (hsv[:, :, 0] + adjustments.hue / 360.0 * 255.0) % 255.0
        if adjustments.saturation:
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + adjustments.saturation), 0.0, 255.0)
        return Image.fromarray(hsv.astype(np.uint8), mode="HSV").convert("RGB")
    return Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")


def patch_from_reference(candidate: Image.Image, reference: Image.Image, mask: FloatArray, feather_px: int = 6) -> Image.Image:
    """Reference pixels where the mask is white, feathered at the edge."""
    size = candidate.size
    ref = np.asarray(reference.convert("RGB").resize(size, Image.Resampling.LANCZOS), dtype=np.float64)
    cand = np.asarray(candidate.convert("RGB"), dtype=np.float64)
    alpha = feather(mask, feather_px)[:, :, None]
    out = cand * (1.0 - alpha) + ref * alpha
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGB")


def composite_with_mask(base: Image.Image, overlay: Image.Image, mask: FloatArray, feather_px: int = 4) -> Image.Image:
    """`overlay` (e.g. an inpaint result) over `base` inside the mask."""
    return patch_from_reference(base, overlay, mask, feather_px)


def mask_bbox(mask: FloatArray, threshold: float = 0.5) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the selected area in pixels, or None when nothing is selected."""
    ys, xs = np.where(mask >= threshold)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
