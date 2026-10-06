"""Prompt output templates.

Adapted from wildbyteai/promptlens (MIT), `templates.js`: the built-in
Detailed / Natural / Tags / Concise reverse-prompt instructions and the
custom-template shape (id, name, description, instruction, profile, limits).
The IndexedDB history and provider adapters are not used — TFG has its own
job store and `film/llm_providers.py`.

Templates serve two purposes here:

* as the *system instruction* when a VLM is asked to write a prompt from a
  ShotSpec (profile → instruction), and
* as the *output style* the deterministic compiler renders
  (`weighted`, `json`, `negative_only` on top of the existing narrative /
  structured / tagged).

Users can edit the instruction text; overrides live in
`<app-data>/prompt_templates.json` and never replace the built-ins on disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TemplateProfile = Literal["detailed", "natural", "tags", "concise", "custom"]
INSTRUCTION_MAX_LENGTH = 4000
CUSTOM_TEMPLATE_LIMIT = 50


class PromptTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    instruction: str
    profile: TemplateProfile = "custom"
    built_in: bool = False
    #: The JSON keys the VLM is asked to return for this profile.
    json_shape: dict[str, str] = Field(default_factory=dict[str, str])


_DETAILED_SHAPE = {
    "prompt": "the positive generation prompt, production-ready",
    "negative_prompt": "what to exclude, comma-separated",
    "subject": "who/what, pose or action, appearance",
    "environment": "location, time of day, depth layers",
    "composition": "framing, camera height, angle, focal length feel",
    "lighting": "source, direction, quality, colour temperature",
    "palette": "dominant colours as words",
    "style": "medium, rendering or photographic style, texture",
    "quality": "resolution/fidelity terms",
}

BUILTIN_TEMPLATES: tuple[PromptTemplate, ...] = (
    PromptTemplate(
        id="detailed",
        name="Detailed",
        description="Production prompt material: subject, environment, composition, lighting, palette, style, quality.",
        profile="detailed",
        built_in=True,
        instruction=(
            "You are an elite reverse-prompt analyst for image and video generation.\n"
            "Your task is not to caption the image. Reconstruct a practical generation prompt that could recreate the "
            "visible image as closely as possible.\n"
            "Analyze only visible evidence. Be specific about subject, pose or action, appearance, environment, composition, "
            "lighting, atmosphere, color palette, materials, texture, camera/framing, style, and image quality.\n"
            "Measured facts supplied with the image are ground truth; never contradict them.\n"
            "Write for professional designers using generation tools: practical production prompt material, not a caption."
        ),
        json_shape=_DETAILED_SHAPE,
    ),
    PromptTemplate(
        id="natural",
        name="Natural language",
        description="One fluent paragraph, for models that want prose (LTX, FLUX, Wan).",
        profile="natural",
        built_in=True,
        instruction=(
            "You are an expert generation-prompt writer using natural language prompts.\n"
            "Reconstruct a fluent English prompt that describes the visible image as a coherent paragraph rather than a keyword list.\n"
            "Prioritize subject, environment, composition, lighting, color, mood, texture, rendering or photographic style, and final image quality.\n"
            "Measured facts supplied with the image are ground truth; never contradict them."
        ),
        json_shape={"prompt": "one paragraph", "negative_prompt": "comma-separated exclusions"},
    ),
    PromptTemplate(
        id="tags",
        name="Weighted tags",
        description="Positive and negative tag material for SD/SDXL/Z-Image style checkpoints.",
        profile="tags",
        built_in=True,
        instruction=(
            "You are an expert at reconstructing tag-oriented generation prompts from visible evidence.\n"
            "Reconstruct the image as positive and negative tag-style prompt material, most load-bearing tags first.\n"
            "Use tags as the primary writing style while preserving enough visual context for downstream editing. "
            "Weighting syntax is added by the compiler, not by you.\n"
            "Measured facts supplied with the image are ground truth; never contradict them."
        ),
        json_shape={"tags": "comma-separated positive tags", "negative_tags": "comma-separated negative tags"},
    ),
    PromptTemplate(
        id="concise",
        name="Quick copy",
        description="A compact prompt that keeps subject, style, lighting, composition and mood.",
        profile="concise",
        built_in=True,
        instruction=(
            "You are a generation-prompt assistant focused on concise practical output.\n"
            "Reconstruct the visible image as a compact prompt that preserves the most important subject, style, lighting, "
            "composition, and mood. Under 60 words.\n"
            "Measured facts supplied with the image are ground truth; never contradict them."
        ),
        json_shape={"prompt": "under 60 words"},
    ),
)


class TemplateStore:
    """Built-ins plus user overrides/customs persisted as one JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._custom: dict[str, PromptTemplate] = {}
        self._overrides: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable prompt templates file %s: %s", self._path, exc)
            return
        if not isinstance(payload, dict):
            return
        data = cast(dict[str, Any], payload)
        raw_overrides = data.get("overrides", {})
        if isinstance(raw_overrides, dict):
            self._overrides = {str(k): str(v) for k, v in cast(dict[str, Any], raw_overrides).items()}
        raw_custom = data.get("custom", [])
        if isinstance(raw_custom, list):
            for item in cast(list[Any], raw_custom):
                try:
                    template = PromptTemplate.model_validate(item)
                except Exception:  # noqa: BLE001
                    continue
                template.built_in = False
                self._custom[template.id] = template

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"overrides": self._overrides, "custom": [t.model_dump() for t in self._custom.values()]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self) -> list[PromptTemplate]:
        result: list[PromptTemplate] = []
        for template in BUILTIN_TEMPLATES:
            copy = template.model_copy(deep=True)
            if template.id in self._overrides:
                copy.instruction = self._overrides[template.id]
            result.append(copy)
        result.extend(t.model_copy(deep=True) for t in self._custom.values())
        return result

    def get(self, template_id: str) -> PromptTemplate:
        for template in self.list():
            if template.id == template_id:
                return template
        return self.list()[0]

    def set_instruction(self, template_id: str, instruction: str) -> PromptTemplate:
        text = instruction.strip()
        if not text:
            raise ValueError("Template instruction cannot be empty")
        if len(text) > INSTRUCTION_MAX_LENGTH:
            raise ValueError(f"Template instruction is longer than {INSTRUCTION_MAX_LENGTH} characters")
        if any(t.id == template_id for t in BUILTIN_TEMPLATES):
            self._overrides[template_id] = text
        elif template_id in self._custom:
            self._custom[template_id].instruction = text
        else:
            raise KeyError(template_id)
        self._save()
        return self.get(template_id)

    def reset(self, template_id: str) -> PromptTemplate:
        self._overrides.pop(template_id, None)
        self._save()
        return self.get(template_id)

    def create(self, name: str, instruction: str, description: str = "", profile: TemplateProfile = "custom") -> PromptTemplate:
        if len(self._custom) >= CUSTOM_TEMPLATE_LIMIT:
            raise ValueError(f"At most {CUSTOM_TEMPLATE_LIMIT} custom templates")
        text = instruction.strip()
        if not text or len(text) > INSTRUCTION_MAX_LENGTH:
            raise ValueError("Template instruction must be 1–4000 characters")
        import uuid

        template = PromptTemplate(
            id=f"custom-{uuid.uuid4().hex[:8]}",
            name=name.strip()[:80] or "Untitled template",
            description=description.strip()[:160],
            instruction=text,
            profile=profile,
        )
        self._custom[template.id] = template
        self._save()
        return template

    def delete(self, template_id: str) -> bool:
        removed = self._custom.pop(template_id, None) is not None
        if removed:
            self._save()
        return removed


def weighted_tag(term: str, weight: float) -> str:
    """SD-style attention syntax; 1.0 stays bare (promptlens/imex convention)."""
    if not term:
        return ""
    return term if abs(weight - 1.0) < 1e-9 else f"({term}:{weight:.1f})"
