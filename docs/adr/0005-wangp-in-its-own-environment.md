# ADR 0005 — WanGP runs in its own environment, as a worker process

**Status:** accepted (post-audit, 2026-09-26)

## Context

The RTX 4070 audit (`docs/HERMES_REVIEW.md`, PR #2) found that the documented
Windows setup forced a choice between a working app and working gates:
81 of Wan2GP's ~99 requirements are not in `backend/uv.lock`, yet the bridge
imported `shared.api` into the backend's own interpreter. `setup:dev:win`
installed WanGP's requirements into `backend/.venv` — generation worked,
pyright failed — and any later `uv sync` pruned them, so the first render
returned `500 No module named 'gradio'`.

Two ways out: lock WanGP's requirements into the backend, or give WanGP its
own environment. Locking would pull WanGP's hard pins (gradio 5.29, a
nightly onnxruntime-gpu, platform-specific insightface wheels, …) into every
backend dependency decision, and every WanGP update would become a backend
lock change. The repo already runs other heavy stacks beside the backend in
their own venvs (`.venv-vision`, `.venv-trainer-*`).

## Decision

- WanGP gets its own venv at `Wan2GP/.venv`, created by
  `scripts/ensure-wangp-venv.{ps1,sh}` (called by `setup:dev:*`): Python
  3.12, CUDA PyTorch 2.10.0 / torchvision 0.25.0 / torchaudio 2.10.0 from the
  cu128 index (the combination the audit rendered with), then
  `Wan2GP/requirements.txt` constrained to that torch build, then an import
  check of `shared.api`.
- When WanGP's interpreter differs from the backend's
  (`select_wangp_mode()` → `"worker"`), the backend starts
  `backend/wangp_worker.py` under it and drives it with
  `WorkerWanGPBridge`, a subclass of `RemoteWanGPBridge` — the same
  `/api/wangp/*` protocol as the container server (ADR 0002), so the
  manifest the backend builds is byte-for-byte what WanGP receives. Being on
  the same machine, inputs go by path and outputs are read in place.
- The worker is standard library only (plus the stdlib-only bridge module,
  loaded by file path), binds 127.0.0.1 on an ephemeral port, requires a
  per-launch bearer token, and exits when its stdin pipe closes — i.e. with
  the backend, even on a crash — so it can never linger holding VRAM. The
  backend talks to it through a loopback client with proxies disabled.
- It is started in the background at backend startup (WanGP's first import
  is slow) and restarted on the next render if it died.
- Model discovery (`defaults/*.json`, `ckpts/`) stays in the backend — it is
  file reading — so status and the Models tab do not need the worker.
- Packaged builds and the container keep one shared environment built once
  (`prepare-python`, the Dockerfile) and never re-synced, so they stay
  in-process: WanGP's interpreter *is* the backend's, `select_wangp_mode()`
  returns `"in_process"`, and nothing changes there.

## Consequences

- `uv sync` in `backend/` can no longer break WanGP, and WanGP updates no
  longer touch `uv.lock`. Import errors in WanGP's environment are reported
  verbatim by the worker (`get_status().reason`, and the render error).
- Two Python processes on the GPU host. VRAM arbitration is unaffected: NVML
  reads the whole card, so the render guard and peak sampling see the
  worker's usage. As before, WanGP keeps its model resident between renders.
- Tested across the real process boundary (`tests/test_wangp_worker.py`):
  real subprocess, real loopback HTTP, a fake `shared/api.py`.
