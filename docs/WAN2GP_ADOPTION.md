# What this app uses from Wan2GP, and what's still on the table

The engine checkout (`Wan2GP/`, 2026-09-22, WanGP v13.13) ships far more than the app
drives. This is the audit from 2026-10-06: what we adopted, what's worth a download,
and what upstream (v17, ~1,800 commits ahead) would add.

## Adopted (no new base weights)

| Feature | What it does here | Cost |
| --- | --- | --- |
| Qwen-Edit-2511 as the restyler | Restyling a picture keeps the person: SFace 0.714 vs USO's 0.282 against the photo (live, 2026-10-06). USO still draws style-only pictures. | none (installed) |
| LTX2 Ingredients IC-LoRA | A film shot rendered on an LTX2 model sends its cast's identity images into the render (`ic-lora-ingredients`, auto-loaded for "I" refs), so identity holds across the whole clip. | 1.3 GB, on D: |

## Worth a download (ride on bases we have, or small)

| Feature | Needs | Why |
| --- | --- | --- |
| EditAnything Ref V2V (distilled, 8 steps) | 1.2 GB LoRA + 0.4 GB module on the installed `ltx2_22B_distilled` | Edit or restyle an existing video from a source video + one reference image: the style-drift fix for restyled clips, and general video editing. |
| LTX 2.5 distilled | 18.2 GB int8 (+ its VAE/upscaler extras) | Lightricks' quality upgrade over 2.3: sharper detail, better visual consistency. Same VRAM class. |
| MSR v2 (identity references for video) | 18.1 GB `distilled-1.1` base + 0.6 GB LoRA | 2–5 reference subjects preserved by a LoRA made for identity, stronger than Ingredients. |
| JoyAI-Echo Surgical | 17.7 GB fp8 finetune | Reuse character identities between shots natively. |
| Shotplan (Wan 2.2 t2v) | ~18 GB high-noise expert | One generation split into shots that reuse the same characters/objects. |
| MiniMax H3 (FL2VA/Ref2VA, PDD 8-step) | ~20–40 GB | Video+synchronized stereo audio, 5–6 GB VRAM for 5 s at 832x480; Ref2VA follows reference people/voices across sliding windows. |

## Upstream-only (needs updating the checkout, ~1,800 commits)

- newer mmgp ("speed boost"), LTX 2.5 refiner, VAE x2 refiner, GPU TinyVAE previews
- PrunaVAED: LTX2 VAE decode 2.7x faster at half the VRAM
- First Block Cache / Sol-Attn step-skipping (helps 15–30-step models, not our
  4–8-step distilled presets)
- SeedVR2 / FlashVSR upsamplers, Wan2.2 Animate 2, Krea 2 Identity Edit, SenseNova U1.5

Updating the checkout is a real project: the worker bridge pins against wgp.py's
settings keys and model ids, so it needs the full test suite plus live smoke tests of
every model the app drives (Wan 2.2 Lightning, LTX2 distilled, FLUX USO/Klein,
Qwen-Edit-2511, Z-Image).

## Not useful here

- TeaCache/MagCache: Wan 2.2 i2v explicitly excludes tea-cache, and skip-step caches
  do nothing for 4–8-step distilled renders.
- DreamOmni2 / UMO FLUX edits: need the 12 GB Kontext base; Qwen-Edit-2511 already
  covers identity-preserving edits better on this card.
