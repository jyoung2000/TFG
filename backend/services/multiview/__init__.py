"""Multi-view generation: one image of an object in, several consistent views out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image

# (azimuth, elevation, label) per Zero123++ v1.2 tile, row-major, relative to the input view.
ZERO123PP_VIEWS: tuple[tuple[int, int, str], ...] = (
    (30, 20, "front-right raised"),
    (90, -10, "right side low"),
    (150, 20, "back-right raised"),
    (210, -10, "back-left low"),
    (270, 20, "left side raised"),
    (330, -10, "front-left low"),
)


@dataclass(frozen=True)
class MultiView:
    path: str
    azimuth: int
    elevation: int
    label: str


class MultiViewGenerator(Protocol):
    def available(self) -> bool: ...

    def generate(self, image_path: str, *, seed: int | None = None, steps: int = 75) -> list[MultiView]: ...

    def unload(self) -> None: ...


def split_grid(grid: Image.Image, rows: int = 3, cols: int = 2) -> list[Image.Image]:
    """Cut a grid image into rows x cols equal tiles, row-major."""
    tile_w = grid.width // cols
    tile_h = grid.height // rows
    return [
        grid.crop((c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h))
        for r in range(rows)
        for c in range(cols)
    ]
