# session-notes.md — TFG production one-shot

## Phases
0 baseline fixes + honest tests · 1 job store + History · 2 vision + VRAM · 3 ShotSpec/formatters/knowledge ·
4 Image Reproduce v2 · 5 Motion + Video Reproduce v2 · 6 3D storyboard · 7 LoRA Train · 8 front door/4070 preset ·
9 containers/remote/tiering · 10 acceptance/docs/PR

**Current phase:** 8 (committing)
**Last passing gate:** Gate 8 (tsc 0 · pyright 0 · vitest 53/53 · pytest 793+5 · e2e 27/27 · main chunk 302 kB)

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

- VF-008 (phase 4): the WanGP keys for reference image + mask on the edit models (Qwen-Image-Edit / Flux Kontext)
  could not be verified here (no WanGP checkout reachable); `ImageGenerationHandler.edit()` and reproduce `_inpaint`
  raise an actionable error until confirmed. Adjustments + patch-from-reference are fully local and tested.
- VF-009: `uv run pytest` re-syncs the lock (pulls torch cu128 → egress 403). Use `backend/.venv/bin/python -m pytest`
  in this container; CI uses `pnpm backend:test` with network.
- VF-010 (phase 5): backend venv has PyAV 18.1, OpenCV 5.0 headless and the imageio-ffmpeg 7.0.2 binary; the real
  `OpticalFlowAnalyzer` and `FfmpegStitcher` are exercised on `samples/clip-01.mp4` in tests (no GPU needed).
- VF-011: WanGP VACE/depth-control keys for the reference clip could not be verified here (no checkout); Video
  Reproduce conditions on the start frame only and records `spec.layout3d.depth_map_path` for phase 6.
- VF-012 (phase 6): blockout `3f2d056` is Apache-2.0 with a NOTICE requiring credit to Sam Wasserman; its engine is
  pure TS on three 0.170 (same as this app) and vendored unchanged; its React shell, GPL FFmpeg builds and
  ffmpeg-static are not used. Blocking-Room `3472ad4` is MIT (130 lines of JS, ported).
- VF-013: WanGP's `video_guide` / `video_prompt_type="V"` settings keys are the documented guide-video inputs; the
  per-model (VACE vs depth) semantics could not be verified here — the bridge sends the depth pass for `*vace*`
  model types and the clean pass otherwise, and the request keys are covered by tests.
- VF-014 (phase 7): WanGP `wgp.py` reads `activated_loras` (a list; `get_lora_URL` returns absolute paths
  unchanged), `loras_multipliers` (space-separated string in the same order), `image_refs` (list), `image_start`,
  `image_end`, `video_guide`, `video_mask`, and the `image_prompt_type` / `video_prompt_type` letter flags
  (`S`/`E` start/end frame, `I` image refs, `V` guide video). Verified from the upstream source at fetch time.
- VF-015: musubi-tuner README: "12GB or more recommended for image training, 24GB or more for video training";
  memory knobs `--blocks_to_swap`, `--fp8_base --fp8_scaled`, `--fp8_llm`/`--fp8_vl`/`--fp8_t5`; scripts
  `zimage_train_network.py`, `qwen_image_train_network.py`, `wan_train_network.py --task t2v-A14B/i2v-A14B`.
- VF-016: ostris ai-toolkit runs `python run.py config.yaml`; config keys `network.type: lora`, `linear`,
  `train.steps`, `model.quantize`, `low_vram`, `trigger_word`, `datasets[].folder_path`/`resolution`,
  `save.save_every`, `sample.sample_every`.
- VF-017: the LTX-2 trainer (`packages/ltx-trainer`) recommends 80 GB and its low-VRAM config targets 32 GB → not
  runnable on a 12 GB card; listed in the catalog only so the UI can say so.
- VF-018: the `dataviz` skill the prompt names is not available in this session (only `docs` and `xlsx` exist);
  the loss sparkline is a plain inline SVG (`views/train/LossSparkline.tsx`).
- VF-019 (phase 8): none of the skills the prompt names for this phase exist in this session (`frontend-design`,
  `modern-web-guidance`, `design:ux-copy`, `design:accessibility-review`, `engineering:code-review`; ListSkills
  returns nothing for them) — the front door, copy and accessibility pass were done by hand and reviewed the same way.
- VF-020: the Wan2GP README (fetched 2026-09-26) names no Wan 2.2 5B TI2V model key and no VRAM figure for it, so a
  second "Wan 2.2 5B" video profile is NOT offered by the 4070 preset; the Settings card says so. Verifying the
  key needs the WanGP checkout on the 4070 (BLOCKED — ENVIRONMENT, docs/RTX_4070_TEST_MATRIX.md).

## Decisions
- D-036 (phase 8): hardware presets live in `backend/state/hardware_presets.py` as settings patches applied through
  the normal `update_settings` path (validation, persistence, listeners); `AppSettings.hardware_preset` records the
  last one. The RTX 4070 preset is recommended by GPU-name markers or any 12 GB NVIDIA card, applied automatically
  once at first run (`handleFirstRunComplete`) and re-appliable from Settings → General.
- D-037: video quality is a `video_profile` setting (fast 540p·6 s / balanced 720p·8 s on `ltx2_22B_distilled`);
  Quick video seeds its defaults from it and the Profile select writes it back.
- D-038: Home is four verbs (Create · Reproduce · Train · History) + Film Studio marked *advanced*; "Analyse video"
  is renamed "Reproduce video" everywhere the person sees it while the `analyze` view id (deep links) is unchanged.
- D-039: route-level code splitting = React.lazy for every view but Home + `manualChunks` for react/lucide; main
  chunk 1.32 MB → 302 kB (react-vendor 203 kB, composer/three 650 kB lazy).
- D-040: app-wide shortcuts are `app.*` actions in every keyboard preset (Alt+1…5 views, Ctrl+/ editor), handled by
  `useGlobalShortcuts` and ignored while typing or while the shortcuts editor is open.
- D-028 (phase 7): trainers are subprocess-only, each in its own venv (`backend/.venv-trainer-*`) cloned by
  `scripts/ensure-trainer.{sh,ps1}`; never vendored. One `LoraTrainer` Protocol, `FakeTrainer` for tests. The
  bootstrap pattern (clone → venv → pip under the app's folders) follows Open-Generative-AI's installer as a
  concept only — no code copied.
- D-029: the 12 GB guard runs before any subprocess: `fits_machine(config)` against `vram.memory_mb()` (or the
  12288 MB constant) and the catalog's `fits_12gb`; Wan 2.2 / LTX-2 stay listed and are refused with the reason.
- D-030: the registry folder layout mirrors WanGP's LoRA directories (`z_image`, `qwen`, `flux2`, `wan`, `ltx2`);
  entries whose file vanished are dropped on load rather than shown.
- D-031: cross-frame consistency = mean CLIP cosine between the shot's first frame and each featured character's
  first reference image; the metric is absent when there is nothing to compare (never invented).
- D-032: pickers ask by model id (`/api/training/loras?model=`) and `compatible()` maps it to a target; Quick video
  asks for `ltx2`, Image Reproduce for its compile target, Film binds per asset.
- D-033: Image Reproduce carries `loras` on the job (persisted) and every candidate render uses them.
- D-034: e2e helpers wait for the "Connect API Keys" modal to clear after load — `forceApiGenerations` defaults
  to true until `/api/runtime-policy` answers, so a cold dev server can flash it over Home.
- D-035: `Dataset.folder` is part of the model (set on save) so the UI and tests can show/verify the on-disk path.
- D-025 (phase 6): the layout solver places grounded objects exactly on their bottom ray's floor hit, so
  reprojection is exact by construction and the round trip is the test (tolerance 0.05 of the frame).
- D-026: blockout thumbnails are deterministic isometric SVGs written server-side (no headless WebGL); the composer
  capture replaces them once a shot is captured or rendered.
- D-027: Deliver renders in the browser (three.js passes) and encodes in the backend (ffmpeg via the stitcher
  service) — no renderer-side ffmpeg; passes are project-relative and travel as `controlVideoPath`/`depthVideoPath`.
- D-021 (phase 5): Video Reproduce reuses the film queue (`queue_shot` with explicit duration / capture / seed on
  `GenerateShotRequest`), waits on the version, scores, stitches; no parallel engine. One `video_gen` child per
  candidate under a `video_reproduce` parent (`jobs.parent()` scope).
- D-022: durations always snap to `get_allowed_durations()` (6/8/10 s) — local renders included — so a shot's clip
  length is legal on every path; the source span stays on `spec.source.start/end`.
- D-023: candidate score = 0.8 × frame composite (start/middle/end vs the shot's extracted frames) + 0.2 × flow
  match (magnitude + pan/tilt direction), renormalised when motion is unmeasured.
- D-024: the VLM is asked per section (4 calls + ≤1 repair each); flow-measured camera move is never overwritten.
- D-017 (phase 4): composite score = 0.35 CLIP-I + 0.25 DINOv2 + 0.15 SSIM + 0.15 palette ΔE2000 + 0.10 layout,
  renormalised over available components (fakes → SSIM/palette/layout only). Seeds `seed0 + (round-1)*100 + n`.
- D-018: Fix canvas is plain Canvas 2D (no Konva/Fabric): mask + adjustment maths mirrored in `services/image_ops.py`
  so the server commit equals the client preview. Inpaint stays behind VF-008.
- D-019: reproduce jobs live in `<outputs>/image_analyses/<id>/` (same folder as the v1 tab) and v1 JSON migrates
  on read; the old `AnalyzeImage.tsx` view is no longer mounted (History "Open in Reproduce" targets the new one).
- D-020: ui-mock `routes/reproduce.ts` compiles prompts with the renderer's own `previewPrompt` so the mock cannot
  drift from `frontend/types/shotspec.ts`; the loop advances on wall clock (one round / 2.5 s).
- D-012 (phase 3): ShotSpec (`film/shot_spec.py` ↔ `frontend/types/shotspec.ts`) is the only analysis→generation
  contract; fusion precedence measured/depth/flow > florence > clip > vlm, `user` locks absolute.
- D-013: new compile targets `ltx2`, `wan22`, `z_image` (own tagged target, no longer an sdxl alias),
  `qwen_image_edit`, `cloud_generic`; styles `weighted|json|negative_only`; `compile_from_spec` returns
  prompt + 4070-safe params (`_TARGET_DEFAULTS`) + conditioning (start_frame/refs/depth).
- D-014: knowledge hints require ≥3 winning events with ≥0.3 spec-key Jaccard overlap on the same target;
  phrases = comma segments shared by ≥2 winners; params = median steps/guidance of winners.
- D-015: imex-next has no LICENSE file but declares MIT in its README; only design + small pure functions ported,
  recorded honestly in INTEGRATED_UPSTREAMS.md.
- D-016: Open-Generative-AI catalog (499 models) extracted to `backend/film/data/model_catalog.json` (~200 KB)
  as capability facts only; used by `capabilities_for()` and phase-9 tiering.
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

## Files touched (phase 3)
- backend/film/{shot_spec,shot_spec_fusion,prompt_templates}.py, film/shot_vocabulary.py (lens/aperture/vocab tables,
  describe_camera), film/prompt_compiler.py (targets, styles, compile_from_spec, PromptHints), film/prompt_api_types.py,
  film/knowledge_{models,store,api_types}.py (candidate kinds, seed/target/spec_keys/metrics, schema v2),
  handlers/{knowledge,prompt}_handler.py, _routes/{knowledge,prompts}.py, film/media_providers.py (catalog),
  film/data/model_catalog.json, app_handler.py (TemplateStore), tests/test_shot_spec.py (14), tests/test_prompt_compiler.py
- frontend/types/shotspec.ts, lib/shotspec/{schema,formatters,fusion}.ts (+ formatters.test.ts), types/knowledge.ts
- scripts/extract-model-catalog.mjs; docs/INTEGRATED_UPSTREAMS.md, NOTICES.md

## Files touched (phase 4)
- backend/services/similarity/{metrics,composite}.py, services/image_ops.py, film/reproduce_models.py,
  handlers/reproduce_handler.py, _routes/reproduce.py, app_factory.py (media query token), app_handler.py (wiring,
  canceller), handlers/image_generation_handler.py (cancel_current, edit stub), film/image_recreation.py (public
  helpers), tests/test_reproduce.py (14)
- frontend/types/reproduce.ts, lib/reproduce-api.ts, views/reproduce/{ImageReproduce,SpecBlocks,CandidateCompare,
  WhyPanel,FixCanvas,MediaImage}.tsx, App.tsx (analyze-image → ImageReproduce), views/Home.tsx (label)
- devtools/ui-mock/routes/reproduce.ts, state.ts (reproduceJobs), server.ts; e2e/reproduce.spec.ts (5),
  e2e/views.spec.ts (label); docs/REPRODUCE.md

## Files touched (phase 5)
- backend/services/motion/{flow_math,motion_analyzer,fake_motion}.py, services/stitcher/video_stitcher.py,
  film/video_reproduce_models.py, handlers/video_reproduce_handler.py, _routes/video_reproduce.py,
  handlers/video_analysis_handler.py (motion, spec fusion, per-section VLM, recreate delegate, public load),
  film/video_analysis_models.py (MotionAnalysis, spec), film/video_analysis_api_types.py (kind, seed),
  film/film_api_types.py + handlers/film_generation_handler.py (explicit duration/capture/seed),
  film/prompt_brief.py (movement from flow), handlers/knowledge_handler.py (task), app_handler.py (bundle + wiring),
  app_factory.py, tests/{test_motion,test_video_reproduce}.py, tests/test_video_analysis.py (xfail → real),
  tests/fakes/services.py, tests/conftest.py
- frontend/types/{video-analysis (motion, spec),video-reproduce}.ts, lib/video-reproduce-api.ts,
  views/reproduce/VideoReproduce.tsx, views/AnalyzeVideo.tsx (panel, measured motion row)
- devtools/ui-mock/routes/{video-analysis (motion/spec),video-reproduce}.ts, state.ts, server.ts;
  e2e/video-reproduce.spec.ts; docs/VIDEO_REPRODUCE.md, docs/VIDEO_ANALYSIS.md

## Files touched (phase 6)
- backend/film/{scene_solver,scene_api_types}.py, handlers/scene_handler.py, _routes/scene.py, _routes/video_analysis.py
  (storyboard3d, shot spec), _routes/film.py (deliver), handlers/film_handler.py (deliver), film/film_api_types.py
  (GenerateShotRequest extras, Deliver DTOs), film/film_models.py (blockout_path, control/depth video),
  film/shot_spec_fusion.py (apply_layout), api_types.py (control paths), services/wangp_bridge.py (video_guide),
  handlers/{video_generation,film_generation}_handler.py, services/stitcher (encode_frames), app_handler.py,
  app_factory.py, tests/test_scene.py (13)
- frontend/views/film/composer/blockout/{engine/* (vendored), moves,underlay,deliver}.ts + NOTICE + LICENSE,
  composer/{keyframes,history,sceneFromAnalysis(+test)}.ts, composer/{composerScene,figure,ShotComposer}.tsx|ts,
  views/film/ShotCard.tsx (blockout thumb), views/AnalyzeVideo.tsx + reproduce/VideoReproduce.tsx (Build 3D
  storyboard), lib/{scene-api,film-api}.ts, types/film.ts (ShotSourceRef, blockout_path, control videos)
- devtools/ui-mock/routes/{scene,video-analysis,film}.ts, server.ts, seed.ts; e2e/storyboard3d.spec.ts;
  docs/{STORYBOARD_3D,SHOT_COMPOSER,INTEGRATED_UPSTREAMS}.md, NOTICES.md

## Files touched (phase 7)
- backend/services/trainer/{__init__,trainer,catalog,subprocess_trainer,fake_trainer}.py; film/{training_models,
  training_presets,training_api_types}.py; handlers/training_handler.py; _routes/training.py; api_types.py
  (LoraUse, loras/referenceImagePaths/endFramePath); services/wangp_bridge.py (_apply_loras, image_refs,
  image_end); handlers/{video,image}_generation_handler.py; film/film_models.py (FilmAsset lora_*/seed_lock);
  film/film_api_types.py (UpdateAssetRequest, ReferenceSheet*); handlers/film_handler.py; film/film_prompt.py;
  handlers/film_generation_handler.py (attach_training, asset_loras, seed lock, _consistency_score,
  generate_reference_sheet); _routes/film.py; handlers/reproduce_handler.py + _routes/reproduce.py +
  film/reproduce_models.py (loras); app_factory.py; app_handler.py; services/vision/fake_vision.py (embed
  tolerates non-image bytes); tests/{test_training.py,fakes/services.py,conftest.py};
  scripts/ensure-trainer.{sh,ps1}
- frontend/types/training.ts, lib/training-api.ts, components/LoraPicker.tsx, views/train/{TrainView,
  LossSparkline}.tsx, App.tsx, contexts/ProjectContext.tsx (openTrain), types/project.ts, views/Home.tsx (Train
  verb), views/QuickMode.tsx + hooks/use-generation.ts + components/SettingsPanel.tsx (loras),
  views/reproduce/ImageReproduce.tsx + lib/reproduce-api.ts + types/reproduce.ts, views/film/AssetsPanel.tsx
  (Consistency Kit), lib/film-api.ts (referenceSheet), types/film.ts, views/history/JobDrawer.tsx
- devtools/ui-mock/routes/{training,film,jobs,reproduce}.ts, state.ts, server.ts, seed.ts; e2e/train.spec.ts;
  docs/{TRAINING,INTEGRATED_UPSTREAMS}.md

## Files touched (phase 8)
- backend/state/{hardware_presets.py,app_settings.py} (hardware_preset, video_profile, image_steps),
  handlers/settings_handler.py (presets/apply_preset), _routes/settings.py (GET presets, POST apply),
  tests/test_hardware_presets.py
- frontend/App.tsx (lazy views, Suspense, first-run preset, global shortcuts), hooks/use-global-shortcuts.ts,
  lib/{presets-api,keyboard-shortcuts}.ts, components/settings/HardwarePresetCard.tsx, components/{SettingsModal,
  KeyboardShortcutsModal}.tsx, views/{Home,QuickMode,AnalyzeVideo}.tsx, types/settings.ts,
  contexts/AppSettingsContext.tsx, vite.config.ts (manualChunks)
- devtools/ui-mock/{routes/settings.ts,seed.ts}; e2e/{views,settings,storyboard3d,video-reproduce}.spec.ts

## Next step
Phase 9: deploy/ containers (backend + vision sidecar + WanGP), Electron remote backend setting, wangp_remote_bridge,
per-task provider capabilities + tiered fallback, docs/AI_PROVIDERS.md.
