# Filmmaking Integration Architecture

This document maps how the local AI filmmaking workstation in this repository is
assembled from three upstream codebases, what was adapted from each, and how the
resulting single application is structured. Everything below is based on direct
inspection of the upstream repositories at the exact commits listed in
[INTEGRATED_UPSTREAMS.md](./INTEGRATED_UPSTREAMS.md).

Upstream snapshots inspected:

| Repo | Commit | Role |
|---|---|---|
| `deepbeepmeep/LTX-Desktop-WanGP` | `4abb4a5ff9391ef0b21826f34de23636e8973b0c` | Host application and generation runtime |
| `bluefish2026/BlueFish` | `8b409c1332e46bc1211d2ffc6d45fe1f01492eca` | Filmmaking / storyboard product reference |
| `Anujatk1999/open-media` | `9bfc076c792e3989c688bc9642c34512db26ee2b` | 3D shot-composition reference |

---

## 1. Current LTX Desktop WanGP architecture (host)

Three-layer Electron application:

- **Frontend** (`frontend/`): React 18 + TypeScript (strict) + Tailwind. State is
  React contexts only (`ProjectContext`, `AppSettingsContext`,
  `KeyboardShortcutsContext`). View routing is state-based
  (`home` / `project` / `playground`); a project has tabs (`gen-space`,
  `video-editor`). Projects (assets + timelines) persist in `localStorage`
  under `ltx-projects`. All backend calls go through
  `backendFetch()` (`frontend/lib/backend.ts`), which resolves the backend URL +
  bearer token via Electron IPC.
- **Electron** (`electron/`): app lifecycle, window, IPC (`preload.ts` defines
  `window.electronAPI`), Python backend process management, ffmpeg export
  (`electron/export`), path approval for `file://` media.
- **Backend** (`backend/`): Python 3.12 FastAPI server. Request flow is strictly
  `_routes/* (thin) → AppHandler → handlers/* (logic) → services/* (side
  effects) + state/* (mutations under one shared RLock)`. Pyright strict;
  integration-first tests with `TestClient` and **no mocks** (fakes are swapped
  in via `ServiceBundle`).

Generation call chain (traced, not assumed):

```
POST /api/generate (GenerateVideoRequest)
  → handler.video_generation.generate(req)          # video_generation_handler.py
      ├─ wangp_enabled     → WanGPBridge.generate_video(...)   # in-process WanGP session
      ├─ force_api         → LTXAPIClient (cloud LTX API)
      └─ otherwise         → local LTX pipeline (pipelines_handler → FastVideoPipeline)
  Progress: GET /api/generation/progress (poll, 500 ms in the UI)
  Cancel:   POST /api/generate/cancel
  Conflict: 409 when a generation is already running (single GPU slot)
```

The request is **synchronous**: the HTTP call returns when generation finishes
(FastAPI runs sync handlers in a thread pool). Only one generation may run at a
time (`GenerationState` union on the single GPU slot). Image generation
(`POST /api/generate-image`) follows the same pattern via
`image_generation_handler` (ZIT local pipeline or FAL API), and it too is
delegated to WanGP when the bridge is enabled.

Other host capabilities reused as-is: model download/status
(`/api/models/...`), health + GPU telemetry (`/api/health`), settings
(`/api/settings`, includes `gemini_api_key`), the Gemini-backed
`suggest_gap_prompt` handler (precedent for LLM calls through the fakeable
`HTTPClient` service), the retake and IC-LoRA pipelines, and the entire
`VideoEditor` (tracks, clips, takes, transitions, effects, subtitles, export).

## 2. Current BlueFish architecture (reference)

Self-hosted web studio: React 19 + zustand client (`bluefish-client/`) and a
FastAPI server (`bluefish-server/`) with JSON-file persistence and cloud
generation providers (Runway, Kling, Vidu, Seedance, DashScope; OpenAI/Google
LLMs; ElevenLabs TTS). Apache-2.0 with a trademark policy excluding the
"Blue Fish" name/branding.

Domain model (`app/models.py`):

- `Project` (name, genre, status) + `ProjectSettings` (style + provider choices)
- `Character` — a **unified entity model**: `entityType` is
  `character | location | prop`, with shared identity fields plus type-specific
  extension fields (personality/appearance/clothing for characters;
  environment/atmosphere/lighting for locations; details/usage for props) and
  reference `images` for visual consistency.
- `Chapter` — a script chunk (scene-level unit) with `originalText` and order.
- `Storyboard` — **the shot**: number/order, description, visualDescription,
  imagePrompt/videoPrompt, dialogue + speaker, `size` (shot size), `movement`
  (camera move), `duration`, per-artifact status fields
  (`firstFrameStatus`, `videoStatus`, `videoError`), rating/favorite flags,
  `userModified`/`aiGenerated` provenance.

Workflow (traced through `app/routes/ai.py` + `llm_service.py`): script text →
LLM (`extract_characters`, `generate_storyboards`) → structured JSON (chapters
with per-shot `size`/`perspective`/`movement`/`focalLength`/`ert`/
`visualDescription`) → saved as reviewable storyboard rows → per-shot frame and
video generation through provider services → per-shot status/error tracking.
`prompt_builder.py` composes style variables (`{realism}`, `{genre_look}`,
`{color_grading}`, …) into prompt templates.

## 3. Current Open Media architecture (reference)

Single-page Vite app (`shot-composer`, MIT): React 19 + react-three-fiber 9 +
drei + three 0.185 + `mannequin-js` 5.2.3 + zustand, plus an MCP server
(`mcp/`) that drives the running app over a WebSocket bridge.

Key modules (all inspected):

- `src/stores/composerStore.ts` — the one shared scene store: `SceneObject`
  (characters/primitives/cameras) with `transform`, `posture`,
  `keyframes[]`, `fov`, `cameraRig`; playback state; a store-level
  `shotSequence`; undo/redo via whole-`objects` snapshots.
- `src/modules/library/calibration/shotSolver.ts` — **the shot solver**: turns
  four semantic parameters (shot size / camera angle / elevation / composition)
  into a camera position + look-at, using character bounding-box anchors.
  OTS is a special aim mode measured against the character's current facing,
  hugging the foreground character's shoulder and aiming past them at a
  secondary character. Composition presets are pure `{screenX, screenY}`
  targets; framing is verified by NDC projection in a built-in self-check.
- `shotAxes.ts` / `compositionPresets.ts` — preset vocabularies (wide/full/
  medium/MCU/close-up; front/¾L/¾R/profile/back/OTS; eye/low/high; center/
  thirds/negative-space).
- `helpers/posture.ts` + `helpers/poseLibrary.ts` — mannequin-js "posture v7"
  serialization (fixed 26-entry arrays), pose library merged from bundled JSON +
  localStorage customs, limb-swap `mirrorPosture`.
- `src/modules/motion/motionPresets.ts` — keyframe-sequence builders (walk/run
  strides from authored poses, turns, start/stop transitions).
- `src/modules/motion/helpers/cameraRig.ts` — procedural rigs (`follow`,
  `orbit`, `shot`) recomputing the camera from live target state each frame.
- `ComposerViewport.tsx` — imperative three.js/R3F viewport with
  `preserveDrawingBuffer: true`; `captureShot()` returns a PNG data URL.
- `src/modules/mcpBridge/commands.ts` + `mcp/tools.js` — ~40 commands mapped
  **1:1 onto real store actions** (get_scene, add_object, set_transform,
  apply_pose, set_shot, set_camera_rig, add_shot_segment, capture_shot, …).
  No hidden AI-only scene state.

## 4. Feature-by-feature comparison

| Capability | LTX Desktop | BlueFish | Open Media | In this app |
|---|---|---|---|---|
| Local model execution | ✅ (LTX pipelines + WanGP bridge) | ❌ (cloud providers) | ❌ | LTX/WanGP path kept as-is |
| Project shell / persistence | localStorage projects | JSON-file server DB | none (scene in memory) | LTX projects + backend film store |
| Script / scenes | ❌ | Chapters | ❌ | Film scenes w/ script panel |
| Storyboard shots | ❌ | Storyboard rows | shot *sequence* (3D only) | `FilmShot` domain object |
| Characters/locations/props | ❌ | unified entity model | mannequins/primitives | Film assets (BlueFish-style) + composer figures |
| Shot size/angle/elevation/composition | camera-motion prompt suffixes only | text fields chosen by LLM | **solved 3D camera** | Structured `framing` + 3D solver |
| Pose editing | ❌ | ❌ | mannequin-js joints | simplified articulated figure, named-joint poses |
| Camera motion | prompt suffixes (`dolly_in`, …) | text field | keyframes + rigs | presets → keyframes + host camera-motion mapping |
| Composition capture | ❌ | ❌ | PNG data URL | capture → reference PNG + composition JSON persisted server-side |
| Generation queue | single slot, sync HTTP | per-shot provider jobs | ❌ | film queue (sequential) on top of the host single slot |
| Versions/takes | editor `AssetTake`s | per-shot URLs | ❌ | `ShotVersion` history + editor takes |
| Timeline/editor | full NLE | basic editor | motion timeline | host NLE kept; shots feed it |
| AI agent control | ❌ | LLM generation routes | MCP commands | AI Director command registry + LLM planner |
| Continuity | ❌ | reference images/consistency tokens | ❌ | asset-based continuity + non-blocking warnings |

## 5. Exact source files/components adapted

From **Open Media** (adapted, reimplemented in host conventions):

- `src/modules/library/calibration/shotSolver.ts` → `frontend/views/film/composer/shotSolver.ts`
  (algorithm ported nearly verbatim, plus a worm's-eye/bird's-eye elevation
  extension and dutch-angle roll; self-check converted into real unit maths kept
  in the module).
- `shotAxes.ts`, `compositionPresets.ts` → preset vocabularies in
  `frontend/types/film.ts` (extended: xwide/xcu sizes, POV/dutch angles,
  bird/worm elevations, symmetrical/leading-lines compositions).
- `motionPresets.ts` + `cameraRig.ts` concepts → `composer/cameraMotion.ts`
  (camera move presets producing camera keyframes: push-in, pull-out, pan,
  tilt, dolly, truck, orbit, follow).
- `composerStore.ts` state shape → `composer/composerState.ts` (scene object
  list, transforms, keyframes, selection; React `useReducer` instead of
  zustand to match host conventions).
- `mcpBridge/commands.ts` pattern → backend AI Director command registry
  (commands map 1:1 to film-store mutations; same "no invented capabilities"
  rule).
- Capture flow (`preserveDrawingBuffer` + `toDataURL`) → `composer/capture.ts`.

From **BlueFish** (concepts adapted; no code copied verbatim — its stack is
React 19/zustand/Mongo-style repo, incompatible with host conventions):

- Unified entity model → `FilmAsset` (`kind: character | location | prop | style`).
- Chapter/Storyboard split → `FilmScene` / `FilmShot`.
- LLM storyboard generation contract (chapters → shots with
  size/perspective/movement/duration/visualDescription) →
  `film_director_handler.generate_storyboard` JSON schema.
- Style-variable prompt building → `film_prompt.py` structured prompt synthesis.
- Per-artifact status state machines (`pending/generating/completed/failed`) →
  `FilmShot.status` + `ShotVersion.status`.

From **LTX Desktop** (kept, not modified): everything listed in §1. New film
code only *calls into* `VideoGenerationHandler`/`ImageGenerationHandler` and
the editor's existing data model.

## 6. Dependencies of candidate components

- Open Media's viewport stack (`@react-three/fiber@9`, `drei@10`) **requires
  React 19**; the host pins React 18. `mannequin-js` is a further transitive
  dependency with its own body-part meshes and a bespoke posture format.
  Decision: do **not** import the stack. The composer here uses plain
  `three` (the only new frontend dependency) with an imperative scene class,
  and a simplified articulated figure built from three.js primitives with
  named joints — preserving the behaviors that matter (posing, framing,
  capture) with a far smaller dependency surface.
- BlueFish components depend on zustand, react-router, its own auth/credit
  system and cloud provider SDKs — none portable; concepts only.
- The shot solver depends only on `three` math (`Vector3`, a `PerspectiveCamera`
  for verification) — fully portable.

## 7. What is ported

- Shot solver math + preset vocabularies (Open Media).
- Composition-preset registry pattern (Open Media).
- Camera-motion preset → keyframe builders (Open Media, generalized to camera
  moves instead of character gaits).
- MCP command-registry pattern for the AI Director (Open Media).
- Domain model shape: scenes/shots/entities/status machines (BlueFish).
- LLM storyboard-generation output contract (BlueFish, re-authored in English
  with the host's Gemini client).

## 8. What is rewritten

- The 3D viewport, gizmo-free transform editing, articulated figure, pose
  format (named joints → Euler degrees instead of mannequin-js v7 arrays),
  pose library persistence (film-store backed instead of localStorage), and
  capture pipeline — all rewritten in plain three.js + React 18.
- Storyboard/asset/scene UI — written fresh in the host's Tailwind design
  language.
- Generation orchestration — written against the host's real
  `GenerateVideoRequest` contract and single-slot semantics.

## 9. What remains external / reference-only

- BlueFish's cloud provider services, credits/auth/subscription system,
  transcription, TTS, music generation — out of scope (host is local-first).
- Open Media's mannequin-js figures, R3F components, MCP WebSocket server,
  motion video export — reference only.
- WanGP itself remains an external installation the backend bridges to.

## 10. Data model mapping

Backend (`backend/film/film_models.py`, Pydantic, versioned):

```
FilmProject v1
├─ schema_version: 1
├─ id == LTX project id (1:1 facet of the host project)
├─ script: FilmScript { content, updated_at }
├─ settings: FilmProjectSettings { default_model, style notes, gap seconds, strict_continuity }
├─ assets: [FilmAsset { kind: character|location|prop|style, name, description,
│            appearance/wardrobe | environment/lighting | prop details,
│            style_prompt, reference_images[], continuity_notes }]
├─ scenes: [FilmScene { order, title, description, location_id, character_ids[],
│            prop_ids[], mood, lighting, time_of_day, continuity_notes,
│            shots: [FilmShot] }]
└─ pose_library: [FilmPose { name, category, joints{name: [x,y,z]°} }]

FilmShot
├─ order, title, description, duration_seconds
├─ framing: ShotFraming { shot_size, camera_angle, camera_elevation,
│            composition, fov_deg, ots { foreground_character_id, subject_character_id } }
├─ characters: [ShotCharacter { asset_id, pose_name?, emotion?, position_hint? }]
├─ location_id, prop_ids[]
├─ action, dialogue, emotion
├─ visual_prompt, negative_prompt (synthesized but user-editable; structured
│  fields are never discarded)
├─ camera_motion (static|push_in|pull_out|pan_left|... ), motion keyframes
├─ composition: CompositionScene { objects[], camera, keyframes[] } — the 3D
│  scene snapshot the composer edits (schema mirrors the frontend composer state)
├─ composition_capture: relative path of the captured reference PNG
├─ generation: ShotGenerationSettings { model, resolution, fps, seed?,
│  use_capture_as_reference, continue_from_previous }
├─ versions: [ShotVersion { number, kind: preview|final, status, prompt,
│  negative_prompt, model, seed, settings snapshot, capture used,
│  output_path, error, created_at }]
├─ current_version
└─ status: draft|composed|ready|queued|generating|review|approved|rejected
```

Frontend `frontend/types/film.ts` mirrors these types exactly (camelCase);
`frontend/views/film/*` renders them; the composer edits
`FilmShot.composition` and nothing else.

Mapping to host editor: an approved `ShotVersion.output_path` is registered as
a host `Asset` (with `generationParams` filled from the version) and appended
to the active `Timeline` as a `TimelineClip` — the same flow GenSpace uses.

## 11. State management mapping

- Backend: film projects are loaded/mutated through `handlers/film_handler.py`
  under the shared `AppHandler` lock, persisted as JSON by `film/film_store.py`
  into `<outputs_dir>/film_projects/<project-id>/project.json` (captures and
  outputs live beside it). No second in-memory copy: the store is read/written
  per request; the generation queue holds only shot references.
- Frontend: `FilmContext` fetches the film project once per project open and
  refetches after every mutation (mutations all go through the backend, so the
  AI Director and the UI mutate the *same* state). Composer edits are local
  component state until "Save composition"/"Capture" posts them back.

## 12. API mapping

New routes (all thin, following `_routes` conventions):

```
GET    /api/film/projects/{pid}                     read (auto-creates empty film facet)
PUT    /api/film/projects/{pid}/script              update script
PUT    /api/film/projects/{pid}/settings            update film settings
POST   /api/film/projects/{pid}/assets              create asset
PUT    /api/film/projects/{pid}/assets/{aid}        update asset
DELETE /api/film/projects/{pid}/assets/{aid}        delete asset
POST   /api/film/projects/{pid}/scenes              create scene
PUT    /api/film/projects/{pid}/scenes/{sid}        update scene
DELETE /api/film/projects/{pid}/scenes/{sid}        delete scene
POST   /api/film/projects/{pid}/scenes/reorder      reorder scenes
POST   /api/film/projects/{pid}/scenes/{sid}/shots  create shot
PUT    .../shots/{shid}                             update shot (incl. framing/composition)
DELETE .../shots/{shid}                             delete shot
POST   .../shots/reorder                            reorder shots
POST   .../shots/{shid}/duplicate                   duplicate shot
POST   .../shots/{shid}/capture                     save capture PNG + composition JSON
POST   .../shots/{shid}/generate                    queue preview|final generation
POST   .../shots/{shid}/versions/{n}/promote        set current version
POST   /api/film/projects/{pid}/generate/batch      queue scene/selection/all
GET    /api/film/queue                              queue + active job status
POST   /api/film/queue/cancel                       cancel active/pending film jobs
GET    /api/film/capabilities                       model capability list (from runtime)
GET    /api/film/projects/{pid}/continuity/{shid}   continuity warnings for a shot
POST   /api/film/projects/{pid}/director/command    one structured AI Director command
POST   /api/film/projects/{pid}/director/instruct   natural-language instruction (Gemini)
POST   /api/film/projects/{pid}/storyboard/generate script → draft scenes/shots (review required)
GET    /api/film/projects/{pid}/media?path=...      serve captures/outputs to the renderer
```

## 13. Generation pipeline mapping

`ShotGenerationRequest` (internal, film layer) is normalized into the host's
**actual** `GenerateVideoRequest` / `GenerateImageRequest`:

- prompt ← `film_prompt.synthesize()` (structured fields → prose; never
  destructive — the structured fields stay on the shot)
- `imagePath` ← the shot's captured reference PNG (if
  `use_capture_as_reference`) or a continuity/previous-shot frame
- `cameraMotion` ← nearest host camera-motion id (`push_in→dolly_in`, …);
  richer motion detail goes into the prompt text
- resolution/fps/duration/model ← version kind: previews clamp to the fastest
  model + lowest supported resolution + capped duration; finals use shot
  settings
- The film queue worker (via the existing `TaskRunner` service) submits jobs
  **sequentially** to `VideoGenerationHandler.generate()` — the host single-slot
  invariant, progress reporting, cancellation and all three execution paths
  (WanGP / forced API / local) are reused untouched.
- Job state transitions are persisted on the shot version at every step, so a
  backend restart leaves shots in a resumable `failed`/`queued` state instead
  of losing them.

## 14. Persistence mapping

```
<outputs_dir>/film_projects/<project-id>/
  project.json          # FilmProject v1 (schema_version field, migrated on load)
  captures/<shot>.png   # captured composition references
  captures/<shot>.json  # composition snapshot at capture time
  outputs/              # copies/links of generated shot outputs (versioned names)
  references/           # uploaded asset reference images
```

`film_store.load()` runs `migrate()` on any older `schema_version` before
parsing — the migration table starts at v1 and is the designated place for
future schema bumps. LTX projects without a film facet keep working: the film
API auto-creates an empty v1 facet on first read, and nothing in the host
project format changed.

## 15. Timeline/editor mapping

"Send to timeline" (frontend, `FilmContext.sendToTimeline`):

1. `window.electronAPI.copyToProjectAssets` copies the version output into the
   host project-assets folder (same as GenSpace).
2. `addAsset(projectId, {...})` with `generationParams` filled from the shot
   version (mode/model/prompt/duration/resolution/fps) so the editor's
   retake/regenerate features work on film shots too.
3. A `TimelineClip` is appended to the active timeline at the end of the
   last clip on track V1 (+ configured inter-shot gap), using the exact clip
   shape from `useClipOperations` (transitions none, default color correction).
4. "Replace current" adds the new output as a **take** on the existing asset
   (`addTakeToAsset`), which the editor already knows how to switch between.

The editor itself is unchanged.

## 16. 3D composer mapping

`frontend/views/film/composer/` (lazy-loaded chunk):

- `ShotComposer.tsx` — full-screen overlay opened from a shot card. Left:
  scene tree (composer objects bound to film characters/props). Center:
  three.js viewport with orbit controls + camera viewfinder preview. Right:
  progressive-disclosure panels (Shot presets / Camera / Pose / Motion).
  Bottom: keyframe strip in motion mode.
- `composerScene.ts` — imperative three.js scene manager (build/dispose,
  raycast selection, figure/primitive/camera factories, render loop,
  viewfinder render-to-texture, capture).
- `figure.ts` — articulated primitive mannequin: named joints
  (`head, neck, torso, l_arm, l_elbow, l_wrist, r_..., l_leg, l_knee,
  l_ankle, ...`), Euler-degree rotations, sized male/female/child variants.
- `shotSolver.ts` — ported solver (§5).
- `poses.ts` — built-in pose set (stand/sit/walk/run/point/arms-crossed/…),
  project pose library CRUD via the film API.
- `cameraMotion.ts` — motion presets → camera keyframes.
- `capture.ts` — renders the shot camera at output aspect, returns PNG data
  URL + `CompositionScene` JSON; posted to the capture endpoint.

Composer state serializes to `FilmShot.composition` (`CompositionScene`), which
is versioned inside the project JSON. Scene resources are disposed on close.

## 17. MCP / AI-agent mapping

The AI Director is a **native command registry** in
`handlers/film_director_handler.py` (no separate MCP server, no WebSocket):

- `director/command` executes one structured command
  (`get_project, get_scene, get_shot, create_scene, create_shot, update_shot,
  add_character, add_location, add_prop, assign_character, set_framing,
  set_composition, apply_pose, set_transform, set_camera_motion, set_duration,
  set_dialogue, set_action, remove_object, generate_shot, …`) against the film
  store — the same store the UI mutates, so there is no AI-only state.
- `director/instruct` sends the instruction + a compact project summary +
  command catalog to Gemini (same `HTTPClient` pattern as
  `suggest_gap_prompt_handler`), validates the returned command list, executes
  it, and reports per-command results. Generation commands are only queued —
  never silently rendered — unless the instruction explicitly asks.
- The composer's camera/scene mutations initiated by the director are stored in
  `FilmShot.composition`; the frontend refetches and re-hydrates the 3D scene
  from it, so director changes are visible in the same viewport the user edits.

## 18. Licensing / attribution

- Host: Apache-2.0 (Lightricks). License and NOTICES retained.
- BlueFish: Apache-2.0; trademark policy forbids using the "Blue Fish"
  name/branding — this app uses none of it. Concepts and model shapes adapted;
  attribution recorded in NOTICES.md and INTEGRATED_UPSTREAMS.md.
- Open Media: MIT; ported solver/preset code carries attribution headers and is
  recorded in NOTICES.md and INTEGRATED_UPSTREAMS.md.
- No `mannequin-js` code or assets are included (avoids both the dependency and
  its separate licensing).

See [INTEGRATED_UPSTREAMS.md](./INTEGRATED_UPSTREAMS.md).

## 19. Migration / backward compatibility

- Host `Project`/`Timeline`/`Asset` formats: **unchanged**. Existing
  localStorage projects load exactly as before; the Storyboard tab simply
  appears alongside Gen Space and Video Editor.
- Film store: every `project.json` carries `schema_version`; `migrate()` is the
  single upgrade path and is unit-tested with a synthetic older payload.
- Backend API: purely additive (new `/api/film/*` routes); every existing
  route, request and response model is untouched.
- `.python-version` was loosened from `3.12.12` to `3.12` (same minor) because
  uv's interpreter registry does not carry that exact patch release in all
  environments.

## 20. Test plan

Backend (integration-style, mock-free, per house rules — see
`backend/tests/test_film_*.py`):

- project auto-create / read / script + settings update / reload round-trip
- schema migration from a v0-style payload; corrupted-file resilience
- asset CRUD; scene CRUD + reorder; shot CRUD + reorder + duplicate
- capture endpoint (PNG bytes land on disk; composition JSON persisted)
- prompt synthesis (structured fields → prompt; negative prompt; style)
- capability endpoint derives from runtime config (wangp/forced-api/local)
- generation: preview vs final mapping, queue ordering, failure persistence,
  cancellation, version history + promote, batch queue
- continuity warnings (wardrobe/location/prop/missing-capture)
- AI Director structured commands (create/update/framing/pose/generate) and
  storyboard generation via heuristic parser (LLM-free path) + Gemini path
  through the fake HTTP client
- shot timing/ordering calculations

Frontend: `tsc --noEmit` strict; solver behavior is validated by the ported
NDC-projection sweep run under the backend test suite's Node-free equivalent
(pure-math port in `shotSolver.ts` mirrored in Python tests for the shared
constants), plus real-browser exercise via Playwright against the dev server.

## 21. Risks

- **Torch index availability**: the pinned `uv.lock` resolves torch from
  `download.pytorch.org` (blocked in some sandboxes). Mitigation: PyPI-equivalent
  env for CI-less environments; lock untouched.
- **R3F/React-19 pull**: avoided entirely (plain three.js).
- **Single GPU slot**: batch generation is sequential by design; the film queue
  surfaces per-shot progress so this reads as intentional, not stuck.
- **LLM dependence**: storyboard generation and `instruct` degrade to a
  deterministic script parser / structured commands when no Gemini key is set.
- **Composition scale**: `project.json` stays small because captures/outputs are
  files referenced by relative path, never embedded.
- **Electron-only IPC**: film UI degrades gracefully in a plain browser (a dev
  shim provides `electronAPI` no-ops so the storyboard/composer remain usable
  against a local backend).
