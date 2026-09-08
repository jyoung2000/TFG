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

## Preview vs final

- **Preview**: fastest model, `settings.preview_resolution` (default 540p),
  duration clamped to `settings.preview_max_seconds` (default 4 s).
- **Final**: the shot's model/resolution (or project defaults) at full shot
  duration.

Versions are append-only (`v1, v2, …` with kind/status/prompt/model/seed/
capture/output/error/wardrobe-snapshot/timestamp). Completed versions can be
promoted to *current* at any time; failed versions keep their error and a
Retry action. Nothing is ever silently overwritten.

## Queue semantics

One background worker drains the film queue sequentially (the host has a
single generation slot); `GET /api/film/queue` reports active + pending, and
`POST /api/film/queue/cancel` drains pending (marking their versions
cancelled) and cancels the active job through the host's cancel path. Every
state transition is persisted to `project.json` first, so a backend restart
leaves shots in `ready`/`failed` states instead of losing them.

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

The Models sub-tab renders all of this — GPU summary, color-coded verdict,
per-model fit badges ("Fits this GPU" / "Incompatible with this GPU"),
required/optional markers — and drives the existing `/api/models/download`
pipeline (with live progress and a sized download button, plus a
skip-text-encoder toggle when cloud encoding makes it optional).
