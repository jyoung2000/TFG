"""Fake multi-view generator for tests: writes six small solid-colour PNGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from services.multiview import ZERO123PP_VIEWS, MultiView

_COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


@dataclass
class FakeMultiViewGenerator:
    output_dir: Path
    enabled: bool = True
    calls: list[str] = field(default_factory=lambda: [])

    def available(self) -> bool:
        return self.enabled

    def generate(self, image_path: str, *, seed: int | None = None, steps: int = 75) -> list[MultiView]:
        self.calls.append(image_path)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(image_path).stem
        views: list[MultiView] = []
        for index, (azimuth, elevation, label) in enumerate(ZERO123PP_VIEWS):
            out = self.output_dir / f"{stem}-z123-{index}.png"
            Image.new("RGB", (64, 64), _COLOURS[index]).save(out)
            views.append(MultiView(path=str(out), azimuth=azimuth, elevation=elevation, label=label))
        return views

    def unload(self) -> None:
        return None
