"""One shot description, compiled for whichever model is going to render it.

The same shot reads differently to different models. LTX's own guidance asks
for a chronological paragraph of natural language. Wan's asks for subject,
scene and motion. Tag-trained image checkpoints want a comma-separated
descriptor list. Writing one string and sending it everywhere means it is wrong
almost everywhere.

So the shot is held once, structured, as a `ShotBrief` — the fourteen sections
a director would actually specify — and compiled per target. The brief is the
source of truth; the compiled string is disposable and regenerated whenever the
target changes.

Two things this module refuses to do:

* **Guess at a model it does not know.** An unrecognised id gets the general
  convention and `matched=False`, and the caller is expected to say so rather
  than implying the prompt was tailored.
* **Silently lose a section.** When a target cannot carry the audio direction,
  or has no negative prompt, or the brief is longer than the model's budget,
  the dropped sections come back in `dropped` with the reason. A prompt that
  quietly lost the continuity constraints is worse than one that says it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

#: How a target wants its prompt shaped. This is the axis that actually differs
#: between model families — not vocabulary, which is shared.
PromptStyle = Literal["narrative", "structured", "tagged"]

#: Where a target's convention comes from. Shown in the UI so a documented
#: convention is never confused with this app's own default.
ConventionBasis = Literal["publisher_guidance", "community_convention", "tfg_default"]


class ShotBrief(BaseModel):
    """The common cinematic representation: one shot, before any model sees it.

    Every field is optional. An empty section is omitted rather than padded —
    a prompt that invents a lens because the field was blank is a prompt that
    lies about the shot.
    """

    #: What this shot is for in the story. Never compiled into a render prompt
    #: — no model can act on "establish the diner" — but carried so the
    #: director, the UI and a human reader keep the shot's purpose with it.
    scene_intent: str = ""
    subjects: list[str] = Field(default_factory=list[str])
    action: str = ""
    location: str = ""
    shot_size: str = ""
    #: Angle, elevation, and where the camera is relative to the subject.
    camera: str = ""
    lens: str = ""
    movement: str = ""
    lighting: str = ""
    style: str = ""
    #: Dialogue, ambience, score. Dropped for targets that render no sound.
    audio: str = ""
    #: Duration, frame rate, beats within the shot.
    timeline: str = ""
    #: What must match the neighbouring shots. These are constraints, not
    #: description, so they survive truncation ahead of style.
    continuity: list[str] = Field(default_factory=list[str])
    negative: list[str] = Field(default_factory=list[str])

    def is_empty(self) -> bool:
        return not any(
            (
                self.scene_intent, self.subjects, self.action, self.location, self.shot_size,
                self.camera, self.lens, self.movement, self.lighting, self.style,
                self.audio, self.timeline, self.continuity, self.negative,
            )
        )


@dataclass(frozen=True, slots=True)
class PromptTarget:
    """How one family of models wants to be addressed."""

    id: str
    label: str
    style: PromptStyle
    basis: ConventionBasis
    #: Why this target differs. Shown next to the compiled prompt.
    note: str
    #: Prompt budget in characters. Beyond it, the least load-bearing sections
    #: are dropped first and reported.
    max_chars: int = 1200
    supports_negative: bool = True
    #: True when the model generates sound, so the audio direction is worth sending.
    renders_audio: bool = False
    #: False for still-image models: movement and timing are dropped and reported.
    renders_motion: bool = True
    #: Substrings that identify this family in a model id. Matched lowercase.
    matches: tuple[str, ...] = ()


#: The general convention, used for anything unrecognised. Natural language is
#: the safer default: a tag list sent to a model that wants prose degrades
#: worse than prose sent to a model that wants tags.
GENERIC = PromptTarget(
    id="generic",
    label="General video model",
    style="narrative",
    basis="tfg_default",
    note=(
        "Not a model this app has a convention for, so the general one is used: "
        "plain descriptive language, action first. Check the model's own prompt "
        "guidance before relying on the result."
    ),
    max_chars=1000,
    supports_negative=True,
)

#: Known families. Each entry says where its convention comes from, because
#: "the publisher documents this" and "this is our house style" are not the
#: same claim and should not look alike in the UI.
TARGETS: tuple[PromptTarget, ...] = (
    PromptTarget(
        id="ltx",
        label="LTX Video",
        style="narrative",
        basis="publisher_guidance",
        note=(
            "LTX's own prompting guidance asks for a single chronological paragraph "
            "that describes the motion as it happens, rather than a list of tags. "
            "Camera direction is written in words, in the same sentence flow."
        ),
        max_chars=1500,
        supports_negative=True,
        matches=("ltx", "lightricks", "ltxv"),
    ),
    PromptTarget(
        id="wan",
        label="Wan",
        style="structured",
        basis="publisher_guidance",
        note=(
            "Wan's prompt guide describes prompts as subject, then scene, then motion, "
            "then aesthetic direction. Compiled as short labelled clauses in that order."
        ),
        max_chars=900,
        supports_negative=True,
        matches=("wan2", "wan-2", "wan_2", "wanx"),
    ),
    PromptTarget(
        id="hunyuan",
        label="HunyuanVideo",
        style="narrative",
        basis="community_convention",
        note=(
            "Descriptive sentences rather than tags, kept short. No published "
            "house style, so this is the convention in common use."
        ),
        max_chars=800,
        supports_negative=True,
        matches=("hunyuan",),
    ),
    PromptTarget(
        id="flux",
        label="FLUX (stills)",
        style="narrative",
        basis="publisher_guidance",
        note=(
            "FLUX is guided toward natural-language descriptions rather than tag lists. "
            "A still, so motion and timeline are dropped."
        ),
        max_chars=700,
        supports_negative=False,
        renders_motion=False,
        matches=("flux",),
    ),
    PromptTarget(
        id="sdxl",
        label="SDXL-family checkpoints (stills)",
        style="tagged",
        basis="community_convention",
        note=(
            "Tag-trained checkpoints respond to comma-separated descriptors with the "
            "most important first. A still, so motion and timeline are dropped."
        ),
        max_chars=600,
        supports_negative=True,
        renders_motion=False,
        matches=("sdxl", "stable-diffusion", "sd15", "sd-1.5", "juggernaut", "z_image", "z-image"),
    ),
    PromptTarget(
        id="veo",
        label="Veo-style hosted video",
        style="narrative",
        basis="community_convention",
        note=(
            "Hosted models in this family take a descriptive paragraph and generate "
            "sound with the picture, so the audio direction is sent rather than dropped."
        ),
        max_chars=1000,
        supports_negative=False,
        renders_audio=True,
        matches=("veo", "sora", "kling", "minimax", "hailuo", "pika", "runway", "seedance"),
    ),
)


def resolve_target(model_id: str) -> tuple[PromptTarget, bool]:
    """Find the convention for a model id.

    Returns `(target, matched)`. `matched` is False when nothing recognised the
    id, so the caller can say the prompt is general rather than tailored.
    """
    needle = (model_id or "").lower()
    if not needle:
        return GENERIC, False
    for target in TARGETS:
        if any(fragment in needle for fragment in target.matches):
            return target, True
    return GENERIC, False


@dataclass(slots=True)
class CompiledPrompt:
    """One brief, rendered for one model, with an account of what it cost."""

    model: str
    target_id: str
    target_label: str
    style: PromptStyle
    basis: ConventionBasis
    note: str
    prompt: str
    negative_prompt: str = ""
    #: True when the model id was recognised. False means the general convention.
    matched: bool = False
    #: Sections left out, each with the reason. Never silently empty.
    dropped: list[str] = field(default_factory=list[str])


#: The order sections are given up in when the budget runs out. Subjects,
#: action, shot size, movement and continuity are absent on purpose: losing any
#: of them changes what gets rendered, so they are never traded for length.
_SACRIFICE_ORDER = ("style", "lens", "timeline", "lighting", "camera", "location")


def _sentence(text: str) -> str:
    cleaned = text.strip().rstrip(".").strip()
    return cleaned


def _join(parts: list[str], separator: str = ". ") -> str:
    return separator.join(part for part in (p.strip() for p in parts) if part)


def _sections(brief: ShotBrief, target: PromptTarget) -> tuple[dict[str, str], list[str]]:
    """The brief as named sections, plus the reasons any were dropped outright."""
    dropped: list[str] = []
    still = not target.renders_motion

    # `scene_intent` is deliberately absent: it says what the shot is *for*,
    # which no render model can act on. It stays on the brief for the director
    # and the UI, and never reaches a prompt.
    sections: dict[str, str] = {}
    if brief.subjects:
        sections["subjects"] = "; ".join(_sentence(s) for s in brief.subjects if s.strip())
    if brief.action:
        sections["action"] = _sentence(brief.action)
    if brief.location:
        sections["location"] = _sentence(brief.location)
    if brief.shot_size:
        sections["shot_size"] = _sentence(brief.shot_size)
    if brief.camera:
        sections["camera"] = _sentence(brief.camera)
    if brief.lens:
        sections["lens"] = _sentence(brief.lens)

    if brief.movement:
        if still:
            dropped.append(f"movement — {target.label} renders a still frame")
        else:
            sections["movement"] = _sentence(brief.movement)
    if brief.lighting:
        sections["lighting"] = _sentence(brief.lighting)
    if brief.style:
        sections["style"] = _sentence(brief.style)

    if brief.audio:
        if target.renders_audio:
            sections["audio"] = _sentence(brief.audio)
        else:
            dropped.append(f"audio — {target.label} renders no sound")
    if brief.timeline:
        if still:
            dropped.append(f"timeline — {target.label} renders a still frame")
        else:
            sections["timeline"] = _sentence(brief.timeline)
    if brief.continuity:
        sections["continuity"] = "; ".join(_sentence(c) for c in brief.continuity if c.strip())

    return {key: value for key, value in sections.items() if value}, dropped


def _narrative(sections: dict[str, str]) -> str:
    """One paragraph, in the order a viewer takes a shot in."""
    opening = _join(
        [
            sections.get("shot_size", ""),
            sections.get("subjects", ""),
        ],
        ". ",
    )
    parts = [
        opening,
        sections.get("action", ""),
        sections.get("location", ""),
        _join([sections.get("camera", ""), sections.get("lens", ""), sections.get("movement", "")], ", "),
        _join([sections.get("lighting", ""), sections.get("style", "")], ", "),
        sections.get("audio", ""),
        sections.get("timeline", ""),
    ]
    body = _join(parts, ". ")
    if sections.get("continuity"):
        body = f"{body}. Must match: {sections['continuity']}" if body else f"Must match: {sections['continuity']}"
    return f"{body}." if body and not body.endswith(".") else body


def _structured(sections: dict[str, str]) -> str:
    """Short labelled clauses: subject, scene, motion, then direction."""
    ordered = (
        ("Subject", _join([sections.get("subjects", ""), sections.get("action", "")], ", ")),
        ("Scene", sections.get("location", "")),
        ("Framing", _join([sections.get("shot_size", ""), sections.get("camera", ""), sections.get("lens", "")], ", ")),
        ("Motion", sections.get("movement", "")),
        ("Light", sections.get("lighting", "")),
        ("Style", sections.get("style", "")),
        ("Audio", sections.get("audio", "")),
        ("Timing", sections.get("timeline", "")),
        ("Continuity", sections.get("continuity", "")),
    )
    return _join([f"{label}: {value}" for label, value in ordered if value], ". ")


def _tagged(sections: dict[str, str]) -> str:
    """Comma-separated descriptors, most load-bearing first."""
    ordered = (
        sections.get("shot_size", ""),
        sections.get("subjects", ""),
        sections.get("action", ""),
        sections.get("location", ""),
        sections.get("camera", ""),
        sections.get("lens", ""),
        sections.get("lighting", ""),
        sections.get("style", ""),
        sections.get("continuity", ""),
    )
    return ", ".join(part for part in ordered if part)


_RENDERERS = {"narrative": _narrative, "structured": _structured, "tagged": _tagged}


def compile_prompt(brief: ShotBrief, model_id: str) -> CompiledPrompt:
    """Render one brief for one model, reporting anything the target cannot carry."""
    target, matched = resolve_target(model_id)
    sections, dropped = _sections(brief, target)
    render = _RENDERERS[target.style]

    text = render(sections)
    # Over budget: give up the least load-bearing sections first, and say which.
    for key in _SACRIFICE_ORDER:
        if len(text) <= target.max_chars:
            break
        if key not in sections:
            continue
        sections.pop(key)
        dropped.append(f"{key.replace('_', ' ')} — over the {target.max_chars}-character budget for {target.label}")
        text = render(sections)
    if len(text) > target.max_chars:
        # Still too long with everything sacrificeable gone: cut at a clause
        # boundary rather than mid-word, and admit it.
        cut = text.rfind(". ", 0, target.max_chars)
        text = (text[: cut + 1] if cut > 0 else text[: target.max_chars]).rstrip()
        dropped.append(f"trailing detail — trimmed to {target.label}'s {target.max_chars}-character budget")

    negative = ""
    if brief.negative:
        if target.supports_negative:
            negative = ", ".join(_sentence(item) for item in brief.negative if item.strip())
        else:
            dropped.append(f"negative constraints — {target.label} takes no negative prompt")

    return CompiledPrompt(
        model=model_id,
        target_id=target.id,
        target_label=target.label,
        style=target.style,
        basis=target.basis,
        note=target.note,
        prompt=text,
        negative_prompt=negative,
        matched=matched,
        dropped=dropped,
    )


def compile_for(brief: ShotBrief, model_ids: list[str]) -> dict[str, CompiledPrompt]:
    """Compile once per target, skipping blanks and duplicates."""
    seen: dict[str, CompiledPrompt] = {}
    for model_id in model_ids:
        key = model_id.strip()
        if not key or key in seen:
            continue
        seen[key] = compile_prompt(brief, key)
    return seen
