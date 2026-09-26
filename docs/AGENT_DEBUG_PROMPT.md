# Full debugging pass — prompt for Hermes Agent, GPT‑6 Sol and Claude Opus 5.5

Copy the **Shared brief** into each agent verbatim, then append that agent's
**adapter** section. Each agent works on its own branch
(`debug/hermes`, `debug/gpt6-sol`, `debug/opus55`) off `production` and
writes its report to `docs/DEBUG_REPORT_<agent>.md`. Three independent
passes over the same code find more than one; merge their reports at the end.

---

## Shared brief (paste verbatim)

You are auditing and fixing **TFG** (repo `jyoung2000/TFG`, branch
`production`): an Electron + React + FastAPI desktop app for local AI image
and video generation on an RTX 4070 (12 GB), with Reproduce (image/video →
ShotSpec → render/score/refine), a 3D storyboard, LoRA training, a unified
History, a container stack, a remote-backend mode, tiered provider
fallback, and an MCP server that exposes every API route to agents.

Your job is to **find every error and inconsistency and fix what you can
prove**, with a regression test for each fix. You are not here to add
features, restyle, or rewrite. Be adversarial: assume the branch was written
in one long autonomous session and look for the mistakes that mode produces —
contracts that drifted between layers, tests that pass for the wrong reason,
docs that describe intent rather than code, edge cases nobody ran.

### Start here (read before touching anything)

1. `CLAUDE.md` / `AGENTS.md` — architecture rules and commands.
2. `session-notes.md` — what was verified (VF-xxx), what was decided
   (D-xxx), what is BLOCKED. Every VF marked "from knowledge, not fetched"
   and every BLOCKED item is a lead.
3. `docs/RTX_4070_TEST_MATRIX.md` — the acceptance rows; if you have the
   card, measure them and replace BLOCKED with MEASURED.
4. `docs/TESTING.md`, `docs/AGENTS_GUIDE.md`, `docs/CONTAINERS.md`,
   `docs/TRAINING.md`, `docs/REPRODUCE.md`, `docs/VIDEO_REPRODUCE.md`,
   `docs/STORYBOARD_3D.md`, `docs/HISTORY.md`, `docs/AI_PROVIDERS.md`,
   `docs/INTEGRATED_UPSTREAMS.md`, `NOTICES.md`.

### Gates (must be green before every push)

```
pnpm typecheck:ts
backend/.venv/bin/pyright                       # strict; also enforced as a test
pnpm test:frontend                               # vitest
backend/.venv/bin/python -m pytest -q tests      # 829+ tests, fakes only, no network
pnpm e2e                                          # Playwright vs `pnpm dev:ui` mock; zero console errors, media intact
pnpm build:frontend                               # main chunk must stay < 600 kB
```

`pnpm backend:test` runs `uv sync` first; if the torch index is unreachable
use the venv commands above. Never mark a test skipped/xfail to get green;
never add `unittest.mock` (a test forbids it); swap services only through
`ServiceBundle` fakes in `backend/tests/fakes/`.

### Non-negotiables you must preserve

- Backend: thin routes → `AppHandler` → handlers → services behind Protocols
  with `Fake*`; discriminated-union state machines; **never hold the RLock
  during heavy work**; `HTTPError` with `from exc`; film generation goes
  through `film_generation_handler`'s queue, never a parallel engine.
- **12 GB VRAM** is a hard constraint: no default may exceed it; anything
  that cannot run is refused with a reason (never attempted, never hidden).
- **Windows first**: `pathlib` / `toFileUrl()`, a `.ps1` beside every `.sh`,
  no GPL ffmpeg binaries added.
- Licensing: only MIT/Apache-2.0 code may be vendored, with headers, an
  `INTEGRATED_UPSTREAMS.md` entry and `NOTICES.md`; CozyClay is AGPL
  (concepts only); `tests/test_licenses.py` must keep failing on violations.
- No telemetry; keys never leave `settings.json`; nothing in logs.

### The audit, layer by layer

Work through every item; for each, either write "checked — OK (how)" or a
finding. Do not skip an area because it looks fine.

**1. Contracts between layers**
- `backend/film/*_models.py`, `api_types.py`, `state/app_settings.py`
  (snake_case) vs `frontend/types/*.ts` vs `devtools/ui-mock/**` (the mock
  is type-checked against the frontend types but not against the backend).
  Diff field by field: names, optionality, defaults, enums
  (`TrainingStatus`, `ItemSource`, `VideoProfile`, `MediaProvider`,
  `JobKind`, `JobStatus`). Every backend field a route returns must exist
  in the TS type; every TS field the UI reads must be produced by the backend.
- `SettingsResponse` ↔ `AppSettings` (camelCase alias) ↔ `normalizeAppSettings`
  in `AppSettingsContext.tsx` ↔ `DEFAULT_APP_SETTINGS` ↔ mock `seedSettings`.
  The renderer POSTs the whole settings object 150 ms after any local
  change (`AppSettingsContext` sync effect): can that overwrite a preset
  apply or a remote change with stale values? Prove it either way.
- OpenAPI (`/openapi.json`) ↔ MCP tools (`backend/agent/mcp_core.py`):
  every route present, names stable, path/query/body flattening correct,
  `$defs` complete, file routes flagged. Tool names quoted in
  `skills/tfg/SKILL.md` and `docs/AGENTS_GUIDE.md` must exist in `tools/list`.
- Electron preload (`electron/preload.ts`) ↔ `frontend/vite-env.d.ts` ↔
  `frontend/lib/browser-electron-shim.ts`: same method set, same shapes.

**2. Backend correctness**
- Lock discipline in every handler added on this branch:
  `training_handler`, `video_reproduce_handler`, `scene_handler`,
  `wangp_server_handler`, `film_generation_handler` (tiers, consistency),
  `video_generation_handler._hosted_fallback`. Any lock held across a
  subprocess, HTTP call, model call or file copy is a bug.
- Every file-serving route enforces a path policy: training dataset/run
  media, `/api/wangp/output`, `/api/film/output`, video-analysis frames,
  reproduce media, shot-library previews. Try `..`, absolute paths outside
  the root, symlinks, Windows drive letters.
- Auth: which paths accept a query token (`app_factory._is_media_path`) —
  is every one read-only and backend-resolved? Is `/mcp` protected? Does
  `system_shutdown` really only accept loopback, and is exposing it as an
  MCP tool acceptable (the skill says exclude it — should the server
  refuse it over MCP outright)?
- Job store terminal states: every handler that opens a History job must
  close it on complete/fail/cancel/exception, including fallback paths and
  remote manifest jobs. Grep for `jobs.start(` and trace each.
- Cancel: Train (`_is_cancelled`), remote WanGP (`cancelled` flag vs
  running bridge), film hosted fallback (a cancel must never fall through),
  Create fallback. Kill mid-run: does restart recovery mark the job failed?
- VRAM guard ordering: `prepare_for_render` / `fits_machine` before any
  subprocess or model load, never after.
- Trainer recipes (`services/trainer/subprocess_trainer.py`) vs upstream
  docs: musubi-tuner script names, `--blocks_to_swap`, `--fp8_base
  --fp8_scaled`, `--network_weights` resume; ai-toolkit YAML keys. Verify
  against the current upstream README/source, not memory; record what
  you verified.
- WanGP keys (`services/wangp_bridge.py`): `activated_loras`,
  `loras_multipliers`, `image_refs`, `image_end`, `video_guide`,
  `video_prompt_type` letters — verify against `wgp.py` in a real checkout.
- `provider_tiers.plan` + `run_with_fallback`: duplicate providers, a
  project provider that is not local, catalog false negatives, `edit`/`i2i`
  refusal messages; `_local_failed` when `_hosted_cancel` is set.
- `RemoteWanGPBridge`: poll loop termination on network errors, upload
  size limits, path rewriting for every file key, cancel propagation,
  download naming collisions.
- FastAPI internals: `iter_api_routes` relies on `_IncludedRouter.effective_candidates()`
  (FastAPI 0.141). Pin the version or add a fallback and a test that fails
  loudly if the shape changes.

**3. Frontend correctness**
- Every polling `setInterval`/`setTimeout` is cleared on unmount
  (`TrainView`, `HistoryView`, Reproduce views, `MediaTiersEditor`).
- Remote-backend mode: grep every `toFileUrl(` and `file://`; any media
  built from a backend path must go through the authenticated output
  route when `isRemoteBackend()`; references/uploads that need local files
  must say so instead of failing silently.
- Lazy views: each `React.lazy` target exports the named component;
  Suspense fallback renders without layout jump; the standalone build
  (`pnpm build:ui`, `inlineDynamicImports`) still works.
- Keyboard shortcuts: `APP_BINDINGS` present in all four presets; Alt+1…5
  do not fire while typing or while the shortcuts editor is open; no
  conflicts with the Video Editor bindings.
- Settings General: Hardware preset card re-fetches after apply; Remote
  backend card handles a 401, a wrong URL, and reload; tiers editor
  survives an empty `mediaTiers`.
- Accessibility: every icon-only button has an `aria-label`; selects and
  inputs added on this branch have labels; focus is visible on the front
  door; `role="progressbar"` values are within range.
- Console: run every view against `pnpm dev:ui` and against a real backend
  with the DevTools console open; zero errors and zero React warnings
  (keys, act, unmounted setState).

**4. Electron**
- `electron/python-backend.ts` remote branch: `startPythonBackend()` with a
  remote configured must not spawn Python, must publish `alive`/`dead`
  correctly, and `applyRemoteBackend({enabled:false})` must restart the
  local backend once, not twice. Token never logged.
- IPC handlers validate their inputs (`set-remote-backend`,
  `test-remote-backend`); `app_state.json` writes are atomic enough.
- `getBackend()` consumers that cache credentials (`frontend/lib/backend.ts`)
  are reset on switch (`resetBackendCredentials` + reload) — confirm no
  stale token in SSE (`/api/jobs/events`) or `<video>` URLs.

**5. Mock parity and e2e gaps**
- Every route added on this branch has a mock counterpart in
  `devtools/ui-mock/routes/*` with the same shape (training, presets, tiers,
  reference-sheet, scene, video-reproduce, wangp is server-only — say so).
- List what the e2e specs do **not** exercise (e.g. Train → History deep
  link, LoRA picker in Film shot settings, remote-backend switch, tiers
  with a key present) and add specs or mark them as manual with a reason.
- e2e helpers wait for the cold-start "Connect API Keys" modal; find a
  root-cause fix (`forceApiGenerations` defaults to `true` until the runtime
  policy answers) so the wait is unnecessary.

**6. Docs vs code**
- Every command, path, env var and tool name in `README.md`, `docs/*.md`,
  `skills/tfg/SKILL.md`, `deploy/*` must exist exactly as written
  (`LTX_APP_DATA_DIR`, `LTX_HOST`, `TFG_VISION_URL`, `TFG_VLM_BASE_URL`,
  `WANGP_REMOTE_URL`, `TFG_BACKEND_URL`, `pnpm agent:mcp`, `pnpm deploy:config`).
- `docs/INTEGRATED_UPSTREAMS.md` and `NOTICES.md` cover every vendored
  file (grep for `Adapted from` / `Copyright` headers).

**7. Deploy (needs a GPU host with Docker)**
- `docker compose -f deploy/docker-compose.yml up -d --build`: does the
  Dockerfile build (uv sync from the lock inside the image, WanGP clone,
  vision venv)? `/health` with the token; `vision` reachable from `backend`;
  Ollama profile pulls the model; volumes persist across `down/up`.
- Desktop → Remote backend → render → media loads; `WANGP_REMOTE_URL` mode
  renders and downloads.

**8. Hardware acceptance (needs the RTX 4070)**
- Run `docs/RTX_4070_TEST_MATRIX.md` rows A–G. Record seconds and peak
  VRAM from History. If a default does not fit, downgrade it in
  `backend/state/hardware_presets.py` / `film/training_presets.py` and say
  so in the row. Confirm the first-run preset actually applies on a fresh
  install (`app_state.json` absent).

**9. Security**
- Base64 uploads (`/api/wangp/upload`): size cap, name sanitising, disk
  fill. `/mcp` batch size. CORS origins. Any place a user-supplied path is
  opened without `require_absolute_file`/`is_within`.

### Known open risks (start from these)

- Wan 2.2 5B TI2V model key unverified → profile deliberately not offered.
- MCP result shapes implemented from spec knowledge (2025-06-18), not fetched.
- Dockerfile never built; compose only validated with `docker compose config`.
- Trainer command lines never run on a GPU; weights paths come from a JSON
  the user fills in.
- Image edit/inpaint over WanGP returns 501 (parameter names unconfirmed).
- Remote backend cannot read local files chosen in OS dialogs (documented).
- `iter_api_routes` depends on FastAPI's private `_IncludedRouter`.
- Settings sync debounce may race a preset apply / remote settings.
- e2e specs wait out a cold-start modal instead of fixing its cause.

### Output

1. `docs/DEBUG_REPORT_<agent>.md`: a table — ID · area · severity
   (blocker / high / medium / low) · reproduction (exact steps or test) ·
   root cause · fix (commit) · regression test · status. Then "checked —
   OK" lines per audit item, and a "could not verify (why)" list. No
   finding without a reproduction; no fix without a test.
2. One commit per finding (`fix(area): …`), gates green before each push,
   on your branch. Open a PR into `production` when done; do not merge.
3. Never claim a hardware or network result you did not observe.

---

## Adapter: Hermes Agent

You have TFG's MCP server. Configure it once
(`docs/AGENTS_GUIDE.md`): stdio `python backend/tfg_mcp.py` against a
running backend, or `url: http://<host>:8000/mcp` for the container stack;
install `skills/tfg` (`hermes skills install <path>`). Use the tools as a
black-box tester in addition to the source audit:

- `tools/list` must equal the route count; call every tool at least once
  with a valid and an invalid argument set and record any 500 or any
  response whose shape differs from the OpenAPI schema.
- Drive the real workflows end to end (Create image/video, Reproduce image
  and video, 3D storyboard → Deliver, Train → apply LoRA, Consistency Kit)
  on the 4070 and record History metrics into the acceptance matrix.
- Use your terminal tool for the gates; keep your own notes in
  `docs/DEBUG_REPORT_hermes.md`. Exclude `system_shutdown` from the server
  config unless you are testing it deliberately.

## Adapter: GPT‑6 Sol

Run in the repository checkout with a terminal. Prioritise the exhaustive
static passes where you are strongest: the contract diff (section 1) as a
generated table (script it — walk pydantic models and TS interfaces, emit
mismatches), the lock-discipline sweep (section 2, grep every `with
self.lock` / `with self._lock` and classify what runs inside), the path
policy sweep, and the docs-vs-code sweep (script that greps every
backticked command/path/env var in `docs/**` and checks it exists). Then
the gates. If torch's index is unreachable, use `backend/.venv` directly as
documented. Do not run GPU rows unless you have the card; say which
sections you could not execute.

## Adapter: Claude Opus 5.5 (Claude Code)

Use the repo's own workflow: read `CLAUDE.md`, then run all gates first to
establish the baseline, then take sections 2–5 with an emphasis on writing
the missing regression tests (backend integration tests with fakes; new
Playwright specs against `pnpm dev:ui` for the e2e gaps). Fix the cold-start
modal root cause and the settings-sync race if you confirm them. Keep
`session-notes.md` updated with VF-/D- entries for anything you verify or
decide, and end with a PR into `production`.
