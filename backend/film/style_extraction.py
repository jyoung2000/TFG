"""An art style read from pictures by a vision model (user, 2026-10-05: "reverse
engineers artstyle from an image"): how the pictures are drawn, never what they
show, as a style guide whose prompt an image model can reuse on any subject.
Shared by film style assets (handlers/film_handler.py) and the app-wide style
library (handlers/style_library_handler.py)."""

from __future__ import annotations

import json
import re
from typing import cast

from film.film_models import FilmAssetStyleGuide
from film.llm_providers import LLMMessage, LLMProvider

#: What a style is made of; each becomes a labelled style-guide trait.
STYLE_FACETS: tuple[str, ...] = ("medium", "line_work", "shading", "texture", "lighting", "composition", "influences")
STYLE_EXTRACTION_PROMPT = (
    "You are an art director reverse-engineering an art style so an image model can reproduce it on any subject. "
    "Describe HOW the images are drawn or rendered, never WHAT they show (no characters, objects, places or story). "
    "If several images are given, describe only what they share. Return JSON ONLY: "
    "{medium: '...', line_work: '...', shading: '...', texture: '...', lighting: '...', composition: '...', "
    "influences: '...', key_traits: [...], color_palette: ['#hex or colour name', ...], mood: '...', "
    "recommended_prompt: '...', description: '...'}. "
    "recommended_prompt is one reusable style prompt of 25-60 words with no subject in it, "
    "e.g. 'flat cel-shaded anime illustration, thin clean ink outlines, two-tone shadows, pastel palette, soft rim light'. "
    "Be specific: name the medium, stroke, edge quality, shading method and palette. Mark uncertain details."
)


class StyleReadError(ValueError):
    """The vision model's reply was not a style."""


def clean_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(item.strip() for item in cast(list[object], value) if isinstance(item, str) and item.strip())
    return ""


def clean_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in cast(list[object], value) if isinstance(item, str) and item.strip()]
    return []


def parse_style_reply(text: str) -> dict[str, object]:
    """The first JSON object of a (small) vision model's reply."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        parsed: object = json.loads(match.group(0) if match else text)
    except (json.JSONDecodeError, AttributeError) as exc:
        raise StyleReadError(f"Style reading returned unparseable JSON: {text[:200]}") from exc
    if not isinstance(parsed, dict):
        raise StyleReadError("Style reading must return a JSON object")
    return cast(dict[str, object], parsed)


def style_guide_of(parsed: dict[str, object]) -> FilmAssetStyleGuide:
    """The style guide in a parsed reply: the style's anatomy leads its traits, labelled."""
    facets = [f"{key.replace('_', ' ')}: {text}" for key, text in ((k, clean_text(parsed.get(k, ""))) for k in STYLE_FACETS) if text]
    return FilmAssetStyleGuide(
        key_traits=facets + clean_list(parsed.get("key_traits", [])),
        color_palette=clean_list(parsed.get("color_palette", [])),
        mood=clean_text(parsed.get("mood", "")),
        recommended_prompt=clean_text(parsed.get("recommended_prompt", "")),
    )


#: The facets a style prompt is made of: how it is drawn, not how a picture is framed.
PROMPT_FACETS: tuple[str, ...] = ("medium", "line work", "shading", "texture", "lighting", "influences")


def style_prompt_of(guide: FilmAssetStyleGuide) -> str:
    """A subject-free style prompt from the guide's facets and palette. MEASURED
    2026-10-05: qwen2.5vl:7b's own recommended_prompt named the picture's subject
    ("a figure holding an umbrella") and every render in the style drew one."""
    facets = [t.split(":", 1)[1].strip() for t in guide.key_traits
              if ":" in t and t.split(":", 1)[0].strip().lower() in PROMPT_FACETS and t.split(":", 1)[1].strip()]
    if not facets:
        return guide.recommended_prompt
    palette = f"palette of {', '.join(guide.color_palette[:5])}" if guide.color_palette else ""
    return ", ".join([*facets, *([palette] if palette else [])])


def read_style(provider: LLMProvider, data_urls: list[str]) -> FilmAssetStyleGuide:
    """The art style the pictures (data URLs, up to three) share."""
    messages = [
        LLMMessage(role="system", content=STYLE_EXTRACTION_PROMPT),
        LLMMessage(
            role="user",
            content=f"Reverse-engineer the art style of {'these images' if len(data_urls) > 1 else 'this image'}.",
            images=data_urls[:3],
        ),
    ]
    return style_guide_of(parse_style_reply(provider.chat(messages, json_mode=True).text.strip()))
