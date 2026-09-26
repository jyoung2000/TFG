"""Fusion: many sources, one ShotSpec.

Rules, in priority order (adapted from macchant/imex-next `fusion.ts`, MIT,
and extended to video):

1. **Measured beats everything** for physical properties: dimensions, aspect,
   palette, luminance/contrast/saturation, edges. A VLM is *told* these and
   is never allowed to overwrite them.
2. **Detection beats description**: Florence's boxes and counts win over a
   VLM's subject list; depth medians attach to those boxes; optical flow wins
   over any guess at camera movement.
3. **CLIP ranks style**; the VLM may add a medium/mood, and when the two agree
   the confidence goes up, when they disagree the higher-confidence one wins
   but is capped so nothing overclaims.
4. **The VLM owns narrative and the unmeasurable**: what happens, purpose,
   location names, lighting direction — with whatever confidence it reported.
5. **Locks are absolute**: a section the user pinned is never touched, by any
   stage, and keeps `provenance = user`.

Every writer goes through `_write()` so provenance and confidence stay
consistent, and a missing source is simply skipped.
"""

from __future__ import annotations

from typing import Any, cast

from film.shot_spec import (
    PROVENANCE_RANK,
    PaletteEntry,
    ShotSpec,
    SpecCamera,
    SpecLighting,
    SpecMotion,
    SpecMotionDominant,
    SpecNarrative,
    SpecScene,
    SpecSource,
    SpecSubject,
    TagTerm,
)
from film.shot_vocabulary import (
    DOF_VOCAB,
    LIGHTING_QUALITY_VOCAB,
    MEDIUM_VOCAB,
    MOOD_VOCAB,
    TIME_OF_DAY_VOCAB,
    shot_size_from_subject_height,
)
from handlers.vision_handler import VisionAnalysis

_STOP_WORDS = frozenset({"the", "and", "with", "for", "from", "into", "style", "illustration", "art", "design", "image", "color", "colors", "a", "an", "of"})


def _write(spec: ShotSpec, section: str, provenance: str, confidence: float, *, force: bool = False) -> bool:
    """Record that `provenance` wrote `section`. Returns False when the section
    is locked (caller must not write) or a higher-ranked source already owns it
    and `force` is False."""
    if spec.is_locked(section):
        return False
    current = spec.provenance.get(section, "")
    if not force and current and PROVENANCE_RANK.get(provenance, 9) > PROVENANCE_RANK.get(current, 9):
        return False
    spec.set_section(section, provenance, confidence)  # type: ignore[arg-type]
    return True


def _labels_roughly_agree(a: str, b: str) -> bool:
    def norm(text: str) -> set[str]:
        cleaned = "".join(ch if ch.isalnum() or ch == " " else " " for ch in text.lower())
        return {w for w in cleaned.split() if len(w) > 2 and w not in _STOP_WORDS}

    sa, sb = norm(a), norm(b)
    if not sa or not sb:
        return False
    overlap = len(sa & sb)
    return overlap / (min(len(sa), len(sb)) or 1) >= 0.4


def infer_medium(vector_likeness: float, edge_density: float, tags: list[TagTerm]) -> tuple[str, float]:
    """imex-next's cross-field inference: a flat, hard-edged image is vector;
    a soft, low-edge one is a photo; CLIP's medium tag can confirm either."""
    if vector_likeness >= 0.7:
        return "vector", round(vector_likeness, 3)
    if vector_likeness <= 0.2 and edge_density < 0.06:
        return "photo", 0.55
    for tag in tags:
        term = tag.term.lower()
        for medium in MEDIUM_VOCAB:
            if medium in term or (medium == "photo" and "photograph" in term):
                return medium, round(min(0.7, tag.score + 0.3), 3)
    return "", 0.0


# ---- stage writers ----------------------------------------------------------


def apply_measured(spec: ShotSpec, analysis: VisionAnalysis) -> None:
    measured = analysis.measured
    spec.source = SpecSource(
        kind=spec.source.kind,
        hash=analysis.content_hash,
        path=analysis.image_path,
        width=measured.width,
        height=measured.height,
        aspect=measured.aspect,
        fps=spec.source.fps,
        start=spec.source.start,
        end=spec.source.end,
    )
    if not _write(spec, "measured", "measured", 1.0, force=True):
        return
    spec.measured.palette = [PaletteEntry(hex=e.hex, share=e.share) for e in measured.palette]
    spec.measured.luminance = measured.luminance
    spec.measured.contrast = measured.contrast
    spec.measured.saturation = measured.saturation
    spec.measured.edge_density = measured.edge_density
    spec.measured.sharpness = measured.sharpness
    spec.measured.exif = dict(measured.exif)


def apply_florence(spec: ShotSpec, analysis: VisionAnalysis) -> None:
    """Boxes → subjects (grouped by label with counts); the caption seeds the
    narrative only when nothing better exists; the biggest subject's height
    gives the shot size."""
    if analysis.regions and _write(spec, "subjects", "florence", 0.8):
        grouped: dict[str, SpecSubject] = {}
        for region in analysis.regions:
            label = region.label.strip().lower() or "object"
            existing = grouped.get(label)
            if existing is None:
                grouped[label] = SpecSubject(label=label, bbox=list(region.bbox), depth_median=region.depth_median, count=1)
            else:
                existing.count += 1
                # Keep the largest box as the representative.
                if len(region.bbox) == 4 and len(existing.bbox) == 4 and region.bbox[2] * region.bbox[3] > existing.bbox[2] * existing.bbox[3]:
                    existing.bbox = list(region.bbox)
                    existing.depth_median = region.depth_median
        spec.subjects = list(grouped.values())
        tallest = max((s for s in spec.subjects if len(s.bbox) == 4), key=lambda s: s.bbox[3], default=None)
        if tallest is not None and not spec.is_locked("camera"):
            size = shot_size_from_subject_height(tallest.bbox[3])
            if _write(spec, "camera", "florence", 0.6):
                spec.camera.shot_size = size
    if analysis.caption and analysis.caption.text and not spec.narrative.what_happens and not spec.is_locked("narrative"):
        if _write(spec, "narrative", "florence", 0.5):
            spec.narrative.what_happens = analysis.caption.text


def apply_clip(spec: ShotSpec, analysis: VisionAnalysis) -> None:
    if analysis.tags is None:
        return
    if not _write(spec, "style", "clip", 0.6):
        return
    tags = [TagTerm(term=t.term, score=t.score) for t in analysis.tags.tags]
    spec.style.tags = sorted(tags, key=lambda t: -t.score)
    spec.style.artists = [t.term for t in analysis.tags.tags if t.category == "artist"][:2]
    spec.style.negatives = sorted({t.term for t in analysis.tags.negatives})
    medium, _ = infer_medium(0.0, spec.measured.edge_density, spec.style.tags)
    for t in analysis.tags.tags:
        if t.category == "medium":
            medium = t.term
            break
    spec.style.medium = medium or spec.style.medium


def apply_depth(spec: ShotSpec, analysis: VisionAnalysis) -> None:
    if analysis.depth is None:
        return
    if spec.is_locked("layout3d"):
        return
    spec.layout3d.depth_map_path = analysis.depth.depth_png
    _write(spec, "layout3d", "depth", 0.5)
    # A subject far nearer than the rest implies shallow depth of field in the photo sense only when
    # sharpness is low elsewhere; we only annotate dof when we can state it.
    if spec.subjects and not spec.camera.dof and not spec.is_locked("camera"):
        medians = [s.depth_median for s in spec.subjects if s.depth_median is not None]
        if medians and analysis.depth.mean:
            spread = max(medians) - min(medians) if len(medians) > 1 else 0.0
            spec.camera.dof = "shallow" if spread < 0.15 and spec.measured.sharpness < 0.002 else "deep" if spread > 0.5 else "medium"
            spec.camera.dof = spec.camera.dof if spec.camera.dof in DOF_VOCAB else ""


def apply_layout(spec: ShotSpec) -> None:
    """Subjects × depth × FOV → `layout3d` (phase 6), keeping the depth map path.
    Provenance `depth` (it ranks with measured); a locked layout is left alone."""
    if spec.is_locked("layout3d") or not any(len(s.bbox) == 4 for s in spec.subjects):
        return
    from film.scene_solver import layout_from_spec

    try:
        layout = layout_from_spec(spec)
    except (ValueError, ZeroDivisionError):
        return
    layout.depth_map_path = spec.layout3d.depth_map_path
    spec.layout3d = layout
    _write(spec, "layout3d", "depth", 0.6, force=True)


def apply_flow(spec: ShotSpec, *, pan: float, tilt: float, zoom: float, roll: float, magnitude: float, subject_motion: float, handheld: bool, pacing: str, fps: float | None = None) -> None:
    """Optical-flow results (phase 5) own `motion` and the camera move."""
    if _write(spec, "motion", "flow", 0.8, force=True):
        spec.motion = SpecMotion(
            dominant=SpecMotionDominant(pan=round(pan, 4), tilt=round(tilt, 4), zoom=round(zoom, 4), roll=round(roll, 4)),
            magnitude=round(magnitude, 4),
            subject_motion=round(subject_motion, 4),
            pacing=pacing,
        )
    if fps is not None:
        spec.source.fps = fps
    if spec.is_locked("camera"):
        return
    components = {"pan": abs(pan), "tilt": abs(tilt), "zoom": abs(zoom), "roll": abs(roll)}
    move = "static"
    if magnitude >= 0.02:
        axis = max(components, key=lambda k: components[k])
        if axis == "pan":
            move = "pan_right" if pan > 0 else "pan_left"
        elif axis == "tilt":
            move = "tilt_up" if tilt > 0 else "tilt_down"
        elif axis == "zoom":
            move = "push_in" if zoom > 0 else "pull_out"
        else:
            move = "orbit"
    spec.camera.move = move
    spec.camera.move_intensity = round(min(1.0, magnitude * 10), 3)
    spec.camera.handheld = handheld
    spec.camera.roll = round(roll, 4)
    current = spec.provenance.get("camera", "")
    if PROVENANCE_RANK.get(current, 9) >= PROVENANCE_RANK["florence"]:
        spec.set_section("camera", "flow", max(spec.confidence.get("camera", 0.0), 0.7))


def apply_vlm(spec: ShotSpec, fields: dict[str, Any], confidence: float = 0.5) -> None:
    """A VLM's structured read: fills what is empty, never overrides a
    measured/detected value, and is capped when it disagrees with the tagger."""
    conf = max(0.0, min(1.0, confidence))

    def text(key: str) -> str:
        value = fields.get(key, "")
        if isinstance(value, list):
            return ", ".join(str(v) for v in cast(list[object], value) if str(v).strip())
        return str(value).strip() if value is not None else ""

    scene = SpecScene(
        location=text("location"),
        environment=text("environment"),
        time_of_day=_pick_vocab(text("time_of_day"), TIME_OF_DAY_VOCAB),
        weather=text("weather"),
        fg=text("foreground"),
        mg=text("midground"),
        bg=text("background"),
    )
    if any(scene.model_dump().values()) and _write(spec, "scene", "vlm", conf):
        spec.scene = scene

    lighting = SpecLighting(
        key_direction=text("light_direction") or text("key_direction"),
        quality=_pick_vocab(text("lighting_quality") or text("lighting"), LIGHTING_QUALITY_VOCAB) or text("lighting_quality"),
        color_temp=text("color_temp") or text("color_temperature"),
        mood=_pick_vocab(text("mood"), MOOD_VOCAB) or text("mood"),
    )
    if any(lighting.model_dump().values()) and _write(spec, "lighting", "vlm", conf):
        spec.lighting = lighting

    narrative = SpecNarrative(what_happens=text("what_happens") or text("description"), purpose=text("purpose") or text("narrative_purpose"), beat=text("beat") or text("story_beat"))
    if any(narrative.model_dump().values()) and _write(spec, "narrative", "vlm", conf, force=True):
        spec.narrative = narrative

    # Camera language from the VLM only fills fields detection could not measure.
    if not spec.is_locked("camera"):
        camera_fields = {
            "angle": text("angle"),
            "height": text("camera_height"),
            "lens_estimate": text("lens_estimate") or text("lens"),
            "focus": text("focus"),
            "aperture": text("aperture"),
        }
        wrote = False
        for key, value in camera_fields.items():
            if value and not getattr(spec.camera, key):
                setattr(spec.camera, key, value)
                wrote = True
        if not spec.camera.shot_size and text("shot_size"):
            spec.camera.shot_size = text("shot_size")
            wrote = True
        if not spec.camera.dof and text("depth_of_field"):
            spec.camera.dof = _pick_vocab(text("depth_of_field"), DOF_VOCAB) or text("depth_of_field")
            wrote = True
        if wrote and "camera" not in spec.provenance:
            spec.set_section("camera", "vlm", conf)

    # Style: merge with CLIP (imex-next rule 3).
    vlm_style = text("style")
    vlm_medium = _pick_vocab(text("medium"), MEDIUM_VOCAB)
    if not spec.is_locked("style"):
        top = spec.style.tags[0] if spec.style.tags else None
        if vlm_style and top is not None:
            if _labels_roughly_agree(vlm_style, top.term):
                spec.set_section("style", "clip", min(0.95, max(spec.confidence.get("style", 0.0), conf) + 0.1))
            elif conf > spec.confidence.get("style", 0.0):
                spec.style.tags.insert(0, TagTerm(term=vlm_style, score=round(min(0.7, conf), 3)))
                spec.set_section("style", "vlm", min(0.7, conf))
        elif vlm_style and top is None and _write(spec, "style", "vlm", min(0.7, conf)):
            spec.style.tags = [TagTerm(term=vlm_style, score=round(conf, 3))]
        if vlm_medium and not spec.style.medium:
            spec.style.medium = vlm_medium
        negatives_raw = fields.get("negatives") or fields.get("negative_prompt")
        if isinstance(negatives_raw, list):
            extra = [str(n).strip() for n in cast(list[object], negatives_raw) if str(n).strip()]
        elif isinstance(negatives_raw, str):
            extra = [n.strip() for n in negatives_raw.split(",") if n.strip()]
        else:
            extra = []
        if extra:
            spec.style.negatives = sorted(set(spec.style.negatives) | set(extra))

    # Subjects only when detection found nothing.
    if not spec.subjects and not spec.is_locked("subjects"):
        raw = fields.get("subjects")
        names = [str(n).strip() for n in cast(list[object], raw) if str(n).strip()] if isinstance(raw, list) else ([text("subject")] if text("subject") else [])
        if names and _write(spec, "subjects", "vlm", min(0.6, conf)):
            spec.subjects = [SpecSubject(label=name.lower(), count=1) for name in names[:6]]


def apply_user(spec: ShotSpec, patch: dict[str, Any], *, lock: bool = True) -> ShotSpec:
    """The user's edit of whole sections; each edited section becomes locked
    (unless `lock=False`) so no later analysis overwrites it."""
    for section, value in patch.items():
        if section not in ("measured", "subjects", "scene", "camera", "lighting", "style", "motion", "layout3d", "narrative"):
            continue
        data = spec.model_dump(mode="json")
        data[section] = value
        updated = ShotSpec.model_validate(data)
        setattr(spec, section, getattr(updated, section))
        spec.set_section(section, "user", 1.0)
        if lock:
            spec.locks[section] = True
    return spec


def _pick_vocab(value: str, vocab: tuple[str, ...]) -> str:
    needle = value.strip().lower()
    if not needle:
        return ""
    for term in vocab:
        if term == needle or term in needle:
            return term
    return ""


# ---- entry points -------------------------------------------------------------


def spec_from_vision(analysis: VisionAnalysis, *, kind: str = "image", base: ShotSpec | None = None) -> ShotSpec:
    """Measured → Florence → CLIP → depth, in that order, onto `base` (or a fresh spec)."""
    spec = base if base is not None else ShotSpec()
    if kind == "video_shot":
        spec.source.kind = "video_shot"
    apply_measured(spec, analysis)
    apply_florence(spec, analysis)
    apply_clip(spec, analysis)
    apply_depth(spec, analysis)
    apply_layout(spec)
    if spec.style.medium == "" and not spec.is_locked("style"):
        medium, confidence = infer_medium(0.0, spec.measured.edge_density, spec.style.tags)
        if medium:
            spec.style.medium = medium
            if "style" not in spec.provenance:
                spec.set_section("style", "measured", confidence)
    return spec


def merge_specs(base: ShotSpec, update: ShotSpec) -> ShotSpec:
    """Take every unlocked section from `update` whose provenance ranks at least
    as high as `base`'s; keep locked sections of `base` untouched."""
    merged = base.model_copy(deep=True)
    for section in ("measured", "subjects", "scene", "camera", "lighting", "style", "motion", "layout3d", "narrative"):
        if merged.is_locked(section):
            continue
        incoming = update.provenance.get(section, "")
        if not incoming:
            continue
        current = merged.provenance.get(section, "")
        if not current or PROVENANCE_RANK.get(incoming, 9) <= PROVENANCE_RANK.get(current, 9):
            setattr(merged, section, getattr(update, section).model_copy(deep=True) if section != "subjects" else [s.model_copy() for s in update.subjects])
            merged.set_section(section, incoming, update.confidence.get(section, 0.0))  # type: ignore[arg-type]
    if update.source.hash:
        merged.source = update.source.model_copy()
    return merged


def spec_camera_defaults(spec: ShotSpec) -> SpecCamera:
    return spec.camera
