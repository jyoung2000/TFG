# Hermes: debug, test and grade every feature of TFG

Paste everything below the line into Hermes Agent as the task. It needs
nothing else; the repository link is inside.

---

You are auditing **TFG**, a local AI image/video studio for an RTX 4070
(12 GB), from this snapshot:

**https://github.com/jyoung2000/TFG/tree/hermes-review**

TFG has: Create (images and clips on Z-Image / distilled LTX-2), Reproduce
(an image or a video → analysed by a local vision stack into an editable
ShotSpec → rendered, scored and refined until it matches), a 3D storyboard
with a shot composer and Deliver (control videos), Train (LoRAs from a
folder, a video or earlier results, with a Consistency Kit for film
characters), History (every job, live, with metrics), a Film Studio
(script → shots → queue → timeline), a container stack, a remote-backend
mode, tiered provider fallback, and an MCP server that exposes every API
route to you as a tool.

Your job has two halves, in this order:

1. **Test every feature the way a filmmaker or hobbyist would and grade it**
   like a demanding customer — what works, what is broken, what should be
   reworked in place, what should be redone with a different approach.
2. **Debug what you find**: reproduce, locate the root cause in the code,
   and, where you can prove the fix with a test, fix it on your branch.
   Anything you cannot prove stays a finding, not a fix.

Never claim something worked that you did not observe. If you cannot test
a feature, say so and why. Numbers come from History or `nvidia-smi`, never
estimates. Do not soften findings; the builder wants the truth.

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

Read `README.md` ("What do you want to make?", "Windows WanGP Quick Start"),
`docs/AGENTS_GUIDE.md`, `skills/tfg/SKILL.md`, `docs/TESTING.md`, and skim
`session-notes.md` (the builder's log: every `VF-` is a verified fact, every
`D-` a decision, and everything marked BLOCKED was never run on hardware —
those are your first leads).

Connect your MCP client (`~/.hermes/config.yaml`), then `hermes mcp test tfg`
(expect ~214 tools) and install the skill from the clone
(`hermes skills install <repo>\skills\tfg`; the GitHub shortcut reads the
repository's default branch, which does not carry this snapshot):

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

Launch the desktop app once too (`pnpm dev`): does the *RTX 4070 · 12 GB*
preset apply on first run, does Home load with zero console errors, is the
four-verb front door (Create · Reproduce · Train · History, Film Studio
advanced) understandable?

Run the gates before anything else and record the baseline:

```
pnpm typecheck:ts
backend\.venv\Scripts\pyright
pnpm test:frontend
backend\.venv\Scripts\python -m pytest -q tests
pnpm e2e
pnpm build:frontend
```

If any setup or gate step fails or is unclear, that is finding #1 — a
real user hits it before anything else.

## 2. Use every feature and grade it

Do each scenario as a user would. Record seconds and peak VRAM from History
(`jobs_get_job` → `metrics`) and `nvidia-smi`.

| # | Scenario | What a user expects |
|---|---|---|
| U1 | **Create an image**: "a rain-soaked neon alley, cinematic" (Z-Image, 8 steps) | a good still in < 30 s after warm-up; History shows it with prompt and seed |
| U2 | **Create a video, Fast**: same prompt, 540p · 6 s | a clip in about a minute; visible progress; cancel mid-render works and frees VRAM |
| U3 | **Create a video, Balanced**: 720p · 8 s | fits in 12 GB; visibly sharper; roughly 3× slower |
| U4 | **Image-to-video** from U1's still, with an end frame and one reference image | motion from the still; the end frame honoured |
| U5 | **Reproduce image**: three references (portrait, landscape, product shot) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | the evidence panel is believable; candidates improve round over round; the best resembles the reference; pin and the fix canvas do what they say |
| U6 | **Reproduce video**: a 10 s clip with one cut and a pan → Detect → Analyse → Start (2 candidates) → pick → stitch | both shots found; the pan appears in the spec; candidates match framing; stitched clip plays |
| U7 | **3D storyboard** from U6 → open a shot in the composer → move a figure, change the camera → Deliver → render | blockout thumbnails match the shots; the composer is usable with a mouse; the render follows the delivered camera/depth |
| U8 | **Train a LoRA**: 8–12 photos of one subject → auto-caption → Z-Image, character preset → train | captions carry the trigger; fits 12 GB; loss curve and samples update live; cancel then resume works; the LoRA appears in the registry |
| U9 | **Apply the LoRA** in U1 and in a Film character (Consistency Kit: bind, seed lock, reference sheet) | the subject is recognisable; the sheet is consistent across angles; a film shot inherits LoRA and trigger |
| U10 | **Video LoRA attempt**: Wan 2.2 or LTX-2 as the training target | refused *before* anything starts, with a reason that makes sense |
| U11 | **History**: run U2 with History open; re-run a job; delete one | live updates without refresh; lineage correct; delete removes what it says |
| U12 | **Film Studio**: new film → two characters, a location → three shots → queue previews → timeline | renders in order; pause/resume works; versions land on the shots |
| U13 | **Settings**: hardware preset card, video profile, fallback tiers, vision toggles, remote-backend card (test against your own backend URL) | every change persists after restart; the tiers editor explains why a tier is skipped |
| U14 | **Kill and relaunch**: kill the backend during U3, start it again | the job is marked failed with a clear message; nothing is stuck; the next render works |
| U15 | **Agent workflow**: do U1, U2, U5 and U8 purely through your MCP tools | sensible schemas and error text; long jobs followable via `jobs_*`; nothing needs the GUI |
| U16 | **Containers** (only with Docker + NVIDIA GPU): `deploy/` stack up, `/health`, desktop Remote backend switch | the documented steps work as written |

Then try to break it: empty prompts, a 1080p · 10 s render, a LoRA with 3
images, a video with no cuts, a dataset folder with a non-image file, paths
with spaces and unicode, two renders at once, closing the app mid-train.

For each scenario: **Grade** A–F (A finished · B rough edges · C needs
workarounds · D mostly broken · F unusable or misleading), **Verdict**
(Working / Broken / Needs rework / Should be redone), what happened (exact
steps, numbers, error text) versus what you expected, and user-experience
notes (discoverable? truthful copy? errors say what to do next? respects
the 12 GB card with refusals instead of crashes? would you wait that long
again?).

## 3. Debug what you found

For every Broken / Needs rework item, and for the code paths nobody has run
on hardware, go to the source:

- Trace the failure to a handler, service, component or script; note the
  file and line. Check the obvious classes of mistake this codebase can
  hide: contracts that drifted between `backend/**/*_models.py` /
  `api_types.py` / `state/app_settings.py`, `frontend/types/*.ts` and
  `devtools/ui-mock/**`; a lock held during a render, subprocess or HTTP
  call; a History job left without a terminal state on failure or cancel;
  a file-serving route that trusts a path; a VRAM check that runs after
  the model load instead of before; a `.ps1` missing beside a `.sh`;
  docs that describe intent rather than code.
- Verify the external facts the code depends on against the real
  installation, not memory: WanGP settings keys in `Wan2GP/wgp.py`
  (`activated_loras`, `loras_multipliers`, `image_refs`, `image_end`,
  `video_guide`, `video_prompt_type`), musubi-tuner / ai-toolkit command
  lines, the Wan 2.2 5B model key (deliberately not offered until verified).
- Fix only what you can prove: one commit per finding, a regression test
  with each (backend tests use `ServiceBundle` fakes, never `unittest.mock`;
  e2e specs run against `pnpm dev:ui`), all gates green before every push.
  Keep the architecture rules in `CLAUDE.md`, the 12 GB constraint,
  Windows-first paths and the licence guard (`tests/test_licenses.py`)
  intact. Never skip or weaken a test to get green.

## 4. Deliver

Commit on branch `review/hermes` and open a PR into `hermes-review` (do not
merge) containing:

1. `docs/HERMES_REVIEW.md` — the user review: setup experience; the U1–U16
   table (grade, verdict, seconds, peak VRAM, notes); break-it outcomes; a
   blunt "would you keep using it?"; the top 10 issues ranked by user pain,
   each with a one-line reproduction; features that oversell (claims in the
   UI, README or docs the software did not deliver); features that quietly
   work well; a rework list and a redo list with reasons; "could not test"
   with reasons; environment (GPU/driver, OS build, commit SHA, WanGP
   commit, Hermes version).
2. `docs/DEBUG_REPORT_hermes.md` — the debugging log: a table of ID · area ·
   severity (blocker / high / medium / low) · reproduction · root cause
   (file:line) · fix commit or "not fixed, because" · regression test ·
   status; then the facts you verified against the real installation
   (WanGP keys, trainer commands, model keys) and everything you could not
   verify.
3. `docs/RTX_4070_TEST_MATRIX.md` updated: every row you ran changes from
   BLOCKED — ENVIRONMENT to MEASURED <date> with the numbers; rows you did
   not run stay BLOCKED with the reason.

One review per run. Every claim tied to something you did.
