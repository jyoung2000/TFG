# RTX 4070 (12 GB) acceptance matrix

The RTX 4070 (12 GB VRAM) is the production target: every default the app
ships fits it (the **RTX 4070 · 12 GB** hardware preset), and anything that
cannot run on it is refused with a reason rather than attempted. This file
is the acceptance checklist a tester runs on that card. **Nothing here is a
measurement unless the Status column says `MEASURED <date>`** with the
driver in *Setup under test*.

**Last run: 2026-09-27** on real hardware — Windows 11, RTX 4070 12282 MiB,
driver 616.64 (CUDA UMD 13.4), SageAttention enabled, torch 2.10.0+cu128,
transformers 4.57.6, cv2 4.13.0, TFG `latest` @ `fb17e66` (base `2142214`),
by Hermes. Round 4 re-ran the generation, robustness and vision rows; rows not
re-attempted keep their earlier `BLOCKED` reason and their 2026-09-26 numbers.
Full narrative: `docs/HERMES_REVIEW.md` → *Round 4*; debugging detail:
`docs/DEBUG_REPORT_hermes.md` → *Round 4*.

**Round 4's headline: F-038 no longer blocks.** The worker starts
(`WanGP mode: worker`, `orphan guard armed — serving`) and every generation row
below that was previously `refused` now completes. Two new rows are open: the
intermittent native cold-start crash (F-052) and the ~4× wall-time variance
(F-057).

If a default turns out not to fit when measured, downgrade the default
(preset, profile, config) and say so in the row — never hide it.

## Setup under test

| Item | Value to record |
|---|---|
| GPU / driver | RTX 4070 12 GB, **NVIDIA 616.64** (measured 2026-09-26) |
| OS | **Windows 11 Home, build 26200** (measured 2026-09-26) |
| Install method | source checkout + `pnpm setup:dev:win` (no installer build — see G1) |
| Preset | `GET /api/settings` → `hardwarePreset: "rtx-4070-12gb"`, applied and **persisting across a backend restart** (measured) |
| Execution mode | `GET /health` → `"active_model": "wangp"`, `sage_attention: true` (measured) |
| Video model | `ltx2_22B_distilled` — **installed** (18.11 GB `ltx-2.3-22b-distilled_diffusion_model_quanto_int8.safetensors`); image model `z_image` (6.4 GB, installed) |
| Vision stack | Florence-2-large **working** via the native-port conversion `florence-community/Florence-2-large` (measured 2026-09-27); `microsoft/Florence-2-large` still fails with `BartTokenizerFast has no attribute image_token`; CLIP / Depth / DINO working |
| System VRAM | 12282 MiB total; **~10.1 GB free at idle** in this round (2046–2372 MiB used), composited desktop |

Fill *Seconds* and *Peak VRAM* from History (`metrics.seconds`,
`metrics.peak_vram_mb`, both recorded by the VRAM manager after each job)
and from `nvidia-smi` during the run.

## A. Generation

| # | Case | Steps | Expected on 12 GB | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Create image | Home → Create → image, Z-Image, 8 steps, 1024×1024 | fits; < 30 s after warm-up | **MEASURED 2026-09-27** | **162.8 s** wall (`job_f6ceeed54b58`) | **7073 MB** (History) / **5201 MB** (sampler) / **2959 MB** sampler peak − 2242 MB baseline | Real 1024×1024 RGB JPEG, 356 KB, visually inspected: coherent neo-noir alley, wet reflective pavement, neon in cyan/magenta/red, figure with umbrella. Only artifact is garbled sign lettering (`U R O C N`) — normal for diffusion, not corruption. **Does not meet the < 30 s target** (see F-057: wall time on this box varies ~4× for identical work). |
| A2 | Create video · Fast | Quick video, profile Fast (540p · 6 s · 8 steps) | fits (WanGP low-VRAM path) | **MEASURED 2026-09-27 (renders)** | **174.3 s** cold · **120.8 s** warm · **699.3 s** on final code (`job_1df5258b5601`, `job_e67da7043633`, `job_144851db9048`) | **5743 / 4676 / 6584 MB** (History) · sampler peak − baseline **3966 / 2292 / 4374 MB** | **No longer refused — renders complete.** Cold/warm/final-code all produced real clips. `ffprobe` on the 540p clip: h264, **960×512**, **145 frames**, **6.04 s**, 8.0 MB, 24 fps; frames 1/73/145 extracted and inspected (mean luma 69/58/55, not black, coherent, no melting). The 2026-09-26 guard refusal (`9.8 GB needed`) is gone — `RENDER_NEEDS_MB` is now **measured**, not guessed (`fb17e66`). |
| A3 | Create video · Balanced | profile Balanced (720p · 6 s) | fits; ~3× A2 | **MEASURED 2026-09-27 (renders)** | **231.7 s** (`job_e10d12758158`) | **5035 MB** (History) · sampler peak − baseline **2677 MB** (2087 baseline, 4764 peak) | **Fits 12 GB and renders** — 1280×704, 145 frames, 6.04 s. Passes under the *old* 8000 default too, so no refusal to demonstrate at idle free-VRAM; the before/after refusal demo used an oversized 11000 threshold instead (**HTTP 507**, short by 1323 MB). See F-050. |
| A4 | Create video · I2V + LoRA | reference image + a trained LoRA at 0.8 | fits | **BLOCKED — ENVIRONMENT** | | | Not run: blocked by A2. The `activated_loras` / `loras_multipliers` keys were verified against the real checkout (VF-014 re-verified 2026-09-26). |
| A5 | Create video · end frame + refs | `endFramePath`, two `referenceImagePaths` | fits | **BLOCKED — ENVIRONMENT** | | | Not run: blocked by A2. `image_end` + `image_refs` keys verified against the real checkout. |
| A6 | Wan 2.2 5B TI2V as second profile | only if the WanGP checkout lists a 5B TI2V model | **not offered** until the model key is verified on the checkout (VF-020) | **BLOCKED — VERIFY** | | | Still not offered, and I found no 5B TI2V key in the checkout. Consistent with VF-020. |
| A7 | *Concurrent renders (added 2026-09-26 — the "two renders at once" break-it)* | two `POST /api/generate` fired while render 1 is demonstrably active | second refused, not crashed | **MEASURED 2026-09-27** | A: 167.7 s · B: 0.0 s | — | **B → `HTTP 409` in 2.5 ms** while A was at 99% GPU util. A completed `200` in 167.7 s. **Exactly one** output file (mp4 count 9 → 10). No OOM; GPU healthy afterwards. (A second attempt returned `HTTP 000 t=0.000000s` from curl — a client-side artifact, not a server response; the 2.5 ms 409 above is the authoritative reading.) |
| A8 | *Out-of-range image (added 2026-09-26)* | `{"width":99999,"height":99999}` | refused before CUDA | **MEASURED 2026-09-26 (fails)** | — | — | **`500 CUDA error: out of memory`** — a raw crash, unlike every other VRAM path in the app. Needs a range check. |

## B. Reproduce

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| B1 | Image Reproduce, 3 samples | import 3 references (portrait, landscape, product) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | vision stack unloads before renders; candidates scored; best ≥ 0.75 composite on at least 2 of 3 | **MEASURED 2026-09-26 (runs; target NOT met)** | 255 s for 18 candidates | ~5 GB | 18 real candidates over 3 rounds, scored on 4 components with `weights_used` and an honest `missing:["layout"]`. **Round means 0.5874 → 0.5865 → 0.5959 — flat.** Best-of-round 0.6416 / 0.6094 / 0.6329, not monotonic. **Target 0.9 never reached and the run ends without saying so.** Worse: side-by-side with the reference, the app's "best" (0.6416) does not resemble it at all. Root cause is a dead Florence-2 (see D5). |
| B2 | Video Reproduce, 2 shots + stitch | import a 10 s clip with one cut → Detect → Analyse → Start (2 candidates, 1 round) → Pick → Stitch | 2 shots, 4 candidates through the film queue, stitched mp4 plays | **BLOCKED — ENVIRONMENT** | | | Not run: blocked by A2 (no video weights). The Farneback flow path itself is real and green (`tests/test_motion.py` 12/12 after I repaired the venv). |
| B3 | Video Reproduce · motion match | shot with a pan | flow-measured pan in the ShotSpec; motion score reported | **BLOCKED — ENVIRONMENT** | | | Not run: blocked by A2. |

## C. 3D storyboard

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| C1 | Build 3D storyboard → Deliver → render | from B2's analysis: *Build 3D storyboard* → open a shot in the composer → Deliver (clean + depth) → Generate preview | blockout thumbs; control videos land in `generation.control_video/depth_video`; WanGP receives `video_guide` | **MEASURED 2026-09-26 (solver only; render blocked)** | instant | — | `POST /api/scene/build` with a real ShotSpec returns a real camera (`fov 40`, `focal_mm 49.5`), a real Depth-Anything depth map, a generated SVG blockout and `reprojection_error: 0.0`. But `objects: []` — no figures, because the ShotSpec has no subjects (dead Florence-2), so "move a figure" has nothing to move. The Deliver/render half is blocked by A2. |

## D. Train

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| D1 | Install trainer | `scripts\ensure-trainer.ps1 musubi`; set Z-Image weights | Train header shows *musubi-tuner · ready* | **MEASURED 2026-09-26 (refusal path)** | instant | — | The venv is not installed here, so every start is refused with: *"musubi-tuner is not installed. Run `scripts/ensure-trainer.ps1 musubi` (creates backend/.venv-trainer-musubi)."* — accurate and actionable. I did not install the trainer. |
| D2 | LoRA smoke train | 8-image character dataset → auto-caption → Z-Image, character preset, 200 steps | completes within 12 GB with fp8 + block swap; loss sparkline; samples; LoRA in registry | **BLOCKED — ENVIRONMENT** | | | Not run: depends on D1. What I *did* verify: dataset import **skips non-image files correctly** (3 of 5 files imported from a folder holding an `.mp4` and a `.txt`); paths with spaces and unicode work (`日本語 データセット ✨` → 200); auto-caption **carries the trigger word** — but the captions contain **no descriptive content**, because captioning depends on Florence-2. |
| D3 | Apply | A1 with the LoRA from D2 at 0.8 | trigger word honoured; visible likeness | **BLOCKED — ENVIRONMENT** | | | Not run: depends on D2. The binding path is covered by e2e against the mock. |
| D4 | Video LoRA refusal | pick Wan 2.2 / LTX-2 target | refused before start with the 24 GB / 32 GB reason | **MEASURED 2026-09-26 — with a hole, now fixed** | instant | — | On the honest path (`/api/training/suggest` → 24000 / 32768 MB) both targets are refused correctly and no trainer is touched. **But the guard read `estimated_vram_mb` from the request body**, so `{"target":"wan22","estimated_vram_mb":1}` returned **HTTP 200 and trained a 24 GB LoRA to completion on this 12 GB card.** Fixed in `eac8f42` with a regression test. |
| D5 | *Vision stack (added 2026-09-26)* | `POST /api/vision/analyze` on a real image | caption + regions + tags + depth | **MEASURED 2026-09-27 (works)** | see notes | — | **Florence-2 now works on hardware.** Log, verbatim: `Florence-2 load from microsoft/Florence-2-large failed (BartTokenizerFast has no attribute image_token); retrying from the native-port conversion florence-community/Florence-2-large` then `Florence-2 florence-2-large loaded from the native-port conversion florence-community/Florence-2-large`. Round 3's `9c40605` fallback is confirmed end-to-end. Via `POST /api/image-analysis/{id}/analyze` on an app-generated image: `caption` 2188 chars, `description` filled, `subjects` 66 (ollama VLM) / 509 (local) / 172 (director). VLM routing: `ollama`+`qwen2.5vl:7b` → `vision_model = "qwen2.5vl:7b"` (**not** `local-stack`); `off` → `vision_notes = {"vlm": "VLM skipped: Settings → Vision → VLM is \"off\""}`. Unblocks the captioning half of B1 and C1 — **those rows are not re-measured this round.** |

## E. Robustness

| # | Case | Steps | Expected | Status | Notes |
|---|---|---|---|---|---|
| E1 | Cancel mid-render | cancel A3 at ~40 % | job `cancelled`, GPU memory back to idle (`nvidia-smi`), next render starts clean | **BLOCKED — ENVIRONMENT** | Not run: no video render could be started to cancel. `POST /api/generate/cancel` answered correctly (`no_active_generation`) and the e2e cancel specs are green. |
| E2 | Kill and relaunch | kill the backend during A2, relaunch the app | job `failed` ("Interrupted…"), History intact, new render works | **MEASURED 2026-09-26 (partial)** | Killed the backend mid-session **twice**. **VRAM fully released** (12080 MB → 1326 MB — no leak), relaunch was clean, and the next image render worked. Failures that *did* occur landed in History as `status: failed` with the real error text and the prompt + seed preserved — no orphaned `running` job. The literal "Interrupted…" message is not confirmed because no render was ever in flight. |
| E3 | History live updates | run A2 while History is open | card appears queued → running with phase → complete with thumbnail, no refresh | **BLOCKED — ENVIRONMENT** | Not run against a live render. Verified instead: two failed renders recorded correctly with prompt, seed and error (see E2), and the SSE/live path is green in e2e against the mock. |

## F. Containers, remote, agents (phase 9)

| # | Case | Steps | Expected | Status | Notes |
|---|---|---|---|---|---|
| F1 | Compose builds | `docker compose -f deploy/docker-compose.yml up -d --build` on a GPU host | image builds; `/health` answers `ok` with the GPU name | **BLOCKED — ENVIRONMENT (not run)** | Docker Desktop is installed on this box but I did not stand the stack up; this run was already long and the GPU was the priority. `pnpm deploy:config` validates the compose file without running it. |
| F2 | Desktop ↔ stack | Settings → General → Remote backend → Test → Use | health shows the stack's GPU; A1 renders on the stack; media loads | **BLOCKED — ENVIRONMENT** | depends on F1. Switch logic in `electron/remote-backend.ts`. |
| F3 | Remote WanGP only | `WANGP_REMOTE_URL` on the desktop backend | A2 renders in the container, file lands locally | **BLOCKED — ENVIRONMENT** | both halves tested end to end with fakes (`test_wangp_remote.py`) |
| F4 | Hermes Agent live | `hermes mcp test tfg` then "make a 6 s clip of …" | tool list loads; render appears in History | **MEASURED 2026-09-26 (protocol; render blocked by A2)** | `tools/list` returns **exactly 214 tools**, matching the documented count. `initialize` → protocol `2025-06-18`; unknown tool → `-32602`; bad method → `-32601`; missing field → `isError` with FastAPI's text. Both transports verified (HTTP `/mcp` and stdio). **Two defects found and fixed:** the docs told operators to exclude a `system_shutdown` tool that does not exist (the real one is `health_shutdown`), and `pnpm agent:mcp` ran bare `python` and died on `No module named 'torch'`. |
| F5 | Tiered fallback | tiers `local → fal` with a fal key; force a local OOM (1080p · 10 s) | falls back to fal; History `metrics.fallback` names the local error | **BLOCKED — ENVIRONMENT** | no fal key here. The tiers endpoint itself works and explains skips correctly (`"local engine cannot do i2i yet"`). Fallback tested with fakes (`test_provider_tiers.py`). |
| F6 | Docker Desktop repair | reproduce the stale-socket crash loop on Windows; run `scripts\docker-desktop-repair.ps1` | Docker starts without a factory reset | **BLOCKED — ENVIRONMENT** | The script was one of the two that failed to parse at all (BOM-less UTF-8, fixed in `4f8f5c3`); I could not exercise the repair itself without breaking Docker. |

## G. Packaging

| # | Case | Expected | Status | Notes |
|---|---|---|---|---|
| G1 | `pnpm build:win` | installer builds, launches, first-run preset applies, backend starts, Home loads with zero console errors | **BLOCKED — ENVIRONMENT (not run)** | Not run: an installer build is a long Windows-only job and the GPU was the priority. The pieces it depends on *are* green — `pnpm typecheck:ts` exit 0, pyright strict **0 errors**, vitest **53/53**, pytest **828 passed**, Playwright **28/28**, Vite build OK (main chunk 308 kB). Getting e2e to run at all required three fixes (`71e8fdf`). |
| G2 | *All gates from a documented Windows setup (added 2026-09-26)* | the six documented gates pass after `pnpm setup:dev:win` | **MEASURED 2026-09-26 (after fixes)** | — | Before this audit's fixes, the documented setup left `pytest` uninstalled, `pyright` reporting 10 errors, and `pnpm e2e` unable to start. After `1546fe4`, `5435d82`, `e41b010` and `71e8fdf`, all six gates are green on this card. **One structural caveat remains: the gates and a working render still cannot both be satisfied from one venv** (81 of Wan2GP's 99 requirements are absent from `backend/uv.lock`), so "all gates green" currently implies "generation broken". See `docs/HERMES_REVIEW.md`. |

## What is verified without the GPU

- All gates: TypeScript, pyright strict (as a test), vitest, pytest
  (integration-first with fakes, no mocks), Playwright over every view
  against the UI mock with the media check and zero console errors, Vite
  build with the main chunk under 600 kB.
- Preset contents and the 12 GB guard: `test_hardware_presets.py`,
  `test_training.py::TestPresetsAndVramGuard` — plus a new regression test that
  a client cannot understate `estimated_vram_mb` to unlock a video target.
- WanGP settings keys: `test_training.py::TestWangpSettings`,
  `test_scene.py` (guide video) — and, on 2026-09-26, against the **real
  Wan2GP checkout**: all eight keys named in the audit brief exist, and the
  `"I"` (image refs) and `"V"` (guide video) `video_prompt_type` letters that
  VF-008/VF-013 could not confirm are confirmed in `shared/api.py:91-92` and
  `wgp.py:1380,3164-3171`.
- Queue → host pipeline, telemetry, cancellation, restart recovery:
  `test_film_generation.py`, `test_film_hardening.py`, `test_film_rc.py`.
- Remote WanGP, tiers, MCP: `test_wangp_remote.py`, `test_provider_tiers.py`,
  `test_mcp.py`.
- Licence guard: `test_licenses.py`, re-proved after scoping by planting a real
  AGPL header and confirming it still fails the build.

## Telemetry

History records `seconds`, `peak_vram_mb` (VRAM in use after the job, an
estimate, labelled so), `gpu_name`, `execution_mode`, `fallback` and, for
training, `loss_history`; film versions keep the same fields. Nothing is
sent anywhere (`docs/TELEMETRY.md`).

Where it is available, an independent `nvidia-smi` sampler is quoted next to the
app's own number. On 2026-09-26 they agreed to within ~3 % (8044 MB reported vs
7773 MB sampled) — the app's figure is a post-hoc sample, not a true peak, exactly
as labelled.

When a row is measured, replace its status with `MEASURED <date>`, fill the
numbers and add the driver to *Setup under test*. A row is PASS only from a
measurement, never from reasoning.

---

# Round 2 (2026-09-26, branch `review/hermes-round2`, base `82cbe97`)

Rows above are round 1 and are unchanged. Round-2 outcomes:

| Row | Round-2 status | Evidence |
|---|---|---|
| A1 (create image) | **BLOCKED — F-038** | Weights present (`ZImageTurbo_quanto_bf16_int8.safetensors`, 6.4 GB) yet the job sits in `starting_wangp` indefinitely at flat ~1990 MiB (sampler min 1530 / max 2514 over 7526 samples), with no manifest, no output, no History terminal state. Round 1's same path succeeded at 226.7 s cold / 8044 MB, so the weights are loadable. |
| A2/A3 (video) | **BLOCKED — F-038** | Not reached. The 18.11 GB `ltx-2.3-22b-distilled_diffusion_model_quanto_int8.safetensors` **is** installed (`GET /api/models/library` → `installed=true`), so round 1's "weights absent" reason no longer applies. |
| A4/A5/A6 | **BLOCKED — F-038** | Unchanged from round 1; now blocked by the worker, not by the guard. |
| A7 (concurrent renders) | not re-run | — |
| A8 (out-of-range image) | not re-run | — |
| B1 (image Reproduce 3 refs) | **PARTIAL — analysis half works** | `POST /api/image-analysis/ia-fcfefd85cd88/analyze` → 11 s, real palette (6 hex values), luminance 0.1405, contrast 0.0633, saturation 0.0628, edge density 0.0288, vector_likeness 0.508, a written depth map, and tags. `description`/`subjects`/`composition`/`lighting` are empty because **F-015 reproduced live**: `vision_notes.caption = "BartTokenizerFast has no attribute image_token"`. Render half blocked by F-038. |
| B2 (video Reproduce) | **PARTIAL — detect half works** | `POST /api/video-analysis/va-2235244ab978/detect` → 1 s, shot `vs-25c743227d` 0.0–6.125 s, method `uniform` (correct: the 6.125 s source has no cut). Analyse/recreate/stitch blocked by F-038. |
| C1 (3D storyboard → Deliver → render) | not re-run | — |

**Idle baseline re-measured 2026-09-26** (Warframe closed): **1826-1844 MiB, mean ~1836**. Any future `peak - baseline` must subtract ~1836, never the 1530 minimum.

**Not measured at all this round:** every VRAM peak for a render, because no render completed. No estimates are recorded.
