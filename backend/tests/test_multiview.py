"""Zero123++ multi-view service: grid splitting, view table, availability, generation (stubbed pipeline)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from services.multiview import ZERO123PP_VIEWS, MultiView, split_grid
from services.multiview.zero123plus import Zero123PlusGenerator

COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


def _grid(tile: int = 320) -> Image.Image:
    grid = Image.new("RGB", (tile * 2, tile * 3))
    for index, colour in enumerate(COLOURS):
        row, col = divmod(index, 2)
        grid.paste(Image.new("RGB", (tile, tile), colour), (col * tile, row * tile))
    return grid


def test_split_grid_row_major() -> None:
    tiles = split_grid(Image.new("RGB", (640, 960)))
    assert len(tiles) == 6
    grid = _grid()
    tiles = split_grid(grid)
    assert [t.size for t in tiles] == [(320, 320)] * 6
    assert [t.getpixel((10, 10)) for t in tiles] == COLOURS


def test_views_table() -> None:
    assert [v[0] for v in ZERO123PP_VIEWS] == [30, 90, 150, 210, 270, 330]
    assert [v[1] for v in ZERO123PP_VIEWS] == [20, -10, 20, -10, 20, -10]
    assert [v[2] for v in ZERO123PP_VIEWS] == [
        "front-right raised",
        "right side low",
        "back-right raised",
        "back-left low",
        "left side raised",
        "front-left low",
    ]


def test_available(tmp_path: Path) -> None:
    gen = Zero123PlusGenerator(tmp_path / "model", tmp_path / "out")
    assert not gen.available()
    model = tmp_path / "model"
    (model / "unet").mkdir(parents=True)
    (model / "_pipeline").mkdir()
    (model / "model_index.json").write_text("{}")
    (model / "unet" / "diffusion_pytorch_model.safetensors").write_bytes(b"x")
    assert not gen.available()
    (model / "_pipeline" / "pipeline.py").write_text("")
    assert gen.available()


class _Result:
    def __init__(self, grid: Image.Image) -> None:
        self.images = [grid]


class _StubPipe:
    def __init__(self) -> None:
        self.seen: list[Image.Image] = []
        self.kwargs: dict[str, Any] = {}

    def __call__(self, image: Image.Image, **kwargs: Any) -> _Result:
        self.seen.append(image)
        self.kwargs = kwargs
        return _Result(_grid())


def test_generate_with_stub_pipeline(tmp_path: Path, monkeypatch: Any) -> None:
    src = tmp_path / "chair.png"
    Image.new("RGBA", (500, 300), (10, 20, 30, 255)).save(src)
    out = tmp_path / "out"
    gen = Zero123PlusGenerator(tmp_path / "model", out)
    stub = _StubPipe()
    monkeypatch.setattr(gen, "_load_pipeline", lambda: stub)

    views = gen.generate(str(src), steps=30)

    assert len(views) == 6
    assert all(isinstance(v, MultiView) for v in views)
    assert [(v.azimuth, v.elevation, v.label) for v in views] == list(ZERO123PP_VIEWS)
    for index, view in enumerate(views):
        assert Path(view.path) == out / f"chair-z123-{index}.png"
        with Image.open(view.path) as img:
            assert img.size == (640, 640)
            assert img.convert("RGB").getpixel((100, 100)) == COLOURS[index]
    cond = stub.seen[0]
    assert cond.size == (320, 320)
    assert cond.mode == "RGB"
    assert cond.getpixel((5, 5)) == (127, 127, 127)
    assert stub.kwargs["num_inference_steps"] == 30
