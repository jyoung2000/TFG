# Final hardening audit (release candidate)

Forensic audit of `jyoung2000/TFG` (branch `claude/ltx-filmmaking-integration-75pnwq`)
at the end of the release-candidate pass, 2026-09-08, extended on 2026-09-09
with the multi-provider / Model Library pass. Every capability is classified
with one of:

| Status | Meaning |
|---|---|
| **VERIFIED WORKING** | exercised by an automated test in this repository *or* by a real Electron run in this environment (Playwright over CDP, `scripts/verify/*.mjs`) |
| **IMPLEMENTED BUT UNVERIFIED** | code exists, typechecks and its unit/integration tests pass, but the exact end-user flow was not exercised end to end here |
| **PARTIAL** | works within a stated boundary |
| **BLOCKED — ENVIRONMENT** | cannot be verified in this environment (no GPU, no Windows/macOS, no reachable AI provider); never reported as PASS |
| **MISSING** | not implemented |

Environment: Linux container, no GPU (`cuda_available=false`, WanGP bridge
detected at the sibling `Wan2GP` checkout so `execution_mode=wangp`; a render
attempt fails fast with `No module named 'mmgp'`), no outbound access to AI
providers, Electron 31 under Xvfb.

## 0. Upstreams inspected

| Repository | Commit | Date | What was compared |
|---|---|---|---|
| `jyoung2000/TFG` (this) | branch head | 2026-09-08 | everything below |
| `deepbeepmeep/LTX-Desktop-WanGP` (host baseline) | `4abb4a5` | 2026-04-14 | host unchanged upstream; TFG carries the film layer on top |
| `deepbeepmeep/Wan2GP` | `362c346` | 2026-09-07 | `defaults/*.json` model definitions (source of the Models tab rows), `ckpts/` layout, `wgp.py` entry |
| `Anujatk1999/bluefish` | `8b409c1` | 2026-04-21 | script → scenes → storyboard → assets → continuity concepts, storyboard output contract |
| `Anujatk1999/open-media` | `9bfc076` | 2026-09-07 | `src/modules/composer/*` (ComposerViewport, SceneTree, Inspector, ShotBuilderPanel, PosePanel, JointControls, TransformGizmo, CompositionControls, cameraUtils, motion Timeline, CameraObject, CameraViewfinder, PoseLibrary), `src/stores/composerStore.ts`, MCP tools |

Concepts adopted from Open Media this pass: transform gizmo with per-type
constraints, lock/visibility/rename/duplicate in the scene tree, manual vs
preset camera, keyframe timeline for camera and objects, MCP-style director
tools (`position_object`, `set_camera`, `add_keyframe`, …). Attribution
headers are kept (`frontend/views/film/composer/*.ts`, `docs/INTEGRATED_UPSTREAMS.md`).

## 1. Capability matrix

### Entry points and product contract

| Capability | Status | Location / evidence |
|---|---|---|
| Home: "What do you want to make?" → Quick video / Filmmaker Studio | VERIFIED WORKING (UI) | `frontend/views/Home.tsx`; `verify-hardening.mjs` #1-3 |
| Quick video: prompt, settings, generate, result actions, history | VERIFIED WORKING (UI, generation itself BLOCKED — ENVIRONMENT) | `frontend/views/QuickMode.tsx` |
| Quick video reference image (image-to-video) | VERIFIED WORKING (UI zone + metadata) / render BLOCKED — ENVIRONMENT | `QuickMode.tsx` `acceptReferenceFile`, `runGeneration`; `verify-rc.mjs` A |
| Edit in Film Maker from Quick video (Scene 1 / Shot 1 / v1, no re-encode) | VERIFIED WORKING (API + UI) | `frontend/lib/film-conversion.ts`, `backend/handlers/film_handler.py::import_generation`; `test_film_quick_mode.py`; `verify-rc.mjs` J |
| Edit in Film Maker from Gen Space cards | IMPLEMENTED BUT UNVERIFIED (UI button; conversion path verified via API) | `frontend/views/GenSpace.tsx` `handleEditInFilmMaker` |
| Edit / Regenerate Shot from the Video Editor (clip + asset menus) | IMPLEMENTED BUT UNVERIFIED (UI); link data verified | `frontend/views/editor/ClipContextMenu.tsx`, `AssetContextMenu.tsx`, `VideoEditor.tsx` `handleEditInFilmMaker`, `Asset.filmRef` |
| Replace the linked timeline clip with a newer version | IMPLEMENTED BUT UNVERIFIED | `frontend/views/film/useShotWorkflow.ts::sendToTimeline({replace})` |
| Build Film with AI: plan → edit → Apply all / Apply selected / Regenerate / Cancel | VERIFIED WORKING (offline planner UI; LLM path tests with fake HTTP) | `frontend/views/film/BuildFilmDialog.tsx`; `verify-rc.mjs` B; `test_film_openrouter.py::TestBuildFilm` |

### AI Director and providers

| Capability | Status | Location / evidence |
|---|---|---|
| OpenRouter provider: key storage in backend settings file, env fallback, masked UI, validate, model discovery from `GET /api/v1/models`, role models, remove | VERIFIED WORKING (tests + UI with placeholder key; real service never called) | `backend/film/llm_providers.py`, `frontend/components/OpenRouterSettings.tsx`; `test_film_openrouter.py`; `verify-hardening.mjs` #11 |
| Gemini provider parity (function calling + JSON) | VERIFIED WORKING (tests, fake HTTP) | `GeminiProvider`; `test_film_openrouter.py::test_gemini_function_calling_path` |
| OpenAI-compatible endpoints (LM Studio, vLLM, Ollama) with model refresh and connection test | VERIFIED WORKING (tests + UI; the endpoint itself unreachable here → typed 502) | `OpenAICompatibleProvider`, `OpenAICompatibleSettings`; `test_film_rc.py::TestOpenAICompatibleProvider`; `verify-rc.mjs` H |
| Claude (Anthropic) provider: key + model settings, live model list, tool calling (`tool_use`/`tool_result` blocks), typed 401/404/429/529 | VERIFIED WORKING (tests + UI with placeholder key; real service never called) | `AnthropicProvider`; `test_model_providers.py::TestAnthropicProvider`; `verify-models.mjs` |
| Grok (xAI) provider (OpenAI-compatible transport, own key/model/model list) | VERIFIED WORKING (tests + UI with placeholder key) | `XAIProvider`; `test_model_providers.py::TestXAIProvider` |
| Provider selection: explicit or Auto (openrouter → anthropic → xai → gemini → openai_compatible), status naming the missing key for an explicitly-selected provider | VERIFIED WORKING (tests + live status) | `film_director_handler.py::_active_provider_name`, `status()`; `test_model_providers.py::TestProviderSelection`; `verify-models.mjs` |
| In-chat Director / Video / Image model chips writing to the project or app defaults | VERIFIED WORKING (live: picking a provider changed the director provider; picking a video model was written onto the project) | `frontend/views/film/ModelPickers.tsx`; `verify-models.mjs` |
| Hosted media providers (fal, WaveSpeed, Replicate): submit → poll → download, progress, cancel, timeout, data-URL conditioning images | VERIFIED WORKING (tests, fake HTTP) | `film/media_providers.py`, `film/media_runner.py`; `test_model_providers.py::TestMediaProviders`, `::TestMediaRunner` |
| Hosted render inside the existing film queue (same versions, telemetry `execution_mode`, outputs, export) | VERIFIED WORKING (tests + live: a keyless hosted render failed with a typed, key-free message and recorded the provider as its execution mode) | `film_generation_handler.py::_run_hosted_job`; `test_model_providers.py::TestHostedFilmGeneration`; `verify-models.mjs` |
| AI-generated asset reference images with the selected image model (local or hosted) | VERIFIED WORKING (tests + live missing-key path) | `film_generation_handler.py::generate_asset_reference`; `test_model_providers.py::TestAssetReference`; `verify-models.mjs` |
| Model Library: one searchable catalog (WanGP defs, native LTX files, Ollama, OpenAI-compatible, OpenRouter/Claude/Grok/Gemini, fal/WaveSpeed/Replicate) with task/source filters, GPU-fit filter, per-source error isolation | VERIFIED WORKING (tests + live search/filter run) | `handlers/model_library_handler.py`, `frontend/views/film/ModelLibrary.tsx`; `test_model_providers.py::TestModelLibrary`; `verify-models.mjs` |
| Model downloads from the library: WanGP weights from Hugging Face, Ollama pulls, progress + cancel; hosted rows refuse with an explanation | VERIFIED WORKING (tests + live refusal and install-state rows); a real multi-GB weight download BLOCKED — ENVIRONMENT | `model_library_handler.py::start_download`; `test_model_providers.py::TestModelLibrary`; `verify-models.mjs` |
| Custom model ids: any pasted id is accepted, used and remembered | VERIFIED WORKING (live) | `POST /api/models/library/remember`; `verify-models.mjs` |
| Honest hosted catalogs: fal/WaveSpeed rows shipped as labelled examples (no public catalog API), each linking to the provider's own list; Replicate discovered via collections | VERIFIED WORKING (tests + live "example"/"Needs API key" states) | `film/media_providers.py::curated_models`, `PROVIDER_CATALOG_URLS` |
| Offline readiness reported honestly (`offline_ready` + note: a local video/image model **and** a local text model) | VERIFIED WORKING (live banner) | `ModelSearchResponse.offline_ready`; `verify-models.mjs` |
| Offline builder / parser without any provider | VERIFIED WORKING | `film_director_handler.py` heuristic planner, `film/script_parser.py` |
| Tool-calling loop, JSON-plan fallback, 12-turn cap, tool results fed back | VERIFIED WORKING (tests) | `FilmDirectorHandler.instruct`; `test_film_openrouter.py::TestToolCallingDirector` |
| Full tool list incl. composer tools (`position/rotate/scale_object`, `update_pose`, `set_ots`, `set_camera`, `add/update/delete_keyframe`, `capture_shot`, `duplicate_shot`, `assign_prop`, `set_shot_type/…`, `generate_preview/final`) | VERIFIED WORKING (tests + live `set_ots`/`position_object` changing real state) | `film_director_handler.py` `_TOOL_SPECS`; `test_film_invariants.py::TestDirectorCompositionTools`; `verify-rc.mjs` D |
| Director safety: id/arg validation, bounded loops, no fs/shell tools, locked objects refused, unknown tool reported | VERIFIED WORKING (tests) | `test_film_rc.py::TestOpenRouterFailureModes`, `test_film_invariants.py::test_locked_object_refuses_director_moves` |
| OpenRouter hardening: 401, 429, timeout, malformed tool args, no choices, error object | VERIFIED WORKING (tests) | `test_film_rc.py::TestOpenRouterFailureModes` |
| Context overflow handling | PARTIAL — provider error surfaced; compact summaries + truncation reduce risk; no automatic re-summarisation | `film_director_handler.py` (`_MAX_TOOL_STEPS`, 6 kB tool result cap) |

### One shot state and Shot Composer

| Capability | Status | Location / evidence |
|---|---|---|
| ONE SHOT STATE: cast ↔ composer objects ↔ framing kept as one record, both directions | VERIFIED WORKING (tests) | `film_handler.py::sync_composition_and_cast`, `update_shot`; `test_film_invariants.py::TestCastCompositionSync` |
| Composer: objects with position/rotation/scale, visibility, lock, rename, duplicate, delete | VERIFIED WORKING (UI: lock/rename/numeric/duplicate controls; gizmo drag not automatable) | `frontend/views/film/composer/{ShotComposer.tsx,composerScene.ts}`; `verify-rc.mjs` E |
| Transform gizmo (move/rotate/scale, W/E/R) | IMPLEMENTED BUT UNVERIFIED (renders; pointer drag not automated) | `composerScene.ts` (`TransformControls`) |
| Characters as first-class assets with body variants | VERIFIED WORKING (UI body-type control; asset link tests) | `ShotComposer.tsx` `FIGURE_VARIANTS`, `composerScene.setFigureVariant` |
| Pose editor: library, per-joint sliders, mirror, save | VERIFIED WORKING (earlier UI runs + `figure.test.ts`) | `composer/figure.ts`, `poses.ts` |
| Camera presets + manual positioning kept in sync (`camera_mode`) | VERIFIED WORKING (UI: numeric edit → manual, saved) | `composerScene.applyFraming`; `verify-rc.mjs` E |
| True spatial OTS with shoulder side | VERIFIED WORKING (`shotSolver.test.ts` mirror test; UI toggle; director `set_ots`) | `composer/shotSolver.ts` `otsShoulder` |
| Motion presets with duration/intensity | VERIFIED WORKING (`cameraMotion.test.ts`) | `composer/cameraMotion.ts` |
| Keyframes for camera and objects with a simple timeline | VERIFIED WORKING (UI: key camera, saved keyframe; object keys via director tests) | `composerScene.ts` keyframe API; `verify-rc.mjs` E |
| Capture / recapture; in-composer Preview / Final / Retry / Versions / Compare / Approve / Send to Timeline with progress | VERIFIED WORKING (panel present; generation BLOCKED — ENVIRONMENT) | `ShotComposer.tsx` Generate section, `useShotWorkflow.ts` |
| Auto-save on close when dirty | IMPLEMENTED BUT UNVERIFIED | `ShotComposer.tsx::closeComposer` |

### Generation, models, GPU

| Capability | Status | Location / evidence |
|---|---|---|
| Queue → real host pipeline (`VideoGenerationHandler`), T2V / I2V / reference / continuation, cancel, progress, failure persistence | VERIFIED WORKING with the fake pipeline; real WanGP render **BLOCKED — ENVIRONMENT** | `handlers/film_generation_handler.py`; `test_film_generation.py`, `test_film_hardening.py`; live failure path `verify-hardening.mjs` #7 |
| Version telemetry (seconds, GPU, VRAM estimate, execution mode) + shot snapshot per version | VERIFIED WORKING (tests) | `test_film_rc.py::TestVersionTelemetry` |
| Model discovery from WanGP `defaults/*.json` + `ckpts` presence; states ACTIVE / INSTALLED / AVAILABLE / DOWNLOADING / UPDATE AVAILABLE / INCOMPATIBLE | VERIFIED WORKING for discovery + states in tests; `update_available` **MISSING** as a detected condition (no upstream version metadata to compare — shown only via remove + re-download) | `services/wangp_bridge.py::list_model_definitions`, `film_generation_handler.py::_wangp_model_rows`; `test_film_rc.py::TestWanGPModelDiscovery`; `verify-rc.mjs` G |
| GPU-aware quality profiles, RTX 4070 recommendation | VERIFIED WORKING (tests) | `test_film_hardening.py::test_profiles_recommend_by_vram` |
| RTX 4070 qualification | BLOCKED — ENVIRONMENT | `docs/RTX_4070_TEST_MATRIX.md` (all rows blocked; telemetry hooks in place) |
| Preview vs final profiles | VERIFIED WORKING (tests) | `test_film_generation.py` |
| Version history: compare / restore (Set current) / duplicate / delete | PARTIAL — compare, promote and retry exist; per-version delete **MISSING** (append-only by design, documented) | `ShotDetailDrawer.tsx`, `ShotComposer.tsx` |

### Continuity

| Capability | Status | Location / evidence |
|---|---|---|
| Levels GOOD / MINOR / SIGNIFICANT / BROKEN with fixes | VERIFIED WORKING (tests + UI) | `film/film_continuity.py`; `verify-hardening.mjs` #6 |
| Deterministic screen-direction checks (180° rule, jump cut, severe framing jump) as warnings | VERIFIED WORKING (tests incl. API) | `camera_continuity_warnings`; `test_film_invariants.py::TestCameraContinuity` |
| Optional AI visual review (Good / Minor Drift / Review Recommended / Likely Break) with honest fallback | VERIFIED WORKING (tests with fake frames + fake provider; UI button) / real model BLOCKED — ENVIRONMENT | `film_director_handler.py::visual_review`; `test_film_rc.py::TestVisualReview`; `verify-rc.mjs` F |
| Continuation validation (previous output required) | VERIFIED WORKING (tests) | `missing_previous_output` warning |

### Storyboard, queue, timeline, projects

| Capability | Status | Location / evidence |
|---|---|---|
| Production queue: pause / resume / cancel one / cancel all / retry / prioritize / reorder (move) / restart recovery | VERIFIED WORKING (tests + UI pause) | `film_generation_handler.py`; `test_film_hardening.py`, `test_film_rc.py::TestQueueMove` |
| Storyboard cards: preview, number, duration, framing, characters, location, model, versions, continuity dot, approval | VERIFIED WORKING (UI) | `ShotCard.tsx`; `verify-rc.mjs` C |
| Inter-shot timing: project default, scene override, shot override | VERIFIED WORKING (tests + UI scene field) | `test_film_rc.py::TestInterShotGaps`; `verify-rc.mjs` C |
| Undo/redo for structural edits | VERIFIED WORKING (UI: delete → undo → redo → undo; refused while queued in tests) | `frontend/contexts/FilmContext.tsx` history + `PUT /api/film/projects/{id}`; `test_film_rc.py::TestReplaceProject`; `verify-rc.mjs` C |
| `.ltxfilm` Compact / Complete with host project + timeline, output path map, no keys | VERIFIED WORKING (tests + API round-trip in UI run) | `film/film_package.py`; `test_film_package.py`, `test_film_rc.py::TestPackageHostProject` |
| Crash recovery (interrupted jobs → failed, not stuck) | VERIFIED WORKING (tests) | `recover_interrupted_jobs`; `test_film_hardening.py` |
| Migration / additive schema | VERIFIED WORKING (tests) | `test_film_store.py`, `test_film_hardening.py::test_old_project_json_gets_new_defaults` |

### Security

| Capability | Status | Location / evidence |
|---|---|---|
| Canonical path policy for media, outputs, packages, imported generations (traversal, symlink escape, suffix) | VERIFIED WORKING (unit + HTTP tests) | `backend/server_utils/path_policy.py`; `test_security.py` |
| Keys never in responses, project JSON, exports, prompts; log + error-body redaction | VERIFIED WORKING (tests + live project JSON check) | `backend/logging_policy.py`; `test_security.py::TestSecretRedaction`; `verify-rc.mjs` I |
| Electron: `contextIsolation`, `nodeIntegration:false`, `sandbox:true`, validated path IPC | unchanged from previous pass (VERIFIED by inspection) | `electron/main.ts`, `preload.ts` |
| Secret storage | PARTIAL by design — backend settings file (same store as the host's LTX/FAL/Gemini keys) or env var; Electron `safeStorage` not adopted (documented) | `docs/OPENROUTER.md` |
| Every new provider key (Claude, Grok, WaveSpeed, Replicate) write-only over the API: only a `has…` flag comes back, `DELETE /api/settings/api-keys/{id}` clears it | VERIFIED WORKING (tests + live check that a saved Claude key never returns) | `state/app_settings.py`, `handlers/settings_handler.py`; `test_model_providers.py::TestProviderKeys`; `verify-models.mjs` |

### Installers and CI

| Capability | Status | Location / evidence |
|---|---|---|
| Linux AppImage + deb | VERIFIED WORKING in an earlier pass (built + launched over CDP with runtime-only Python) | `docs/INSTALLER.md`, `scripts/verify/check-appimage.mjs` |
| Windows NSIS installer | BLOCKED — ENVIRONMENT (no Wine); pipeline unsigned-by-default; **CI job added** that builds and verifies contents on `windows-latest` | `.github/workflows/ci.yml` `installer-windows`; `RELEASE_CHECKLIST.md` § 2 |
| CI: typecheck, frontend unit tests, backend tests (mac + win), frontend build, installer jobs with artifact verification/upload, no publishing | IMPLEMENTED BUT UNVERIFIED (workflow not executed from this environment) | `.github/workflows/ci.yml` |

### Not done / out of scope

| Item | Status |
|---|---|
| AI editing of the timeline (cut/trim by chat) | MISSING (director tools cover the storyboard) |
| Cross-project shot library | MISSING |
| Per-version delete | MISSING (append-only history) |
| Automatic "update available" detection for model weights | MISSING (needs upstream version metadata) |
| Screen-reader audit, performance budgets | not performed |

## 1b. Provider and Model Library pass (2026-09-09)

Added after the RC audit above, verified the same way (mock-free backend
tests + a live Electron walkthrough, `verify-models.mjs`, 21/21):

- **Five text providers** — OpenRouter, Claude (Anthropic), Grok (xAI),
  Gemini, and any local OpenAI-compatible server — behind one `LLMProvider`
  contract, with per-provider keys and models, live model lists, and an Auto
  order that names the missing key when a provider is chosen explicitly.
- **Four media targets** — Local (the host engine, unchanged and still the
  default) plus fal, WaveSpeed and Replicate, driven by one submit → poll →
  download loop inside the existing film queue: same versions, same progress
  and cancel, same outputs, same export, `execution_mode` recording the
  provider.
- **Model Library** — one searchable catalog over local WanGP definitions,
  native LTX files, Ollama, an OpenAI-compatible server and every configured
  hosted provider, with task/source/GPU-fit filters, real downloads
  (Hugging Face weights, Ollama pulls) with progress and cancel, per-source
  error isolation, custom ids that are accepted and remembered, and an honest
  `offline_ready` signal.
- **In-chat model pickers** — Director / Video / Image chips in the AI
  Director bar, writing to the open film project or to the app defaults.
- **AI asset reference images** using the selected image model, local or
  hosted.

Two fixes came out of the live run rather than the unit tests: hosted rows
showed *example* even without a key (the state precedence now puts
`needs_key` first, which is what the user needs to see), and fal image
results shaped `{"images":[{"url":…}]}` were not extracted by the result
parser.

## 2. Fixes made during this audit

- **Settings sync 422 (host-wide)**: the renderer's debounced `POST /api/settings`
  sent `openrouterModels.prompt_refinement` while the backend aliased that
  field to `promptRefinement` with `extra="forbid"` — every UI settings change
  failed silently since role models were introduced. Fixed by keeping the
  role id snake_case on the wire (`state/app_settings.py`) and pinned by
  `test_film_rc.py::TestSettingsSyncPayload`. Found by the live E2E run, not
  by unit tests.
- **Undo race**: a poll response that started before a restore could land
  afterwards, recording the restore as a new edit and clearing redo. Fixed
  with latest-wins load epochs in `FilmContext`.
- **Cast/composer sync direction**: removing a character from the card
  re-added it from its figure; the sync is now cast-authoritative for cast
  edits and composer-authoritative for composer saves.
- **Framing edits on composed shots were discarded** (composition framing
  overwrote them); now written into the composition.
- **`clear_gap` crashed `update_shot`** (setattr of a request-only field).
- **Export destination pointing at a directory** slipped past the suffix
  rule; refused before suffixing now.
- **Visibility not persisted** by the composer serializer.
- Model rows had an empty `state` in local/API modes.

## 3. Test inventory

| Suite | Count | Result |
|---|---|---|
| Backend pytest (`backend/tests`, mock-free, incl. pyright-strict test) | 461 | PASS |
| Frontend vitest (`frontend/**/*.test.ts`) | 29 | PASS |
| `tsc --noEmit` / `pyright` strict | — | 0 errors |
| Vite production build | — | PASS (composer is a lazy chunk) |
| E2E `scripts/verify/verify-hardening.mjs` (live Electron) | 33 | 33/33 PASS |
| E2E `scripts/verify/verify-rc.mjs` (live Electron) | 39 | 39/39 PASS |
| E2E `scripts/verify/verify-models.mjs` (live Electron) | 21 | 21/21 PASS |
| Real GPU render, real provider calls, real weight download, Windows/macOS installers | — | BLOCKED — ENVIRONMENT |

New in the provider/model pass: `test_model_providers.py` (28) and
`verify-models.mjs` (21 live checks). Earlier passes added
`test_film_invariants.py` (20), `test_security.py` (21), `test_film_rc.py`
(28), the vitest suites (29) and `verify-rc.mjs` (39 checks).

## 4. Acceptance tests (product contract)

| # | Test | Result |
|---|---|---|
| A | Quick video: prompt → generate → result → Edit in Film Maker | UI + conversion VERIFIED; the render step BLOCKED — ENVIRONMENT (fails fast with an actionable error) |
| B | AI film: idea → plan → apply selected → storyboard | VERIFIED WORKING (offline planner; LLM path with fake HTTP) |
| C | Project round trip: export `.ltxfilm` → import into a clean project incl. host project + output map | VERIFIED WORKING (tests + API) |
| D | AI Director "over-the-shoulder, right shoulder" changes actual shot state (framing, shoulder, cast, composition) and the composer shows it | VERIFIED WORKING (live) |
| E | Failure / retry: failed version persisted with reason, retry available, cancel resolves, restart recovery | VERIFIED WORKING (live failure path + tests) |

## 5. Remaining issues

| Priority | Issue |
|---|---|
| P0 | Windows installer has never been installed on a clean Windows machine from this repository (CI job builds and inspects it; the clean-VM checklist in `RELEASE_CHECKLIST.md` § 2 is still open). |
| P0 | No real GPU render has been observed from this repository; the RTX 4070 matrix is entirely BLOCKED. |
| P1 | No real provider call was made from this environment — OpenRouter, Claude, Grok, Gemini, a local endpoint, fal, WaveSpeed or Replicate (all provider tests use fake HTTP with a placeholder key); per-model tool-support quality and hosted render latency are unknown. |
| P1 | No weight was actually downloaded through the Model Library (no bandwidth/disk for a multi-GB Hugging Face pull, no Ollama server here); the download plumbing is verified with fakes and the refusal paths live. |
| P2 | fal and WaveSpeed publish no catalog API, so their rows are shipped examples marked `curated` — ids should be checked against the provider's own list (which every row links to). Any pasted id works and is remembered. |
| P1 | Gizmo pointer interaction and Video Editor context-menu actions are verified by code and types only, not by automated UI. |
| P2 | Model "update available" state cannot be detected (no version metadata); "update" = remove + re-download. |
| P2 | Per-version delete and cross-project shot library absent. |
| P3 | Screen-reader pass and performance budgets not done; the Vite main chunk is ~1 MB. |
