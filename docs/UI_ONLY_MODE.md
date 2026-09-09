# UI-only mode

Work on the interface without installing the app. Two ways in.

## A file you can double-click

**`ui-preview/ltx-desktop-ui.html` is committed to the repo** — download it and
open it. Nothing to build.

```bash
pnpm build:ui        # rebuilds that file from source
```

One self-contained HTML file (~1.8 MB). Open it from your file manager, mail
it, drop it in a Slack thread, put it on a USB stick — it runs from `file://`
with **nothing** installed and no server anywhere, because the mock backend
runs in the tab.

Because it is committed, it can fall behind the source. Rebuild it in any
commit that changes the interface.

Its state lives in that browser's `localStorage`, so your changes survive a
reload. To start over, clear site data for the page, or open it in a private
window.

## A dev server with hot reload

```bash
pnpm install
pnpm dev:ui          # http://localhost:5173
```

Use this while you are actually editing components: it is the same thing with
Vite's hot reload. Still no Python, no `uv sync`, no torch, no WanGP checkout,
no GPU, no model weights, no Electron.

## What it is

**The same renderer.** UI-only mode is not a second UI, a storybook or a set of
component stubs — it is `frontend/` exactly as the packaged app ships it,
running against a mock of the backend contract. If a screen looks or behaves
differently here than in the real app, that is a bug in the mock, not a
deliberate simplification.

Two pieces make that work:

| Piece | What it stands in for |
|---|---|
| `devtools/ui-mock/` | The Python backend. |
| `frontend/lib/browser-electron-shim.ts` | The Electron preload bridge (`window.electronAPI`). |

The mock's routes and state machine are one body of code with no Node or DOM
dependencies, reached two ways:

- **`pnpm dev:ui`** — `node-adapter.ts` serves it as real HTTP from the dev
  server, on the app's own origin. Nothing is patched, so `<img src>`,
  `<video src>`, redirects and status codes exercise the same paths they do
  against Python.
- **`pnpm build:ui`** — `browser.ts` runs it in the tab behind a patched
  `fetch`, keeps state in `localStorage`, and resolves media to `data:` and
  `blob:` URLs, because a `file://` page has no origin that could serve them.

Same handlers, same responses, either way.

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
| Rendered clips | `dev:ui` redirects to an MP4 already in the repo (`public/splash/splash.mp4`); the standalone file records a few seconds of canvas animation with `MediaRecorder`, which is real, playable video and adds nothing to the file's size |

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

### Two things the standalone file does not carry

- **Home's background video.** It lives in `public/` (27 MB, decorative), and
  copying it would defeat the point of a single file. The banner falls back to
  its gradient.
- **Web fonts**, if you are offline. They load from Google in the packaged app
  too, so the fallback stack is the same one real users see offline.

`dev:ui` has neither limitation — it serves `public/` normally.

### One browser caveat

`dev:ui` serves the repo's H.264 sample clip. Chromium builds without
proprietary codecs (Playwright's bundled Chromium, some Linux distribution
builds) cannot decode it, so the storyboard's video thumbnail stays blank
there; Chrome, Edge, Safari and Firefox with system codecs all play it. The
standalone file is unaffected — it records VP8/VP9, which every browser
decodes.

## Keeping it 1:1

The mock imports the renderer's own types — `frontend/types/film.ts`,
`types/models.ts`, `types/settings.ts` — and `pnpm typecheck` checks it
(`tsc -p devtools/ui-mock/tsconfig.json`). Change a response shape in the app
and this build breaks, which is the point: the mock cannot quietly drift out of
step with the thing it stands in for.

What that does **not** catch is the backend changing while the frontend types
stay still. Those types are the contract for both, so treat
`frontend/types/*.ts` as the place a backend change lands first.

To check the whole mode end to end — the same 21 checks run against either
way in:

```bash
pnpm dev:ui
node scripts/verify/verify-ui-only.mjs

pnpm build:ui
UI_ONLY_URL=file://$PWD/ui-preview/ltx-desktop-ui.html node scripts/verify/verify-ui-only.mjs
```

## Adding an endpoint

1. Add the request and response types to the renderer's mirror in
   `frontend/types/`.
2. Register a handler in the matching `devtools/ui-mock/routes/*.ts`.
3. Run `pnpm typecheck` — the mock is checked against those types.

## It cannot reach production

`VITE_UI_MOCK` is set only by `pnpm dev:ui` and `VITE_UI_STANDALONE` only by
`pnpm build:ui`. Vite replaces both with literals at build time, so every
branch that reads them — `lib/file-url.ts`, `lib/media-resolver.ts`,
`lib/browser-electron-shim.ts`, the demo-project seed and the in-browser mock
itself — is eliminated from the app bundle, and the dev-server plugin is
`apply: 'serve'`. The production build is checked to contain no trace of the
mock.
