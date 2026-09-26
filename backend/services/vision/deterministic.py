"""Model-free image measurements.

Adapted from macchant/imex-next (MIT) — `pipeline/color.ts` and
`pipeline/analyze.ts`: CIELAB k-means palette, border-based background
isolation, vector-likeness, Sobel edge density, aspect snapping and EXIF.
Ported to numpy/PIL; the TypeScript twin in `frontend/lib/shotspec/
deterministic.ts` gives the renderer an instant preview of the same numbers.
Server values are the ones stored in the ShotSpec.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps

from services.vision.protocol import MeasuredStats, PaletteEntry

_ANALYSIS_EDGE = 256
_PALETTE_K = 6
_ASPECTS: dict[str, float] = {
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "16:9": 16 / 9,
    "21:9": 21 / 9,
    "9:16": 9 / 16,
    "2:3": 2 / 3,
    "3:4": 3 / 4,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
}
_EXIF_TAGS: dict[int, str] = {
    271: "make",
    272: "model",
    306: "datetime",
    33434: "exposure_time",
    33437: "f_number",
    34855: "iso",
    37386: "focal_length",
    41989: "focal_length_35mm",
}

FloatArray = NDArray[np.float64]


def snap_aspect(width: int, height: int) -> str:
    ratio = width / height if height else 1.0
    best = min(_ASPECTS.items(), key=lambda item: abs(math.log(ratio / item[1])))
    return best[0] if abs(math.log(ratio / best[1])) < 0.08 else f"{width}:{height}"


def _srgb_to_lab(rgb: FloatArray) -> FloatArray:
    """rgb in 0..1, shape (n, 3) → CIELAB (D65)."""
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    matrix = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = linear @ matrix.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    lab = np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)
    return lab


def _lab_to_hex(lab: FloatArray) -> str:
    l, a, b = float(lab[0]), float(lab[1]), float(lab[2])
    fy = (l + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    def inv(t: float) -> float:
        return t**3 if t**3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883
    matrix = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    linear = matrix @ np.array([x, y, z])
    srgb = np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * np.power(np.clip(linear, 0, None), 1 / 2.4) - 0.055)
    r, g, bb = (int(round(float(v) * 255)) for v in np.clip(srgb, 0, 1))
    return f"#{r:02x}{g:02x}{bb:02x}"


def kmeans_palette(rgb: FloatArray, k: int = _PALETTE_K, iterations: int = 12, seed: int = 7) -> list[PaletteEntry]:
    """k-means in CIELAB so cluster distances match perceived colour distance.
    Deterministic: fixed seed, fixed iteration count, largest cluster first."""
    if rgb.shape[0] == 0:
        return []
    lab = _srgb_to_lab(rgb)
    rng = np.random.default_rng(seed)
    k = min(k, lab.shape[0])
    centers = lab[rng.choice(lab.shape[0], size=k, replace=False)]
    labels = np.zeros(lab.shape[0], dtype=np.int64)
    for _ in range(iterations):
        distances = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = distances.argmin(axis=1)
        for index in range(k):
            members = lab[labels == index]
            if members.shape[0]:
                centers[index] = members.mean(axis=0)
    counts = np.bincount(labels, minlength=k).astype(np.float64)
    order = np.argsort(-counts)
    total = float(counts.sum()) or 1.0
    entries: list[PaletteEntry] = []
    for index in order:
        if counts[index] == 0:
            continue
        entries.append(PaletteEntry(hex=_lab_to_hex(centers[index]), share=round(float(counts[index] / total), 4)))
    return entries


def _sobel_edges(gray: FloatArray) -> FloatArray:
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64)
    ky = kx.T
    padded = np.pad(gray, 1, mode="edge")
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    for dy in range(3):
        for dx in range(3):
            window = padded[dy : dy + gray.shape[0], dx : dx + gray.shape[1]]
            gx += kx[dy, dx] * window
            gy += ky[dy, dx] * window
    return np.hypot(gx, gy)


def _laplacian_variance(gray: FloatArray) -> float:
    padded = np.pad(gray, 1, mode="edge")
    center = padded[1:-1, 1:-1]
    lap = padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:] - 4 * center
    return float(lap.var())


def _exif(image: Image.Image) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        exif = image.getexif()
    except Exception:  # noqa: BLE001 - EXIF is optional
        return result
    for tag, name in _EXIF_TAGS.items():
        value = exif.get(tag)
        if value is None:
            continue
        result[name] = str(value)
    try:
        detail = exif.get_ifd(0x8769)
        for tag, name in _EXIF_TAGS.items():
            value = detail.get(tag)
            if value is not None and name not in result:
                result[name] = str(value)
    except Exception:  # noqa: BLE001
        pass
    return result


def measure_image(image: Image.Image) -> MeasuredStats:
    width, height = image.size
    exif = _exif(image)
    oriented = ImageOps.exif_transpose(image) or image
    rgb_image = oriented.convert("RGB")
    rgb_image.thumbnail((_ANALYSIS_EDGE, _ANALYSIS_EDGE))
    rgb = np.asarray(rgb_image, dtype=np.float64) / 255.0
    flat = rgb.reshape(-1, 3)
    gray = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    hsv = np.asarray(rgb_image.convert("HSV"), dtype=np.float64) / 255.0
    saturation = float(hsv[:, :, 1].mean())
    luminance = float(gray.mean())
    contrast = float(gray.std())
    edges = _sobel_edges(gray)
    edge_density = float((edges > 0.25).mean())
    sharpness = _laplacian_variance(gray)

    # Background: the border ring; a "clear" background means the ring is one colour.
    ring = np.concatenate([rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0)
    ring_lab = _srgb_to_lab(ring)
    ring_spread = float(ring_lab.std(axis=0).mean())
    background_hex = _lab_to_hex(ring_lab.mean(axis=0)) if ring_spread < 6.0 else ""

    # Vector-likeness: few distinct colours + hard edges.
    quantised = (flat * 15).round().astype(np.int64)
    unique_colours = np.unique(quantised, axis=0).shape[0]
    colour_term = max(0.0, 1.0 - unique_colours / 400.0)
    hard_edge_term = float((edges > 1.0).sum() / max(1.0, (edges > 0.25).sum()))
    vector_likeness = round(min(1.0, 0.6 * colour_term + 0.4 * hard_edge_term), 3)

    palette = kmeans_palette(flat)
    return MeasuredStats(
        width=width,
        height=height,
        aspect=snap_aspect(width, height),
        palette=palette,
        luminance=round(luminance, 4),
        contrast=round(contrast, 4),
        saturation=round(saturation, 4),
        edge_density=round(edge_density, 4),
        sharpness=round(sharpness, 6),
        background_hex=background_hex,
        vector_likeness=vector_likeness,
        exif=exif,
    )


def measure_path(path: str | Path) -> MeasuredStats:
    with Image.open(path) as image:
        return measure_image(image)
