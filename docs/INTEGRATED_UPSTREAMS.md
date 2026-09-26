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


## kijai/ComfyUI-Florence2 (Florence-2 task map, model registry)

- **URL**: https://github.com/kijai/ComfyUI-Florence2
- **License**: MIT
- **Commit inspected**: main as of 2026-09 (the repository could not be fetched
  from this build container; the adaptation was written from the documented
  task tokens and registry — see `session-notes.md` VF-006)
- **What was adapted**: the task → post-processing map (box/label parsing,
  caption cleanup) and the HF model registry (base/large/ft, PromptGen v2,
  CogFlorence, Flux-Large captioner) → `backend/services/vision/florence2.py`.
  ComfyUI model management and folder plumbing are replaced by
  `services/vram/VramManager` and the app-data models directory; the model
  classes come from `transformers` natively (no `trust_remote_code`), so
  nothing from `model/` was vendored.

## pharmapsychotic/clip-interrogator (term lists + ranking)

- **URL**: https://github.com/pharmapsychotic/clip-interrogator
- **Commit inspected**: `bc07ce62c179d3aab3053a623d96a071101d11cb`
- **License**: MIT (reproduced at `backend/services/vision/clip_data/LICENSE`)
- **Vendored unchanged**: `clip_interrogator/data/{artists,flavors,mediums,
  movements,negative}.txt` → `backend/services/vision/clip_data/`
- **Ported**: `LabelTable` (chunked text embedding + on-disk cache),
  `rank_top`, `chain`, the classic and negative orderings, the low-VRAM
  `flavor_intermediate_count` knob → `backend/services/vision/clip_tagger.py`
  on `transformers`' CLIP (`openai/clip-vit-large-patch14`). The package is
  not installed (dormant since 2023); BLIP is not used — Florence captions
  seed `chain()`.

## macchant/imex-next (deterministic image stats, ShotSpec design)

- **URL**: https://github.com/macchant/imex-next
- **Commit inspected**: `e682df2adf71`
- **License**: MIT as declared in the README ("MIT — see LICENSE"); the LICENSE
  file itself is absent from the repository at that commit, so this record
  relies on the author's declaration. Only design and small pure functions
  were ported; nothing was vendored verbatim.
- **What was adapted (phase 3 part)**: `types/schema.ts` (one canonical
  schema with per-field confidence + sources) → `backend/film/shot_spec.py`,
  `frontend/types/shotspec.ts`, `frontend/lib/shotspec/schema.ts`;
  `pipeline/fusion.ts` (deterministic beats VLM for physical properties,
  tagger/VLM agreement bumps confidence, disagreement caps it, medium
  inference, negative injection) → `backend/film/shot_spec_fusion.py`,
  `frontend/lib/shotspec/fusion.ts`; `pipeline/synthesize.ts` (per-model
  formatters, weighted tags) → the `weighted`/`json` styles in
  `backend/film/prompt_compiler.py` and `frontend/lib/shotspec/formatters.ts`;
  `pipeline/vocab.ts` (style/linework/mood lists) → `backend/film/shot_vocabulary.py`.
  `vlm.ts` and SigLIP are not used.
- **What was adapted (phase 2 part)**: `pipeline/color.ts` + `pipeline/analyze.ts`
  — CIELAB k-means palette, border-ring background isolation, vector-likeness,
  Sobel edge density, aspect snapping, EXIF → `backend/services/vision/
  deterministic.py` (server truth) and `frontend/lib/shotspec/deterministic.ts`
  (client preview). `types/schema.ts`, `fusion.ts`, `synthesize.ts` and
  `vocab.ts` land in phase 3 (ShotSpec). `vlm.ts`/SigLIP are not used.

## NomaDamas/CozyClay — **concepts only, no source used**

- **URL**: https://github.com/NomaDamas/CozyClay — **AGPL-3.0**
- Nothing from this repository is copied, vendored or imported.
  `backend/tests/test_licenses.py` fails the build on any AGPL text or
  CozyClay import. Concepts referenced (written from scratch in phase 3+):
  camera → film-vocabulary derivation, composable prompt blocks with
  provenance/locks, crane-height paths.

## robbietilton/Compositor — **concepts only, no source used**

- **URL**: https://github.com/robbietilton/Compositor — MIT, Swift/macOS
- No Swift source is portable to this Electron app; the layer/mask/adjustment
  concepts inform `FixCanvas` (phase 4). `test_licenses.py` rejects `.swift`
  files.


## wildbyteai/promptlens (prompt templates)

- **URL**: https://github.com/wildbyteai/promptlens
- **Commit inspected**: `41c053939450`
- **License**: MIT
- **Ported**: `templates.js` built-in Detailed / Natural / Tags / Concise
  instructions and the custom-template shape (id, name, description,
  instruction, profile, 4000-character limit, 50 custom max) →
  `backend/film/prompt_templates.py` (+ `/api/prompts/templates`). The
  marketing template, IndexedDB history and provider adapters are not used.

## Anil-matcha/Open-Generative-AI (model catalog, cinema vocabulary)

- **URL**: https://github.com/Anil-matcha/Open-Generative-AI
- **Commit inspected**: `9d939bc8f29a`
- **License**: MIT
- **Ported**: `packages/studio/src/components/CinemaStudio.jsx` camera body /
  lens / focal-length / aperture phrase tables → `backend/film/shot_vocabulary.py`;
  `packages/studio/src/models.js` (499 hosted model definitions) → extracted by
  `scripts/extract-model-catalog.mjs` into `backend/film/data/model_catalog.json`
  (id, name, vendor, task, accepted inputs, aspect ratios, resolutions,
  durations only — muapi endpoints and marketing fields stripped), read by
  `backend/film/media_providers.py::capabilities_for`. The Next.js components,
  Workflow Studio and the Wan2GP HTTP client (phase 9) are not part of this
  phase.
