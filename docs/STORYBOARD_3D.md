# 3D shot analysis → editable storyboard

`Analyse video → Build 3D storyboard` (also from the Video Reproduce panel).
Every analysed shot becomes a film shot whose card carries an isometric
**blockout** thumbnail and whose composer opens pre-seeded from the
analysis; edits fold back into the shot's ShotSpec so the prompt — and the
next Reproduce render — follow the 3D scene.

## Solving the layout

`backend/film/scene_solver.py` (pure maths, tested by round trip):

1. **Camera**: the lens FOV from the spec (`fov_deg` / `focal_mm`, default
   40° vertical) and the aspect give the frustum. Height and pitch are
   solved so every whole figure's feet ray lands on the floor: the pitch is
   searched (±30°) for the least disagreement between figures, regularised
   toward level (or the spec's high/low hint), and an implausible camera
   height (below 0.3 m) pushes the search to tilt down instead.
2. **Objects**: a box whose bottom ray reaches the floor is placed exactly
   where that ray lands (grounded); anything else (a window, a bird, a box
   cut by the frame edge) floats at a distance from its relative depth
   median (1.2–14 m). Sizes come from the frame height at that distance, so
   a figure's `scale` is its real height over 1.7 m, and the body type
   (child < 1.35 m < female < 1.72 m ≤ male) follows the bbox height.
3. **Reprojection**: `reproject_layout` projects every object back to
   normalised boxes; `reprojection_error` must stay under `TOLERANCE`
   (0.05 of the frame) — asserted for single/multi-figure, prop, clipped and
   long/wide-lens cases.

The layout lands in `spec.layout3d` with provenance `depth` during fusion
(`apply_layout`, after `apply_depth`), keeping `depth_map_path` for the
composer underlay and the phase-5 conditioning.

## Composer scene

`composer_scene_from_layout` (twin: `sceneFromAnalysis.ts`) turns the layout
into a `CompositionScene`: figures with the right variant, props as cubes,
the shot camera at the solved pose, and start/end keyframes for the measured
camera move (`spec.camera.move` from optical flow, intensity from the flow
magnitude). `layout_from_composition` is the inverse, used when the composer
saves. `describe_camera(layout3d)` gives the framing words (shot size, angle,
height, lens) written from scratch after the CozyClay concept.

## Storyboard build

`POST /api/video-analysis/{id}/storyboard3d` reconstructs the film project
(or reuses the linked one), seeds every shot's `composition`, `framing`,
`camera_move`, writes `captures/<shot>-blockout.svg` (`blockout_path`, shown
on the card until a capture or render exists) and records one `scene_build`
job with the thumbnails as outputs. Building again updates the same project.

## Round trip

`PUT /api/video-analysis/{id}/shots/{shot}/spec` accepts section edits or a
composer scene: the scene becomes `layout3d` (provenance `user`, lockable),
the camera words are re-derived into `spec.camera` and the shot's visual
fields, and the prompts are recomposed unless a person edited them. A locked
section survives re-analysis (`merge_specs`).

## Tests

`backend/tests/test_scene.py` (solver round trips, FOV/height hints, body
types, composer scene ↔ layout, `/api/scene/build|describe`, storyboard3d
seeding + thumbnails + job, spec round trip + locks, Deliver passes → control
signals → render request, WanGP guide keys), `sceneFromAnalysis.test.ts`
(twin round trip, keyframe rules, Blocking-Room ports), and
`e2e/storyboard3d.spec.ts` (cards with blockouts → composer with underlay,
figures, camera words, move library, Deliver, apply-to-spec; zero console
errors). Real-GPU: `docs/RTX_4070_TEST_MATRIX.md`.
