# Hermes audit — round 2 (video on the RTX 4070)

One paste, self-contained. Round 1 (`docs/HERMES_REVIEW.md`, PR #2, audited
`64bb6a3`) proved the image path and found video unreachable. Everything it
blocked on has since been changed; this round measures whether video now
works on the real card and audits every commit it has not seen.

---

You are running **round 2** of the TFG audit on the same machine as round 1
(Windows 11, RTX 4070 12 GB). Snapshot:

**https://github.com/jyoung2000/TFG/tree/hermes-review**

Read first, in this order: `docs/HERMES_REVIEW.md` and
`docs/DEBUG_REPORT_hermes.md` (your own round-1 findings),
`docs/adr/0005-wangp-in-its-own-environment.md`, the newest sections of
`session-notes.md` (D-049 onward), then `docs/ONESHOT_AUDIT_PROMPT.md` — its
§0 (tools, known-broken MCP servers, terminal fallbacks), §2a (GUI sweep
method) and hard rules still apply unchanged. Where this prompt and that one
differ, this one wins.

Hard rules (same as round 1): never claim what you did not observe; numbers
come from History and an independent `nvidia-smi` sampler, never estimates;
a feature you could not test is listed with the reason; fixes only when a
test proves them red-then-green; do not soften findings.

## 1. What changed since you audited `64bb6a3`

| Commit | Change | What it claims |
|---|---|---|
| `f4508cb` | LoRA download from a Hugging Face / Civitai / direct `.safetensors` link (Train → LoRA registry) | History `download` job with MB progress and cancel; optional API key used once and stored nowhere; lands in the registry and compatible pickers |
| `99190d2` | Assets tab redesign + "New asset" wizard | consistency contract (REF/GUIDE/LORA/SEED) on every card; one seed image → style guide + 4-view reference sheet; editable style guide persists; reference delete removes the file |
| `ff96202` | Your findings 1–3 | VRAM guard defaults now 8 GB (+512 MB margin) for 12 GB-class models and **overridable** via the `vram_render_needs_mb` setting; a render with missing weights is refused (409 → Models tab) instead of silently downloading; Florence caption failures are loud (502 with the real reason) |
| `33771d9` / `8f3b834` | Your PR #2 merged, plus follow-ups | `server.fs.deny` restated Vite's defaults (your version dropped the `.env`/cert protection) and fixed directory globs; `agent:mcp` no longer needs `sh` |
| `db98b4a` | **WanGP in its own environment** (your "shared venv" root cause) | `Wan2GP\.venv` created by `scripts\ensure-wangp-venv.ps1`; the backend runs WanGP from it as a worker process over loopback HTTP; `uv sync` in `backend\` can no longer remove WanGP's packages |

## 2. Set up — prove the environment split first

Consent: the builder has approved **one** download of the LTX-2 distilled
checkpoint (~19.4 GB) for this round. Check free disk space first (the
checkpoint + the WanGP venv need roughly 40 GB); if there is not enough,
stop and report instead of deleting anything.

```powershell
git fetch origin; git checkout hermes-review; git pull
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line ok
pnpm setup:dev:win      # now also builds Wan2GP\.venv via scripts\ensure-wangp-venv.ps1
```

Record, with timings: whether `ensure-wangp-venv.ps1` succeeded on a clean
run, its final "WanGP import OK - torch … - CUDA available: True" line, and
the disk it used. Then prove the claim that matters most:

1. Start the app (`pnpm dev`). The backend log must say
   `WanGP mode: worker`. Note the worker's PID (`Get-Process python` —
   two Pythons: the backend and `wangp_worker.py`).
2. Render one image (U1's prompt) — it must still work.
3. Stop the app, run `cd backend; uv sync --extra dev --extra test; cd ..`,
   start the app again, render the same image. **Round 1's failure was a
   500 `No module named 'gradio'` at exactly this step.** It must not recur.
4. Kill the backend process (not the worker) — the worker must exit by
   itself within a few seconds. Kill only the worker during idle — the next
   render must restart it.
5. Run the six gates from round 1 and record them.

## 3. Video — the point of this round

1. **Explicit download.** Before downloading, try a video render: it must be
   refused with a message pointing at the Models tab and **must not** start
   a download (check the `Wan2GP\ckpts` folder and network activity). Then
   download the LTX-2 distilled model from the Models tab (Model Library →
   Local · WanGP models) and grade that experience: progress, speed, cancel,
   what happens if you cancel and restart.
2. **Measure the real need.** With nothing else loaded, record the idle
   `nvidia-smi` used MB (baseline), then render U2 (Fast, 540p · 6 s) cold
   and warm. For each: wall seconds, the History job's peak VRAM, your
   sampler's peak, and **peak − baseline** (what the render actually needs
   free). Look at the clip — is it coherent and prompt-faithful?
3. **Set the guard from the measurement.** If the measured need differs
   from the 8000 MB default by more than ~300 MB, set it:
   `POST /api/settings` with `{"vram_render_needs_mb": {"ltx2_22B_distilled": <need rounded up to 100>}}`
   (read back as `vramRenderNeedsMb` on `GET /api/settings`; the guard adds
   its own 512 MB margin). Re-render and confirm the guard neither refuses a
   render that fits nor admits one that OOMs. Commit the measured value as
   the new default in `backend\services\vram\vram_manager.py`
   (`RENDER_NEEDS_MB`) with the measurement in the comment and a test.
4. **Arbitration under pressure.** Load the Ollama VLM (or run an image
   analysis so Florence/CLIP are resident), then render a clip: the guard
   must free them first, or refuse with an actionable "Free X GB" message —
   never a CUDA OOM.
5. **Now run what round 1 could not:** U2, U3 (Balanced 720p · 8 s — if it
   cannot fit, the refusal must say so honestly), U4 (image-to-video with
   start + end frame + reference), U6 (Reproduce video end to end), and the
   render halves of U7 (3D storyboard → Deliver → render with the control
   video), U9 and U12 (Film Studio queue renders real clips). For U9 you no
   longer need to finish a training run: download a LoRA for Z-Image or
   LTX-2 from Hugging Face or Civitai (§4) and apply it through the
   Consistency Kit.
6. **The 4070 preset.** Round 1's "one ask": the preset promised "a clip in
   about a minute on a 4070" and Florence-2 captions. Using your
   measurements, either confirm the claims or change the preset copy
   (`backend\state\hardware_presets.py` and wherever the UI repeats it) to
   the measured truth.

## 4. Audit the new features (GUI first, then API/MCP cross-check)

- **LoRA download:** a Hugging Face `/blob/` link, a Civitai model page
  (`civitai.com/models/<id>`), a Civitai download link, a direct URL, a repo
  page (must be refused with guidance), a non-`.safetensors` link. A gated
  Civitai file with and without a key. Cancel mid-download (nothing left
  behind, including `.downloading\`). **Key hygiene:** after using a key,
  search `settings.json`, the History job JSON and the backend log for it —
  it must appear nowhere. Re-download the same file: one registry entry,
  not two.
- **Assets tab:** grid filters and badges against real assets; the wizard
  end to end on the real card (seed image → style guide → 4-view reference
  sheet — measure it); edit a trait/palette/prompt and confirm it survives
  an app restart; delete a reference and confirm the file is gone from
  `film_projects\<id>\references\`; the "what every shot inherits" preview
  versus the prompt a shot actually gets (open a shot and compare).
- **Render guard + weights check + loud captions:** the settings override
  (set, read back, `0` restores the default); caption a dataset while
  Florence is broken — expect a 502 carrying the real reason, and no
  fabricated trigger-only captions.
- **Florence-2 root cause** (your round-1 note: `Florence2Processor` needs
  `tokenizer.image_token`, absent in the locked transformers). Find the
  smallest correct fix — a transformers pin compatible with the rest of the
  lock, a processor/`trust_remote_code` change, or a different Florence
  checkpoint — and prove it with a real caption on the 4070. If it needs a
  dependency change you cannot prove safe for the rest of the backend, file
  it as a finding with the evidence instead.
- **WanGP worker:** besides §2, try to break it: start two renders at once
  (the second must get a clear "busy"/queue answer), cancel mid-render
  (the worker must stop WanGP, not just the UI), and read
  `backend\wangp_worker.py` + `backend\services\wangp_worker_bridge.py`
  as a reviewer — token handling, loopback binding, proxy bypass, orphan
  processes, Windows specifics.

## 5. Deliver

Branch `review/hermes-round2`, PR into `hermes-review` (do not merge):

1. `docs/HERMES_REVIEW.md` — **append** a "Round 2" section (keep round 1
   intact): environment-split proof, the video measurements table
   (U2/U3/U4/U6 and the render halves of U7/U9/U12: grade, verdict, cold/warm
   seconds, History peak, sampler peak, peak − baseline, notes), new-feature
   verdicts, what round-1 findings are now resolved / still open, and an
   updated "would you keep using it?".
2. `docs/review-screenshots/round2/` — every GUI claim's screenshot.
3. `docs/DEBUG_REPORT_hermes.md` — append findings from F-035 on, same
   columns as round 1.
4. `docs/RTX_4070_TEST_MATRIX.md` — rows you ran become MEASURED with
   numbers; the rest keep their reason.
5. Fixes on the branch, each with a red-then-green test, gates green.

Before you stop: every claim maps to something you ran; every MEASURED row
has numbers; nothing uncommitted; the "could not test" list gives a reason
for each item.
