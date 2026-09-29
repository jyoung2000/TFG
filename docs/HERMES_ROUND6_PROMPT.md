# Hermes round 6 — remake any image or video, 95–100 % identical, on any local model the RTX 4070 can run

**Model:** run this as **`stealth/space-bunny-alpha` through OpenRouter**, as a
single model. If your harness gives you "reference" responses from other
models, ignore them entirely: they are drafts, not tool output. **Only output
from a tool you ran in this turn is evidence.** Check state from disk once at
the start of a task and once before you commit it, and no more. Do not narrate
which references you rejected; do the work.

You work on this Windows 11 machine (RTX 4070 12 GB, 32 GB RAM, ~248 GB free
on `C:`) with shell access, in `C:\Users\jalon\TFG`, branch `latest`. Nobody
watches each step. The user wants every feature tested **as a real user
would**: through the real app window, not only the API.

```powershell
git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch origin
git checkout -B latest origin/latest      # the single working branch — no PRs
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line ok
```

Read first: `AGENTS.md` (especially **Shipping to the installed app**),
`docs/HERMES_INSTALLED_APP_PROMPT.md`, and rows F-062 … F-078 in
`docs/DEBUG_REPORT_hermes.md`.

## The goal

On this machine, **Reproduce image** and **Reproduce video** take a reference,
let the user choose **which AI reads it** and **which local model remakes it**,
and **keep looping until the remake is 95–100 % identical to the reference**.
This must work for **every local image and video model that fits the 4070**,
in the source app (`pnpm dev`) **and** in the installed **LTX Desktop WanGP**.

## State at the start (verified 2026-09-29 — re-check once, don't re-litigate)

- `origin/latest` is `32a2bfc`. `edc2172` makes the installed app find a
  WanGP checkout that has its own venv (via a junction
  `%LOCALAPPDATA%\LTXDesktop\Wan2GP` → `C:\Users\jalon\TFG\Wan2GP`).
- `32a2bfc`'s message ("render blocked by CPU-staged Qwen3 text encoder") is
  **wrong**: afterwards a Z-Image render completed (`job_0f434e88f89f`, 57 s,
  768×1360 JPEG), and the loop scored 0.6405 → 0.7066 → 0.7497 over three
  rounds. The `cudaErrorAlreadyMapped` failure came from a stale worker.
  Don't rewrite history; correct it in a new `DEBUG_REPORT` row.
- **Uncommitted:** `backend/tests/test_model_library_add.py` (a red test for
  adding models from Hugging Face and Ollama). Finish it or replace it.
- The installed app (1.0.2) was **hand-patched** to include `edc2172`. That
  does not survive an update. Ship properly (see *Ship*).
- Installed weights: Z-Image (image), LTX-2 22B distilled (video), Qwen3 text
  encoder. `Wan2GP/defaults/` lists ~233 model definitions, including
  `ti2v_2_2` (Wan 2.2 5B TI2V, not installed).
- Ollama has `qwen2.5vl:7b` (vision, ~6 GB when loaded) and other models;
  `POST /api/show` returns each model's `capabilities`
  (`qwen2.5vl:7b` → `completion, vision`).
- The loop's budget today is `candidates_per_round` / `max_rounds` /
  `target_score` (default target 0.9), and it stops at `max_rounds`.

## The 95–100 % bar (the user's requirement — read carefully)

- **Measure:** the loop's composite score (SSIM + DINO + CLIP + palette,
  already computed in `services/similarity/composite.py`). "95 % identical" =
  composite ≥ **0.95**. Report every component too, so a high composite can't
  hide a low SSIM. Add **per-frame** scoring for video (sample frames across
  the clip; report the mean and the worst frame).
- **The loop does not stop at a round count.** Default `target_score` = 0.95,
  and no `max_rounds` cap by default (keep the field so a user can set one).
  It stops only when: (a) the target is reached, (b) the user cancels, or
  (c) it has **genuinely plateaued**: no improvement ≥ 0.005 in the best score
  after every escalation step below has been tried. On (c) it stops, says
  plainly "target not reached: best X", keeps the best candidate, and never
  reports it as a success. An endless loop that cannot improve only burns the
  GPU.
- **Text prompts alone will not get there** (round 5 plateaued around 0.75).
  The loop must escalate, in this order, trying each before declaring a plateau:
  1. prompt refinement from the vision AI's diff of reference vs best candidate
     (what differs: pose, wardrobe, framing, background, colour);
  2. seed search around the best candidate;
  3. **reference conditioning**: image-to-image from the reference with a
     denoise strength that steps down toward the reference; reference/edit
     models (e.g. Qwen-Image-Edit, FLUX Kontext) if installed and they fit;
  4. for video: first-frame / end-frame conditioning from the reference clip,
     and control video (depth/pose) extracted from it (`controlVideoPath`,
     `depthVideoPath` already exist in the API);
  5. same aspect and resolution as the reference (never letterboxed/cropped).
- Record, per round, which strategy ran and the score it produced, so the
  report shows *what* got the score up.
- **Acceptance:** for at least one image model and one video model, a run that
  reaches ≥ 0.95 on the reference below (or, if no strategy can, the measured
  plateau with every strategy's best score, stated as not reached).

## Hard rules

- **Evidence.** Every number comes from a command you ran. Before quoting
  on-screen text, find it with `git grep`. Every GUI claim needs a screenshot
  (downscaled to ≤1600 px, JPEG q85).
- **Tests.** Every fix or feature gets a test that fails before it and passes
  after. `ServiceBundle` fakes, never `unittest.mock`. Never skip, weaken or
  delete a test. Run the full backend suite, `pnpm typecheck`,
  `pnpm test:frontend` and the relevant `pnpm e2e` specs before each push.
- **Architecture.** ADR 0005: `backend\.venv` and `Wan2GP\.venv` stay
  separate. Don't downgrade the backend's transformers. Keep
  `tests/test_licenses.py`. Never rebuild `Wan2GP\.venv`.
- **Downloads are allowed** for models that fit 12 GB, up to **150 GB in
  total** this round; log each one (name, source, size) and stop before the
  budget runs out. Never delete or re-download installed weights. Sources:
  Hugging Face and the Ollama library only.
- **The user's other apps.** Never install the normal flavour
  (`release\LTX Desktop-Setup.exe` is upstream's identity and replaces the
  user's LTX Desktop 1.2.7); after every install, confirm the upstream exe's
  SHA-256 is unchanged. Kill processes by exact name or path only — never a
  substring like `win-unpacked` (that killed the user's Hermes app before).
  Don't touch user data in `%LOCALAPPDATA%\LTXDesktop` except model folders.
- **Measurements.** Kill stale `wangp_worker.py` / `ltx2_server.py` first;
  run nothing heavy (tests, builds) during a render; take the idle
  `nvidia-smi` baseline just before each render; report History peak and your
  sampler peak, and `max − baseline`.
- **Builds** into a new output folder each time
  (`-c.directories.output=release-wangp-<new>`): rebuilding into an existing
  one fails with `EBUSY … app.asar` on this machine.
- **Never reboot. Never force-push.** Anything public (a GitHub release, an
  upload) needs the user's go-ahead in chat for that specific item.
- **Line endings:** keep each file's committed line endings; check
  `git diff --stat` for whole-file rewrites.

## Tasks, in order — one commit per task, pushed as you go

### 1. VRAM and loading (do this first; it blocks everything else)

- **Ollama vs the renderer.** The vision model (~6 GB) and a render can't
  share 12 GB; round-5 failures read `Free 3.0 GB of VRAM … 5.8 GB needed`.
  Before any render (Create, Reproduce, Film queue), the app must release the
  Ollama model (`keep_alive: 0`) and wait until the VRAM is actually free;
  `VramManager` already has an Ollama release path — find it and make every
  render path use it. The loop alternates analysis (VLM) and rendering, so it
  must sequence them, never overlap them.
- **Stale worker.** When a render fails with a CUDA-context error such as
  `cudaErrorAlreadyMapped`, restart the WanGP worker once and retry once;
  report the error if the retry fails. Never loop on it.
- **Loading is visible:** worker start and model load show progress in the UI.
- **Acceptance:** with `qwen2.5vl:7b` loaded, analyse a reference, then start
  the loop — the render must be admitted and complete. Report VRAM before and
  after the release.

### 2. "Analyse with" picker

Next to **Analyse** in Reproduce image and Reproduce video, a dropdown lists
the vision-capable models the app can reach: Ollama models whose
`/api/show` capabilities include `vision`, plus the configured director
provider. The choice is saved per job and used by Analyse and by the loop's
diff step; the header's `read by …` shows it. Text-only models are listed as
not image-capable, not hidden. Mock-backend e2e test plus a backend test.

### 3. Add models from Hugging Face and Ollama

Finish `backend/tests/test_model_library_add.py`: install a WanGP model from a
Hugging Face URL (through the checkout's own downloader; reject non-HF URLs
before anything runs), and pull an Ollama model by name with progress, from
Settings → AI Models. Show each model's size and whether it fits 12 GB before
downloading.

### 4. "Render with" — remake on any installed local model

Today every image candidate renders with Z-Image whatever tab is selected.
Add a **Render with** choice listing the installed **image** models (Reproduce
image) and **video** models (Reproduce video) that fit the 4070, and compile
the prompt for that model's dialect automatically. Models not installed or not
fitting say why. Keep **Analyse with**, **prompt written for** and **Render
with** visibly separate and labelled.

### 5. The 95 % loop

Implement *The 95–100 % bar* above: the default target, the stop conditions,
the escalation ladder with per-round strategy records, per-frame video
scoring, and UI that shows the current best score against the 0.95 target and
which strategy is running. Tests for each stop condition (reached, cancelled,
plateau after all strategies) with fakes.

### 6. Build the model matrix, then prove it

List every WanGP image and video model definition, its weights size, and
whether it fits 12 GB (measure; don't guess). Install the ones that fit
(within the budget), then for **each installed model**:

- **Reproduce image**: the reference
  `C:\Users\jalon\Downloads\295a64e37f4a4b7da81c0bec22df5668.jpeg`. Report per
  round: strategy, candidate file, decoded size, composite and its parts, and
  the best score so far; the final result against 0.95.
- **Reproduce video**: a 10 s clip with one cut → Detect → Analyse → Start →
  Pick → Stitch. Report `ffprobe` of every candidate and of the stitched file,
  and per-shot mean/worst-frame scores against 0.95.
- If a model fails, its error is the finding; move on to the next model.

The local scorer is the primary measure. You may add an **optional** second
opinion from a vision model through OpenRouter (the user's key, never logged):
same pair, a 0–10 similarity with reasons, reported next to the local score,
never instead of it.

### 7. Test every feature as a user

Drive the real Electron window (installed app and `pnpm dev`) through Home,
Create, Reproduce image, Reproduce video, Train, History, Film Studio, Assets
(with the New-asset wizard), Playground and Settings. For each screen: does it
work, is progress visible while work runs, are errors clear, does a degraded
feature say so. Screenshots in `docs/review-screenshots/round6/`.

### 8. Ship

- `pnpm wangp:ship` (or a fresh-folder build if `release-wangp` is locked).
  Verify: installed exe hash = build, upstream exe hash unchanged, installed
  app logs `WanGP mode: worker`. No hand-patching.
- To publish a release (e.g. `v1.0.3`) so the installed app auto-updates,
  **ask the user first.**

## Deliver

- `docs/DEBUG_REPORT_hermes.md`: rows from the next free F-number, including
  the correction to `32a2bfc`.
- `docs/HERMES_REVIEW.md`: a **Round 6** section with the model matrix, every
  render (wall time, History peak, sampler peak, baseline, `max − baseline`),
  every Reproduce run's score history against 0.95 and which strategies moved
  it, GUI grades, and "could not test, and why".
- `docs/RTX_4070_TEST_MATRIX.md`: rows you ran become `MEASURED <date>`.
- Push after every task; report the CI result; fix what your change broke.
- **If you run low on budget,** stop after the current task, commit, push,
  and write the Round 6 section for what you finished, listing the rest by
  number. A partial round with honest gaps beats a complete-looking one.
