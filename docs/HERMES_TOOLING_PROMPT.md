# Hermes: tooling addendum for the TFG audit

Paste this after `docs/HERMES_PROMPT.md` (or on its own — the repository
link is inside). It tells Hermes which of its installed skills and MCP
servers to use at each step, and which to leave alone.

---

You are running the TFG audit from
**https://github.com/jyoung2000/TFG/tree/hermes-review** (the task text is
`docs/HERMES_PROMPT.md` in that branch: set up, use every feature as a
user, grade it, debug what you find, deliver a review PR into
`hermes-review`). Use your installed skills and MCP servers as follows.
Load a skill before the step it is for; do not load skills you will not
use. When a skill and the repository disagree about how TFG works, the
repository wins — the skills `tfg-ltx-desktop` and `ltx-desktop-wangp`
predate this snapshot; read them for background, then trust `README.md`,
`docs/*.md` and the code.

## 0. Before you start

- `hermes-mcp-config` — add the TFG server to `~/.hermes/config.yaml`
  (stdio: `<repo>\backend\.venv\Scripts\python.exe <repo>\backend\tfg_mcp.py`,
  env `TFG_BACKEND_URL=http://127.0.0.1:8000`, `tools.exclude: [system_shutdown]`),
  then `hermes mcp test tfg` (~214 tools).
- `hermes-skill-installation` — install `<repo>\skills\tfg` from the local
  clone (the GitHub shortcut reads the default branch, which lacks it).
- `hermes-token-optimization` — this is a long run with big logs; keep
  tool output trimmed (`| tail`, `| Select-Object -Last`), read files by
  range, and write findings to disk as you go.
- `memory` MCP — store every finding the moment you make it (id, area,
  reproduction, status) so a crash or context reset does not lose it;
  rebuild the report from memory at the end.
- Known-broken servers (`git`, `headroom`, `pinterest-api`, `ponytail`):
  do not depend on them. Use terminal `git` for every git operation. If
  you need a `uvx` server, clear the interpreter path first
  (`PYTHONPATH=""`) as your notes say.
- `windows-dev-setup` — check Node 18+, pnpm, `uv`, git, ffmpeg and the
  NVIDIA driver before `pnpm setup:dev:win`; missing prerequisites are
  finding #1, not an excuse.

## 1. Setup and baseline gates

- `superpowers-using-git-worktrees` — work in a worktree on branch
  `review/hermes` so the `hermes-review` checkout stays pristine for
  reproductions.
- `dogfood` — this is the posture for section 2 of the audit: you are
  the customer; log every moment you had to read code to get past a screen.
- `desktop-app-qa` — first-run and Home checks on the Electron app
  (`pnpm dev`): preset applied, zero console errors, front door clarity.
- `windows-mcp` — drive the desktop app like a user (click the four verbs,
  open Settings, run a Quick video) and take screenshots for the review;
  it is the only way to judge the real Electron UI, since Playwright cannot
  attach to it.
- `browser-testing-with-devtools` — console and network of the renderer:
  `pnpm dev` exposes the Electron inspector with `pnpm dev:debug`;
  `pnpm dev:ui` serves the same UI in a browser against the mock backend.
- `playwright` MCP and `browser-harness` — run and extend the e2e specs
  against `pnpm dev:ui`; use them for any new UI regression you file.
  They exercise the mock backend, not the GPU — say so in the report.

## 2. Using every feature (U1–U16)

- `tfg` MCP (the server you configured) — the primary way to run U15 and
  to drive every scenario without the GUI. Call each tool at least once
  with valid and invalid arguments; log every 500 and every response that
  does not match its `inputSchema`/OpenAPI shape.
- `image-reconstruction-workflows` and `imugi` MCP — for U5/U6 (Reproduce):
  compare the best candidate to the reference visually (side-by-side,
  diff) and record whether the app's composite score agrees with what
  your eyes and the diff say. A high score on a poor match is a finding.
- `comfyui` / `ltx-desktop-wangp` / `tfg-ltx-desktop` — background on
  WanGP model types, resolutions and LoRA folders; use them to sanity-check
  the settings TFG sends (`activated_loras`, `video_guide`, …) against
  `Wan2GP/wgp.py` in your checkout, which is the source of truth.
- `huggingface-hub` — fetch or verify the weights the trainer needs
  (Z-Image DiT/VAE/text encoder for musubi-tuner, U8) and the vision
  models; record exact repo ids and sizes in the environment section.
- `performance-optimization` and `observability-and-instrumentation` —
  read timings and peak VRAM from History (`jobs_get_job` → `metrics`) and
  from `nvidia-smi`; note where History's numbers disagree with
  `nvidia-smi` or are missing.
- Serialize GPU work: one render or training run at a time, the way the
  app's queue expects. `superpowers-dispatching-parallel-agents` is fine
  for reading code and docs in parallel, never for two GPU jobs at once
  (that is itself a test case — U-break "two renders at once" — run it
  once, deliberately).
- `make-interfaces-feel-better` and `desktop-ui-overflow-fixes` — the lens
  for the user-experience notes: discoverability, copy that tells the
  truth, error text that says what to do next, layout breakage at
  1366×768 and at 4K scaling.

## 3. Debugging what you found

- `superpowers-systematic-debugging` (or `systematic-debugging`,
  `diagnosing-bugs`, `debugging-and-error-recovery`) — reproduce first,
  bisect, root-cause to file:line, then fix; never patch a symptom.
- `serena` MCP — symbol-level navigation of the backend and frontend
  (find references of a handler, a settings field, a job kind) for the
  contract-drift and lock-discipline sweeps; it is faster and more
  reliable than grep for "who reads this field".
- `python-debugpy` — the backend runs with a debugger when started as
  `pnpm dev:debug` (`BACKEND_DEBUG=1`); attach to step through a failing
  handler (training start, film queue, remote WanGP bridge).
- `node-inspect-debugger` — same for the Electron main process
  (`ELECTRON_DEBUG=1`): remote-backend switching, IPC handlers, the
  Python process lifecycle.
- `code-audit` / `codebase-audit` / `security-and-hardening` — the source
  sweeps listed in the audit prompt: path policy on every file-serving
  route, auth exemptions, upload limits, `system_shutdown` over MCP,
  locks held across renders/subprocesses/HTTP, History jobs without a
  terminal state.
- `api-and-interface-design` and `documentation-and-adrs` — the
  contract and docs-vs-code checks: backend models ↔ `frontend/types` ↔
  `devtools/ui-mock` ↔ OpenAPI ↔ MCP tool schemas; every command, path
  and env var in `README.md`, `docs/**`, `deploy/**`, `skills/tfg/SKILL.md`.
- `test-driven-development` / `tdd` — every fix ships with a regression
  test: backend integration tests with `ServiceBundle` fakes (no
  `unittest.mock`), Playwright specs against `pnpm dev:ui` for UI. Gates
  (`pnpm typecheck:ts`, pyright, vitest, pytest, e2e, build) green before
  every push.
- `code-simplification` / `simplify-code` — only on code you already
  changed for a fix; do not refactor for its own sake.

## 4. Delivering

- `triage` / `omh-triage` — rank the findings by user pain for the top 10
  and assign severity (blocker / high / medium / low).
- `to-tickets` and `github-issues` — one GitHub issue per unfixed finding
  in `jyoung2000/TFG`, titled `[hermes] <area>: <one-line>`, body = the
  reproduction, root cause if known, and the review section it came from.
- `github-pr-workflow` — the PR from `review/hermes` into `hermes-review`
  with `docs/HERMES_REVIEW.md`, `docs/DEBUG_REPORT_hermes.md`, the updated
  `docs/RTX_4070_TEST_MATRIX.md` and your fix commits; do not merge.
- `superpowers-verification-before-completion` — before you call it done:
  every claim in the review maps to something you ran; every MEASURED row
  has numbers; every fix has a test; the gates are green on your branch;
  the "could not test" list says why for each item.
- `superpowers-finishing-a-development-branch` — leave the worktree
  clean, nothing uncommitted, PR link in your final message.

## Leave alone

Pinterest servers, `apple`, `email`, `smart-home`, `social-media`,
`meridian` / `meridian-gateway`, `ai-model-gateways`, media/download
skills: none of them are part of this audit. If a skill's advice conflicts
with `CLAUDE.md` in the repository (thin routes, handlers own logic,
services behind Protocols with fakes, no mocks, 12 GB constraint,
Windows-first, licence guard), the repository's rules win.
