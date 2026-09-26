# session-notes.md — TFG production one-shot

## Phases
0 baseline fixes + honest tests · 1 job store + History · 2 vision + VRAM · 3 ShotSpec/formatters/knowledge ·
4 Image Reproduce v2 · 5 Motion + Video Reproduce v2 · 6 3D storyboard · 7 LoRA Train · 8 front door/4070 preset ·
9 containers/remote/tiering · 10 acceptance/docs/PR

**Current phase:** 1
**Last passing gate:** Gate 0 (tsc 0 · vitest 35/35 · pytest 658 passed + 1 strict xfail · e2e 8/8)

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
- VF-001: preinstalled Chromium (/opt/pw-browsers, rev 1194) has no H.264 decoder (`canPlayType` = ""); VP9/AV1 OK.
  e2e helper verifies H.264 `<video>` by HTTP when the decoder is absent and reports it as codec-limited.
- VF-002: pyright 1.1.414 flags `contextlib.contextmanager` as deprecated (2 errors); the locked 1.1.408 is clean.
- VF-003: `@playwright/test` 1.63 expects Chromium 1243; config falls back to `PW_CHROMIUM_PATH` / `/opt/pw-browsers/chromium`.
- VF-004: ui-mock persists state in `node_modules/.cache/ui-mock/state.json`; e2e resets via `POST /api/__ui_mock/reset` per test.

## Decisions
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

## Next step
Phase 1: services/job_store (sqlite WAL + migrations), handlers/jobs_handler.py, _routes/jobs.py, SSE, instrument handlers, History view + mock routes + e2e.
