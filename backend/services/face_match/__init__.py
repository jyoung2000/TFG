"""Face identity: does a rendered person have the face of the reference photo?

Added 2026-10-02: Raven's 3D-studio angle shots scored 0.25-0.43 against her
photo (OpenCV SFace cosine; 0.363 = same person), so the LoRA learned a blend
of strangers' faces. Renders are now chosen, and datasets filtered, by this.
"""

from __future__ import annotations

import math
from typing import Protocol

#: OpenCV SFace cosine threshold for "same person" (opencv_zoo face_recognition_sface).
SAME_PERSON = 0.363


class FaceMatcher(Protocol):
    def available(self) -> bool: ...

    def embedding(self, image_path: str) -> list[float] | None:
        """The largest face's identity vector, or None when no face is found."""
        ...

    def face_box(self, image_path: str) -> tuple[float, float, float, float] | None:
        """The largest face's box in the image's own pixels (x, y, w, h), or None."""
        ...


def similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
