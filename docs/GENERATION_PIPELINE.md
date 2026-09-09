# Film Generation Pipeline

Film shots do not have their own inference engine. The film queue adapts each
shot into the host's real `GenerateVideoRequest` and calls
`VideoGenerationHandler.generate` — so all three existing execution paths are
reused untouched:

| Runtime | Path |
|---|---|
| `WANGP_ROOT` set | WanGP bridge (in-process `shared.api.WanGPSession`) |
| forced API / no CUDA GPU | LTX cloud API |
| CUDA + downloaded models | local LTX pipelines |

When a **hosted media provider** is selected (fal, WaveSpeed or Replicate)
the same queue instead submits the same adapted request to that provider and
downloads the result — see *Hosted providers* below. Local remains the
default and the offline path.

## Request adaptation

For each queued job a `ShotVersion` records everything reproducible:

- **prompt** — synthesized from the structured shot state
  (`film/film_prompt.py`): framing phrases, characters (description/
  appearance/wardrobe/emotion/pose), action or description, dialogue,
  location (scene lighting wins over location lighting), props, mood,
  camera-move phrasing, project + style-asset prompts. The structured fields
  are never discarded; a user-edited prompt locks synthesis for that shot.
- **imagePath** — the composition capture (when
  `use_capture_as_reference`), else the last frame of the previous shot's
  current output when `continue_from_previous` is enabled (extracted through
  the `VideoProcessor` service and saved beside the captures, so the
  reference is visible and traceable).
- **cameraMotion** — mapped to the nearest host motion id
  (`push_in→dolly_in`, `tilt_up→jib_up`, …); moves the host has no motion id
  for (pans, orbit, follow) ride in the prompt text with motion `none`.
- **duration/fps/resolution/model/seed/aspect** — per-shot settings with
  project defaults; forced-API mode snaps duration to the API's allowed set.
  A per-shot seed rides through the host's locked-seed mechanism for exactly
  that job, then the user's own seed settings are restored.

## Preview vs final, quality profiles

- **Preview**: fastest model, `settings.preview_resolution` (default 540p),
  duration clamped to `settings.preview_max_seconds` (default 4 s).
- **Final**: resolved from the shot's **quality profile** at full shot
  duration:

| Profile | Model | Resolution | Recommended for |
|---|---|---|---|
| `fast_preview` | fast | 540p | < 8 GB VRAM |
| `balanced` | fast | 720p | 8–16 GB (e.g. RTX 4070 12 GB) — the project default |
| `quality` | pro | 1080p | ≥ 16 GB |
| `custom` | the shot's own `generation.model` / `resolution` | | |

  A shot's `generation.quality_preset` defaults to `project`, which inherits
  `settings.default_quality_preset`. An explicit `model` or `resolution` on
  the shot always wins (treated as custom). `GET /api/film/capabilities`
  returns the profiles with `recommended` (by detected VRAM) and `fits_gpu`;
  Settings → AI Models lists them and the shot drawer offers the picker.

Versions are append-only (`v1, v2, …` with kind/status/prompt/model/seed/
capture/output/error/wardrobe-snapshot/timestamp). Completed versions can be
promoted to *current* at any time; failed versions keep their error and a
Retry action. Nothing is ever silently overwritten.

## Hosted providers (fal / WaveSpeed / Replicate)

`media_provider` is `local` by default. Set it to `fal`, `wavespeed` or
`replicate` — app-wide in *Settings → API Keys*, or per project from the
*Video* / *Image* chips in the AI Director bar — and the queue routes the job
through `MediaRunner` instead of the host engine. Resolution order per job:
the project's `media_provider` / `video_model`, then the app defaults, then
`local`.

What is identical to a local render:

- the same `_prepare_request` output — synthesized prompt, reference image,
  duration, fps, resolution, aspect and seed;
- one queue, one job at a time, with pause/resume, per-job cancel,
  prioritize and live progress (`MediaRunner` reports ramped progress while
  polling and honours the same cancel flag);
- a `ShotVersion` per attempt, the downloaded file stored beside local
  renders, and the same timeline / editor / `.ltxfilm` behaviour;
- the same telemetry event, with `execution_mode` set to the provider name
  rather than `wangp` / `api` / `local`.

What differs:

- conditioning images are sent inline as `data:` URLs (nothing is uploaded to
  a third-party file host);
- a missing key fails the job immediately with a typed, key-free message
  naming the provider and the setting to fill in — it never starts a render
  it cannot finish;
- provider timeouts fail that job instead of stalling the queue.

Asset reference images follow the same rule: *Assets → Generate with AI* runs
locally when the project generates locally, otherwise on the selected hosted
provider with the chosen image model.

## Queue semantics

One background worker drains the film queue sequentially (the host has a
single generation slot). Every state transition is persisted to
`project.json` first.

| Route | Effect |
|---|---|
| `GET /api/film/queue` | `active`, `pending[]`, `paused`, host `progress` % and `phase` for the active job |
| `POST /api/film/queue/pause` | stop starting new jobs (the active one finishes) |
| `POST /api/film/queue/resume` | restart the worker |
| `POST /api/film/queue/{shotId}/cancel` | drop a pending job (version → `cancelled`) or cancel the active one through the host's cancel path |
| `POST /api/film/queue/{shotId}/prioritize` | move a pending job to the front |
| `POST /api/film/queue/cancel` | cancel everything |

**Restart recovery**: on startup `FilmGenerationHandler.recover_interrupted_jobs()`
scans every film project and turns versions left `queued`/`generating` by a
dead process into `failed` ("Interrupted: the app restarted …") with the shot
back in `ready`/`composed` — no shot can stay stuck in *generating*. The
storyboard header shows the active job with progress, a pending list with
per-job cancel/prioritize, and Pause/Resume.

## Model management

The **Model Library** (`GET /api/models/library`) is the searchable catalog
over every model this app can use — local WanGP weights, the native LTX
files, an Ollama or OpenAI-compatible server's models, and each configured
hosted provider's list — with downloads for the ones that run on this
machine (`POST /api/models/library/download`, Hugging Face weights and Ollama
pulls). It also reports `offline_ready`: whether a local video/image model
and a local text model are both installed. Full reference in
`AI_PROVIDERS.md`.

Besides download (`POST /api/models/download`), `DELETE /api/models/{type}`
removes a downloaded local model (`checkpoint | upsampler | text_encoder |
zit`) so it can be re-downloaded (update) or freed; refused while a download
or generation is running, and in WanGP mode (models live in the WanGP
checkout). Settings → AI Models offers the remove action per downloaded model.

## Model capabilities (`GET /api/film/capabilities`)

Derived from the actual runtime, never a hardcoded catalog:

- execution mode from `RuntimeConfig` (wangp / api / local),
- the real model-download specs (ids, descriptions, on-disk sizes), their
  live downloaded state and required/optional flags for local mode (the text
  encoder becomes optional when an LTX API key enables cloud text encoding),
- detected GPU name + VRAM from the `GpuInfo` service,
- a per-GPU `gpu_verdict` (+ severity) and per-model `fits_gpu` flags using
  this repository's documented figures (WanGP bridge: ~6 GB minimum; native
  local pipeline: ~32 GB; API: none),
- `total_required_download_gb` — the real size of what's still missing,
- in local mode, an advisory **WanGP bridge** row so 6–31 GB GPUs see their
  compatible path (with setup pointer) even before configuring it.

Settings → AI Models renders all of this — GPU summary, color-coded verdict,
per-model fit badges ("Fits this GPU" / "Incompatible with this GPU"),
required/optional markers — and drives the existing `/api/models/download`
pipeline (with live progress and a sized download button, plus a
skip-text-encoder toggle when cloud encoding makes it optional).
