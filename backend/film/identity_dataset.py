"""A character LoRA dataset that learns the person, not the words around them.

Found 2026-10-02 (Raven: one photo -> asset -> 22-image LoRA, 1100 steps):
every training sample from step 0 to the end rendered "raven" as the bird.
Florence captions described her whole look ("a woman with dark wavy hair in a
black leather jumpsuit..."), so the look was learned through those words and
the trigger carried nothing; the trigger was an English word the model already
knew; and the one real photo was 1 image in 22, its face small in a full-length
frame, beside AI renders whose faces drifted. Here:

- captions keep only what varies (the person word, view, framing) so the
  identity - face, hair, outfit - binds to the trigger;
- the default trigger is a rare token, not the asset's name;
- the source photo is weighted up with head and upper-body crops of it, so the
  real face is seen close, not only the generated ones.
"""

from __future__ import annotations

import re

from PIL import Image

_PERSON = re.compile(r"\b(woman|man|girl|boy|lady|person)\b", re.IGNORECASE)

#: File-name tokens (asset sheet views and multi-angle names) -> caption words.
#: Longest first: "back-34-left" before "back", "34-left" before "front".
_VIEW_WORDS: tuple[tuple[str, str], ...] = (
    ("source-face", "close-up portrait"),
    ("source-upper", "medium shot"),
    ("closeup", "close-up portrait"),
    ("medium", "medium shot"),
    ("full", "full body shot"),
    ("back-34-left", "three-quarter back view from the left"),
    ("back-34-right", "three-quarter back view from the right"),
    ("34-left", "three-quarter view from the left"),
    ("34-right", "three-quarter view from the right"),
    ("three-quarter-view", "three-quarter view"),
    ("profile-left", "profile view from the left"),
    ("profile-right", "profile view from the right"),
    ("profile", "profile view"),
    ("back", "seen from behind"),
    ("front", "front view"),
    ("high", "high angle"),
    ("low", "low angle"),
)


def rare_trigger(name: str) -> str:
    """A trigger the model has no meaning for: the name's consonants plus "x"
    ("Raven" -> "rvnx"). "raven" itself rendered the bird (2026-10-02)."""
    letters = "".join(ch for ch in name.lower() if ch.isalnum())
    consonants = "".join(ch for ch in letters if ch not in "aeiou")
    core = consonants if len(consonants) >= 2 else letters
    return f"{core[:6] or 'subj'}x"


def character_caption(florence_text: str, trigger: str, file_name: str) -> str:
    """`<trigger>, <person word>[, framing][, view...]` - nothing about how they look."""
    person = _PERSON.search(florence_text or "")
    parts = [trigger, person.group(1).lower() if person else "person"]
    rest = file_name.lower()
    used: list[str] = []
    for token, words in _VIEW_WORDS:
        if f"-{token}" in rest:
            if words not in used:
                used.append(words)
            rest = rest.replace(f"-{token}", "-")
    parts.extend(used)
    return ", ".join(p for p in parts if p)


def source_crops(image: Image.Image, face_bbox: list[float], *, min_edge: int = 384) -> list[tuple[str, Image.Image]]:
    """Head-and-shoulders and upper-body crops around a face box (normalised
    [x, y, w, h]); a crop smaller than `min_edge` on its short side is skipped,
    as is everything when the box is not a plausible face."""
    if len(face_bbox) != 4:
        return []
    width, height = image.size
    fx, fy, fw, fh = face_bbox[0] * width, face_bbox[1] * height, face_bbox[2] * width, face_bbox[3] * height
    if fw <= 0 or fh <= 0 or fw > width * 0.9 or fh > height * 0.9:
        return []
    cx = fx + fw / 2
    out: list[tuple[str, Image.Image]] = []
    for suffix, half_width, top, bottom in (("source-face", 1.6 * fw, fy - 0.6 * fh, fy + 2.4 * fh), ("source-upper", 2.6 * fw, fy - 0.6 * fh, fy + 5.5 * fh)):
        left, right = max(0.0, cx - half_width), min(float(width), cx + half_width)
        upper, lower = max(0.0, top), min(float(height), bottom)
        box = (int(left), int(upper), int(right), int(lower))
        if min(box[2] - box[0], box[3] - box[1]) < min_edge:
            continue
        out.append((suffix, image.crop(box)))
    return out
