# Testing strategy

The pyramid, bottom to top. Each layer must fail when the feature it covers is
broken — a test that passes on both outcomes is a defect (see the history of
`test_video_analysis.py::TestRecreation`).

| Layer | Tool | Where | Runs on | What it proves |
|---|---|---|---|---|
| Static | `tsc --noEmit` (app + `devtools/ui-mock`), pyright strict (also `tests/test_pyright.py`) | `pnpm typecheck` | every PR | contracts hold across renderer, mock backend and Python |
| Unit (TS) | vitest, colocated `*.test.ts` | `pnpm test:frontend` | every PR | pure helpers: file URLs, composer math, shot spec fusion, formatters |
| Integration (Py) | pytest + Starlette `TestClient` against the real FastAPI app with `Fake*` services (no `unittest.mock`) | `pnpm backend:test` | every PR | handlers, state machines, routes, job store, queues, persistence |
| Guardrails | `test_no_mock_usage.py`, `test_import_safety.py`, `test_licenses.py`, `test_pyright.py` | with pytest | every PR | architecture and licensing rules stay enforced |
| End-to-end (UI) | Playwright against `pnpm dev:ui` (mock backend, no GPU) with the media-integrity helper | `pnpm e2e` | every PR | every view renders, every `<img>`/`<video>` decodes, zero console errors |
| GPU acceptance | manual/scripted runs on the RTX 4070, results in `docs/RTX_4070_TEST_MATRIX.md` | per release | real renders, VRAM peaks, timings |

## Media-integrity helper (`e2e/helpers/media.ts`)

`attachConsoleGuard(page)` records console errors, page errors, failed
requests and 4xx/5xx responses (Google Fonts excluded — some CI proxies block
it and the app must not depend on it). `expectMediaIntact(page, guard)`
asserts every `<img>` has `naturalWidth > 0`, every `<video>` reached
`HAVE_METADATA`, and the guard is empty. In a Chromium build without an H.264
decoder the video row is verified by HTTP (2xx + `video/*`) and reported as
codec-limited instead of silently passing.

## Rules

- New backend feature → integration test with fakes (`tests/fakes/`), never a
  mock. New heavy side effect → `services/<x>/` Protocol + real + `Fake*`.
- New view or panel → e2e spec in `e2e/` using the helper; the mock backend in
  `devtools/ui-mock/` gets the matching routes (it is type-checked against
  `frontend/types/*`).
- A behaviour that cannot run in CI (GPU, installer, live provider) is
  recorded as `BLOCKED — ENVIRONMENT` in the matrix, never faked green.
- `xfail` only with `strict=True` and a reason naming the phase that removes it.

## Commands

```
pnpm typecheck && pnpm test:frontend && pnpm backend:test && pnpm e2e
cd backend && uv run pytest tests/test_video_analysis.py -v --tb=short   # one file
pnpm e2e -- --grep "Assets"                                               # one spec
E2E_BASE_URL=http://127.0.0.1:5173 pnpm e2e                               # reuse a running dev:ui
```
