# Video Reproduce v2

`Home → Analyse video → Recreate video`. An analysed clip is rendered again
shot by shot through the film queue, every candidate is scored against the
source, the best (or your pick) per shot is stitched in order, and the whole
run is visible in History with lineage.

## What replaced the stub

The phase-0 audit found `recreate_video()` returning a canned response while
the route concatenated every prompt into one synchronous T2V request with an
illegal duration (D1, D2) and a test that passed either way (D3). Now:

- the route is plumbing; `VideoAnalysisHandler.recreate_video` delegates to
  `handlers/video_reproduce_handler.py`;
- **one film-queue job per candidate**: the analysis is reconstructed into an
  ordinary film project (once), and each shot renders through
  `FilmGenerationHandler.queue_shot` — the same queue, versions, cancel and
  History job as any storyboard shot;
- **image-to-video by default** from the shot's first extracted frame (copied
  into the project's `captures/`, passed as `capture_path`);
- **duration snapped** to `get_allowed_durations()` for the resolved model
  (a 2 s shot renders at 6 s; the source span is kept on the spec);
- `candidates` and `rounds` are honoured; seeds are `seed + (round-1)*100 + n`
  when a seed is given, and recorded on every candidate;
- **per-shot scoring** on sampled frames (start/middle/end) with the phase-4
  composite (SSIM + palette, plus CLIP-I/DINOv2 when the vision stack is up)
  mixed 0.8 / 0.2 with a **flow-magnitude match** against the shot's measured
  motion (`docs/REPRODUCE.md` for the composite);
- **stitching** of the picked candidates in shot order through
  `services/stitcher` (ffmpeg concat: stream copy, re-encode fallback; binary
  from `TFG_FFMPEG`, the `imageio-ffmpeg` wheel, or PATH — nothing added to
  the repo);
- **lineage** in History: `analysis` → `video_reproduce` parent → one
  `video_gen` child per candidate (with `scores` in its metrics) → the
  stitched file as the parent's first output.

## Motion analysis

`services/motion/OpticalFlowAnalyzer` samples frames with PyAV, downsizes to
160 px and runs OpenCV Farneback dense flow. Each frame pair is fitted with a
least-squares similarity transform (`flow_math.estimate_global_motion`): the
translation is pan/tilt, the scale term is zoom, the rotation is roll, and the
residual is subject motion. Aggregated over the shot this gives `spec.motion`
(dominant pan/tilt/zoom/roll, magnitude, subject motion, pacing) and
`spec.camera.move` / `move_intensity`, plus `shot.motion` on the analysis with
a handheld flag from high-frequency jitter. The camera-move words are
**measured** provenance and win over a VLM's guess from stills. RAFT is not
wired (weights cannot be fetched offline); Farneback classifies the move and
its magnitude well enough for prompts and scoring.

## The VLM pass, split

The monolithic 40-field JSON call is gone. Each shot is described in four
focused calls — visual, cinematography, narrative, prompt lens — each with a
compact shape and one **repair round** that sends the broken reply back with
the shape it owed. A section that never parses is named in `evidence_note`
and the others are kept. The VLM never overwrites what flow measured, and its
scene/lighting/narrative reads land in the ShotSpec only where the local
stack left gaps (`apply_vlm`). With the VLM off, Florence + CLIP + flow +
stats still produce a usable spec and prompt.

## UI

`views/reproduce/VideoReproduce.tsx`, mounted under the analysis: one row per
shot with the reference frame beside the chosen candidate, per-shot score
bars, every candidate with its score/round/seed and a pick star, **Redo** for
one more candidate, **Stitch picks**, cancel while running, and the stitched
result. Clips play through `/api/video-reproduce/{id}/media` (token in the
query, only files the document recorded).

## API

`/api/video-reproduce/{analysis_id}`: `GET` (document), `POST /start`
(`candidates`, `rounds`, `shot_ids`, `kind: preview|final`, `seed`),
`POST /cancel`, `POST /shots/{shot}/pick/{candidate}`,
`POST /shots/{shot}/redo`, `POST /stitch`, `GET /media?path=`.
`POST /api/video-analysis/{id}/recreate` is the same start call and returns
the legacy `VideoRecreationResponse`. Types: `backend/film/video_reproduce_models.py`
↔ `frontend/types/video-reproduce.ts`.

## Tests

- `backend/tests/test_motion.py`: the similarity fit on synthetic pan / zoom /
  roll / subject fields, jitter → handheld, the classifier, and the real
  analyzer over `samples/clip-01.mp4`.
- `backend/tests/test_video_reproduce.py`: flow → shot/spec/prompt, flow
  failure degrades, per-section VLM with repair, one job per candidate with
  lineage + snapping + I2V conditioning, selection/pick/redo/restitch, a failed
  render recorded not hidden, cancel from History, refusals, and the real
  ffmpeg stitcher doubling the sample clip.
- `e2e/video-reproduce.spec.ts`: the strip fills live, every candidate plays,
  pick / redo / stitch / cancel, zero console errors (UI mock).
- Real-GPU: `docs/RTX_4070_TEST_MATRIX.md`.
