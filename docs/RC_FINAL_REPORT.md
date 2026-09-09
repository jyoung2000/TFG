# TFG release-candidate final report

Date: 2026-09-08, updated 2026-09-09 · Branch: `claude/ltx-filmmaking-integration-75pnwq`

## 1. Executive status

**READY WITH KNOWN LIMITATIONS.**

Everything that can be verified without a GPU, a Windows machine or a
reachable AI provider is verified: 461 backend tests, 29 frontend unit
tests, strict type checks, a production build, and 93 live end-to-end checks
against the real Electron app all pass. What cannot be verified here is
stated as **BLOCKED — ENVIRONMENT**, never as PASS: a real WanGP render on an
RTX 4070, a clean-machine Windows install, real provider calls, and a real
multi-GB weight download. Those are the release blockers listed in §8 and in
`RELEASE_CHECKLIST.md`.

## 2. Changes by subsystem (this pass)

**Backend**
- ONE SHOT STATE invariant (`sync_composition_and_cast`) with direction-aware
  authority; framing edits on composed shots now stick; `clear_gap` fix.
- AI Director composer tools (`position/rotate/scale_object`, `update_pose`,
  `set_ots` with shoulder, `set_camera` manual mode, keyframe add/update/delete,
  `capture_shot`, `duplicate_shot`, `assign_prop`, `set_shot_type/angle/elevation/composition`,
  `generate_preview/final`), locked-object refusal, unknown-tool reporting.
- Providers: OpenAI-compatible endpoints as a first-class provider sharing
  the OpenRouter adapter; multimodal message encoding (OpenAI content parts,
  Gemini `inline_data`); typed failure mapping for 401/404/429/timeouts/malformed replies.
- Continuity: deterministic screen-direction / jump-cut / framing-jump
  warnings from composer geometry; optional AI visual review endpoint.
- Security: one canonical path policy (`server_utils/path_policy.py`) behind
  media, outputs, packages and imported clips; secret redaction on every log
  record and error body; keys stripped from host-project data in packages.
- Queue `move`; per-version telemetry + shot snapshot; scene/shot gap
  overrides; whole-project replace endpoint (undo/redo) guarded by the queue;
  WanGP model discovery from `defaults/*.json` with product states; `models_path`,
  RAM and CUDA in capabilities.
- **Host bug fixed:** the renderer's settings sync had been failing with 422
  on every change (role-model field alias mismatch).

**Frontend**
- Shot Composer: TransformControls gizmo, lock/hide/rename/duplicate/delete,
  body variants, numeric transforms, camera preset ↔ manual mode with
  numeric/aim controls, OTS shoulder toggle, motion intensity, keyframe
  timeline for camera and objects, in-composer Capture / Preview / Final /
  Retry / Versions / Compare / Approve / Send to Timeline with queue progress,
  auto-save on close.
- Shared `useShotWorkflow` (drawer + composer); `Asset.filmRef` linkage;
  "Edit / Regenerate Shot in Film Maker" in clip and asset menus; "Edit in
  Film Maker" on Gen Space cards; replace-linked-clip on promote.
- Quick video reference image (image-to-video) preserved through history,
  asset and film shot.
- Undo/redo (snapshot history, Ctrl+Z / Ctrl+Shift+Z, toolbar) with a
  latest-wins load guard; scene gap field; drawer gap-before field; card
  model/version/approval labels.
- Build Film dialog: per-scene include (Apply selected) and Regenerate plan.
- Models tab states + metadata + "Open model location"; Settings section for
  local OpenAI-compatible endpoints; drawer AI visual check.

**Tooling / CI / docs**
- Vitest suite; CI jobs for frontend tests and unsigned Windows / Linux
  installer builds with artifact verification and upload (no publishing).
- `scripts/verify/verify-rc.mjs` live walkthrough (39 checks).
- Docs updated: AI Director tools + safety, Continuity, Shot Composer,
  Project format, OpenRouter + local endpoints, Installer CI, Release
  checklist, RTX 4070 matrix, this report, the audit.

## 2b. Multi-provider and Model Library pass (2026-09-09)

**Backend**
- Text providers: `AnthropicProvider` (native messages API — system prompt at
  the top level, `tool_use`/`tool_result` content blocks, consecutive tool
  results merged into one user message, typed 401/404/429/529) and
  `XAIProvider` (OpenAI-compatible transport), alongside the existing
  OpenRouter / Gemini / OpenAI-compatible providers. Per-provider key + model
  settings, live model lists, and an Auto order
  (openrouter → anthropic → xai → gemini → openai_compatible) that still
  names the missing key when a provider is selected explicitly.
- Media providers: `film/media_providers.py` (fal queue API, WaveSpeed v3,
  Replicate predictions + collection discovery) and `film/media_runner.py` —
  one submit → poll → download loop with timeout, ramped progress and the
  queue's cancel flag. Conditioning images ride inline as `data:` URLs.
- `FilmGenerationHandler` routes a job to the hosted path when the project or
  app settings select one, keeping the single queue, versions, outputs,
  export behaviour and telemetry (`execution_mode` = provider). Missing keys
  fail the job with a typed, key-free message. `generate_asset_reference`
  produces asset reference images locally or hosted.
- `ModelLibraryHandler` + `/api/models/library`: unified search over WanGP
  `defaults/*.json`, native LTX files, Ollama `/api/tags`, an
  OpenAI-compatible `/models`, and each configured hosted catalog; downloads
  for Hugging Face-hosted WanGP weights and Ollama pulls with progress and
  cancel; per-source error isolation; `offline_ready`.

**Frontend**
- `views/film/ModelLibrary.tsx` — search, task/source tabs, only-compatible
  toggle, offline banner, download progress + cancel, per-row
  Download / Pull / Use / Add key, a custom-id row with a provider select,
  and one error line per unreachable source. The Models tab now opens on it,
  with the previous GPU/weights view as *Installed & GPU*.
- `components/AiProviderSettings.tsx` — a card per text provider (key, model,
  live refresh) and per media provider, plus the media-provider chooser.
- `views/film/ModelPickers.tsx` — Director / Video / Image chips in the AI
  Director bar, writing to the open project or the app defaults.
- *Generate with AI* on asset reference images.

**Tooling / docs**
- `scripts/verify/verify-models.mjs` (21 live checks).
- `docs/AI_PROVIDERS.md` (new) plus updates to the Director, filmmaking,
  pipeline, OpenRouter and verify docs.

## 3. Upstream repositories inspected

| Repository | Commit | Files / concepts compared |
|---|---|---|
| `deepbeepmeep/LTX-Desktop-WanGP` | `4abb4a5` (2026-04-14) | host baseline: unchanged upstream since the TFG fork point |
| `deepbeepmeep/Wan2GP` | `362c346` (2026-09-07) | `defaults/*.json` (model name/architecture/URLs → Models tab), `ckpts/` presence, `wgp.py` bundling |
| `Anujatk1999/bluefish` | `8b409c1` (2026-04-21) | script/scenes/storyboard/assets/continuity flow; storyboard output contract reused by the `storyboard` role |
| `Anujatk1999/open-media` | `9bfc076` (2026-09-07) | `ComposerViewport`, `SceneTree` (lock/visibility/rename/duplicate), `Inspector`, `ShotBuilderPanel`, `PosePanel`/`JointControls`, `TransformGizmo`, `CompositionControls`, `cameraUtils`, motion `Timeline`, `CameraObject`/`CameraViewfinder`, `PoseLibrary`, `composerStore` (locked, duplicateObject, duplicateKeyframe), MCP tools → adopted as native three.js + director tools; solver attribution kept |

## 4. Tests

| Suite | Result |
|---|---|
| `pnpm typecheck` (tsc + pyright strict) | PASS — 0 errors |
| `pnpm test:frontend` (vitest) | PASS — 29 tests |
| `pnpm backend:test` (pytest, mock-free) | PASS — 461 tests |
| `pnpm build:frontend` | PASS |
| `scripts/verify/verify-hardening.mjs` (live Electron) | PASS — 33/33 |
| `scripts/verify/verify-rc.mjs` (live Electron) | PASS — 39/39 |
| `scripts/verify/verify-models.mjs` (live Electron) | PASS — 21/21 |
| Required-list coverage: invariants, director composition tools, screen direction, queue move/recovery, versions/telemetry, package host round-trip, path policy, redaction, provider failure modes, settings clear, OpenAI-compatible, replace-project, visual review | PASS (see `docs/FINAL_HARDENING_AUDIT.md` § 3) |
| Real GPU render, real provider calls, Windows/macOS installers, gizmo pointer drags | BLOCKED — ENVIRONMENT |

## 5. Installer

- **Windows NSIS**: pipeline builds unsigned by default; **not built or
  installed in this environment** (no Wine). CI `installer-windows` now builds
  it on `windows-latest`, verifies the installer exists (> 60 MB), that the
  unpacked tree carries `backend/`, `Wan2GP/`, `python-deps-hash.txt`,
  `app.asar` and no tests, records SHA-256 and uploads the artifact. The
  clean-VM install/launch/uninstall checklist remains **BLOCKED — ENVIRONMENT**
  (`RELEASE_CHECKLIST.md` § 2).
- **Linux AppImage + deb**: built and launched over CDP in an earlier pass
  (runtime-only Python bundle); CI `installer-linux` rebuilds and inspects it.
- **macOS**: unchanged upstream; unverified.
- No GitHub Release is published by CI.

## 6. WanGP configurations tested

| Configuration | Result |
|---|---|
| Bridge auto-detected at sibling `Wan2GP` (`execution_mode=wangp`), no GPU | Detected; render attempt fails fast with `No module named 'mmgp'`; version marked `failed`, shot returns to `composed`, actionable error shown (VERIFIED live) |
| Model discovery from `defaults/*.json` + `ckpts/` | VERIFIED (tests with a synthetic checkout) |
| T2V / I2V (capture) / reference / continuation / cancel / progress / failure persistence through the host pipeline | VERIFIED with the fake pipeline; **no real render observed** |
| RTX 4070 12 GB profiles (Fast Preview 540p, Balanced 720p recommended, Quality 1080p flagged) | Recommendation logic VERIFIED; measurements BLOCKED (`docs/RTX_4070_TEST_MATRIX.md`) |

## 7. Provider behaviour tested

All with fake HTTP and a placeholder key, never a real key or a real call.

**Text providers** — key stored only in the backend settings file / env;
never in responses, logs, project JSON, exports or prompts;
`401 → OPENROUTER_KEY_INVALID` without echo; `429 → OPENROUTER_RATE_LIMITED`;
timeout → 504; malformed tool arguments tolerated; nameless tool calls
dropped; no-choices / error-object bodies → typed 502; unknown tool →
reported to the model; 12-turn cap; model discovery cached 10 min; role
models; validate endpoint; remove clears cleanly. Claude and Grok add their
own status / chat / tool round-trip / error-mapping coverage, and the Auto
order plus the explicitly-selected-but-unconfigured case are pinned. Live:
the OpenAI-compatible endpoint path returns a typed, key-free 502 when the
local server is unreachable, and the director status names the active
provider and its model.

**Media providers** — fal, WaveSpeed and Replicate submit/poll/download,
result-URL extraction across every envelope shape those APIs use, timeouts,
cancel mid-poll, and the queue integration (a hosted render produces a normal
version and output). Live: a hosted render with no key fails with
`FAL_KEY_MISSING: add the fal API key in Settings → API Keys, or switch this
project back to local generation` and the failed version records `fal` as its
execution mode; the project can be switched back to local generation from the
chat chips.

**Model Library** — search, filters, GPU-fit, per-source error isolation,
download start/status/cancel, hosted rows refusing download with an
explanation, and remembered custom ids. Live: 23 rows for a "flux" query,
hosted text sources listing nothing until a key exists, hosted video rows
marked *Needs API key*, the install path reported as
`<WanGP>/ckpts`, and a pasted id joining the library.

## 8. Remaining issues

| Priority | Issue | Owner action |
|---|---|---|
| P0 | Clean-machine Windows install never performed | run `RELEASE_CHECKLIST.md` § 2 on Windows (or take the CI artifact) |
| P0 | No real GPU render from this repository | run `docs/RTX_4070_TEST_MATRIX.md` on an RTX 4070 |
| P1 | No real provider call (OpenRouter / Claude / Grok / Gemini / local endpoint / fal / WaveSpeed / Replicate) | one manual smoke per provider with a real key; verify tool support of the chosen director model and one hosted render end to end |
| P1 | No real weight downloaded through the Model Library (no bandwidth/disk here, no Ollama server) | pull one WanGP model and one Ollama model on a real machine and confirm `offline_ready` flips |
| P2 | fal / WaveSpeed rows are shipped examples (those vendors publish no catalog API) | check ids against the linked catalogs; any pasted id already works |
| P1 | Gizmo drags and Video Editor menu actions verified by code/types only | manual smoke (5 min) |
| P2 | "Update available" model state not detectable; per-version delete and shot library absent | product decision |
| P3 | Accessibility screen-reader pass; main bundle ~1 MB | later |

## 9. Release recommendation

Tag a **release candidate**, not a final release: ship the CI-built Linux
AppImage and Windows installer artifacts to testers with the checklist, and
promote to release only after the two P0 items are executed on real hardware
and recorded (installer SHA-256, GPU/driver, matrix rows). The codebase
itself is in a releasable state: green CI equivalents, no known
correctness defects, secrets handled as documented, and every unverified
claim marked as such.
