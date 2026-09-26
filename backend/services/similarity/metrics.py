"""Pure similarity metrics on numpy arrays. No models here: embeddings come
from the vision service, everything else is computed from pixels."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps

FloatArray = NDArray[np.float64]
LUMA_EDGE = 256


def luma_array(image: Image.Image, edge: int = LUMA_EDGE) -> FloatArray:
    """Grayscale, resized to a fixed square so two images compare pixel to pixel."""
    oriented = ImageOps.exif_transpose(image) or image
    gray = oriented.convert("L").resize((edge, edge), Image.Resampling.BILINEAR)
    return np.asarray(gray, dtype=np.float64) / 255.0


def ssim(a: FloatArray, b: FloatArray, window: int = 8) -> float:
    """Structural similarity over non-overlapping windows (mean), in 0..1.
    A window-based SSIM without the Gaussian is enough to say "same layout
    and contrast structure"; it is one of five signals, not the verdict."""
    if a.shape != b.shape:
        raise ValueError("ssim: shapes differ")
    c1, c2 = (0.01) ** 2, (0.03) ** 2
    h, w = a.shape
    scores: list[float] = []
    for y in range(0, h - window + 1, window):
        for x in range(0, w - window + 1, window):
            pa = a[y : y + window, x : x + window]
            pb = b[y : y + window, x : x + window]
            mu_a, mu_b = float(pa.mean()), float(pb.mean())
            var_a, var_b = float(pa.var()), float(pb.var())
            cov = float(((pa - mu_a) * (pb - mu_b)).mean())
            score = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2))
            scores.append(score)
    if not scores:
        return 0.0
    return float(max(0.0, min(1.0, (sum(scores) / len(scores) + 1) / 2)))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.size == 0 or vb.size == 0 or va.shape != vb.shape:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    return float(max(0.0, min(1.0, float(va @ vb) / denom)))


def hex_to_lab(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) != 6:
        return 0.0, 0.0, 0.0
    r, g, b = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = lin(r), lin(g), lin(b)
    x = (0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl) / 0.95047
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = (0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000 colour difference (Sharma et al. 2005)."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    avg_l = (l1 + l2) / 2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    avg_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(avg_c**7 / (avg_c**7 + 25**7))) if avg_c else 0.0
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    avg_cp = (c1p + c2p) / 2

    def hp(a: float, b: float) -> float:
        if a == 0 and b == 0:
            return 0.0
        h = math.degrees(math.atan2(b, a))
        return h + 360 if h < 0 else h

    h1p, h2p = hp(a1p, b1), hp(a2p, b2)
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dlp = l2 - l1
    dcp = c2p - c1p
    dhp_term = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    if c1p * c2p == 0:
        avg_hp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        avg_hp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        avg_hp = (h1p + h2p + 360) / 2
    else:
        avg_hp = (h1p + h2p - 360) / 2
    t = 1 - 0.17 * math.cos(math.radians(avg_hp - 30)) + 0.24 * math.cos(math.radians(2 * avg_hp)) + 0.32 * math.cos(math.radians(3 * avg_hp + 6)) - 0.20 * math.cos(math.radians(4 * avg_hp - 63))
    d_theta = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(avg_cp**7 / (avg_cp**7 + 25**7)) if avg_cp else 0.0
    sl = 1 + (0.015 * (avg_l - 50) ** 2) / math.sqrt(20 + (avg_l - 50) ** 2)
    sc = 1 + 0.045 * avg_cp
    sh = 1 + 0.015 * avg_cp * t
    rt = -math.sin(math.radians(2 * d_theta)) * rc
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp_term / sh) ** 2 + rt * (dcp / sc) * (dhp_term / sh))


def palette_similarity(reference: Sequence[tuple[str, float]], candidate: Sequence[tuple[str, float]]) -> float:
    """Share-weighted nearest-colour ΔE2000 in both directions → 0..1
    (ΔE 0 = identical, ΔE ≥ 40 counts as unrelated)."""
    if not reference or not candidate:
        return 0.0

    def one_way(source: Sequence[tuple[str, float]], target: Sequence[tuple[str, float]]) -> float:
        total = sum(share for _, share in source) or 1.0
        labs_target = [hex_to_lab(h) for h, _ in target]
        acc = 0.0
        for hex_value, share in source:
            lab = hex_to_lab(hex_value)
            nearest = min(delta_e2000(lab, other) for other in labs_target)
            acc += share * max(0.0, 1.0 - nearest / 40.0)
        return acc / total

    return round((one_way(reference, candidate) + one_way(candidate, reference)) / 2, 4)


def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def layout_similarity(reference: Sequence[tuple[str, Sequence[float]]], candidate: Sequence[tuple[str, Sequence[float]]]) -> float:
    """Half count agreement per label, half greedy IoU of matched boxes."""
    if not reference and not candidate:
        return 1.0
    if not reference or not candidate:
        return 0.0
    labels = {label for label, _ in reference} | {label for label, _ in candidate}
    count_scores: list[float] = []
    iou_scores: list[float] = []
    for label in labels:
        ref_boxes = [box for lab, box in reference if lab == label]
        cand_boxes = [box for lab, box in candidate if lab == label]
        count_scores.append(1.0 - abs(len(ref_boxes) - len(cand_boxes)) / max(len(ref_boxes), len(cand_boxes), 1))
        remaining = list(cand_boxes)
        for ref_box in ref_boxes:
            if not remaining:
                iou_scores.append(0.0)
                continue
            best_index = max(range(len(remaining)), key=lambda i: box_iou(ref_box, remaining[i]))
            iou_scores.append(box_iou(ref_box, remaining.pop(best_index)))
    count_part = sum(count_scores) / len(count_scores) if count_scores else 0.0
    iou_part = sum(iou_scores) / len(iou_scores) if iou_scores else 0.0
    return round(0.5 * count_part + 0.5 * iou_part, 4)
