# RTX 4070 (12 GB) acceptance matrix

The RTX 4070 (12 GB VRAM) is the production target: every default the app
ships fits it (the **RTX 4070 · 12 GB** hardware preset), and anything that
cannot run on it is refused with a reason rather than attempted. This file
is the acceptance checklist a tester runs on that card. **Nothing here is a
measurement unless the Status column says `MEASURED <date>`** with the
driver in *Setup under test*. The environment that authored this branch had
no GPU, no Docker daemon and no Windows, so every hardware row is
**BLOCKED — ENVIRONMENT**; the rows are still honest about what the code
path does and which test proves it without the card.

If a default turns out not to fit when measured, downgrade the default
(preset, profile, config) and say so in the row — never hide it.

## Setup under test

| Item | Value to record |
|---|---|
| GPU / driver | RTX 4070 12 GB, NVIDIA driver version |
| OS | Windows 11 build … (primary) / Ubuntu … |
| Install method | `LTX Desktop-<version>-Setup.exe` (SHA-256 …) from `pnpm build:win` |
| Preset | Settings → General → Hardware preset shows *RTX 4070 · 12 GB · Applied* (applied automatically at first run) |
| Execution mode | Settings → AI Models shows *WanGP bridge* (`execution_mode = wangp`) |
| Video model | `ltx2_22B_distilled`; image model `z_image`; vision stack Florence-2-large / CLIP ViT-L/14 / Depth-Anything-V2-small / DINOv2-small; VLM off |
| System RAM | Models tab header (`system_ram_gb`) |

Fill *Seconds* and *Peak VRAM* from History (`metrics.seconds`,
`metrics.peak_vram_mb`, both recorded by the VRAM manager after each job)
and from `nvidia-smi` during the run.

## A. Generation

| # | Case | Steps | Expected on 12 GB | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Create image | Home → Create → image, Z-Image, 8 steps, 1024×1024 | fits; < 30 s after warm-up | BLOCKED — ENVIRONMENT | | | `image_generate_image` over MCP is the same path |
| A2 | Create video · Fast | Quick video, profile Fast (540p · 6 s · 8 steps) | fits (WanGP low-VRAM path); ~1 min | BLOCKED — ENVIRONMENT | | | default profile of the preset |
| A3 | Create video · Balanced | profile Balanced (720p · 8 s) | fits; ~3× A2 | BLOCKED — ENVIRONMENT | | | if it does not fit: lower Balanced to 720p · 6 s in `hardware_presets.py` and record it here |
| A4 | Create video · I2V + LoRA | reference image + a trained LoRA at 0.8 | fits | BLOCKED — ENVIRONMENT | | | `activated_loras` / `loras_multipliers` keys verified against wgp.py (VF-014) |
| A5 | Create video · end frame + refs | `endFramePath`, two `referenceImagePaths` | fits | BLOCKED — ENVIRONMENT | | | `image_end` + `image_refs` keys (VF-014) |
| A6 | Wan 2.2 5B TI2V as second profile | only if the WanGP checkout lists a 5B TI2V model | **not offered** until the model key is verified on the checkout (VF-020) | BLOCKED — VERIFY | | | record the model key here if it exists |

## B. Reproduce

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| B1 | Image Reproduce, 3 samples | import 3 references (portrait, landscape, product) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | vision stack unloads before renders; candidates scored; best ≥ 0.75 composite on at least 2 of 3 | BLOCKED — ENVIRONMENT | | | scoring is unit-tested; the VLM stays off |
| B2 | Video Reproduce, 2 shots + stitch | import a 10 s clip with one cut → Detect → Analyse → Start (2 candidates, 1 round) → Pick → Stitch | 2 shots, 4 candidates through the film queue, stitched mp4 plays | BLOCKED — ENVIRONMENT | | | durations snap to 6/8/10 s (D-022) |
| B3 | Video Reproduce · motion match | shot with a pan | flow-measured pan in the ShotSpec; motion score reported | BLOCKED — ENVIRONMENT | | | Farneback flow path tested with fakes |

## C. 3D storyboard

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| C1 | Build 3D storyboard → Deliver → render | from B2's analysis: *Build 3D storyboard* → open a shot in the composer → Deliver (clean + depth) → Generate preview | blockout thumbs; control videos land in `generation.control_video/depth_video`; WanGP receives `video_guide` | BLOCKED — ENVIRONMENT | | | `video_guide` / `video_prompt_type` keys (VF-013) |

## D. Train

| # | Case | Steps | Expected | Status | Seconds | Peak VRAM | Notes |
|---|---|---|---|---|---|---|---|
| D1 | Install trainer | `scripts\ensure-trainer.ps1 musubi`; set Z-Image weights | Train header shows *musubi-tuner · ready* | BLOCKED — ENVIRONMENT | | | |
| D2 | LoRA smoke train | 8-image character dataset → auto-caption → Z-Image, character preset, 200 steps | completes within 12 GB with fp8 + block swap; loss sparkline; samples; LoRA in registry | BLOCKED — ENVIRONMENT | | | if OOM: raise `blocks_to_swap` in `training_presets.py` and record it |
| D3 | Apply | A1 with the LoRA from D2 at 0.8 | trigger word honoured; visible likeness | BLOCKED — ENVIRONMENT | | | |
| D4 | Video LoRA refusal | pick Wan 2.2 / LTX-2 target | refused before start with the 24 GB / 32 GB reason | verified by `test_training.py` (no GPU needed) | | | honest refusal, not a crash |

## E. Robustness

| # | Case | Steps | Expected | Status | Notes |
|---|---|---|---|---|---|
| E1 | Cancel mid-render | cancel A3 at ~40 % | job `cancelled`, GPU memory back to idle (`nvidia-smi`), next render starts clean | BLOCKED — ENVIRONMENT | cancel path unit-tested |
| E2 | Kill and relaunch | kill the backend during A2, relaunch the app | job `failed` ("Interrupted…"), History intact, new render works | BLOCKED — ENVIRONMENT | restart recovery unit-tested |
| E3 | History live updates | run A2 while History is open | card appears queued → running with phase → complete with thumbnail, no refresh | BLOCKED — ENVIRONMENT | SSE feed tested against the mock in e2e |

## F. Containers, remote, agents (phase 9)

| # | Case | Steps | Expected | Status | Notes |
|---|---|---|---|---|---|
| F1 | Compose builds | `docker compose -f deploy/docker-compose.yml up -d --build` on a GPU host | image builds; `/health` answers `ok` with the GPU name | BLOCKED — ENVIRONMENT (no Docker daemon, no GPU here) | `docker compose config` validates; Dockerfile mirrors the uv setup |
| F2 | Desktop ↔ stack | Settings → General → Remote backend → Test → Use | health shows the stack's GPU; A1 renders on the stack; media loads | BLOCKED — ENVIRONMENT | switch logic in `electron/remote-backend.ts` |
| F3 | Remote WanGP only | `WANGP_REMOTE_URL` on the desktop backend | A2 renders in the container, file lands locally | BLOCKED — ENVIRONMENT | both halves tested end to end with fakes (`test_wangp_remote.py`) |
| F4 | Hermes Agent live | `hermes mcp test tfg` then "make a 6 s clip of …" | tool list loads; render appears in History | BLOCKED — ENVIRONMENT (no Hermes install here) | protocol tested in `test_mcp.py`; config verified against Hermes docs (VF-021) |
| F5 | Tiered fallback | tiers `local → fal` with a fal key; force a local OOM (1080p · 10 s) | falls back to fal; History `metrics.fallback` names the local error | BLOCKED — ENVIRONMENT | fallback tested with fakes (`test_provider_tiers.py`) |
| F6 | Docker Desktop repair | reproduce the stale-socket crash loop on Windows; run `scripts\docker-desktop-repair.ps1` | Docker starts without a factory reset | BLOCKED — ENVIRONMENT | script follows docker/for-win#15063 workaround |

## G. Packaging

| # | Case | Expected | Status | Notes |
|---|---|---|---|---|
| G1 | `pnpm build:win` | installer builds, launches, first-run preset applies, backend starts, Home loads with zero console errors | BLOCKED — ENVIRONMENT (Linux container, no Windows) | frontend build, TypeScript, pyright and e2e are green (see PR) |

## What is verified without the GPU

- All gates: TypeScript, pyright strict (as a test), vitest, pytest
  (integration-first with fakes, no mocks), Playwright over every view
  against the UI mock with the media check and zero console errors, Vite
  build with the main chunk under 600 kB.
- Preset contents and the 12 GB guard: `test_hardware_presets.py`,
  `test_training.py::TestPresetsAndVramGuard`.
- WanGP settings keys: `test_training.py::TestWangpSettings`,
  `test_scene.py` (guide video).
- Queue → host pipeline, telemetry, cancellation, restart recovery:
  `test_film_generation.py`, `test_film_hardening.py`, `test_film_rc.py`.
- Remote WanGP, tiers, MCP: `test_wangp_remote.py`, `test_provider_tiers.py`,
  `test_mcp.py`.

## Telemetry

History records `seconds`, `peak_vram_mb` (VRAM in use after the job, an
estimate, labelled so), `gpu_name`, `execution_mode`, `fallback` and, for
training, `loss_history`; film versions keep the same fields. Nothing is
sent anywhere (`docs/TELEMETRY.md`).

When a row is measured, replace its status with `MEASURED <date>`, fill the
numbers and add the driver to *Setup under test*. A row is PASS only from a
measurement, never from reasoning.
