# ADR 0003 — Per-task provider capabilities and tiered fallback

**Status:** accepted (phase 9)

## Context

`media_provider` was one global switch: local or one hosted vendor. A 12 GB
card sometimes cannot render what a hosted model can, and a hosted vendor
sometimes fails; either way the person wants the clip, not the error.

## Decision

- `film/provider_tiers.py`: a **tier list per task** (`t2i`, `i2i`, `t2v`,
  `i2v`, `edit`) stored in `AppSettings.media_tiers`; a missing task means
  the old single provider. `plan()` checks each tier — local engine
  capability (i2i/edit stay off until WanGP's edit parameters are
  confirmed), hosted key present, model id configured, and the capability
  catalog (`model_catalog.json`, from Open-Generative-AI) saying the model
  can do the task — and records *why* a tier is skipped.
- `run_with_fallback()` tries usable tiers in order; a failure moves on, a
  cancel stops. Used by Create video (`VideoGenerationHandler`), film shots
  and asset reference images. A film project's explicit provider still wins
  (no tiering), and the film queue owns its tiers (`allow_fallback=False`
  on the shared video handler).
- History records `metrics.fallback` with every attempt's reason; the
  Settings editor shows the resolved plan (`GET /api/settings/tiers`).

## Consequences

- Local-first is the default; a hosted tier never appears unless
  configured, so nothing leaves the machine by surprise.
- Fallback re-sends the same prompt and seed; provider-specific model ids
  come from `default_video_model` / `default_image_model`.
