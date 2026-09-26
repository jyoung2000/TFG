# One-shot audit prompt (any capable agent model)

One paste, self-contained. Written for an agentic model with a terminal and
desktop control (Hermes with `windows-mcp`, or a preview model such as
`stealth/space-bunny-alpha` on OpenRouter run inside a harness): the tooling
section is conditional, so it degrades to plain terminal commands when a
tool is absent — except the GUI, which must be tested for real whenever
desktop control exists.

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

1. **Open the real desktop app and test every feature through its GUI,
   extensively**, the way a filmmaker or hobbyist would — clicking, typing,
   dragging, waiting — and grade it like a demanding customer: what works,
   what is broken, what should be reworked in place, what should be redone
   with a different approach. The GUI is the primary test surface;
   the API/MCP is the cross-check, not the substitute.
2. **Debug what you find**: reproduce, locate the root cause in the code,
   and, where you can prove the fix with a test, fix it on your branch.
   Anything you cannot prove stays a finding, not a fix.

Hard rules for the whole run: never claim something worked that you did not
observe; if you cannot test a feature, say so and why; numbers come from
History or `nvidia-smi`, never estimates; do not soften findings — the
builder wants the truth, not encouragement.

## 0. Your tools (use what you have, skip what you don't)

Work in a terminal; everything below has a plain-terminal path **except
GUI testing** — if you have desktop control, using it is mandatory.

- **Desktop control** (Hermes: `windows-mcp`; else any OS-level automation
  or computer-use tools): this is how you run section 2. Launch the app,
  screenshot every view into `docs/review-screenshots/` (named
  `<scenario>-<step>.png`), click/type/drag like a person, read dialogs and
  toasts, notice what a screenshot notices (clipped text, dead buttons,
  spinners that never stop). Only if you truly have no desktop control may
  you fall back to the API plus the browser UI (`pnpm dev:ui`), and then
  the report must say in bold that the real desktop GUI was not exercised.
- **MCP config / skill install** (Hermes: `hermes-mcp-config`,
  `hermes-skill-installation`): register the TFG MCP server from step 1 and
  install `<repo>/skills/tfg` from the local clone. No MCP client? Use
  `POST http://127.0.0.1:8000/mcp` (JSON-RPC 2.0: `initialize`,
  `tools/list`, `tools/call`) or `curl` against the REST API.
- **Persistent memory / notes** (a memory MCP, or just a file): append
  every finding to `docs/DEBUG_REPORT_notes.md` the moment you make it
  (id, area, reproduction, status) so a crash or context reset loses
  nothing; rebuild the final report from it.
- **Token/output discipline**: trim tool output (`| tail`,
  `| Select-Object -Last`), read files by range, write long results to disk.
- **Browser automation** (a Playwright MCP or `pnpm e2e`): run and extend
  the Playwright specs against `pnpm dev:ui` (the mock backend — never
  claim GPU or desktop results from it).
- **Visual diffing** (an image-compare MCP such as imugi, or ImageMagick
  `magick compare` / Python PIL): for Reproduce, put the best candidate
  next to the reference and record whether the app's composite score
  agrees with the visible match. A high score on a poor match is a finding.
- **Code navigation** (an LSP/symbols MCP such as serena, else `grep -rn`):
  for the contract-drift and lock-discipline sweeps.
- **Debuggers**: `pnpm dev:debug` exposes Python `debugpy` and the Electron
  inspector; attach when a reproduction needs stepping.
- **Git**: terminal `git` only; work on branch `review/hermes` (a worktree
  if you can, so the snapshot checkout stays pristine).
- **Known-broken or irrelevant tools** (for Hermes: the `git`, `headroom`,
  `pinterest-api`, `ponytail` MCP servers; Pinterest/apple/email/
  smart-home/social/meridian anything): do not touch them for this audit.
- Background skills about this very app (Hermes: `tfg-ltx-desktop`,
  `ltx-desktop-wangp`, `comfyui`) predate this snapshot: read for context,
  but when they disagree with the repository, **the repository wins**.
- **GPU discipline**: one render or training run at a time. Parallelism is
  fine for reading code, never for two GPU jobs — except once,
  deliberately, as the "two renders at once" break-it case.

## 1. Set up from the repository alone (Windows, RTX 4070)

```powershell
git clone https://github.com/jyoung2000/TFG.git
cd TFG
git checkout hermes-review
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line must say ok
corepack enable; corepack prepare pnpm@latest --activate                    # Node 18+
pnpm setup:dev:win        # deps, backend venv (uv), clones Wan2GP into .\Wan2GP
```

(Linux: `setup:dev:linux` and the `.sh` twins.) Check prerequisites first —
Node 18+, pnpm, `uv`, git, ffmpeg, NVIDIA driver; a missing prerequisite is
finding #1, not an excuse.

Read `README.md` ("What do you want to make?", "Windows WanGP Quick
Start"), `docs/AGENTS_GUIDE.md`, `skills/tfg/SKILL.md`, `docs/TESTING.md`,
and skim `session-notes.md` — the builder's log: every `VF-` is a verified
fact, every `D-` a decision, and everything marked **BLOCKED** was never
run on hardware. Those BLOCKED items are your first leads.

Start the app for GUI testing with `pnpm dev` (Electron + backend). For
API/MCP work you can also run the backend headless with
`pnpm backend:dev:win` — but the app you grade is the Electron one.
Register the MCP server if you have an MCP client (expect ~214 tools):

```yaml
mcp_servers:
  tfg:
    command: "<repo>\\backend\\.venv\\Scripts\\python.exe"
    args: ["<repo>\\backend\\tfg_mcp.py"]
    env:
      TFG_BACKEND_URL: "http://127.0.0.1:8000"
    tools:
      exclude: [health_shutdown]
```

Run the gates and record the baseline before changing anything:

```
pnpm typecheck:ts
backend\.venv\Scripts\pyright
pnpm test:frontend
backend\.venv\Scripts\python -m pytest -q tests
pnpm e2e
pnpm build:frontend
```

If any setup or gate step fails or is unclear, that is finding #1.

## 2. Test the GUI, extensively

**Everything in this section happens in the running Electron app, with your
desktop-control tool, screenshotting as you go.** Keep the DevTools console
open the whole time (`pnpm dev` allows it): any console error or React
warning during any step is a finding with the step attached.

### 2a. GUI sweep — every screen, every control

Before the scenarios, walk the whole surface once and screenshot each view:

- **First run**: delete the app-data folder, launch fresh. Does the
  *RTX 4070 · 12 GB* preset apply itself? Any setup wizard steps — are they
  comprehensible without reading docs?
- **Home**: the four verbs (Create · Reproduce · Train · History), Film
  Studio (advanced), sidebar, project cards (create, rename, delete), the
  getting-started panel and its dismiss. Click every verb and come back.
- **Keyboard shortcuts**: Alt+1…5 from several views; Ctrl+/ opens the
  shortcuts editor; typing in a text field must NOT trigger them; the
  Video Editor's own keys still work.
- **Quick video (Create)**: prompt box, negative prompt, Fast/Balanced
  profile select, duration/aspect/fps controls, the LoRA picker, the
  reference-image drop zone (drag a file onto it), Generate, live progress,
  cancel, the result actions (again / save to project / editor / film).
- **Reproduce image**: import button and drag-drop, the recent list,
  Analyse, every spec block (edit one, lock one), the evidence panel
  ("Why"), prompt style/target switches, budget fields, Start loop, live
  rounds, candidate grid (click each), pin, the fix canvas (draw, commit),
  cancel, delete an item.
- **Reproduce video**: import, shot detection list, split/merge a shot,
  Analyse, per-shot specs, "Build 3D storyboard", Start, per-shot candidate
  strips, pick, redo, Stitch, play the result inside the app.
- **Train**: new dataset, all import paths from the GUI (folder picker,
  images picker, video + fps field, "From History" picker, analysis
  frames), the caption grid (edit a caption, remove an image),
  auto-caption, preset/target/trigger fields, the config editor and its
  VRAM estimate, the wan22/ltx2 refusal message, Start, the live run view
  (loss sparkline, samples, ETA, step counter), Cancel, Resume, the run's
  "Open in History", the LoRA registry (rename, trigger, strength, import
  a .safetensors via the picker, delete).
- **History**: filters (kind/status/search), live card updates during a
  render, the drawer (outputs lightbox, params, metrics incl. loss curve
  and consistency, lineage, children), re-run, cancel, delete with files.
- **Film Studio**: create a film, script tab, assets tab (create character/
  location/prop, add reference image via picker, generate reference, the
  Consistency Kit row — bind LoRA, trigger, strength, seed lock, reference
  sheet button), storyboard (create scenes/shots, reorder, shot drawer,
  Compose Shot → the 3D composer: orbit, move a figure, camera keyframes,
  move library, underlay, undo/redo, Deliver), generate preview/final,
  the queue panel (pause/resume/cancel/prioritize), timeline tab, export.
- **Playground and Video Editor**: open them, run one action each, check
  the editor's transport and shortcut keys.
- **Settings, every tab**: General (hardware preset card apply/re-apply,
  remote backend card test), AI Models (provider cards, media provider
  buttons, fallback-tier editor add/remove), Vision (toggles persist,
  unload), API Keys (save/clear a dummy key — it must never echo back),
  Inference, Prompt Enhancer, Knowledge, Shot Library, About.
- **Resize and scaling**: run the main views at 1366×768 and at 200 %
  Windows scaling; screenshot anything clipped, overlapping or unreachable.
- **Window behaviors**: minimize/restore during a render, close the window
  during a training run (what happens to the job?), relaunch.

Log every dead control, mislabeled button, lying tooltip, spinner that
never resolves, and view that needed code-reading to understand.

### 2b. Scenarios — through the GUI, graded

Do each scenario **by driving the GUI** (except U15, which is MCP by
design). Record seconds and peak VRAM from History (drawer → metrics) and
`nvidia-smi`, plus at least one screenshot per scenario.

| # | Scenario | What a user expects |
|---|---|---|
| U1 | **Create an image**: "a rain-soaked neon alley, cinematic" (Z-Image, 8 steps) | a good still in < 30 s after warm-up; History shows it with prompt and seed |
| U2 | **Create a video, Fast**: same prompt, 540p · 6 s | a clip in about a minute; visible progress; cancel mid-render works and frees VRAM |
| U3 | **Create a video, Balanced**: 720p · 8 s | fits in 12 GB; visibly sharper; roughly 3× slower |
| U4 | **Image-to-video** from U1's still, with an end frame and one reference image | motion from the still; the end frame honoured |
| U5 | **Reproduce image**: three references (portrait, landscape, product shot) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | believable evidence panel; candidates improve; the best resembles the reference (verify with your own visual diff); pin and fix canvas work |
| U6 | **Reproduce video**: a 10 s clip with one cut and a pan → Detect → Analyse → Start (2 candidates) → pick → stitch | both shots found; the pan appears in the spec; candidates match framing; stitched clip plays in-app |
| U7 | **3D storyboard** from U6 → composer → move a figure, change camera → Deliver → render | blockout thumbs match; composer usable with a mouse; render follows the delivered camera/depth |
| U8 | **Train a LoRA**: 8–12 photos of one subject → auto-caption → Z-Image, character preset → train | captions carry the trigger; fits 12 GB; loss curve + samples live; cancel then resume works; LoRA in registry. Record the Hugging Face repo ids and sizes of the weights musubi-tuner needed |
| U9 | **Apply the LoRA** in U1 and on a Film character (Consistency Kit: bind, seed lock, reference sheet) | subject recognisable; sheet consistent across angles; a film shot inherits LoRA + trigger |
| U10 | **Video LoRA attempt**: Wan 2.2 or LTX-2 target | refused in the GUI *before* anything starts, with a reason that makes sense |
| U11 | **History**: run U2 with History open; re-run a job; delete one | live updates without refresh; lineage correct; delete removes what it says |
| U12 | **Film Studio**: new film → two characters, a location → three shots → queue previews → timeline | renders in order; pause/resume works; versions land on the shots |
| U13 | **Settings**: change preset, profile, tiers, vision toggles, remote-backend probe; restart the app | every change persists; the tiers editor explains why a tier is skipped |
| U14 | **Kill and relaunch**: kill the backend during U3, watch the GUI, relaunch | the GUI reports the failure clearly (no infinite spinner); nothing stuck; next render works |
| U15 | **Agent workflow (MCP only)**: repeat U1, U2, U5, U8 purely through the MCP tools; also call every tool once with valid and invalid args | sensible schemas and error text; long jobs followable via `jobs_*`; results match what the GUI showed |
| U16 | **Containers** (only with Docker + NVIDIA GPU): `deploy/` stack up, `/health`, the desktop's Remote backend switch | the documented steps work as written |

Then try to break the GUI: empty prompts, a 1080p · 10 s render, a LoRA
with 3 images, a video with no cuts, a dataset folder with a non-image
file, paths with spaces and unicode, double-clicking Generate, two renders
queued at once, mashing cancel, closing the app mid-train, unplugging the
mock inputs mid-flow.

For each scenario: **Grade** A–F (A finished · B rough edges · C needs
workarounds · D mostly broken · F unusable or misleading), **Verdict**
(Working / Broken / Needs rework / Should be redone — rework = fixable in
place, redone = the approach is wrong), what happened (exact steps,
numbers, error text, screenshot names) versus what you expected, and
user-experience notes: discoverable? copy tells the truth? errors say what
to do next? refusals-not-crashes on the 12 GB card? would you wait that
long again?

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
  without a size cap; a VRAM check that runs after the model load; a `.ps1`
  missing beside a `.sh`; docs that describe intent rather than code
  (check every command, path and env var in `README.md`, `docs/**`,
  `deploy/**`, `skills/tfg/SKILL.md` against reality).
- Verify the external facts against the real installation, not memory:
  WanGP settings keys in `Wan2GP/wgp.py` (`activated_loras`,
  `loras_multipliers`, `image_refs`, `image_end`, `video_guide`,
  `video_prompt_type`), musubi-tuner / ai-toolkit command lines, the
  Wan 2.2 5B model key (deliberately not offered until verified — check
  whether the checkout has one).
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

1. `docs/HERMES_REVIEW.md` — the user review: setup experience; the GUI
   sweep findings (per view, with screenshot names); the U1–U16 table
   (grade, verdict, seconds, peak VRAM, screenshots, notes); break-it
   outcomes; a blunt "would you keep using it?" paragraph; the top 10
   issues ranked by user pain, each with a one-line reproduction; features
   that oversell; features that quietly work well; a rework list and a
   redo list with reasons; "could not test" with reasons; environment
   (GPU/driver, OS build, commit SHA, WanGP commit, your model/agent name).
2. `docs/review-screenshots/` — the screenshots referenced above.
3. `docs/DEBUG_REPORT_hermes.md` — the debugging log: ID · area · severity
   (blocker / high / medium / low) · reproduction · root cause (file:line) ·
   fix commit or "not fixed, because" · regression test · status; then the
   external facts you verified (WanGP keys, trainer commands, model keys,
   Hugging Face repo ids) and everything you could not verify.
4. `docs/RTX_4070_TEST_MATRIX.md` updated: rows you ran become
   MEASURED <date> with numbers; rows you did not run stay BLOCKED with
   the reason.
5. Optionally, one GitHub issue per unfixed blocker/high finding in
   `jyoung2000/TFG`, titled `[audit] <area>: <one-line>`.

Before you stop, verify your own completion: every claim maps to something
you ran; every GUI claim has a screenshot; every MEASURED row has numbers;
every fix has a test; the gates are green on your branch; nothing
uncommitted; the "could not test" list gives a reason for each item. One
review per run.
