# Train: LoRA training on a 12 GB card

The Train tab (Home → **Train**) teaches the image model a character, a
style or an object. It is built for an RTX 4070 (12 GB): every default fits
the card, anything that cannot is refused *before* a subprocess starts, and
the trainers run in their own environments so their pins never touch the
app's.

## What runs where

| Target | Trainer | Estimated peak | On 12 GB |
|---|---|---|---|
| Z-Image | musubi-tuner (Apache-2.0) — `zimage_train_network.py` | ~10.5 GB (fp8 base + 8 swapped blocks) | yes |
| Qwen-Image | musubi-tuner — `qwen_image_train_network.py` | ~11.2 GB (fp8 + 20 swapped blocks) | yes |
| FLUX | ostris ai-toolkit (MIT) — `run.py config.yaml`, `quantize` + `low_vram` | ~11.5 GB | yes |
| Wan 2.2 (video) | musubi-tuner — `wan_train_network.py` | 24 GB per upstream README | **refused** |
| LTX-2 (video) | Lightricks `ltx-trainer` | 32 GB low-VRAM config, 80 GB recommended | **refused** |

The refusals are honest: the UI lists the video targets, explains the VRAM
they need, and the backend rejects a start with the same message
(`film/training_presets.fits_machine`). Nothing here pretends a video LoRA
can be trained on this card.

Estimates come from the upstream documentation recorded in
`session-notes.md` (VF-014…VF-016); a real run on the 4070 is the
acceptance test (`docs/RTX_4070_TEST_MATRIX.md`).

## Installing a trainer

Trainers are **not vendored**. Each is cloned and installed beside the
backend, in its own venv, by one idempotent script:

```powershell
scripts\ensure-trainer.ps1 musubi       # backend\.venv-trainer-musubi + backend\.trainer-musubi
scripts\ensure-trainer.ps1 ai-toolkit   # backend\.venv-trainer-aitoolkit + backend\.trainer-ai-toolkit
```

(`scripts/ensure-trainer.sh` is the same for macOS/Linux; `TFG_TRAINER_CUDA`
picks the torch wheel index, default `cu128`.) The Train header shows each
trainer as *ready* / *not installed* / *needs more than 12 GB*, and a start
against a missing trainer fails with the exact command to run.

**Weights.** musubi-tuner needs the base DiT, VAE and text-encoder files
for each target. Set them once per target with
`PUT /api/training/weights/<target>` (`{"dit": …, "vae": …, "text_encoder": …}`);
the UI's Trainer settings writes the same file
(`<app-data>/training/trainer-weights.json`). A start with missing weights
is refused with the list of what is missing.

## Building a dataset

`<app-data>/training/datasets/<id>/` holds the images, one `.txt` caption
sidecar per image (what every trainer reads) and `dataset.json`.

Sources (any mix, in the Train tab or `POST /api/training/datasets/{id}/import`):

- a folder of PNG / JPG / WebP;
- individual image paths;
- a video, sampled at *n* fps through the media probe (`video_fps`,
  `video_max_frames`);
- **History** outputs (`job_ids`): every image output of those jobs;
- a video analysis (`analysis_id`): all extracted frames;
- an Image Reproduce job (`reproduce_id`): its candidates.

**Captions.** *Auto-caption* runs Florence-2 through the vision stack and
prepends the trigger word (`mara_v1, a woman …`; style datasets get
`…, in the style of relaystyle`). Captions a person edited are kept unless
*overwrite edited* is asked for. The review grid edits captions inline and
removes images.

**Presets** set the defaults per target (`film/training_presets.py`):

| Preset | Rank | Steps | LR |
|---|---|---|---|
| character | 16 | 600–800 × image-count factor | 1e-4 |
| style | 24 | 1.5× | 8e-5 |
| object | 12 | 0.8× | 1.2e-4 |

Steps scale with the image count (12 images ≈ 1×, clamped 200–3000). Every
field is editable before starting; the estimate is shown against the card.

## Training runs

A run is a **History job** (`kind: training`) with live progress, phase,
ETA, a loss sparkline (`metrics.loss_history`) and the sample grid the
trainer renders at `sample_every`. Under the hood
(`handlers/training_handler.py`):

1. the VRAM manager unloads the vision models
   (`prepare_for_render("training", needed_mb=estimate)`);
2. the trainer builds its config (musubi: dataset TOML, cache latents,
   cache text-encoder outputs, then `accelerate launch … --fp8_base
   --fp8_scaled --blocks_to_swap N --network_dim rank`; ai-toolkit: one
   YAML with `quantize: true`, `low_vram: true`, `trigger_word`);
3. stdout is parsed for `step/total`, `avr_loss=` / `loss:` and the tqdm
   ETA; new sample PNGs and checkpoints are picked up as they appear;
4. on completion the LoRA is copied into the registry.

**Cancel** stops the subprocess (also from History's cancel button).
**Resume** starts a new run from the last checkpoint
(`--network_weights` / ai-toolkit resume), inheriting the config.
Failures surface the last log line as the run error.

## The LoRA registry

`<app-data>/loras/<folder>/*.safetensors` + `registry.json`, where `<folder>`
is the WanGP LoRA directory for the target (`z_image`, `qwen`, `flux2`,
`wan`, `ltx2`). Each entry records the base model, trigger word, dataset,
run and job it came from, a default strength, and whether it was imported.
Entries whose file disappeared are dropped on load.

**Import** takes any local `.safetensors` file. **Download from a link**
(`POST /api/training/loras/download`, the "paste a link" row in the
registry) accepts a Hugging Face file URL (`/blob/` or `/resolve/`, it is
fetched via `/resolve/`), a Civitai model page
(`civitai.com/models/<id>[?modelVersionId=…]`, resolved through Civitai's
public API to the primary `.safetensors` file) or Civitai download link, or
any direct `https://…/*.safetensors` URL. The download runs as a History
`download` job (progress in MB, cancellable) into
`<loras>/<folder>/.downloading/` and is registered on completion. Gated
files can take an API key with the request; it is sent once for that fetch
and never stored — not in settings, not on the job, not in logs.

Pickers ask `GET /api/training/loras?model=<model id>` and only get LoRAs
whose target matches that model (`z_image_turbo` → `z_image`,
`qwen_image_20B` → `qwen_image`, anything `ltx…` → `ltx2`). The picker sits
in Quick video (LTX-2 LoRAs), Image Reproduce (the compile target's LoRAs)
and the Film Assets panel.

## How LoRAs reach WanGP

`GenerateVideoRequest.loras` / `GenerateImageRequest.loras` carry
`[{name: <absolute safetensors path>, multiplier}]`. The bridge writes the
keys `wgp.py` reads (verified against upstream, VF-014):

- `activated_loras`: list of absolute paths (`get_lora_URL` returns them
  unchanged);
- `loras_multipliers`: space-separated strengths in the same order;
- `image_refs` + `video_prompt_type += "I"` for reference images;
- `image_end` + `image_prompt_type += "E"` for an end frame.

Files that do not exist are dropped rather than sent.

## Consistency Kit (Film → Assets)

Per character / location / prop:

- **LoRA binding** (`lora_id`, `lora_trigger`, `lora_multiplier`): every
  shot that features the asset inherits the LoRA (deduplicated across
  assets) and the trigger word is prepended to the character description
  in the synthesized prompt.
- **Seed lock** (`seed_lock`): shots whose version has no seed of its own
  render with the asset's seed.
- **Reference sheet**: front / three-quarter / profile / back views rendered
  with one seed and the bound LoRA, saved as reference images; the seed is
  locked afterwards if it was not already.
- **Cross-frame consistency**: after a shot renders, the first frame is
  embedded with CLIP and compared to the reference image of each character
  in it; the average cosine lands in History as `metrics.consistency`.
  Absent (not invented) when there is nothing to compare against.

## Tests

`backend/tests/test_training.py` runs everything above against
`FakeTrainer` (steps, a falling loss, sample PNGs, checkpoints, failure and
cancel on demand) and the fake vision stack; the subprocess trainers are
tested down to the command line and config they would launch. Playwright
`e2e/train.spec.ts` covers the tab against the UI mock, including the 12 GB
refusal, cancel → resume, the registry, the pickers and the Consistency Kit.

Real-GPU training is **BLOCKED — ENVIRONMENT** in this session; the
acceptance row lives in `docs/RTX_4070_TEST_MATRIX.md`.
