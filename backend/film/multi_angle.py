"""Camera prompts for Qwen-Image-Edit-2511 with fal's Multiple-Angles LoRA.

User, 2026-10-04: "Add support for these models to help make accurate multiple
angles and to produce accurate styleguides and loras". The LoRA (Apache-2.0,
fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA) was trained on 96 camera
positions and takes `<sks> [azimuth] [elevation] [distance]` with fixed words:
8 azimuths, 4 elevations, 3 distances; strength 0.8-1.0, 0.9 recommended. Its
model card puts the order azimuth -> elevation -> distance and requires the
`<sks>` trigger. FLUX.2 Klein, the previous default, was told the angle in
words and often ignored it: the style sheet's "three-quarter" and "profile"
views came back facing the camera (2026-10-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: The LoRA's file, under the app's LoRA folder, and the strength its card recommends.
ANGLES_LORA_FOLDER = "qwen_image_edit"
ANGLES_LORA_FILE = "qwen-image-edit-2511-multiple-angles-lora.safetensors"
ANGLES_LORA_STRENGTH = 0.9
#: lightx2v's 8-step distillation (Apache-2.0). MEASURED 2026-10-04 on the RTX 4070:
#: without it, 30 steps at CFG 4 came back black (NaN) after ~10 minutes an angle;
#: with it, a clean angle in 148 s. The bridge renders 8 steps at CFG 1 when present.
LIGHTNING_LORA_FILE = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
#: The angles a character's LoRA dataset gets from Qwen (user, 2026-10-04: "use qwen
#: to make multiple angles ... for z-image turbo LoRA's"): both sides at full length
#: (the outfit; "-full-" shots train twice) and close-ups (the face). The photo is
#: the front view.
LORA_ANGLE_SHOTS: tuple[str, ...] = (
    "full-34-left", "full-34-right", "full-profile-left", "full-profile-right", "full-back",
    "closeup-front", "closeup-34-left", "closeup-34-right",
)
#: The size a dataset angle is asked at: ~1 MP, which Qwen-Image-Edit fits to the
#: photo's shape. Training runs at 384-512 px; the sheet's 1664x928 doubled the time.
LORA_ANGLE_SIZE = (1024, 1024)

#: The WanGP model type of Qwen-Image-Edit-2511.
QWEN_EDIT_2511 = "qwen_image_edit_plus2_20B"
#: The setting value that picks Zero123++ (not a WanGP model).
ZERO123PP = "zero123plus"
QWEN_ANGLES_LABEL = "Qwen-Image-Edit-2511 + Multiple-Angles LoRA"
ZERO123PP_LABEL = "Zero123++ v1.2"


@dataclass(frozen=True)
class AngleEngine:
    """What renders an asset's angles: Qwen 2511 with the angles LoRA, Zero123++'s
    six-view turnaround, or a FLUX.2 model composing from words and a guide."""

    kind: Literal["qwen", "zero123", "flux"]
    model: str
    label: str
    lora: Path | None = None


#: Shot-name tokens (frontend/views/film/composer/angleViews.ts) -> the LoRA's
#: azimuth words, longest first. "left" is the subject's left, as the angle
#: presets name it.
_AZIMUTHS: tuple[tuple[str, str], ...] = (
    ("back-34-left", "back-left quarter view"),
    ("back-34-right", "back-right quarter view"),
    ("34-left", "front-left quarter view"),
    ("34-right", "front-right quarter view"),
    ("profile-left", "left side view"),
    ("profile-right", "right side view"),
    ("back", "back view"),
    ("front", "front view"),
)
_ELEVATIONS: tuple[tuple[str, str], ...] = (("high", "elevated shot"), ("low", "low-angle shot"))
_DISTANCES: tuple[tuple[str, str], ...] = (("closeup", "close-up"), ("medium", "medium shot"), ("full", "wide shot"))

#: Style-sheet views (film_generation_handler SHEET_VIEW_WORDS): full length, at eye level.
_SHEET: dict[str, str] = {
    "front view": "front view",
    "three-quarter view": "front-left quarter view",
    "profile view": "left side view",
    "back view": "back view",
}


def _pick(name: str, table: tuple[tuple[str, str], ...], default: str) -> str:
    padded = f"-{name.lower()}-"
    return next((words for token, words in table if f"-{token}-" in padded), default)


def _prompt(azimuth: str, elevation: str, distance: str) -> str:
    return f"<sks> {azimuth} {elevation} {distance}"


def angle_prompt(shot_name: str) -> str:
    """The LoRA's camera prompt for an angle-set shot ("full-34-left", "closeup-front", "full-high")."""
    return _prompt(
        _pick(shot_name, _AZIMUTHS, "front view"),
        _pick(shot_name, _ELEVATIONS, "eye-level shot"),
        _pick(shot_name, _DISTANCES, "medium shot"),
    )


def sheet_angle_prompt(view: str) -> str | None:
    """The LoRA's camera prompt for a style-sheet view, full length; None for a view it has no camera for."""
    azimuth = _SHEET.get(view.strip().lower())
    return _prompt(azimuth, "eye-level shot", "wide shot") if azimuth else None
