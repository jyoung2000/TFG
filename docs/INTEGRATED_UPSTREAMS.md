# Integrated Upstreams

This application combines the LTX Desktop WanGP host with concepts and code
adapted from two additional open-source projects. This file records exactly
what was inspected and adapted, from which commits, under which licenses.

## deepbeepmeep/LTX-Desktop-WanGP (host)

- **URL**: https://github.com/deepbeepmeep/LTX-Desktop-WanGP
- **Commit inspected/imported**: `4abb4a5ff9391ef0b21826f34de23636e8973b0c`
- **License**: Apache-2.0 (see `LICENSE.txt`; upstream is itself a fork of
  Lightricks' LTX Desktop — original notices retained in `NOTICES.md`)
- **Role**: the entire base application. Everything outside the film feature
  is upstream code, imported unmodified except for:
  - `backend/services/wangp_bridge.py` — three latent strict-typing fixes
  - `backend/app_factory.py` — additive: film routers + query-token auth for
    two read-only media GET endpoints
  - `backend/handlers/video_generation_handler.py` — `_get_allowed_durations`
    renamed public (used by the film adapter)
  - `backend/.python-version` — `3.12.12` → `3.12`
  - `electron/csp.ts` — loopback backend origin added to `img-src`/`media-src`
  - `frontend/views/Project.tsx`, `frontend/types/project.ts`,
    `frontend/App.tsx`, `frontend/main.tsx` — additive Storyboard tab wiring

## bluefish2026/BlueFish (filmmaking workflow reference)

- **URL**: https://github.com/bluefish2026/BlueFish
- **Commit inspected**: `8b409c1332e46bc1211d2ffc6d45fe1f01492eca`
- **License**: Apache-2.0. Trademark policy excludes the "Blue Fish"
  name/logo/branding from the code license — **no Blue Fish naming or
  branding is used anywhere in this application.**
- **What was adapted** (concepts and model shapes; no source files copied —
  its React 19/zustand/cloud-provider stack is incompatible with this host):
  - Unified entity model (`Character.entityType: character|location|prop` with
    type-specific extension fields) → `backend/film/film_models.py::FilmAsset`
  - Chapter/Storyboard split with per-shot size/movement/duration/status →
    `FilmScene`/`FilmShot`
  - LLM script→storyboard generation contract (scenes with fully-specified
    shots: size/perspective/movement/duration/visual description) →
    `handlers/film_director_handler.py::generate_storyboard` (re-authored in
    English for Gemini, plus an offline deterministic parser)
  - Style-variable prompt assembly → `backend/film/film_prompt.py`
- **Modifications**: everything re-implemented against this host's typed
  handler/service architecture and local-first generation.

## Anujatk1999/open-media (shot composition reference)

- **URL**: https://github.com/Anujatk1999/open-media
- **Commit inspected**: `9bfc076c792e3989c688bc9642c34512db26ee2b`
- **License**: MIT
- **What was adapted** (algorithms ported; components re-implemented in plain
  three.js because upstream's react-three-fiber 9 stack requires React 19 and
  `mannequin-js`, neither of which is included here):
  - `src/modules/library/calibration/shotSolver.ts` → ported nearly verbatim
    as `frontend/views/film/composer/shotSolver.ts` (attribution header in
    file). Extended with: xwide/xcu shot-size spans, bird/worm elevations,
    POV angle, dutch-angle camera roll.
  - `shotAxes.ts` + `compositionPresets.ts` → preset vocabularies in
    `frontend/types/film.ts` (extended set).
  - `motionPresets.ts` keyframe-builder pattern → camera-move builders in
    `frontend/views/film/composer/cameraMotion.ts`.
  - `composerStore.ts` scene-object/keyframe state shape →
    `CompositionScene`/`CompositionObject`/`CompositionKeyframe` schema
    (persisted per shot in the backend film store).
  - `mcpBridge/commands.ts` "commands map 1:1 onto real store actions"
    principle → `backend/handlers/film_director_handler.py` command registry.
  - `ComposerViewport.tsx` interaction model (orbit + raycast select +
    picture-in-picture viewfinder + `preserveDrawingBuffer` PNG capture) →
    `frontend/views/film/composer/composerScene.ts`.
  - `helpers/poseLibrary.ts` merge rules (bundled + user poses, same-name
    override) → `frontend/views/film/composer/poses.ts`; the mannequin-js v7
    posture format was replaced with a named-joint Euler-degrees format for
    this app's own articulated figure (`figure.ts`).
- **Not used**: mannequin-js and its meshes/pose files, react-three-fiber,
  drei, zustand, the MCP WebSocket server, video export.
