# TFG — debugging log (Hermes audit, RTX 4070)

Snapshot `hermes-review` @ `64bb6a3`, audited 2026-09-26 on Windows 11 build
26200 / RTX 4070 12282 MiB / driver 616.64 / Wan2GP `4fbc9827`. Branch
`review/hermes`. Working notes were kept in `docs/DEBUG_REPORT_notes.md` and this
document is the rebuilt, final version.

Every row was reproduced on this machine unless marked otherwise. "Not fixed"
means I could not prove a fix in one run, and I say why rather than shipping a
guess.

| ID | Area | Severity | Reproduction | Root cause (file:line) | Fix commit | Regression test | Status |
|---|---|---|---|---|---|---|---|
| F-001 | setup / docs | low | `git clone` + `git fetch origin`; `hermes-review` is neither HEAD nor listed by `git branch -a` | the branch exists only on the remote (`refs/heads/hermes-review` @ `64bb6a3`); a plain fetch does not create a local branch for it | — | — | open (docs) |
| F-002 | gates | — | `scripts/verify-hermes-ready.ps1` | — | — | — | **pass**, 29/29 ok, exit 0 |
| F-003 | gates | — | `pnpm typecheck:ts` | — | — | — | **pass**, exit 0 |
| F-004 | gates | — | `pnpm test:frontend` | — | — | — | **pass**, 53/53 in 9 files |
| F-005 | gates | — | `pnpm build:frontend` | — | — | — | **pass**; main chunk 308.16 kB (D-039 claimed 302 kB) |
| F-006 | **setup / deps** | **blocker** | `pnpm setup:dev:win` then `backend\.venv\Scripts\python -m pytest -q tests` → `No module named pytest` | `scripts/setup-dev.ps1:49` and `scripts/setup-dev.sh:39` run `uv sync --extra dev`; `uv sync` prunes unrequested extras, and `test` (`backend/pyproject.toml:48`) holds pytest | `1546fe4` | manual (the gate itself is the proof) | **fixed** |
| F-007 | **setup / deps** | **blocker** | same setup, then `backend\.venv\Scripts\pyright` → 10 errors | `scripts/ensure-wan2gp.ps1:101` pip-installs `Wan2GP/requirements.txt` into `backend\.venv` (`setup-dev.ps1:55`). Wan2GP pins `transformers==4.54.0`, `numpy==2.1.2`, `pydantic==2.11.10`, `diffusers==0.36.0`; `uv.lock` pins `transformers 4.57.6`, `numpy 2.4.2`, `pydantic 2.12.5`, `diffusers` @ git `01de02e8`. Setup wins and moves the venv off-lock | — | — | **open** (see F-017 for the architecture) |
| F-008 | **backend / vision** | **blocker** | in the setup-produced venv: `from transformers import Florence2ForConditionalGeneration` → `ImportError` | `backend/services/vision/florence2.py:128` needs transformers ≥ 4.56; the shared venv was forced to 4.54.0. The conflict is structural: `backend/services/wangp_bridge.py:364-366` does `sys.path.insert(0, wan2gp_root)` + `importlib.import_module("shared.api")` **in-process**, so both projects must share one interpreter | — | — | **open** (same root as F-017) |
| F-009 | gates / pyright | high | `cd backend && .venv/Scripts/pyright` → 10 errors | consequence of F-007: `floating[Unknown]`/`signedinteger` in `services/motion/flow_math.py:39`, `services/motion/motion_analyzer.py:11`, `services/vision/depth.py:124`, `services/vision/deterministic.py:64`, and the unknown import symbol at `florence2.py:128` | — | — | **resolved by restoring the lock** — with the locked deps pyright reports **0 errors** |
| F-010 | **setup / scripts** | **blocker** | `pnpm backend:dev:win` → PowerShell `ParserError`, backend never starts | `scripts/start-backend.ps1` and `scripts/docker-desktop-repair.ps1` are UTF-8 **without BOM** and contain U+2192. Windows PowerShell 5.1 decodes BOM-less files with the OEM codepage (IBM437 here), so `→` (E2 86 92) becomes `0x92` = `'`, closing the string literal early and cascading into ~8 parse errors | `4f8f5c3` | `[Parser]::ParseFile` over all 10 `.ps1` in `scripts/`: 2 failed before, 0 after | **fixed** |
| F-011 | **training / guard** | **high** | `POST /api/training/runs {"dataset_id":…,"config":{"target":"wan22","estimated_vram_mb":1,…}}` → **HTTP 200, run completes** | `backend/film/training_presets.py::fits_machine` compared `config.estimated_vram_mb` — a **request-body field** — against VRAM, so any hand-written config (MCP call, curl, stale UI payload) could lower the bar. `backend/handlers/training_handler.py:428` | `eac8f42` | `test_a_client_cannot_understate_the_vram_estimate_to_unlock_a_video_target` — proved red first (`assert 200 == 400`), green after; asserts both `wan22` and `ltx2` are refused and no trainer is touched | **fixed** |
| F-012 | gates / licences | medium | `pytest tests/test_licenses.py` after a local build → 407 AGPL offenders | `backend/tests/test_licenses.py:18` `SKIP_DIRS` omitted `python-embed` (gitignored, 0 tracked files) and `Wan2GP`, so the guard scanned ~28 MB of third-party wheels (cv2, ultralytics) | `e41b010` | re-proved by planting a real AGPL header at `backend/_agpl_probe.py` — still fails; removed → 4/4 pass | **fixed** (not weakened) |
| F-013 | gates / motion | medium | `pytest tests/test_motion.py::TestRealAnalyzer` → `AttributeError: module 'cv2' has no attribute 'calcOpticalFlowFarneback'` | **corrupted install, not code**: `site-packages/cv2/` held only `data/`, `gapi/`, `ml/` and a videoio DLL; 37 of the distribution's own files including `cv2/__init__.py` were missing, so `cv2` imported as an empty namespace package. Caused by the shared-venv `uv pip install` (F-007) | — (environment repair) | `tests/test_motion.py` 12/12 after `uv pip install --reinstall-package opencv-python-headless==4.13.0.92` | **fixed** (environment) |
| F-014 | gates / pyright | medium | `pytest tests/test_pyright.py` where pyright is not on PATH → `FileNotFoundError [WinError 2]` | `backend/tests/test_pyright.py:37` called `subprocess.run(["pyright", …])`; the raise happens before any output exists, so the `pytest.skip` in the `JSONDecodeError` handler (line 52) was unreachable | `5435d82` | the gate itself: now runs and reports 0 errors instead of crashing | **fixed** |
| F-015 | **backend / vision** | **high** | `POST /api/vision/analyze` on a real image → `200` but `caption: null`, `regions: []`, `notes:{"caption":"BartTokenizerFast has no attribute image_token"}` | `Florence2Processor.__init__` in transformers 4.57.6 (`models/florence2/processing_florence2.py:121`) reads `tokenizer.image_token`; the stock `BartTokenizerFast` for `microsoft/Florence-2-large` has no such attribute and the cached `tokenizer_config.json` contains only `model_max_length`. `GET /api/vision/status` still reports the component `available: true` — availability is a config/spec check, never an import or attribute check | — | — | **open, not fixed**: the fix is a transformers-version or model-asset decision I could not prove here |
| F-016 | training / UX | low | `POST /api/training/datasets/{id}/import` on a folder with `clip-01.mp4` + `README.md` | — | — | — | **works** — 3 of 5 imported, junk skipped |
| F-017 | **runtime / deps** | **blocker** | after any `uv sync`: `POST /api/generate-image` → `500 "No module named 'gradio'"`, then `"No module named 'mmgp'"` | `uv sync` prunes everything outside `backend/uv.lock`, but **81 of Wan2GP's 99 top-level requirements are not in that lock** (measured: apprise, gradio, mmgp, librosa, ultralytics, rembg, insightface, decord, timm, …). `WanGPBridge` imports `shared.api` in-process, so a render needs all of them | — | — | **open**: the repair is architectural (give Wan2GP its own venv, as the trainers already get `backend/.venv-trainer-*` per D-028, or lock the union) |
| F-018 | vram / docs | medium | `POST /api/generate` → `507 "Free 1.3 GB of VRAM before rendering: 8.5 GB free, 9.8 GB needed. Loaded: nothing this app owns."` | `backend/services/vram/vram_manager.py:34-43` `RENDER_NEEDS_MB["ltx2_22B_distilled"]=9500` + `SAFETY_MARGIN_MB=512`. The guard is **correct** — `nvidia-smi` confirms 8.95 GB is the ceiling — but the comment on line 33 says the table is "overridable in settings" and it is not: `render_needs_mb` is a constructor parameter (line 142) that **no caller passes** (`backend/app_handler.py:182`, `backend/vision_worker.py:78` both use defaults) | — | — | **open** (comment is wrong; numbers unproven either way) |
| F-019 | U1 render | — | `POST /api/generate-image` "a rain-soaked neon alley, cinematic", 1024², 8 steps | — | — | — | **measured**: 226.7 s cold, `peak_vram_mb` 8044 (app) / 7773 (`nvidia-smi`) |
| F-020 | **U2/U3 video** | **blocker** | `POST /api/generate` 540p · 6 s | two causes: (1) F-018's 9.8 GB bar exceeds the card's 8.95 GB ceiling; (2) with the bar forced down the job began downloading `ltx-2.3-22b-distilled_diffusion_model_quanto_int8.safetensors` (**19.4 GB**) even though `GET /api/models/library` reports `ltx2_22B_distilled installed: false` — the image path checks weights up front (`backend/handlers/video_generation_handler.py:370`), the WanGP path does not | — | — | **open**; guard restored to 9500, `git diff` clean |
| F-021 | History | — | two failed renders → `GET /api/jobs` | — | — | — | **works**: `status: failed`, real error text, prompt + seed kept, no orphans |
| F-022 | **U5 Reproduce** | **high** | import ×3 → `analyze` → `start {candidates:2, rounds:1, target_score:0.9}` | `backend/services/similarity/composite.py` + `backend/handlers/reproduce_handler.py`; see F-023 for why the scores are inflated | — | — | **open** — loop runs, scores not trustworthy, target never reached |
| F-023 | U5 scoring | high | same run: `spec.provenance`, `spec.subjects`, `scores.weights_used` | F-015 empties the spec (`provenance` has no `florence`, `subjects: []`, `scene` all empty), so the compiled prompt never describes the picture. Remaining weights: CLIP 0.39, DINOv2 0.28, SSIM 0.17, palette 0.17 — SSIM+palette are 0.33 and both are satisfied by "brownish, similar layout" | — | — | **open** (chained to F-015) |
| F-024 | **U13 preset** | **high** | apply `rtx-4070-12gb`, read `GET /api/settings/presets` | `backend/state/hardware_presets.py` selects `florence-2-large` and a video profile whose `changes` text promises "a clip in about a minute on a 4070" | — | — | **open** — the preset advertises F-015 and F-020 |
| F-025 | U13 persistence | — | apply preset → restart backend → `GET /api/settings` | — | — | — | **works**: `hardwarePreset`, `videoProfile`, `imageSteps`, `vision.vlmProvider` all survive |
| F-026 | Film Studio | — | film → 3 assets → scene → 3 shots → queue pause/resume | — | — | — | **works** (structure); render half blocked by F-020 |
| F-027 | 3D storyboard | medium | `POST /api/scene/build` with a real ShotSpec | solver is sound (`reprojection_error: 0.0`, real depth map, SVG blockout) but `objects: []` because `spec.subjects` is empty (F-015) | — | — | **open** (degraded by F-015) |
| F-028 | two renders at once | — | concurrent `POST /api/generate-image` | — | — | — | **works**: A `200` 18.9 s, B `409 "Generation already in progress"` |
| F-029 | U1 steady state | — | warm 1024², 8 steps | — | — | — | **measured**: 30.0 s, `peak_vram_mb` 6524 |
| F-030 | **MCP / safety docs** | **medium** | apply the documented `tools: exclude: [system_shutdown]` and look for that tool | `docs/AGENTS_GUIDE.md:33,94` and `skills/tfg/SKILL.md:54,131` all name `system_shutdown`; `tools/list` contains **no such tool**. The real one is **`health_shutdown`** (from `POST /api/system/shutdown`, tagged `health`), so the documented exclusion silently matches nothing | `71e8fdf` | verified against `tools/list` | **fixed in docs**; renaming the tool would be the better fix |
| F-031 | MCP surface | — | `initialize`, `tools/list`, `tools/call` ×{valid, unknown tool, bad method, missing field, bad id} | — | — | — | **works**: exactly **214** tools; `-32602`/`-32601`; `isError` with FastAPI text |
| F-032 | **e2e / infra** | **blocker** | `pnpm e2e` → `Error: Timed out waiting 120000ms from config.webServer` | two Windows-only causes: (1) `playwright.config.ts:15` polled `http://127.0.0.1:5173` (IPv4) while Vite's default host `localhost` binds `[::1]` only on Windows (`netstat` confirmed `TCP [::1]:5173 LISTENING`); (2) line 38 ran `pnpm dev:ui -- --port N --strictPort --host 127.0.0.1` — pnpm forwards the bare `--`, vite reads it as end-of-options, so **every flag was discarded**. Underneath both, Vite's dep scanner descended into `python-embed/` and tried to pre-bundle gradio's bundled Svelte app | `71e8fdf` | `pnpm e2e` → **28 passed (2.0 m)** | **fixed** |
| F-033 | **agent tooling** | high | `echo '{…initialize…}' \| pnpm agent:mcp` → `ModuleNotFoundError: No module named 'torch'` | `package.json` `"agent:mcp": "python backend/tfg_mcp.py"` used bare `python` from PATH (3.11.15, no deps) while the project pins 3.12 in `backend/.venv` | `71e8fdf` | `pnpm agent:mcp` → `TFG MCP: 214 tools` + valid `initialize` | **fixed** |
| F-034 | **break-it** | medium | `POST /api/generate-image {"width":99999,"height":99999}` → `500 CUDA error: out of memory` | no upper bound on width/height before the render reaches CUDA; every other VRAM path in this app refuses politely | — | — | **open** (not fixed — the correct bound is a product decision) |

### Fixes shipped on `review/hermes`

`4f8f5c3` scripts BOM · `1546fe4` setup test extra · `eac8f42` training VRAM
floor · `e41b010` licence guard scope · `5435d82` pyright resolution · `71e8fdf`
e2e host/flags + `agent:mcp` + shutdown-tool docs. Each fix ships with the
evidence that proved it, in the commit body.

---

## External facts verified against the real installation

I checked these against the actual Wan2GP checkout and the actual venv, not from
memory. `Wan2GP` @ `4fbc9827bad970be22d933470e0b7ffec31c99f9`.

**WanGP settings keys — all eight named in the brief exist and are used as
TFG sends them** (`backend/services/wangp_bridge.py:230-270`):

| Key | Occurrences in Wan2GP | TFG sends it | Semantics confirmed |
|---|---|---|---|
| `activated_loras` | 20 | yes (:269) | list of absolute paths |
| `loras_multipliers` | 26 | yes (:270) | space-separated, same order |
| `image_refs` | 54 | yes (:237) | list of paths |
| `image_start` | 40 | yes (:230) | start frame |
| `image_end` | 26 | yes (:234) | end frame |
| `video_guide` | 35 | yes (:250) | guide video path |
| `video_prompt_type` | 125 | yes (:238, :249) | letter flags |
| `image_mask` | 13 | no | not currently used |

**The two semantics the builder could not verify (VF-008, VF-013) — now
verified:**

- `"I"` is the image-refs letter: `Wan2GP/shared/api.py:91-92` adds `"I"` to
  `video_prompt_type` when `image_refs` is set; `wgp.py:1380,1386` reads it. TFG
  appends `"I"` at `wangp_bridge.py:238`. **Matches.**
- `"V"` is the guide-video letter, and TFG's replace-then-append logic is right:
  `wgp.py:3164-3171` manipulates exactly these letters. **Matches.**
- `image_ref_choices` / `one_image_ref_only` exist (`wgp.py:1386,3208`), which is
  the per-model nuance VF-008 could not confirm. TFG's *image-edit* path still
  raises an actionable error rather than guessing (VF-008's mitigation holds).

**musubi-tuner (VF-015, VF-016):** the repo's recipe is consistent with the
builder's notes — `--fp8_base --fp8_scaled --blocks_to_swap`, `zimage_train_network.py`,
and the catalog's refusal text ("Wan 2.2 video LoRA training needs 24 GB per
musubi-tuner's documentation") matches the upstream README's "12GB or more
recommended for image training, 24GB or more for video training". I did not
install musubi-tuner, so the *command line* is verified only against the tests
that assert it, not by execution.

**Hugging Face repo ids and sizes actually on disk** (from
`GET /api/models/library`): `openai/clip-vit-large-patch14` 1.0 GB (installed),
`depth-anything-v2-small` 0.2 GB (installed), `microsoft/Florence-2-large` 1.7 GB
(cache present, **not functional** — F-015), `florence-2-base` 0.6 GB,
`dino(v2)-small` 0.1 GB, `dino(v2)-base` 0.4 GB, `promptgen-large-v2` 1.7 GB,
`z_image` (installed), `ltx2_22B_distilled` **not installed** (19.4 GB
quantised int8 checkpoint, F-020).

**Wan 2.2 5B model key (VF-020):** still **not offered** by the 4070 preset, and I
did not add one — consistent with the builder's decision, which I could not
contradict from the checkout.

### Could not verify

- That the 9.8 GB video VRAM figure is *correct* (only that it is unreachable and
  undocumented as overridable). Establishing the true figure needs a real render,
  which needs 19.4 GB of weights and a free GPU.
- The README's "6 GB" headline, on any code path.
- Any real LoRA training run, the container stack, and the Electron UI by hand —
  reasons in `docs/HERMES_REVIEW.md` → *Could not test*.
- The `Florence2ForConditionalGeneration` availability claim (VF-005) holds in
  the *locked* transformers 4.57.6 but not in the venv the documented setup
  produces (F-008) — both verified.
