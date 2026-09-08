# Shot Composer

Every shot card's **Compose** button opens a native, full-screen 3D
workspace (no iframe, no second application). It is a plain three.js
implementation (lazy-loaded chunk) whose framing mathematics are ported from
Open Media's shot solver (MIT — see `INTEGRATED_UPSTREAMS.md`).

## Layout

- **Left** — scene tree: the shot's characters (seeded from its cast, or
  added from the project's character assets), primitive prop shapes
  (cube/cylinder/sphere/cone/plane), visibility toggles, remove.
- **Center** — the editor viewport: orbit/pan/zoom camera, click to select,
  drag characters across the ground plane, quick-rotate buttons for the
  selection. The bottom-right inset is a live picture-in-picture viewfinder
  through the **shot camera**.
- **Right** — progressive-disclosure panels:
  - **Shot**: shot size (Extreme Wide…Extreme Close-Up), camera angle
    (Front/¾/Profile/Back/OTS/POV/Dutch), elevation (Worm's Eye…Bird's Eye)
    and composition (Center/Thirds/Negative Space/Symmetrical/Leading
    Lines). Every change re-solves the shot camera against the framed
    character — presets change structured state, never just prompt text.
  - **Camera**: field of view (with rough focal-length equivalent).
  - **Pose**: the pose library (built-in poses + project poses saved from
    here), per-joint XYZ rotation sliders for the 15 named joints, reset,
    limb-pair mirror, and "save pose as…" into the project library.
  - **Motion**: camera-move presets (Static, Push In, Pull Out, Pan, Tilt,
    Truck, Orbit, Follow) that build start/end camera keyframes over the
    shot's duration, with a scrubber to preview the move.

## Over-the-shoulder

Choosing the OTS (or POV) angle exposes the relationship controls: which
figure is the **foreground** (camera hugs their shoulder, following their
facing as they turn) and which is the **subject** (the camera aims past the
foreground at their chest). This is solved geometry, not prompt text.

## Capture

**Capture Shot** renders the shot camera at 1280×720, saves the PNG plus the
full composition snapshot (objects, transforms, poses, framing, camera,
keyframes) to the film store
(`film_projects/<id>/captures/<shot>.png|.json`), stamps the shot `ready`,
and syncs the shot's framing/camera-move fields. The capture becomes the
image-to-video conditioning reference at generation time (toggleable per
shot). **Save** persists the composition without capturing.

Compositions are versioned inside `project.json`; re-opening a composed shot
rehydrates the exact scene. All three.js resources are disposed when the
composer closes.
