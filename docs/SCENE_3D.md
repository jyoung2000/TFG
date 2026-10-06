# 3D scene from a shot (index)

The 3D storyboard pipeline is documented in two files:

- [`STORYBOARD_3D.md`](STORYBOARD_3D.md) — from an analysed shot to a 3D
  layout: the scene solver (`backend/film/scene_solver.py`), reprojection
  checks, blockout thumbnails, the `storyboard3d` route and how a layout
  becomes an editable storyboard card.
- [`SHOT_COMPOSER.md`](SHOT_COMPOSER.md) — the plain-three.js Shot Composer:
  figures, camera keyframes, the move library, the reference underlay,
  undo/redo, and **Deliver** (clean / depth passes → control videos for the
  render, `docs/adr` and `INTEGRATED_UPSTREAMS.md` for the blockout and
  Blocking-Room attributions).

Agents drive the same pipeline through the `video_analysis_storyboard3d`,
`scene_*` and `film_deliver` MCP tools (`AGENTS_GUIDE.md`).
