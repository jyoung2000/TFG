# ADR 0001 — Local vision stack: in-process with an optional sidecar

**Status:** accepted (phase 2) · **Date:** 2026-09-26

## Context

Reproduce, video analysis and the 3D storyboard need local vision models:
Florence-2 (captions, detection, grounding), CLIP ViT-L/14 (style tags,
image embeddings), Depth-Anything-V2 (depth) and DINOv2 (structural
embeddings), plus an optional vision-language model (VLM) on Ollama. The
backend already carries `torch` and `transformers<5`, and it imports the
WanGP checkout **in-process** (`services/wangp_bridge.py::_load_api_module`),
so WanGP's pins live in the same interpreter.

The question was whether the vision models run in that interpreter or in a
sidecar with their own environment.

## Facts established

- `transformers` 4.57 (the version resolved by `backend/pyproject.toml`)
  ships native `Florence2ForConditionalGeneration`, `CLIPModel`,
  `DepthAnythingForDepthEstimation` and `Dinov2Model`, so **no
  `trust_remote_code` and no vendored model classes** are needed
  (verified in this session's venv, see `session-notes.md` VF-005).
- The WanGP checkout's `transformers` pin could not be inspected here (no
  checkout in the container; `download.pytorch.org` and `huggingface.co`
  are blocked by the sandbox's egress policy), so compatibility with a
  future WanGP pin is **unproven**.
- 12 GB of VRAM is the hard budget. Every model here is class S or M
  (≤ 3 GB); the VLM is class L and lives in Ollama, not in our process.

## Decision

1. **One contract:** `services/vision/protocol.py::VisionService`. The
   backend, the analyzers and the tests only see the Protocol.
   `FakeVision` is the test implementation; `test_no_mock_usage.py` still
   holds.
2. **In-process by default** (`services/vision/local_vision.py`): the
   model wrappers run in the backend interpreter, load lazily, and
   register with `services/vram/VramManager` so a render can unload them.
   Rationale: no second process to babysit on a desktop, the wrappers
   use only `transformers`/`torch` already present, and the shared
   interpreter is where the VRAM manager can actually free memory.
3. **Sidecar available, same code:** `backend/vision_worker.py` serves the
   same wrappers over loopback HTTP from its own environment
   (`backend/vision-requirements.txt`, `scripts/ensure-vision.{ps1,sh}`).
   The backend switches to it when `TFG_VISION_URL` is set and the worker
   answers `/health` (`services/vision/remote_vision.py`). This is the
   escape hatch for a WanGP pin that cannot load Florence-2, and the
   deployment shape for the compose stack (phase 9), where vision is its
   own service next to the backend and WanGP.
4. **Deterministic stats never cross a process boundary**: pure PIL/numpy
   (`services/vision/deterministic.py`), identical in both modes, with a
   TypeScript twin for instant client previews.
5. **VRAM classes**: S ≤ 1.5 GB, M ≤ 3 GB, L > 3 GB. Unload order before a
   render: Ollama VLM (`keep_alive: 0`) → DINO → depth → CLIP → Florence
   (kept when headroom allows). A render that still cannot fit fails with
   an actionable message, never a CUDA trace.

## Consequences

- Reproduce and video analysis work fully offline (Florence + CLIP + stats
  + depth), the VLM is optional and has its own settings slot
  (Settings → Vision), independent of the AI Director (fixes D9).
- Model weights are downloaded through the Model Library (`task=vision`)
  into `<app-data>/vision-cache/models/hf/` in the transformers cache
  layout, as `download` jobs visible in History.
- If the sidecar is used, it must see the same filesystem as the backend
  (paths, not bytes, cross the wire). The compose file mounts the outputs
  and app-data volumes into both services.
- Revisit when: WanGP moves to `transformers>=5` (then the sidecar becomes
  the default), or when the 3D scene build needs a pose model (class M) —
  the registry already carries the class for the arbitration.
