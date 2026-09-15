"""The words this app describes a shot with.

One table per structured field, shared by everything that turns a shot into
text: the host's own prompt synthesis and the per-model compiler both read from
here, so the same framing never gets two different descriptions depending on
which path produced it.
"""

from __future__ import annotations

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
