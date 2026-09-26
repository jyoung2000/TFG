# Image Reproduce v2

`Home → Reproduce image`. Import a reference, get a ShotSpec with evidence
per block, edit or lock blocks, then run a scored loop that renders
candidates and steers the prompt from measured differences until a target
score is reached. Everything the loop does is a job in History with lineage
(`image_reproduce` parent → `image_gen` children).

## Flow

1. **Import** copies the file to `<outputs>/image_analyses/<id>/reference.<ext>`
   and creates a `ReproduceJob` (schema v2; v1 documents from the old
   "Recreate from image" tab are migrated on read, their candidates kept as
   `source: legacy`).
2. **Analyse** runs the local vision stack (`VisionHandler.analyze`:
   deterministic stats → Florence-2 → CLIP tagger → Depth-Anything) and fuses
   it into a `ShotSpec` (`film/shot_spec_fusion.spec_from_vision`). The
   optional VLM (Settings → Vision) fills scene/lighting/narrative only where
   the local stack left gaps. The `why` map keeps the evidence behind each
   block; the UI shows it under *Why · evidence per block*.
3. **Spec blocks** are editable. An edit marks the block `provenance: user`
   and locks it; locked blocks survive re-analysis (`merge_specs`). The prompt
   is recompiled server-side (`compile_from_spec`) for the chosen target and
   style unless a prompt override is set.
4. **Start loop** opens the parent job and renders `candidates_per_round`
   images per round on the task runner through `ImageGenerationHandler`
   (never a parallel engine). Seeds are `seed0 + (round-1)*100 + n` so a run
   is reproducible from its seed. After each round the composite score is
   computed and, when below target:
   - **metric-guided patches** add phrases per weak component (palette →
     colour terms from the reference palette, layout → subject/shot-size
     phrases, ssim → contrast/exposure words, clip/dino → caption/tags);
   - on a **plateau** (best score did not improve) and `use_vlm`, the VLM
     compares reference vs best candidate and proposes one phrase;
   - knowledge hints (`KnowledgeHandler.hints_for`) are applied from round 2.
   Every candidate is recorded as `candidate_scored`; the final pick as
   `candidate_picked`, so the knowledge loop improves later runs.
5. **Pin** a candidate as the new reference for further rounds (or pin the
   source again). **Pick** marks the deliverable. **Fix** opens the canvas.

## Scoring

`services/similarity/composite.py`, weights renormalised over the components
that are available:

| component | weight | what |
|---|---|---|
| clip | 0.35 | CLIP-I cosine between image embeddings |
| dino | 0.25 | DINOv2 CLS cosine (structure) |
| ssim | 0.15 | SSIM over a 256-px luma downscale |
| palette | 0.15 | ΔE2000 between k-means palettes, share-weighted |
| layout | 0.10 | subject count match + best-IoU of detected boxes |

Without vision embeddings (fake services, vision disabled) the score is
SSIM + palette + layout renormalised; the breakdown lists `missing`.

## Fix canvas

Plain Canvas 2D, no new dependencies. Brush / eraser / marquee mask, undo,
exposure / contrast / saturation / hue / black & white point / gamma /
temperature sliders, reference overlay. Commits go to
`POST /api/reproduce/{id}/candidates/{cid}/fix` and are applied server-side by
`services/image_ops.py` (same maths as the client preview), producing a new
candidate with `source: fix | patch | inpaint` and `parent_id`. *Patch from
reference* composites the reference through the feathered mask. *Inpaint*
needs the WanGP edit model (Qwen-Image-Edit / Flux Kontext); until the WanGP
reference/mask keys are verified on a real checkout the endpoint answers with
an actionable error (session-notes VF-008).

## API

`/api/reproduce` (list), `POST /import`, `GET|DELETE /{id}`, `POST /{id}/analyze`,
`PUT /{id}/spec`, `PUT /{id}/prompt`, `POST /{id}/start|cancel`,
`POST /{id}/pin/{cid|source}`, `POST /{id}/pick/{cid}`,
`POST /{id}/candidates/{cid}/fix`, `GET /{id}/media?path=` (token in query).
Types: `backend/film/reproduce_models.py` ↔ `frontend/types/reproduce.ts`.

## VRAM (12 GB)

Before each render the loop enters `VisionHandler.render_scope`, which unloads
vision models by priority until the render class fits; a render that cannot
fit fails the job with HTTP 507 and a message naming what to free. Peak VRAM
per candidate is stored in the child job's `metrics.peak_vram_mb`.

## Tests

- `backend/tests/test_reproduce.py`: metrics against reference values
  (ΔE2000 Sharma pairs), composite renormalisation, image ops, analyse →
  spec + evidence, the loop with fake generation (scores, jobs, knowledge
  events), metric-guided patches, early stop, pin/pick/fix, spec edit locks,
  v1 migration, cancel from History.
- `e2e/reproduce.spec.ts`: import → analyse → lock/style → loop with live
  rounds → every candidate loads → pin/pick/lightbox → fix canvas → cancel,
  zero console errors against the UI mock.
- Real-GPU runs (RTX 4070): see `docs/RTX_4070_TEST_MATRIX.md`.
