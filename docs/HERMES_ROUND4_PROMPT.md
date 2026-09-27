# Hermes audit — round 4 (verify round 3 on the RTX 4070)

One paste, self-contained. Round 3 (PR #4, branch `fix/hermes-round3`) fixed
the round-2 findings **off-hardware**, in a cloud container with no GPU,
Windows or desktop. It made no hardware claims. This round checks those fixes
on the real card and does the measurements round 3 deliberately left alone.

---

You are running **round 4** of the TFG audit on the same machine as rounds
1–2: Windows 11, RTX 4070 12 GB, repo at `C:\Users\jalon\TFG`.

```powershell
git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch origin
git checkout -B review/hermes-round4 origin/fix/hermes-round3
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line ok, incl. the refspec check
```

Read these first, in order:
1. `CLAUDE.md`.
2. The **Round 3** section at the end of `docs/HERMES_REVIEW.md`, and its "Needs the 4070" list.
3. Rows F-042..F-051 in `docs/DEBUG_REPORT_hermes.md`.
4. Your own round-2 **"A correction"** section. A previous agent put invented artifacts and VRAM figures in its write-up; do not repeat that.

**Don't rebuild these:** `Wan2GP\.venv` (torch 2.10.0+cu128) and the installed
checkpoints (LTX-2 22B distilled, 18.11 GB; Z-Image, 6.4 GB). `uv sync` in
`backend\` is safe to run.

## Hard rules

- **Report only what tool output showed you.** Every number comes from a command you ran, or from History.
- **Baseline per render.** Take the idle `nvidia-smi` baseline right before each render; the compositor drifts 1517–1972 MiB over a session. Report peak minus that baseline.
- **Clean slate before each measurement.** Kill stale `wangp_worker.py` and `ltx2_server.py` processes. Run nothing else heavy (pyright, pytest, pip) while a render is going.
- **Tests.**
  - Every fix gets a test that fails before it and passes after.
  - Use `ServiceBundle` fakes, never `unittest.mock`.
  - Never skip, weaken or delete a test.
- **Don't break the architecture.**
  - Keep ADR 0005: separate `backend\.venv` and `Wan2GP\.venv`; never merge them.
  - Don't downgrade the backend's transformers.
  - Keep `tests/test_licenses.py` intact.
- **When a render fails, the launcher error is the finding.** Round 3 made it carry the exit code, the deadline that applied, the last 12 lines of output, the stage markers and faulthandler stack dumps. Paste it verbatim.

## 1. F-038 — does a render get through the app now?

1. Start the app with `pnpm dev`. From the backend log, record:
   - The `WanGP mode: worker` line.
   - The worker's stage markers (`[wangp-worker +N.NNNs] …`), which show how long each startup stage took. Import time is the one to watch.
   - The line `orphan guard armed — serving`.
2. **If the worker does not start**, stop here. Paste the full launcher error. It now names the stage it stalled in, and after 120 s of stall it contains every thread's stack. That stack is the root cause round 2 could not find. Report it as F-052, with the stack verbatim.
3. **If it starts**, render these through the app:
   - **Image:** `POST /api/generate-image` with `{"prompt":"a rain-soaked neon alley, cinematic","width":1024,"height":1024,"numSteps":8}`.
   - **Video:** one Fast clip (540p · 6 s).

   For each render, record:
   - Wall time.
   - The History job id and its peak.
   - Your own `nvidia-smi` sampler's peak.
   - Peak minus a baseline taken immediately before the render.

   Look at each output yourself. Round 1 measured the image at 226.7 s cold, 8044 MB total. If yours differs a lot, report the difference; don't adjust anything to make it match.
4. Before you move on, run `diag_preready.py` (A/B/C) against the **pre-fix** worker at `8e759ff`, and record its verdict word for word. If the stdin-pipe hypothesis is ever to be confirmed or refuted, this is where it happens.

## 2. The worker under stress

1. **Two renders at once:** the second must get a clean 409.
2. **Cancel mid-render:** WanGP actually stops (GPU utilisation drops), no output file appears, and no orphan process is left.
3. **Kill the backend while a render is running:** the worker must exit by itself within seconds, via its stdin guard. Check `Get-Process python`.
4. **Kill only the worker while idle:** the next render must restart it and succeed.

## 3. Florence-2 — a real caption

Import an image and `POST /api/image-analysis/{id}/analyze`.

- **Pass:** `caption` is non-empty, and `description` and `subjects` are filled.
- Record which checkpoint loaded. The backend log says `loaded from the native-port conversion florence-community/…` when round 3's fallback was used.
- **If it fails:** the error should name **both** repos it tried. Record that as a finding. Don't guess a different checkpoint without evidence.

Also test the VLM route. Set Settings → Vision → VLM to `ollama` with `qwen2.5vl:7b` and run the analysis again. `vision_model` must name the VLM, not `local-stack`. Then set the VLM to `off` and confirm `vision_notes` says `VLM skipped: …` and not nothing.

## 4. The VRAM guard, from data

1. Measure **Fast and Balanced** video through the app. Take the baseline right before each render.
2. Set `vram_render_needs_mb` from the measured `peak − baseline`, rounded up with margin, via `POST /api/settings`. The guard adds its own 512 MB on top.
3. Show both of these:
   - A render that the old 8000 MB default refused now passes.
   - An oversized request still refuses.
4. Commit the measured defaults in `backend\services\vram\vram_manager.py` (`RENDER_NEEDS_MB`). Put the measurement and its date in the comment, and add a test.
5. If Balanced doesn't fit on 12 GB, the refusal message must say so plainly.

## 5. The real Electron app, by hand

Round 2 only tested the API. This time:

- Drive the actual window through a full sweep: Create (image + video), Reproduce, Train (including the LoRA-from-link download), Film Studio, the Assets tab and New-asset wizard, History, and Settings.
- Save screenshots to `docs/review-screenshots/round4/`.
- Grade what a user sees:
  - Progress while a render runs.
  - The copy, especially the Fast preset's new "~10 min cold, ~3 min warm" note: does the measured reality match it now?
  - Error messages, and whether degradation is visible.

## 6. Deliver

Commit on `review/hermes-round4` and open a PR into `hermes-review`. Don't merge it. It contains round 3's commits too, so it supersedes PR #4, the way PR #4 superseded PR #3.

- **`docs/HERMES_REVIEW.md`:** append a **Round 4** section. Don't touch rounds 1–3.
  - F-038 verdict, with evidence.
  - The measurement table: wall time, History peak, sampler peak, and peak − baseline for each render.
  - Stress results.
  - Florence verdict.
  - VRAM guard before and after.
  - GUI grades.
  - An updated "would you keep using it?".
- **`docs/DEBUG_REPORT_hermes.md`:** append rows from F-052 onward. Change the status of earlier rows only in new rows, by reference.
- **`docs/RTX_4070_TEST_MATRIX.md`:** rows you ran become `MEASURED <date>` with numbers. The rest keep their `BLOCKED` reason.
- **Fixes:** one commit each, each with a test that failed before it and passes after. The gates must be green on your branch.

Before you stop, check your own write-up:
- Every number traces to a tool output.
- Every GUI claim has a screenshot.
- Every "fixed" has a test.
- Nothing is uncommitted.
- Every "could not test" item says why.

If F-038 still blocks, say so. A documented blocker with the captured stack is a better deliverable than a guess.
