# UI-only mode (`pnpm dev:ui`)

Work on the interface without installing the app.

```bash
pnpm install
pnpm dev:ui          # http://localhost:5173
```

No Python, no `uv sync`, no torch, no WanGP checkout, no GPU, no model
weights, no Electron. Just Vite and a browser.

## What it is

**The same renderer.** UI-only mode is not a second UI, a storybook or a set of
component stubs — it is `frontend/` exactly as the packaged app ships it,
running against a mock of the backend contract. If a screen looks or behaves
differently here than in the real app, that is a bug in the mock, not a
deliberate simplification.

Two pieces make that work:

| Piece | What it stands in for |
|---|---|
| `devtools/ui-mock/` | The Python backend. A Vite plugin serves it as real HTTP on the dev server's own origin. |
| `frontend/lib/browser-electron-shim.ts` | The Electron preload bridge (`window.electronAPI`). |

The mock is served over **real HTTP** rather than by patching `fetch` in the
renderer. That distinction is what keeps the mode faithful: `<img src>` and
`<video src>` load, redirects and status codes work, error bodies come back in
the backend's own `{detail, message}` envelope, and no renderer code knows the
difference.

## What you get on first run

A seeded demo film, **The Relay (demo)**, listed on Home like any saved
project:

- two scenes, six shots, every asset kind (characters, locations, a prop, a
  style), and a screenplay in the Script tab;
- a shot with a composition and a capture, one with a completed render, one
  with a failed version and a Retry;
- a deliberate continuity break (a ridge shot carrying the station's location)
  so the dots, the drawer's warning list and one-click Fix all have something
  real to act on;
- a Model Library with local and hosted rows, GPU-fit badges against a
  simulated RTX 4070, and honest `needs_key` states.

**New film** still creates an *empty* project, exactly as it does in the real
app.

State lives in `node_modules/.cache/ui-mock/state.json` and survives a restart.
To start over:

```bash
curl -X POST http://localhost:5173/api/__ui_mock/reset
```

## What is simulated, and how honestly

| Area | Behaviour |
|---|---|
| Film CRUD (scenes, shots, assets, poses, reorder, duplicate, capture, promote) | Real reads and writes against the mock's store |
| Continuity | The deterministic checks from `film_continuity.py`, ported: same kinds, severities, messages, fixes |
| Production queue | One job at a time, pause/resume, cancel, prioritize, progress and phases — advanced from wall-clock time, so it moves while you watch |
| Quick-mode generation | Blocks like the real endpoint, reports phases, then "completes" |
| Model downloads | Progress and completion are simulated; nothing is fetched |
| Build Film / storyboard generation | The deterministic offline planner — the same thing the real backend falls back to with no provider |
| AI Director | With no provider: the real `AI_DIRECTOR_KEY_MISSING` message and disabled state. Save any placeholder key and it answers with correctly shaped responses whose text says plainly that they came from the mock, never from a model. A small built-in reader does understand shot size, OTS, push-in and durations, so the storyboard visibly reacts |
| Captures and reference images | Generated SVG frames, labelled with the shot or asset so layout and cropping problems are visible |
| Rendered clips | A real MP4 already in the repo (`public/splash/splash.mp4`), served by redirect — so playback, canvas thumbnail extraction and the timeline all behave normally |

Secrets follow the real rule: a key can be written but never read back, only
`has*` flags come out, and `DELETE /api/settings/api-keys/{provider}` clears
it. Nothing in UI-only mode makes a network request to any provider.

### Not simulated

- **Video export** needs ffmpeg from the Electron main process; the button
  reports that rather than pretending.
- **IC-LoRA** endpoints answer `501` so the UI shows its unavailable states.
- **The AI visual continuity review** reports "unavailable", which is also what
  the backend says with no provider.
- **Real file dialogs.** The shim returns plausible paths so the flows continue.

## Keeping it 1:1

The mock imports the renderer's own types — `frontend/types/film.ts`,
`types/models.ts`, `types/settings.ts` — and `pnpm typecheck` checks it
(`tsc -p devtools/ui-mock/tsconfig.json`). Change a response shape in the app
and this build breaks, which is the point: the mock cannot quietly drift out of
step with the thing it stands in for.

What that does **not** catch is the backend changing while the frontend types
stay still. Those types are the contract for both, so treat
`frontend/types/*.ts` as the place a backend change lands first.

To check the whole mode end to end:

```bash
pnpm dev:ui
node scripts/verify/verify-ui-only.mjs   # 21 checks, from a dir with playwright
```

## Adding an endpoint

1. Add the request and response types to the renderer's mirror in
   `frontend/types/`.
2. Register a handler in the matching `devtools/ui-mock/routes/*.ts`.
3. Run `pnpm typecheck` — the mock is checked against those types.

## It cannot reach production

`VITE_UI_MOCK` is only set by `pnpm dev:ui`. Vite replaces it with a literal at
build time, so the two branches that read it (`lib/file-url.ts`,
`lib/browser-electron-shim.ts`) and the demo-project seed are eliminated from
the bundle, and the plugin itself is `apply: 'serve'`. The production build is
checked to contain no trace of the mock.
