# Shot Composer

Every shot card's **Compose** button opens a native, full-screen 3D
workspace (no iframe, no second application). It is a plain three.js
implementation (lazy-loaded chunk) whose framing mathematics are ported from
Open Media's shot solver (MIT — see `INTEGRATED_UPSTREAMS.md`).

## Layout

- **Left** — scene tree: the **Shot Camera** row (select it to move the
  camera with the gizmo), the shot's characters (seeded from its cast, or
  added from the project's character assets), primitive prop shapes
  (cube/cylinder/sphere/cone/plane). Per object: lock, hide, inline rename
  (double-click), duplicate, delete; figures also get a body-type switch
  (adult tall / adult / child).
- **Center** — the editor viewport: orbit/pan/zoom camera, click to select,
  drag on the ground plane, or use the **transform gizmo** (W move · E rotate
  · R scale; figures stay grounded and upright with uniform scale). The
  overlay shows numeric X/Y/Z, yaw and scale for the selection, or the
  camera's position/FOV with *Aim at…* when the camera is selected. The
  bottom-right inset is a live picture-in-picture viewfinder through the
  **shot camera**; a queue badge shows render progress for this shot.
- **Right** — progressive-disclosure panels:
  - **Shot**: shot size (Extreme Wide…Extreme Close-Up), camera angle
    (Front/¾/Profile/Back/OTS/POV/Dutch), elevation (Worm's Eye…Bird's Eye)
    and composition (Center/Thirds/Negative Space/Symmetrical/Leading
    Lines). Every change re-solves the shot camera against the framed
    character — presets change structured state, never just prompt text.
  - **Camera**: field of view (with rough focal-length equivalent) and the
    **preset ↔ manual** mode. Moving the camera by hand (gizmo, numeric
    inputs, *Aim at*) switches to manual and presets stop overriding it;
    *Back to presets* re-solves it. The mode is stored on the framing
    (`camera_mode`) so the director and the card agree.
  - **Pose**: the pose library (built-in poses + project poses saved from
    here), per-joint XYZ rotation sliders for the 15 named joints, reset,
    limb-pair mirror, and "save pose as…" into the project library.
  - **Motion**: camera-move presets (Static, Push In, Pull Out, Pan, Tilt,
    Truck, Orbit, Follow) with an **intensity** slider, and a simple
    **timeline**: scrub time, *Key camera* / *Key <object>* records the
    current pose at the scrub time, keyframes can be retimed, deleted or
    jumped to. Scrubbing previews the camera **and** keyframed objects, then
    restores the live state. Keyframes drive the preview and the capture;
    the video model receives the camera move as prompt language.
  - **Generate**: Capture → Preview / Final from inside the composer (a fresh
    capture is taken first), queue position/progress with cancel, the
    version list with playback, retry for failures, *Set current*, side-by-
    side **Compare**, Approve / Reject and *Send to Timeline* (or *Replace
    timeline clip* when one is already linked).

Closing the composer auto-saves an unsaved composition.

## Over-the-shoulder

Choosing the OTS (or POV) angle exposes the relationship controls: which
figure is the **foreground** (camera hugs their shoulder, following their
facing as they turn), which is the **subject** (the camera aims past the
foreground at their chest), and **which shoulder** the camera looks over
(the right-shoulder solve is the mirror image of the left). This is solved
geometry, not prompt text — the AI Director's `set_ots` tool sets the same
fields.

## One shot state

Cast and composer objects are one record: assigning a character adds its
figure, placing a figure linked to a character adds it to the cast, removing
either removes the other, and the shot's framing *is* the composition's
framing. The rules live in `sync_composition_and_cast`
(`backend/handlers/film_handler.py`) and are pinned by
`backend/tests/test_film_invariants.py`.

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
