"""Saved art styles applied to pictures (user, 2026-10-05: "reverse engineer artstyle
from an image ... save the art style to an asset to use later and also use those
styles to transform an image from 1 art style to another accurately and efficiently",
"reference assets in prompts and use the character, artstyle, prop, or location
consistently like a LoRA without being a lora").

A style asset is its pictures plus the words the vision model read from them
(`FilmAsset.style_prompt`, `style_guide`). A transfer gives the image model both:
FLUX.1 USO Dev (built for style transfer: "KI" = the content picture, then up to two
style pictures; "KIJ" = style pictures only) when installed, else FLUX.2 Klein
("KI" = the picture to redraw, then the style picture).

The user's grades steer which of a style's pictures are used: graded up first,
graded down never (film/taste.py).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from film.film_models import FilmAsset

#: FLUX.1 USO Dev: WanGP's style-transfer model (defaults/flux_dev_uso.json).
USO_MODEL = "flux_dev_uso"
#: Transfer models, best first. Klein is the installed fallback (4 steps, Apache 2.0).
STYLE_TRANSFER_MODELS: tuple[str, ...] = (USO_MODEL, "flux2_klein_9b", "flux2_klein_4b")
#: FLUX.1 Dev is not a few-step model: 4 steps is noise; ~28 is its usual count.
USO_STEPS = 28
#: Style pictures a model takes beside the content picture.
_STYLE_SLOTS = {USO_MODEL: 2}


def style_text(style: FilmAsset) -> str:
    """The style in words: its prompt (or the guide's), then the guide's traits,
    palette and mood. Never the subject of its pictures."""
    guide = style.style_guide
    head = style.style_prompt.strip() or (guide.recommended_prompt.strip() if guide else "")
    bits = [head] if head else []
    if guide is not None:
        bits += [t.strip() for t in guide.key_traits if t.strip() and t.strip().lower() not in head.lower()]
        if guide.color_palette:
            bits.append("palette: " + ", ".join(c.strip() for c in guide.color_palette if c.strip()))
        if guide.mood.strip():
            bits.append(f"mood: {guide.mood.strip()}")
    return "; ".join(bits) or style.name.strip()


def style_slots(model: str) -> int:
    return _STYLE_SLOTS.get(model, 1)


def pick_style_images(
    paths: Sequence[str], *, rejected: Callable[[str], bool], liked: Callable[[str], bool], count: int,
) -> list[str]:
    """`count` of a style's pictures: graded-up first, graded-down never, else in order."""
    kept = [p for p in paths if not rejected(p)]
    return sorted(kept, key=lambda p: 0 if liked(p) else 1)[:count]


def transfer_mode(model: str, *, has_content: bool) -> str:
    """WanGP's `video_prompt_type` letters for a transfer."""
    if model == USO_MODEL:
        return "KI" if has_content else "KIJ"
    return "KI" if has_content else "I"


def transfer_prompt(model: str, style: str, *, subject: str = "", styles: int = 1) -> str:
    """The prompt of a transfer of `subject` (or the content picture) into `style`."""
    style = style.strip().rstrip(".")
    if model == USO_MODEL:
        # USO reads the style from its style pictures; the prompt names the content.
        what = subject.strip().rstrip(".") or "The same picture as the reference image, same subjects, poses and composition"
        return f"{what}. Art style: {style}." if style else f"{what}."
    pictures = "picture 2" if styles == 1 else f"pictures 2 to {styles + 1}"
    content = f" showing {subject.strip().rstrip('.')}" if subject.strip() else ""
    return (
        f"Redraw picture 1{content} in exactly the art style of {pictures}"
        + (f": {style}" if style else "")
        + ". Keep picture 1's composition, subjects, faces, poses, outfits and layout; take only the art style "
        f"(medium, line work, shading, colour palette, texture, lighting) from {pictures}, not its content."
    )
