# Round 5 — the GPU work (Claude Code on the RTX 4070)

One paste, self-contained. Round 4 proved the core render path on the card.
After it, the cloud container fixed everything that needs no GPU (see
"Before you start"). This round does the work only the card can do, and
checks the off-hardware fixes on it.

---

You are running **round 5** of the TFG audit on the same machine as rounds
1–4: Windows 11, RTX 4070 12 GB, repo at `C:\Users\jalon\TFG`. You are Claude
Code with shell access. There is no human watching each step, so follow the
order below and stop where it says to.

```powershell
git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch origin
git checkout -B latest origin/latest      # the single working branch — no PRs
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line ok
```

Read these first, in order:
1. `CLAUDE.md`.
2. In `docs/HERMES_REVIEW.md`: the **Round 4** section, then **Round 4 follow-up**.
3. Rows F-052..F-058 in `docs/DEBUG_REPORT_hermes.md`, and the newest rows after them.
4. Round 2's **"A correction"** section and round 4's withdrawal of the F-054
   "34s–1m" quote. Both are about claims that did not survive a check. Don't
   repeat either.

**Don't rebuild these:** `Wan2GP\.venv` (torch 2.10.0+cu128) and the installed
checkpoints (LTX-2 22B distilled, 18.11 GB; Z-Image, 6.4 GB). `uv sync` in
`backend\` is safe to run.

## Before you start: what changed since round 4 (off-hardware)

All of these have tests and passed every local gate. None is checked on the card yet.

- **F-054, frozen progress bar.** The WanGP worker and the remote route now
  carry WanGP's own `current_step` / `total_steps` to the app. Before, the
  worker dropped them and the bar fell back to a 45 s guess that froze.
  Without step counts, the fallback now follows a curve that keeps rising and
  says "taking longer than usual" past its estimate
  (`frontend/lib/generation-progress.ts`).
- **F-056, `busy:false` during a render.** The backend's `/api/wangp/status`
  now reports the app's own local render as busy, with its History job id.
  A remote manifest submitted during a local render gets a 409.
- **F-053.** The `set_overrides` docstring now says `{}` through the settings
  API changes nothing, and that only `0` drops an override. A test pins it.
- **F-058, VRAM thresholds.** Now 5200 (video) / 5400 (image), set from
  `max(History peak, sampler peak) − baseline`. Round 4 had used the sampler
  alone.
- **CI** now runs on pushes to `latest`, including the Windows installer and
  Linux AppImage jobs.
- **Home copy** now quotes measured times.

## Hard rules

- **Report only what tool output showed you.** Every number comes from a command you ran, or from History.
- **Peaks.** Take the idle `nvidia-smi` baseline right before each render.
  Report **both** History's peak and your sampler's peak, and use
  `max(History, sampler) − baseline` for any threshold. Both read whole-GPU
  `used` at intervals, so the larger one is closer to the truth.
- **Clean slate before each measurement.** Kill stale `wangp_worker.py` and
  `ltx2_server.py`. Run nothing else heavy (pyright, pytest, pip, a build)
  while a render is going.
- **Text in screenshots.** Before you quote on-screen text as a finding, find
  that string in the source with `git grep`. A screenshot read that has no
  source match is not evidence.
- **Screenshots.** Downscale to at most 1600 px wide and save as JPEG quality
  85 or an optimised PNG **before** you commit them. Round 4 committed 20 MB of
  full-resolution PNGs.
- **Tests.**
  - Every fix gets a test that fails before it and passes after.
  - Use `ServiceBundle` fakes, never `unittest.mock`.
  - Never skip, weaken or delete a test.
- **Don't break the architecture.**
  - Keep ADR 0005: separate `backend\.venv` and `Wan2GP\.venv`; never merge them.
  - Don't downgrade the backend's transformers.
  - Keep `tests/test_licenses.py` intact.
- **Line endings.** Keep each file's existing line endings. Check with
  `git diff --stat` that an edit didn't turn into a whole-file rewrite.

## 1. Check the off-hardware fixes on the card (short; do this first)

Start the app with `pnpm dev`. Render one **Fast** clip (540p · 6 s) through
the Create view, and while it runs:

1. **F-054:** poll `GET /api/generation/progress` every few seconds. Record
   whether `currentStep` / `totalSteps` are non-null during the denoise
   phases, and whether the progress bar in the window keeps moving until the
   clip finishes. Take a screenshot mid-render.
2. **F-056:** poll `GET /api/wangp/status` on the backend. It must show
   `busy:true` and the History job id during the render, and `busy:false`
   after it.
3. **F-058:** record the peaks as described above. The render must be
   admitted under the 5200 / 5400 thresholds. If a measured
   `max − baseline` beats a threshold, raise that threshold (worst + ~11%),
   and extend `test_defaults_cover_every_round4_measured_peak` with the new
   number.

If any of the three fails, fix it now (red-then-green test), then carry on.

## 2. F-057 — the ~4× wall-time variance (highest value)

Round 4 ran the same Fast payload in 121 s, 174 s and 699 s. The slow run
averaged 20.6 % GPU utilisation, against 38–49 % for the others. The cause was
not found. A user would see this as "sometimes it hangs".

1. Run the same Fast payload **five times** back to back, with the app
   restarted between runs 3 and 4.
2. For every run, log once a second:
   - `nvidia-smi --query-gpu=utilization.gpu,memory.used,clocks.sm,power.draw,temperature.gpu,clocks_throttle_reasons.active --format=csv -l 1`.
   - System RAM in use and hard page faults/s:
     `Get-Counter '\Memory\Available MBytes','\Memory\Pages/sec'`.
   - Disk read MB/s of the drive that holds the checkpoints.
3. Test one hypothesis at a time and label it as one until the data proves
   it. The leading candidate: WanGP block-offloads the 18 GB checkpoint
   through system RAM, so when RAM is short it pages from disk and the GPU
   waits. Record the box's installed RAM and the free RAM before each run.
4. If one variable explains the slow runs, fix what the app controls. Examples:
   - A pre-render check that warns when free RAM is too low.
   - A WanGP profile or offload setting chosen from RAM, not only from VRAM.

   Add a test for the fix. If nothing explains the slow runs, report the logs
   and what they ruled out.

## 3. F-052 — the native `0xc000070a` crash on first cold start

1. Cold-start the app 10 times: reboot once, then kill every
   python/electron process between starts.
2. If it recurs, collect:
   - The Windows Event Log Application Error entry:
     `Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000} -MaxEvents 5 | Format-List`.
   - Any WER dump under `%LOCALAPPDATA%\CrashDumps`.
   - The launcher error, which carries the stage markers.
3. Report the faulting module and its offset verbatim. Don't guess a cause
   from the exception code alone.

## 4. The installer (P0 for any release)

1. Run `pnpm build:win`. It builds unsigned by default. Record the
   installer's size and SHA-256.
2. Install it in **Windows Sandbox** (or a clean VM if Sandbox isn't
   available; say which). Record:
   - Did the first run stage the Python runtime?
   - Does `/api/health` answer from the packaged backend?
   - Does Home load?
3. Render one image in the installed app. If the Sandbox can't reach the GPU,
   say so and render on the host install instead.
4. Uninstall. The install directory must be gone and user data left in place.
5. Record each step in `docs/RELEASE_CHECKLIST.md` §2 terms, and fill matrix
   row G1.

## 5. The blocked matrix rows

Render each row through the app, record it as `MEASURED <date>`, and keep going
if one fails. Its error is the finding.

- A4: I2V + LoRA.
- A5: end frame + refs.
- B2: Video Reproduce, 2 shots + stitch.
- B3: motion match.
- D2: LoRA smoke train.
- D3: apply the trained LoRA.
- E3: History live updates.

Skip these, and give the reason in the matrix:
- F1–F3 (Docker stack) unless Docker Desktop is healthy.
- F5, which needs a fal key.
- A6 (5B TI2V) unless the WanGP checkout lists the model.

## 6. The GUI screens round 4 did not sweep

Drive the real Electron window through Reproduce, Train, Film Studio, the
Assets tab with the New-asset wizard, and Settings. Screenshots go to
`docs/review-screenshots/round5/`, downscaled. Grade each screen on:
- Progress while work runs.
- Error messages.
- Whether a degraded feature says it is degraded.

## 7. Deliver

**No pull requests.** Commit directly on `latest` and `git push origin latest`
(pull first if the push is rejected; never force-push). CI now runs on every
push to `latest`. If you can read the run's result, report it; if a job fails
because of your change, fix it.

- **`docs/HERMES_REVIEW.md`:** append a **Round 5** section. Don't touch earlier rounds.
  - Results of §1.
  - The F-057 finding, with its logs summarised.
  - The F-052 result.
  - The installer walk-through.
  - A measurement table: wall time, History peak, sampler peak, baseline, and `max − baseline` for each render.
  - GUI grades.
  - An updated "would you keep using it?".
- **`docs/DEBUG_REPORT_hermes.md`:** append rows from the next free F-number.
  Change the status of earlier rows only in new rows, by reference.
- **`docs/RTX_4070_TEST_MATRIX.md`:** rows you ran become `MEASURED <date>` with numbers. The rest keep their `BLOCKED` reason.
- **Fixes:** one commit each, each with a test that failed before it and passes after.

Before you stop, check your own write-up:
- Every number traces to a tool output.
- Every quoted UI string has a source match.
- Every GUI claim has a screenshot.
- Every "fixed" has a test.
- Nothing is uncommitted.
- Every "could not test" item says why.

**If you run low on budget,** stop after the section you are in, commit, push,
and write the Round 5 section for what you finished. List the unfinished
sections by number. A partial round with honest gaps beats a complete-looking
one with guesses.
