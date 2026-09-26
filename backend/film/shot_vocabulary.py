"""The words this app describes a shot with.

One table per structured field, shared by everything that turns a shot into
text: the host's own prompt synthesis and the per-model compiler both read from
here, so the same framing never gets two different descriptions depending on
which path produced it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from film.shot_spec import SpecLayout3D

SHOT_SIZE_PHRASES: dict[str, str] = {
    "xwide": "extreme wide shot",
    "wide": "wide shot",
    "full": "full shot",
    "medium": "medium shot",
    "mcu": "medium close-up",
    "closeup": "close-up",
    "xcu": "extreme close-up",
}
ANGLE_PHRASES: dict[str, str] = {
    "front": "front angle",
    "threeQuarterLeft": "three-quarter left angle",
    "threeQuarterRight": "three-quarter right angle",
    "profile": "profile angle",
    "back": "shot from behind",
    "ots": "over-the-shoulder shot",
    "pov": "point-of-view shot",
    "dutch": "dutch angle, tilted horizon",
}
ELEVATION_PHRASES: dict[str, str] = {
    "eye": "eye-level camera",
    "low": "low-angle camera looking up",
    "high": "high-angle camera looking down",
    "bird": "bird's-eye view from above",
    "worm": "worm's-eye view from ground level",
}
COMPOSITION_PHRASES: dict[str, str] = {
    "center": "subject centered in frame",
    "leftThird": "subject on the left third of the frame",
    "rightThird": "subject on the right third of the frame",
    "upperThird": "subject in the upper third of the frame",
    "lowerThird": "subject in the lower third of the frame",
    "negativeSpace": "strong negative space, subject far off-center",
    "symmetrical": "symmetrical composition",
    "leadingLines": "leading lines drawing the eye to the subject",
}
CAMERA_MOVE_PHRASES: dict[str, str] = {
    "static": "static camera, locked-off shot",
    "push_in": "slow push in, camera moving toward the subject",
    "pull_out": "slow pull out, camera moving away from the subject",
    "pan_left": "camera panning left",
    "pan_right": "camera panning right",
    "tilt_up": "camera tilting up",
    "tilt_down": "camera tilting down",
    "dolly_left": "camera trucking left, lateral movement",
    "dolly_right": "camera trucking right, lateral movement",
    "orbit": "camera orbiting around the subject",
    "follow": "camera following the subject",
}


# ---------------------------------------------------------------------------
# Lens, camera and aperture phrases.
#
# Adapted from Anil-matcha/Open-Generative-AI (MIT), `CinemaStudio.jsx`:
# CAMERA_MAP, LENS_MAP, FOCAL_PERSPECTIVE and APERTURE_EFFECT — the words a
# cinematographer's choices turn into for a prompt. Extended with the focal
# lengths and stops the analysers estimate.

CAMERA_BODY_PHRASES: dict[str, str] = {
    "modular_8k_digital": "modular 8K digital cinema camera",
    "full_frame_cine_digital": "full-frame digital cinema camera",
    "grand_format_70mm_film": "grand format 70mm film camera",
    "studio_digital_s35": "Super 35 studio digital camera",
    "classic_16mm_film": "classic 16mm film camera",
    "premium_large_format_digital": "premium large-format digital cinema camera",
}

LENS_PHRASES: dict[str, str] = {
    "creative_tilt": "creative tilt lens effect",
    "compact_anamorphic": "compact anamorphic lens",
    "extreme_macro": "extreme macro lens",
    "70s_cinema_prime": "1970s cinema prime lens",
    "classic_anamorphic": "classic anamorphic lens",
    "premium_modern_prime": "premium modern prime lens",
    "warm_cinema_prime": "warm-toned cinema prime lens",
    "swirl_bokeh_portrait": "swirl bokeh portrait lens",
    "vintage_prime": "vintage prime lens",
    "halation_diffusion": "halation diffusion filter",
    "clinical_sharp_prime": "ultra-sharp clinical prime lens",
}

#: Focal length (mm, full-frame equivalent) → perspective phrase.
FOCAL_PHRASES: dict[int, str] = {
    8: "ultra-wide perspective",
    14: "wide-angle perspective",
    18: "wide-angle perspective with slight distortion",
    24: "wide-angle dynamic perspective",
    28: "wide perspective",
    35: "natural cinematic perspective",
    50: "standard portrait perspective",
    85: "classic portrait perspective, compressed background",
    135: "telephoto compression, isolated subject",
    200: "long telephoto compression",
}

APERTURE_PHRASES: dict[str, str] = {
    "f/1.4": "shallow depth of field, creamy bokeh",
    "f/2": "shallow depth of field, soft background",
    "f/2.8": "moderately shallow depth of field",
    "f/4": "balanced depth of field",
    "f/5.6": "mostly sharp, gentle background falloff",
    "f/8": "deep focus, sharp throughout",
    "f/11": "deep focus clarity, sharp foreground to background",
}


def focal_phrase(focal_mm: float) -> str:
    """The nearest documented perspective phrase for a focal length."""
    if focal_mm <= 0:
        return ""
    nearest = min(FOCAL_PHRASES, key=lambda mm: abs(mm - focal_mm))
    return FOCAL_PHRASES[nearest]


def focal_from_fov(fov_deg: float, sensor_width_mm: float = 36.0) -> float:
    """Horizontal FOV → full-frame-equivalent focal length."""
    import math

    if fov_deg <= 0 or fov_deg >= 179:
        return 0.0
    return round(sensor_width_mm / (2 * math.tan(math.radians(fov_deg) / 2)), 1)


def aperture_phrase(aperture: str) -> str:
    return APERTURE_PHRASES.get(aperture.strip().lower().replace("f", "f"), "") or APERTURE_PHRASES.get(aperture, "")


# ---------------------------------------------------------------------------
# Style / medium / lighting / mood / composition vocabularies.
#
# Adapted from macchant/imex-next (MIT), `pipeline/vocab.ts` and
# `types/schema.ts`: short, high-precision lists the taggers rank against and
# the VLM is asked to prefer; recall comes from the models, not the list.

STYLE_VOCAB: tuple[str, ...] = (
    "flat vector illustration", "corporate memphis style", "bauhaus geometric design", "art deco illustration",
    "pop art with halftone", "kawaii cute illustration", "risograph print", "mid-century modern illustration",
    "tattoo flash style", "y2k chrome aesthetic", "studio ghibli style", "anime illustration", "watercolor painting",
    "oil painting", "pencil sketch", "low-poly 3D render", "isometric illustration", "pixel art", "photorealistic",
    "cinematic still",
)
LINEWORK_VOCAB: tuple[str, ...] = (
    "monoline uniform strokes", "thick black outlines", "no outline shape-only", "stippling dot shading",
    "halftone dot shading", "crosshatch shading", "flat color blocks", "rough hand-drawn lines",
)
MOOD_VOCAB: tuple[str, ...] = ("cheerful", "serious", "playful", "mysterious", "minimal", "energetic", "calm", "nostalgic")
MEDIUM_VOCAB: tuple[str, ...] = ("vector", "photo", "3d-render", "painting", "pixel-art", "line-art", "anime")
LIGHTING_QUALITY_VOCAB: tuple[str, ...] = ("flat", "soft", "studio", "dramatic", "natural", "rim", "neon", "hard", "diffused")
LIGHT_DIRECTION_VOCAB: tuple[str, ...] = ("front", "side", "back", "top", "under", "three-quarter", "window", "overhead")
COLOR_TEMP_VOCAB: tuple[str, ...] = ("warm", "neutral", "cool", "mixed", "golden hour", "blue hour", "tungsten", "daylight")
COMPOSITION_VOCAB: tuple[str, ...] = (
    "centered-isolated", "rule-of-thirds", "knolling-grid", "wide-scene", "portrait-bust", "full-body",
)
TIME_OF_DAY_VOCAB: tuple[str, ...] = ("dawn", "morning", "midday", "afternoon", "golden hour", "dusk", "night")
CAMERA_HEIGHT_VOCAB: tuple[str, ...] = ("eye", "low", "high", "bird", "worm", "crane")
DOF_VOCAB: tuple[str, ...] = ("shallow", "medium", "deep")

#: Shot size from a *detection box*: the fraction of the frame height the
#: subject's box covers. A box is clipped at the frame edge, so once it fills
#: the frame the shot is at least medium — a box cannot tell medium from
#: close-up; the 3D estimate below can.
SUBJECT_HEIGHT_TO_SHOT_SIZE: tuple[tuple[float, str], ...] = (
    (0.15, "xwide"),
    (0.4, "wide"),
    (0.85, "full"),
    (9.0, "medium"),
)

#: Shot size from the *true* subject height over the frame height (may exceed
#: 1 when the frame crops the subject) — what a 3D layout gives.
FRAME_FRACTION_TO_SHOT_SIZE: tuple[tuple[float, str], ...] = (
    (0.15, "xwide"),
    (0.4, "wide"),
    (1.1, "full"),
    (1.8, "medium"),
    (2.6, "mcu"),
    (4.0, "closeup"),
    (999.0, "xcu"),
)


def shot_size_from_subject_height(height_fraction: float) -> str:
    """From a detection box (clipped to the frame)."""
    for limit, size in SUBJECT_HEIGHT_TO_SHOT_SIZE:
        if height_fraction < limit:
            return size
    return "medium"


def shot_size_from_frame_fraction(fraction: float) -> str:
    """From the real subject height over the frame height (3D layouts)."""
    for limit, size in FRAME_FRACTION_TO_SHOT_SIZE:
        if fraction < limit:
            return size
    return "xcu"


def describe_camera(layout3d: "SpecLayout3D") -> dict[str, str]:
    """Film vocabulary from a 3D layout: shot size, angle, height, lens, move.

    Written from scratch (the CozyClay *concept* of deriving camera language
    from a scene — no source used). Input is the ShotSpec's `layout3d`:
    the camera's position/rotation/FOV and the objects; the first figure (or
    the first object) is the subject.
    """
    import math

    cam = layout3d.camera
    pos = list(cam.pos) + [0.0] * (3 - len(cam.pos))
    fov = float(cam.fov or 40.0)
    figures = [o for o in layout3d.objects if o.kind == "figure"] or list(layout3d.objects)
    result: dict[str, str] = {}
    if figures:
        subject = figures[0]
        spos = list(subject.pos) + [0.0] * (3 - len(subject.pos))
        scale = list(subject.scale) + [1.0] * (3 - len(subject.scale))
        subject_height = 1.7 * scale[1]
        dx, dy, dz = spos[0] - pos[0], spos[1] - pos[1], spos[2] - pos[2]
        distance = max(0.05, math.sqrt(dx * dx + dy * dy + dz * dz))
        frame_height = 2 * distance * math.tan(math.radians(fov) / 2)
        result["shot_size"] = shot_size_from_frame_fraction(subject_height / max(0.01, frame_height))
        # Height: where the camera sits relative to the subject's eyes.
        eye = spos[1] + subject_height * 0.9
        if pos[1] > eye + 1.5:
            result["height"] = "bird" if pos[1] > eye + 4 else "high"
        elif pos[1] < spos[1] + subject_height * 0.3:
            result["height"] = "worm" if pos[1] < spos[1] + 0.2 else "low"
        else:
            result["height"] = "eye"
        # Angle: the subject's facing (yaw) against the direction to the camera.
        rot = list(subject.rot) + [0.0] * (3 - len(subject.rot))
        facing = rot[1]
        to_camera = math.atan2(pos[0] - spos[0], pos[2] - spos[2])
        signed = (facing - to_camera + math.pi) % (2 * math.pi) - math.pi
        delta = abs(signed)
        if delta < math.radians(25):
            result["angle"] = "front"
        elif delta < math.radians(70):
            result["angle"] = "threeQuarterLeft" if signed > 0 else "threeQuarterRight"
        elif delta < math.radians(115):
            result["angle"] = "profile"
        else:
            result["angle"] = "back"
    cam_rot = list(cam.rot) + [0.0] * (3 - len(cam.rot))
    if abs(cam_rot[2]) > math.radians(4):
        result["angle"] = "dutch"
    focal = focal_from_fov(fov)
    if focal:
        result["focal_mm"] = str(focal)
        result["lens_estimate"] = focal_phrase(focal)
    return result


def camera_sentence(described: dict[str, str]) -> str:
    """The derived vocabulary as prompt language."""
    parts = [
        SHOT_SIZE_PHRASES.get(described.get("shot_size", ""), ""),
        ANGLE_PHRASES.get(described.get("angle", ""), ""),
        ELEVATION_PHRASES.get(described.get("height", ""), ""),
        described.get("lens_estimate", ""),
    ]
    return ", ".join(p for p in parts if p)
