# RTX 4070 (12 GB) qualification matrix

The RTX 4070 (12 GB VRAM) is the reference "mid-range" target for the WanGP
path. This matrix is the checklist a tester runs on real hardware; the app
records the telemetry needed to fill it in (see *Telemetry* below). Nothing
in this file is a measurement unless the *Status* column says **MEASURED**
with a date and driver — this repository's CI and development container have
no GPU, so every row starts as **BLOCKED — ENVIRONMENT (no GPU available)**.

## Setup under test

| Item | Value to record |
|---|---|
| GPU / driver | RTX 4070 12 GB, NVIDIA driver version |
| OS | Windows 11 build … / Ubuntu … |
| Install method | `LTX Desktop-<version>-Setup.exe` (SHA-256 …) or AppImage |
| Execution mode | Storyboard → Models shows *WanGP bridge* (`execution_mode = wangp`) |
| Active model | `WANGP_VIDEO_MODEL_TYPE` (default `ltx2_22B_distilled`), quantisation shown in the Models tab |
| System RAM | Models tab header (`system_ram_gb`) |

## Matrix

Each row = one generation. Fill from the version's telemetry (`generation_seconds`,
`gpu_name`, `peak_vram_gb` — an estimate taken after the job) shown in the
shot drawer / composer version list, plus the outcome.

| # | Profile | Resolution | Duration | Mode | Expected on 12 GB | Status | Seconds | Peak VRAM (est.) | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Fast Preview | 540p | 4 s | T2V | fits (WanGP low-VRAM path) | BLOCKED — ENVIRONMENT | | | |
| 2 | Fast Preview | 540p | 4 s | I2V (composer capture) | fits | BLOCKED — ENVIRONMENT | | | |
| 3 | Balanced (recommended for 12 GB) | 720p | 5 s | T2V | fits | BLOCKED — ENVIRONMENT | | | |
| 4 | Balanced | 720p | 5 s | I2V | fits | BLOCKED — ENVIRONMENT | | | |
| 5 | Balanced | 720p | 5 s | continue-from-previous | fits | BLOCKED — ENVIRONMENT | | | |
| 6 | Quality | 1080p | 5 s | T2V | **may not fit** — profile is flagged `fits_gpu=false` at 12 GB | BLOCKED — ENVIRONMENT | | | expect OOM → actionable error |
| 7 | Balanced | 720p | 10 s | T2V | fits, slow | BLOCKED — ENVIRONMENT | | | |
| 8 | Any | any | any | cancel mid-render | job cancelled, version `cancelled`, GPU released | BLOCKED — ENVIRONMENT | | | |
| 9 | Any | any | any | kill backend mid-render, relaunch | version `failed` ("Interrupted…"), shot not stuck | BLOCKED — ENVIRONMENT | | | restart recovery is unit-tested |
| 10 | Batch | 720p | 3 × 5 s | scene batch | sequential, progress per job, pause/resume works | BLOCKED — ENVIRONMENT | | | |

Pass criteria per row: output plays in the shot drawer, `generation_seconds`
recorded, no unhandled error, GPU memory returns to idle after the job
(`nvidia-smi`).

## What is verified without the GPU

- The queue → host pipeline path, telemetry capture, cancellation, restart
  recovery and failure persistence are covered by backend tests with the
  fake pipeline (`backend/tests/test_film_generation.py`,
  `test_film_hardening.py`, `test_film_rc.py::TestVersionTelemetry`).
- Profile recommendation for a 12 GB GPU (Balanced) is covered by
  `test_film_hardening.py::test_profiles_recommend_by_vram`.
- The Models tab marks profiles that may not fit and models that are
  incompatible with the detected VRAM.

## Telemetry

Every rendered version stores `generation_seconds`, `gpu_name`,
`peak_vram_gb` (labelled an estimate: VRAM used as reported by the GPU
service after the job — not a true peak) and `execution_mode`. The UI shows
seconds and mode next to each version. Nothing is sent anywhere; see
`docs/TELEMETRY.md`.

When rows are measured, replace the status with `MEASURED <date>` and add
the driver version to *Setup under test*. Do not mark a row PASS from
reasoning alone.
