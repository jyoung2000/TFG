# session-notes.md — TFG production one-shot

## Phases
0 baseline fixes + honest tests · 1 job store + History · 2 vision + VRAM · 3 ShotSpec/formatters/knowledge ·
4 Image Reproduce v2 · 5 Motion + Video Reproduce v2 · 6 3D storyboard · 7 LoRA Train · 8 front door/4070 preset ·
9 containers/remote/tiering · 10 acceptance/docs/PR

**Current phase:** 2
**Last passing gate:** Gate 1 (tsc 0 · pyright 0 · vitest 35/35 · pytest 679 passed + 1 strict xfail · e2e 12/12)

## Environment (this session)
- Cloud Linux container (not the Windows 4070 box the prompt assumes). No GPU, no nvidia-smi.
- Python 3.11 system; backend needs 3.12 → `uv venv --python 3.12 backend/.venv`.
- Egress policy blocks `download.pytorch.org` (403 at CONNECT) → `uv sync --frozen` cannot fetch torch cu128.
  Workaround for tests only: PyPI torch into `backend/.venv` (scratch req list), not committed.
- token-optimizer / Context7 / Playwright MCPs are NOT available here → built-in tools; Playwright via `@playwright/test`
  npm package + preinstalled Chromium at `/opt/pw-browsers` (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1).
- Consequence: every "real-GPU" gate is recorded as BLOCKED — ENVIRONMENT (honestly, in the matrix), fakes-based gates run.

## Baseline (feat/video-recreation-and-assets-gallery @ 5468a95)
- pnpm install OK; `pnpm typecheck:ts` EXIT 0.
- vitest 33/33, vite build OK (main chunk 1.20 MB), pytest 653 passed (with PyPI-torch venv, pyright pinned 1.1.408 as in uv.lock).

## Verified facts
- VF-005: transformers 4.57.6 has native `Florence2ForConditionalGeneration`, `CLIPModel`,
  `DepthAnythingForDepthEstimation`, `Dinov2Model` (checked in backend/.venv).
- VF-006: huggingface.co is unreachable from this container (curl → 000), GitHub raw is reachable; kijai/ComfyUI-Florence2
  could not be cloned here — the Florence task map/registry was written from the documented task tokens (MIT attribution kept).
- VF-007: `imageio-ffmpeg` in the backend env ships an ffmpeg binary; `scripts/make-samples.py` used it to build
  `samples/clip-01.mp4` (synthetic, CC0). No ffmpeg binary was added to the repo.
- VF-001: preinstalled Chromium (/opt/pw-browsers, rev 1194) has no H.264 decoder (`canPlayType` = ""); VP9/AV1 OK.
  e2e helper verifies H.264 `<video>` by HTTP when the decoder is absent and reports it as codec-limited.
- VF-002: pyright 1.1.414 flags `contextlib.contextmanager` as deprecated (2 errors); the locked 1.1.408 is clean.
- VF-003: `@playwright/test` 1.63 expects Chromium 1243; config falls back to `PW_CHROMIUM_PATH` / `/opt/pw-browsers/chromium`.
- VF-004: ui-mock persists state in `node_modules/.cache/ui-mock/state.json`; e2e resets via `POST /api/__ui_mock/reset` per test.

## Decisions
- D-008 (phase 2, ADR 0001): vision runs **in-process by default** behind `VisionService`; the sidecar
  (`backend/vision_worker.py`, own env) is selected when `TFG_VISION_URL` answers `/health`. Reason: transformers 4.57
  loads Florence-2/CLIP/Depth-Anything/DINOv2 natively (no trust_remote_code), WanGP pins could not be inspected here.
- D-009: `VisionSettings.vlm_provider` defaults to `director` (keeps pre-2.0 behaviour) but a failing/text-only VLM now
  degrades to the local-stack prompt instead of a 502 (D9 fixed); the 4070 preset (phase 8) sets it to `off`.
- D-010: VRAM classes S ≤ 1.5 GB / M ≤ 3 GB / L; unload order Ollama VLM → DINO → depth → CLIP → Florence; render
  needs table in `services/vram/vram_manager.py::RENDER_NEEDS_MB` (+512 MB margin); a non-fitting render → HTTP 507
  with an actionable message; peak VRAM sampled into `job.metrics.peak_vram_mb`.
- D-011: clip-interrogator lists vendored unchanged (1.9 MB, MIT); flavors ranked over the first 2048 terms by default
  (low-VRAM knob), tables cached as .npy under the vision cache dir.
- D-003 (phase 1): jobs get their own lock + SQLite store (`<app-data>/jobs.sqlite`); `GenerationHandler` forwards
  transitions to jobs *after* releasing the app lock; thumbnails are made outside any lock.
- D-004: film-queued shots open a *queued* job at `queue_shot()` and pass it into `video_generation.generate(job_id=)`,
  so local and hosted renders share one record; `_finish_version` is the idempotent closer.
- D-005: re-run = new queued job (same params + seed, parent = original) executed on the task runner; only
  `video_gen`/`image_gen` support it for now.
- D-006: UI-mock/standalone poll from the start (no SSE possible); desktop uses EventSource with polling fallback.
- D-007: legacy `ltx-quick-history` localStorage is imported once through `POST /api/jobs/import`, then removed.
- D-001: Branch `feat/production-oneshot` created from `feat/video-recreation-and-assets-gallery` per prompt §0.
- D-002: `toFileUrl()` in `frontend/lib/file-url.ts` is the single file→URL helper; it must percent-encode path
  segments (spaces/#/%), fixing D11 at the helper rather than at each call site.

## Files touched
- Phase 0: frontend/views/AnalyzeVideo.tsx (D4, D5), frontend/views/QuickMode.tsx + lib/file-url.ts (+test) (D11),
  components/FirstRunSetup.tsx, PythonSetup.tsx, lib/film-conversion.ts (hand-rolled file:// removed),
  frontend/views/film/AssetsPanel.tsx + components/Lightbox.tsx (D12), backend/_routes/video_analysis.py +
  handlers/video_analysis_handler.py (D2, 501), backend/tests/test_video_analysis.py (D3 strict xfail),
  backend/tests/test_licenses.py, e2e/ + playwright.config.ts + package.json (pnpm e2e), devtools/ui-mock/seed.ts
  (asset reference images), AGENTS.md/CLAUDE.md (3.12, CI list), docs/TESTING.md

## Files touched (phase 1)
- backend/services/job_store/{__init__,job_models,sqlite_job_store,thumbnails}.py, handlers/jobs_handler.py,
  _routes/jobs.py, api_types.py (import DTOs), app_factory.py (router + SSE query token), app_handler.py (wiring,
  cancellers/rerunners, recover_interrupted), state/app_state_types.py (GenerationRunning.job_id),
  handlers/{generation,video_generation,image_generation,retake,ic_lora,film_generation,video_analysis,download,
  model_library}_handler.py, film/image_recreation.py, tests/test_jobs.py (21 tests)
- frontend/types/jobs.ts, lib/jobs-api.ts, views/history/{HistoryView,JobCard,JobDrawer,useJobs}.tsx|ts,
  contexts/ProjectContext.tsx (history view, openAnalysis/pendingAnalysis, quickPreset), App.tsx, views/Home.tsx,
  views/QuickMode.tsx (jobs-backed history), views/AnalyzeImage.tsx + AnalyzeVideo.tsx (pendingAnalysis), index.css
- devtools/ui-mock/routes/jobs.ts, state.ts, server.ts; e2e/history.spec.ts; docs/HISTORY.md

## Files touched (phase 2)
- backend/services/vision/{protocol,deterministic,florence2,clip_tagger,depth,local_vision,remote_vision,fake_vision}.py
  + clip_data/ (vendored lists + LICENSE + README), backend/services/vram/vram_manager.py, handlers/vision_handler.py,
  _routes/vision.py, state/app_settings.py (VisionSettings), app_handler.py (VramManager/VisionHandler wiring, bundle
  vision/nvml, TFG_VISION_URL), handlers/settings_handler.py (listeners), handlers/{video,image}_generation_handler.py
  (render_scope + peak VRAM), handlers/model_library_handler.py (task=vision + downloads), film/image_recreation.py
  (local stack first, offline prompt, graceful VLM failure), handlers/video_analysis_handler.py (Florence grounding),
  _routes/image_analysis.py (vision slot), _routes/model_library.py, api_types.py, backend/vision_worker.py,
  backend/vision-requirements.txt, tests/test_vision.py (28), tests/fakes/services.py, conftest.py
- frontend/types/settings.ts (VisionSettings), contexts/AppSettingsContext.tsx, components/VisionSettings.tsx,
  components/SettingsModal.tsx (Vision tab), lib/shotspec/deterministic.ts (+test), types/models.ts, lib/model-library-api.ts,
  views/film/{ModelLibrary,ModelPickers}.tsx; devtools/ui-mock/routes/vision.ts, routes/settings.ts (nested merge), seed.ts,
  server.ts; e2e/settings.spec.ts; scripts/ensure-vision.{ps1,sh}, scripts/make-samples.py, samples/; docs/adr/0001-*.md,
  docs/INTEGRATED_UPSTREAMS.md, NOTICES.md

## Next step
Phase 3: film/shot_spec.py + frontend/types/shotspec.ts (§4 contract), film/shot_spec_fusion.py, prompt_compiler.compile_from_spec + targets z_image/qwen_image_edit/cloud_generic + styles weighted/json/negative_only (film/prompt_templates.py), shot_vocabulary merge + describe_camera, knowledge loop (KnowledgeEvent per candidate, hints_for), curated_models seed.
