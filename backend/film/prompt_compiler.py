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

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from film.shot_spec import ShotSpec

#: How a target wants its prompt shaped. This is the axis that actually differs
#: between model families — not vocabulary, which is shared.
PromptStyle = Literal["narrative", "structured", "tagged", "weighted", "json", "negative_only"]

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
        id="ltx2",
        label="LTX-2 (22B distilled)",
        style="narrative",
        basis="publisher_guidance",
        note=(
            "LTX-2 follows the LTX guidance: one chronological paragraph of natural language, camera "
            "direction in the same flow. The distilled model runs 8 steps at 540p/720p on a 12 GB card."
        ),
        max_chars=1500,
        supports_negative=True,
        renders_audio=True,
        matches=("ltx2", "ltx-2", "ltx_2", "22b"),
    ),
    PromptTarget(
        id="wan22",
        label="Wan 2.2",
        style="structured",
        basis="publisher_guidance",
        note=(
            "Wan 2.2 keeps Wan's subject → scene → motion → aesthetics order; the 5B TI2V "
            "build renders 720p at 24 fps and takes a start frame."
        ),
        max_chars=900,
        supports_negative=True,
        matches=("wan2.2", "wan22", "wan_2_2", "wan-2.2", "ti2v"),
    ),
    PromptTarget(
        id="z_image",
        label="Z-Image (stills)",
        style="tagged",
        basis="community_convention",
        note=(
            "Z-Image responds to comma-separated descriptors with the most important first; "
            "the distilled build has an 8-step floor. A still, so motion and timeline are dropped."
        ),
        max_chars=700,
        supports_negative=True,
        renders_motion=False,
        matches=("z_image", "z-image", "zimage"),
    ),
    PromptTarget(
        id="qwen_image_edit",
        label="Qwen-Image-Edit (edit a reference)",
        style="narrative",
        basis="publisher_guidance",
        note=(
            "An editing model: the prompt is an instruction about what to change in the reference "
            "image, written as plain sentences. The reference travels as conditioning, not prose."
        ),
        max_chars=600,
        supports_negative=True,
        renders_motion=False,
        matches=("qwen_image_edit", "qwen-image-edit", "qwen_edit", "kontext", "image_edit"),
    ),
    PromptTarget(
        id="cloud_generic",
        label="Hosted model (generic)",
        style="narrative",
        basis="tfg_default",
        note=(
            "A hosted provider whose model is not documented here: a descriptive paragraph, "
            "no weighting syntax, negatives only if the API exposes them."
        ),
        max_chars=1000,
        supports_negative=False,
        renders_audio=True,
        matches=("cloud_generic",),
    ),
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
        matches=("sdxl", "stable-diffusion", "sd15", "sd-1.5", "juggernaut"),
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
        if target.id == needle:
            return target, True
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


def _weighted(sections: dict[str, str]) -> str:
    """SD attention syntax, strongest signals emphasised (imex-next SDXL formatter)."""
    from film.prompt_templates import weighted_tag

    ordered = (
        (sections.get("subjects", ""), 1.2),
        (sections.get("action", ""), 1.1),
        (sections.get("shot_size", ""), 1.1),
        (sections.get("location", ""), 1.0),
        (sections.get("camera", ""), 1.0),
        (sections.get("lens", ""), 1.0),
        (sections.get("lighting", ""), 1.0),
        (sections.get("style", ""), 1.1),
        (sections.get("continuity", ""), 0.9),
    )
    return ", ".join(weighted_tag(part, weight) for part, weight in ordered if part)


def _json_style(sections: dict[str, str]) -> str:
    """The sections as a JSON object — for models/APIs that take structured prompts."""
    return json.dumps({key: value for key, value in sections.items() if value}, ensure_ascii=False)


def _negative_only(sections: dict[str, str]) -> str:
    """Nothing positive: the caller only wants the negative prompt (see compile_from_spec)."""
    return ""


_RENDERERS = {
    "narrative": _narrative,
    "structured": _structured,
    "tagged": _tagged,
    "weighted": _weighted,
    "json": _json_style,
    "negative_only": _negative_only,
}


def compile_prompt(brief: ShotBrief, model_id: str, style: PromptStyle | None = None) -> CompiledPrompt:
    """Render one brief for one model, reporting anything the target cannot carry.
    `style` overrides the target's own convention (the Reproduce editor's tabs)."""
    target, matched = resolve_target(model_id)
    sections, dropped = _sections(brief, target)
    chosen: PromptStyle = style or target.style
    render = _RENDERERS[chosen]

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
        style=chosen,
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



# ---------------------------------------------------------------------------
# ShotSpec → prompt + parameters + conditioning
#
# The Reproduce path compiles from the canonical ShotSpec rather than a hand
# written brief. Parameters default to what a 12 GB card renders comfortably.


class SpecParams(BaseModel):
    seed: int | None = None
    steps: int = 8
    guidance: float = 1.0
    width: int = 0
    height: int = 0
    duration: float = 0.0
    fps: int = 24
    resolution: str = ""


class SpecConditioning(BaseModel):
    start_frame: str = ""
    control_video: str = ""
    depth: str = ""
    refs: list[str] = Field(default_factory=list[str])
    loras: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])


class PromptHints(BaseModel):
    """What the knowledge engine learned for this kind of shot on this target:
    phrase sets that won before, parameters that worked, and the evidence."""

    phrases: list[str] = Field(default_factory=list[str])
    params: dict[str, float | int] = Field(default_factory=dict[str, float | int])
    evidence: list[str] = Field(default_factory=list[str])
    sample: int = 0


class SpecCompileResult(BaseModel):
    target_id: str
    target_label: str
    style: PromptStyle
    prompt: str
    negative_prompt: str = ""
    params: SpecParams = Field(default_factory=SpecParams)
    conditioning: SpecConditioning = Field(default_factory=SpecConditioning)
    dropped: list[str] = Field(default_factory=list[str])
    hints_applied: list[str] = Field(default_factory=list[str])
    matched: bool = True


#: 4070-safe defaults per target: (steps, guidance, long edge or resolution, duration s, fps).
_TARGET_DEFAULTS: dict[str, dict[str, Any]] = {
    "ltx2": {"steps": 8, "guidance": 1.0, "resolution": "540p", "duration": 6.0, "fps": 24},
    "ltx": {"steps": 8, "guidance": 1.0, "resolution": "540p", "duration": 6.0, "fps": 24},
    "wan22": {"steps": 20, "guidance": 4.0, "resolution": "720p", "duration": 5.0, "fps": 24},
    "wan": {"steps": 20, "guidance": 4.0, "resolution": "480p", "duration": 5.0, "fps": 16},
    "hunyuan": {"steps": 20, "guidance": 6.0, "resolution": "540p", "duration": 5.0, "fps": 24},
    "veo": {"steps": 0, "guidance": 0.0, "resolution": "720p", "duration": 5.0, "fps": 24},
    "cloud_generic": {"steps": 0, "guidance": 0.0, "resolution": "720p", "duration": 5.0, "fps": 24},
    "z_image": {"steps": 8, "guidance": 1.0, "long_edge": 1024},
    "qwen_image_edit": {"steps": 20, "guidance": 4.0, "long_edge": 1024},
    "flux": {"steps": 20, "guidance": 3.5, "long_edge": 1024},
    "sdxl": {"steps": 25, "guidance": 6.0, "long_edge": 1024},
    "generic": {"steps": 20, "guidance": 4.0, "resolution": "540p", "duration": 5.0, "fps": 24},
}
_ALLOWED_DURATIONS: tuple[float, ...] = (4.0, 5.0, 6.0, 8.0, 10.0)
_DEFAULT_NEGATIVES: tuple[str, ...] = ("text", "watermark", "logo", "distorted hands", "extra limbs", "blurry")


def _snap_duration(seconds: float) -> float:
    if seconds <= 0:
        return 6.0
    return min(_ALLOWED_DURATIONS, key=lambda d: abs(d - seconds))


def _size_for(aspect: str, width: int, height: int, long_edge: int) -> tuple[int, int]:
    """Multiples of 16, long edge capped, aspect preserved."""
    ratio = (width / height) if width and height else 16 / 9
    if not (width and height) and ":" in aspect:
        try:
            a, b = aspect.split(":")
            ratio = float(a) / float(b)
        except ValueError:
            ratio = 16 / 9
    if ratio >= 1:
        w, h = long_edge, long_edge / ratio
    else:
        w, h = long_edge * ratio, long_edge
    return max(64, round(w / 16) * 16), max(64, round(h / 16) * 16)


def brief_from_spec(spec: "ShotSpec") -> ShotBrief:
    """The spec as the compiler's fourteen sections. Vocabulary comes from
    `shot_vocabulary` so words never drift between paths."""
    from film.shot_vocabulary import (
        ANGLE_PHRASES,
        CAMERA_MOVE_PHRASES,
        ELEVATION_PHRASES,
        SHOT_SIZE_PHRASES,
        aperture_phrase,
        focal_phrase,
    )

    subjects: list[str] = []
    for subject in spec.subjects:
        label = f"{subject.count} {subject.label}" if subject.count > 1 else subject.label
        if subject.attributes:
            label = f"{label} ({', '.join(subject.attributes)})"
        subjects.append(label)
    scene = spec.scene
    location = ", ".join(p for p in (scene.location, scene.environment, scene.time_of_day, scene.weather) if p)
    layers = "; ".join(f"{name}: {value}" for name, value in (("foreground", scene.fg), ("midground", scene.mg), ("background", scene.bg)) if value)
    if layers:
        location = f"{location}. {layers}" if location else layers
    camera = spec.camera
    camera_text = ", ".join(
        p for p in (ANGLE_PHRASES.get(camera.angle, camera.angle), ELEVATION_PHRASES.get(camera.height, camera.height and f"{camera.height} camera height")) if p
    )
    lens_parts = [camera.lens_estimate or (focal_phrase(camera.focal_mm) if camera.focal_mm else "")]
    if camera.focal_mm:
        lens_parts.append(f"{int(camera.focal_mm)}mm lens")
    if camera.aperture:
        lens_parts.append(aperture_phrase(camera.aperture) or camera.aperture)
    if camera.dof:
        lens_parts.append(f"{camera.dof} depth of field")
    if camera.focus:
        lens_parts.append(f"focus on {camera.focus}")
    lens = ", ".join(p for p in lens_parts if p)
    movement = CAMERA_MOVE_PHRASES.get(camera.move, camera.move)
    if movement and camera.move != "static":
        intensity = "subtle" if camera.move_intensity < 0.3 else "steady" if camera.move_intensity < 0.7 else "fast"
        movement = f"{intensity} {movement}"
    if camera.handheld:
        movement = f"{movement}, handheld" if movement else "handheld camera"
    lighting = ", ".join(
        p
        for p in (
            f"{spec.lighting.quality} light" if spec.lighting.quality else "",
            f"key light from the {spec.lighting.key_direction}" if spec.lighting.key_direction else "",
            f"{spec.lighting.color_temp} colour temperature" if spec.lighting.color_temp else "",
            f"{spec.lighting.mood} mood" if spec.lighting.mood else "",
        )
        if p
    )
    style_parts: list[str] = []
    if spec.style.medium:
        style_parts.append(spec.style.medium if spec.style.medium != "photo" else "photograph")
    style_parts.extend(spec.top_tags(8))
    style_parts.extend(f"in the style of {a}" for a in spec.style.artists[:1])
    palette = ", ".join(e.hex for e in spec.measured.palette[:3])
    if palette:
        style_parts.append(f"palette of {palette}")
    timeline = ""
    if spec.source.kind == "video_shot" and spec.source.start is not None and spec.source.end is not None:
        timeline = f"{max(0.5, spec.source.end - spec.source.start):.1f} second shot"
        if spec.motion.pacing:
            timeline += f", {spec.motion.pacing} pacing"
    negatives = list(dict.fromkeys([*spec.style.negatives, *_DEFAULT_NEGATIVES]))
    return ShotBrief(
        scene_intent=spec.narrative.purpose,
        subjects=subjects,
        action=spec.narrative.what_happens,
        location=location,
        shot_size=SHOT_SIZE_PHRASES.get(camera.shot_size, camera.shot_size),
        camera=camera_text,
        lens=lens,
        movement=movement,
        lighting=lighting,
        style=", ".join(dict.fromkeys(p for p in style_parts if p)),
        timeline=timeline,
        negative=negatives,
    )


def compile_from_spec(
    spec: "ShotSpec",
    target: str,
    style: PromptStyle | None = None,
    hints: PromptHints | None = None,
    *,
    seed: int | None = None,
) -> SpecCompileResult:
    """Deterministic: the same spec, target, style, hints and seed always give
    the same result. Hints add phrases the knowledge engine saw win before
    and override parameters it saw work."""
    resolved, matched = resolve_target(target)
    brief = brief_from_spec(spec)
    applied: list[str] = []
    if hints is not None:
        existing = brief.style.lower()
        extra = [phrase for phrase in hints.phrases if phrase and phrase.lower() not in existing]
        if extra:
            brief.style = ", ".join(p for p in (brief.style, *extra) if p)
            applied.extend(extra)
    compiled = compile_prompt(brief, resolved.id, style)
    chosen: PromptStyle = style or resolved.style
    prompt = "" if chosen == "negative_only" else compiled.prompt
    negative = compiled.negative_prompt
    if chosen == "negative_only" and not negative:
        negative = ", ".join(brief.negative)

    defaults = _TARGET_DEFAULTS.get(resolved.id, _TARGET_DEFAULTS["generic"])
    params = SpecParams(seed=seed, steps=int(defaults.get("steps", 20)), guidance=float(defaults.get("guidance", 4.0)))
    if resolved.renders_motion:
        params.resolution = str(defaults.get("resolution", "540p"))
        source_seconds = (spec.source.end - spec.source.start) if spec.source.start is not None and spec.source.end is not None else 0.0
        params.duration = _snap_duration(source_seconds or float(defaults.get("duration", 6.0)))
        params.fps = int(defaults.get("fps", 24))
    else:
        params.width, params.height = _size_for(spec.source.aspect, spec.source.width, spec.source.height, int(defaults.get("long_edge", 1024)))
    if hints is not None:
        for key, value in hints.params.items():
            if key == "steps":
                params.steps = max(1, int(value))
                applied.append(f"steps={params.steps}")
            elif key == "guidance":
                params.guidance = float(value)
                applied.append(f"guidance={params.guidance}")
    if resolved.id == "z_image":
        params.steps = max(8, params.steps)  # the distilled model's floor (wangp_bridge)

    conditioning = SpecConditioning(depth=spec.layout3d.depth_map_path)
    if resolved.id == "qwen_image_edit" and spec.source.path:
        conditioning.refs = [spec.source.path]
    if resolved.renders_motion and spec.source.path:
        conditioning.start_frame = spec.source.path

    return SpecCompileResult(
        target_id=resolved.id,
        target_label=resolved.label,
        style=chosen,
        prompt=prompt,
        negative_prompt=negative,
        params=params,
        conditioning=conditioning,
        dropped=list(compiled.dropped),
        hints_applied=applied,
        matched=matched,
    )
