# One-shot audit prompt (any capable agent model)

One paste, self-contained. Written for an agentic model with a terminal
(Hermes, or a stealth/preview model such as `stealth/space-bunny-alpha` on
OpenRouter): the tooling section is conditional, so it degrades cleanly to
plain terminal commands when the fancy tools are absent.

---

You are auditing **TFG**, a local AI image/video studio for an RTX 4070
(12 GB), from this snapshot — do the whole job in this one run:

**https://github.com/jyoung2000/TFG/tree/hermes-review**

TFG has: Create (images and clips on Z-Image / distilled LTX-2), Reproduce
(an image or a video → analysed by a local vision stack into an editable
ShotSpec → rendered, scored and refined until it matches), a 3D storyboard
with a shot composer and Deliver (control videos), Train (LoRAs from a
folder, a video or earlier results, with a Consistency Kit for film
characters), History (every job, live, with metrics), a Film Studio
(script → shots → queue → timeline), a container stack, a remote-backend
mode, tiered provider fallback, and an MCP server that exposes every API
route as a tool.

Your job, in order:

1. **Test every feature the way a filmmaker or hobbyist would and grade it**
   like a demanding customer — what works, what is broken, what should be
   reworked in place, what should be redone with a different approach.
2. **Debug what you find**: reproduce, locate the root cause in the code,
   and, where you can prove the fix with a test, fix it on your branch.
   Anything you cannot prove stays a finding, not a fix.

Hard rules for the whole run: never claim something worked that you did not
observe; if you cannot test a feature, say so and why; numbers come from
History or `nvidia-smi`, never estimates; do not soften findings — the
builder wants the truth, not encouragement.

## 0. Your tools (use what you have, skip what you don't)

Work in a terminal; everything below has a plain-terminal path. If you have
richer tools, map them like this and load each only at the step it serves:

- **MCP config / skill install** (Hermes: `hermes-mcp-config`,
  `hermes-skill-installation`): register the TFG MCP server from step 1 and
  install `<repo>/skills/tfg` from the local clone. No MCP client? Use the
  HTTP endpoint `POST http://127.0.0.1:8000/mcp` (JSON-RPC 2.0:
  `initialize`, `tools/list`, `tools/call`) or plain `curl` against the
  REST API — the tools are one-to-one with the API routes.
- **Persistent memory / notes** (a memory MCP, or just a file): append
  every finding to `docs/DEBUG_REPORT_notes.md` the moment you make it
  (id, area, reproduction, status) so a crash or context reset loses
  nothing; rebuild the final report from it.
- **Token/output discipline**: trim tool output (`| tail`,
  `| Select-Object -Last`), read files by range, write long results to
  disk instead of scrollback.
- **Desktop automation** (Hermes: `windows-mcp`; otherwise any OS-level
  automation you have): drive the Electron app like a user — click the four
  verbs, open Settings, run a Quick video — and screenshot for the review.
  Without it, judge the UI through `pnpm dev` manually described steps,
  the e2e suite, and the DevTools console; say in the report that the
  pixel-level experience was not exercised.
- **Browser automation** (a Playwright MCP or `pnpm e2e` directly): run and
  extend the Playwright specs against `pnpm dev:ui` (the mock backend —
  never claim GPU results from it).
- **Visual diffing** (an image-compare MCP, or ImageMagick
  `magick compare`/Python PIL): for Reproduce, put the best candidate next
  to the reference and record whether the app's composite score agrees with
  the visible match. A high score on a poor match is a finding.
- **Code navigation** (an LSP/symbols MCP such as serena, else
  `grep -rn` + your editor): for the contract-drift and lock-discipline
  sweeps, "who reads this field" questions.
- **Debuggers**: backend `pnpm dev:debug` exposes Python `debugpy` and the
  Electron inspector (`BACKEND_DEBUG=1`, `ELECTRON_DEBUG=1`); attach when
  a reproduction needs stepping, else add temporary logging and remove it.
- **Git**: terminal `git` only; work on branch `review/hermes` (a worktree
  if you can, so the snapshot checkout stays pristine for reproductions).
- **Known-broken or irrelevant tools** (for Hermes: the `git`, `headroom`,
  `pinterest-api`, `ponytail` MCP servers; Pinterest/apple/email/
  smart-home/social/meridian anything): do not touch them for this audit.
- Background skills about this very app (Hermes: `tfg-ltx-desktop`,
  `ltx-desktop-wangp`, `comfyui`) predate this snapshot: read for context,
  but when they disagree with the repository, **the repository wins** —
  `README.md`, `docs/*.md`, `CLAUDE.md` and the code are the truth.
- **GPU discipline**: one render or training run at a time (the app's queue
  assumes it). Parallelism is fine for reading code and docs, never for two
  GPU jobs — except once, deliberately, as the "two renders at once"
  break-it case.

## 1. Set up from the repository alone (Windows, RTX 4070)

```powershell
git clone https://github.com/jyoung2000/TFG.git
cd TFG
git checkout hermes-review
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line must say ok
corepack enable; corepack prepare pnpm@latest --activate                    # Node 18+
pnpm setup:dev:win        # deps, backend venv (uv), clones Wan2GP into .\Wan2GP
pnpm backend:dev:win      # headless backend: prints URL, data folder, WanGP root, MCP command
```

(Linux: `setup:dev:linux`, `backend:dev`, and the `.sh` twins of every
script.) Check prerequisites first — Node 18+, pnpm, `uv`, git, ffmpeg,
NVIDIA driver; a missing prerequisite is finding #1, not an excuse.

Read `README.md` ("What do you want to make?", "Windows WanGP Quick
Start"), `docs/AGENTS_GUIDE.md`, `skills/tfg/SKILL.md`, `docs/TESTING.md`,
and skim `session-notes.md` — the builder's log: every `VF-` is a verified
fact, every `D-` a decision, and everything marked **BLOCKED** was never
run on hardware. Those BLOCKED items are your first leads.

Register the MCP server (if you have an MCP client):

```yaml
mcp_servers:
  tfg:
    command: "<repo>\\backend\\.venv\\Scripts\\python.exe"
    args: ["<repo>\\backend\\tfg_mcp.py"]
    env:
      TFG_BACKEND_URL: "http://127.0.0.1:8000"
    tools:
      exclude: [system_shutdown]
```

Expect ~214 tools from `tools/list`.

Launch the desktop app once (`pnpm dev`): does the *RTX 4070 · 12 GB*
preset apply on first run, does Home load with zero console errors, is the
four-verb front door (Create · Reproduce · Train · History, Film Studio
advanced) understandable?

Run the gates and record the baseline before changing anything:

```
pnpm typecheck:ts
backend\.venv\Scripts\pyright
pnpm test:frontend
backend\.venv\Scripts\python -m pytest -q tests
pnpm e2e
pnpm build:frontend
```

If any setup or gate step fails or is unclear, that is finding #1 — a real
user hits it before anything else.

## 2. Use every feature and grade it

Do each scenario as a user would. Record seconds and peak VRAM from History
(`jobs_get_job` → `metrics`) and `nvidia-smi`.

| # | Scenario | What a user expects |
|---|---|---|
| U1 | **Create an image**: "a rain-soaked neon alley, cinematic" (Z-Image, 8 steps) | a good still in < 30 s after warm-up; History shows it with prompt and seed |
| U2 | **Create a video, Fast**: same prompt, 540p · 6 s | a clip in about a minute; visible progress; cancel mid-render works and frees VRAM |
| U3 | **Create a video, Balanced**: 720p · 8 s | fits in 12 GB; visibly sharper; roughly 3× slower |
| U4 | **Image-to-video** from U1's still, with an end frame and one reference image | motion from the still; the end frame honoured |
| U5 | **Reproduce image**: three references (portrait, landscape, product shot) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | the evidence panel is believable; candidates improve round over round; the best resembles the reference; pin and the fix canvas do what they say; verify the score against your own visual diff |
| U6 | **Reproduce video**: a 10 s clip with one cut and a pan → Detect → Analyse → Start (2 candidates) → pick → stitch | both shots found; the pan appears in the spec; candidates match framing; stitched clip plays |
| U7 | **3D storyboard** from U6 → open a shot in the composer → move a figure, change the camera → Deliver → render | blockout thumbnails match the shots; the composer is usable with a mouse; the render follows the delivered camera/depth |
| U8 | **Train a LoRA**: 8–12 photos of one subject → auto-caption → Z-Image, character preset → train | captions carry the trigger; fits 12 GB; loss curve and samples update live; cancel then resume works; the LoRA appears in the registry. Weights for musubi-tuner (Z-Image DiT/VAE/text encoder) come from Hugging Face — record exact repo ids and sizes |
| U9 | **Apply the LoRA** in U1 and in a Film character (Consistency Kit: bind, seed lock, reference sheet) | the subject is recognisable; the sheet is consistent across angles; a film shot inherits LoRA and trigger |
| U10 | **Video LoRA attempt**: Wan 2.2 or LTX-2 as the training target | refused *before* anything starts, with a reason that makes sense |
| U11 | **History**: run U2 with History open; re-run a job; delete one | live updates without refresh; lineage correct; delete removes what it says |
| U12 | **Film Studio**: new film → two characters, a location → three shots → queue previews → timeline | renders in order; pause/resume works; versions land on the shots |
| U13 | **Settings**: hardware preset card, video profile, fallback tiers, vision toggles, remote-backend card (test against your own backend URL) | every change persists after restart; the tiers editor explains why a tier is skipped |
| U14 | **Kill and relaunch**: kill the backend during U3, start it again | the job is marked failed with a clear message; nothing is stuck; the next render works |
| U15 | **Agent workflow**: do U1, U2, U5 and U8 purely through the MCP tools (or `/mcp` over HTTP) | sensible schemas and error text; long jobs followable via `jobs_*`; nothing needs the GUI. Also call every tool at least once with valid and invalid arguments; log every 500 and every response that does not match its schema |
| U16 | **Containers** (only with Docker + NVIDIA GPU): `deploy/` stack up, `/health`, desktop Remote backend switch | the documented steps work as written |

Then try to break it: empty prompts, a 1080p · 10 s render, a LoRA with 3
images, a video with no cuts, a dataset folder with a non-image file, paths
with spaces and unicode, two renders at once, closing the app mid-train.

Judge the UI while you go with a user's eye: discoverability, copy that
tells the truth, error text that says what to do next, layout at 1366×768
and at 4K scaling, refusals-not-crashes on the 12 GB card.

For each scenario: **Grade** A–F (A finished · B rough edges · C needs
workarounds · D mostly broken · F unusable or misleading), **Verdict**
(Working / Broken / Needs rework / Should be redone — rework = fixable in
place, redone = the approach is wrong), what happened (exact steps,
numbers, error text) versus what you expected, and the user-experience
notes above.

## 3. Debug what you found

For every Broken / Needs rework item, and for the BLOCKED code paths
nobody has run on hardware, go to the source:

- Trace the failure to a handler, service, component or script; note
  file:line. Check the classes of mistake a long autonomous build hides:
  contracts drifted between `backend/**/*_models.py` / `api_types.py` /
  `state/app_settings.py`, `frontend/types/*.ts` and `devtools/ui-mock/**`;
  a lock held during a render, subprocess or HTTP call; a History job left
  without a terminal state on failure or cancel; a file-serving route that
  trusts a path (try `..`, absolute paths, drive letters); an upload
  without a size cap; a VRAM check that runs after the model load instead
  of before; a `.ps1` missing beside a `.sh`; docs that describe intent
  rather than code (check every command, path and env var in `README.md`,
  `docs/**`, `deploy/**`, `skills/tfg/SKILL.md` against reality).
- Verify the external facts the code depends on against the real
  installation, not memory: WanGP settings keys in `Wan2GP/wgp.py`
  (`activated_loras`, `loras_multipliers`, `image_refs`, `image_end`,
  `video_guide`, `video_prompt_type`), musubi-tuner / ai-toolkit command
  lines, the Wan 2.2 5B model key (deliberately not offered until
  verified — check whether the checkout has one).
- Reproduce first, bisect, root-cause, then fix — never patch a symptom.
  Fix only what you can prove: one commit per finding, a regression test
  with each (backend integration tests use `ServiceBundle` fakes, never
  `unittest.mock` — a test enforces this; UI regressions get Playwright
  specs against `pnpm dev:ui`), all gates green before every push. Keep
  the architecture rules in `CLAUDE.md`, the 12 GB constraint,
  Windows-first paths and the licence guard (`tests/test_licenses.py`)
  intact. Never skip or weaken a test to get green. Simplify only code you
  already changed.

## 4. Deliver

Commit on branch `review/hermes` and open a PR into `hermes-review` (do
not merge). If you cannot open a PR, push the branch and print its name
and the compare URL. The PR contains:

1. `docs/HERMES_REVIEW.md` — the user review: setup experience; the U1–U16
   table (grade, verdict, seconds, peak VRAM, notes); break-it outcomes; a
   blunt "would you keep using it?" paragraph; the top 10 issues ranked by
   user pain, each with a one-line reproduction; features that oversell
   (claims in the UI, README or docs the software did not deliver);
   features that quietly work well; a rework list and a redo list with
   reasons; "could not test" with reasons; environment (GPU/driver, OS
   build, commit SHA, WanGP commit, your model/agent name and version).
2. `docs/DEBUG_REPORT_hermes.md` — the debugging log: a table of ID ·
   area · severity (blocker / high / medium / low) · reproduction · root
   cause (file:line) · fix commit or "not fixed, because" · regression
   test · status; then the external facts you verified against the real
   installation (WanGP keys, trainer commands, model keys, Hugging Face
   repo ids) and everything you could not verify.
3. `docs/RTX_4070_TEST_MATRIX.md` updated: every row you ran changes from
   BLOCKED — ENVIRONMENT to MEASURED <date> with the numbers; rows you did
   not run stay BLOCKED with the reason.
4. Optionally, one GitHub issue per unfixed blocker/high finding in
   `jyoung2000/TFG`, titled `[audit] <area>: <one-line>`, body = the
   reproduction and root cause if known.

Before you stop, verify your own completion: every claim in the review
maps to something you ran; every MEASURED row has numbers; every fix has a
test; the gates are green on your branch; nothing uncommitted; the
"could not test" list gives a reason for each item. One review per run.
