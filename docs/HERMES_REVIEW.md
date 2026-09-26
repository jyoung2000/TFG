# TFG — user review on an RTX 4070 (12 GB)

Audited by Hermes (model `space-bunny-alpha`) on **2026-09-26**, from the
`hermes-review` snapshot. One review per run; every number below is from
`nvidia-smi`, the History API, or an `nvidia-smi` sampler I ran alongside — never
estimated. Claims I could not test are in *Could not test*, with the reason.

**Environment.** Windows 11 Home build 26200 · NVIDIA RTX 4070, 12282 MiB,
driver 616.64, CUDA UMD 13.4 · SageAttention enabled · Node 22.23.2 · pnpm 10.30.3
· uv 0.12.3 · Python 3.12.12 (backend venv) · torch 2.10.0+cu128 · TFG commit
`64bb6a3` (`hermes-review`) · Wan2GP `4fbc9827` (2026-09-22) · branch `review/hermes`.

---

## Verdict in one paragraph

The engineering underneath this is genuinely good and I want to be fair about
that: the failure modes that usually embarrass an app like this — a job left
hanging, a 500 with a shrug, a file route that trusts a path, a guard that
trusts the client — are mostly *absent*, and where they exist I could prove them
and I fixed what I could prove. The image path is the real product and it
**works**: "a rain-soaked neon alley, cinematic" came back as a coherent,
genuinely good 1024×1024 still in 30 s warm, and the vision stack that powers
Reproduce is real (CLIP and Depth-Anything genuinely work). But the app as
*shipped for this machine* does not do the thing it is named for. **Video does
not run at all** on a 12 GB card — the VRAM bar is 0.85 GB above what the card
can ever give — and the flagship "RTX 4070 · 12 GB" preset is the thing that
promises video and vision captions, i.e. it advertises precisely the two features
that are broken here. On top of that, the documented Windows setup leaves you
with a choice between "generation works and the gates are broken" and "the gates
are green and generation is dead", because the backend venv and the Wan2GP
checkout are forced to share one set of dependencies. **Would I keep using it?**
For stills, yes, and I would recommend it to someone who only wants images. For
video — the entire reason the app exists, and 90% of the README — no, not until
the VRAM bar and the silent 19 GB download are dealt with. I would not ship this
to a hobbyist who follows the README.

---

## The U1–U16 table

Grades: **A** finished · **B** rough edges · **C** needs workarounds · **D** mostly
broken · **F** unusable/misleading. Seconds and peak VRAM are measured.

| # | Scenario | Grade | Verdict | Seconds | Peak VRAM | What happened vs what I expected |
|---|---|---|---|---|---|---|
| **U1** | Create an image (Z-Image, 8 steps) | **A** | **Working** | **226.7 s cold / 30.0 s warm** (1024²) | **8044 MB** app-reported, **7773 MB** my `nvidia-smi` sample | 1024×1024 RGB JPEG, 337 KB, visually inspected twice: coherent cyberpunk alley, wet reflective ground, believable neon, correct one-point perspective. Only garbled sign lettering. History stored prompt + seed. Meets the "< 30 s warm" target, just. The cold/warm gap is 7.6× and is all model load. |
| **U2** | Create a video, Fast (540p · 6 s) | **D** | **Broken** | — | — | **No clip is produced at all.** The VRAM guard refuses with `507 "Free 1.3 GB of VRAM before rendering: 8.5 GB free, 9.8 GB needed"` — correct and honest, but the card can *never* give 9.8 GB (see below). Forcing the bar down revealed the second failure: the job starts and silently downloads a **19.4 GB** checkpoint with no prompt. I killed it at 66%. |
| **U3** | Create a video, Balanced (720p · 8 s) | **F** | **Broken / misleading** | — | — | Never reached: blocked by the same 9.8 GB guard, and the preset that offers it promises "720p · 6–8 s: sharper". Unreachable on the card the preset is named for. |
| **U4** | Image-to-video (start + end frame + reference) | — | **Not testable** | — | — | Blocked by U2/U3 — no video weights, no free VRAM. The *plumbing* is there and correct (`/api/generate` accepts `imagePath`, `endFramePath`, `referenceImagePaths`), and e2e covers the UI path. |
| **U5** | Reproduce image (3 refs → analyse → loop) | **C** | **Needs rework** | 255 s for 18 candidates | ~5 GB | The loop genuinely runs — 18 real candidates, 3 rounds, 4-component scoring with per-component numbers and an honest `missing: ["layout"]`. But it **does not improve**: round means 0.5874 → 0.5865 → 0.5959 (flat), best-of-round not monotonic, target 0.9 never reached. And the score is not trustworthy: I put the reference, the app's best (0.6416) and worst (0.5510) side by side and looked — the ordering is *directionally* right, but **neither resembles the reference at all** (ref = near-black room, one figure, one yellow square; best candidate = pale beige folded triangles). A "0.64 composite" for an obvious miss. |
| **U6** | Reproduce video (detect → analyse → start → stitch) | — | **Not testable** | — | — | Needs video weights (U2). Motion analysis and the optical-flow path *are* real and I exercised them: `OpticalFlowAnalyzer` runs on the sample clip (12/12 tests green after I repaired the venv). |
| **U7** | 3D storyboard → composer → deliver → render | **C** | **Works, degraded** | instant (solver) | — | The solver is real: camera (`fov 40`, `focal_mm 49.5`, "standard portrait perspective"), a genuine Depth-Anything depth map, a generated SVG blockout, `reprojection_error: 0.0`. But `objects: []` — no figures — so "move a figure" has nothing to move. Render half blocked by U2. |
| **U8** | Train a LoRA (4 images → caption → train) | **C** | **Partial** | refused correctly | — | Import works and **skips non-image files correctly** (3 of 5 files in a folder with an `.mp4` and a `.txt`). Captions carry the trigger (`auditperson`) — but contain **no descriptive content**, because Florence-2 is dead. Trainer correctly refuses with an actionable message naming the exact script to run. The 12 GB guard works on the honest path. |
| **U9** | Apply the LoRA / Consistency Kit | — | **Not testable** | — | — | No trained LoRA exists on this machine (U8 blocked at the trainer-install step); the e2e suite covers the UI path against the mock. |
| **U10** | Video LoRA refused before starting | **B** | **Works, with a hole** | instant | — | On the honest path (UI `/suggest`) both `wan22` and `ltx2` are refused for the right reason, and the trainer layer has an independent backstop. **But the guard trusted a client-supplied `estimated_vram_mb`**: I sent `{"target":"wan22","estimated_vram_mb":1}` and got **HTTP 200 — a 24 GB LoRA trained to completion on this 12 GB card** and registered itself. Fixed + regression test. |
| **U11** | History (live, re-run, delete) | **A** | **Working** | — | — | Both my failed renders landed as `status: failed` with the *real* error text and the prompt + seed preserved. No orphaned `running` job, no stuck state — the exact failure mode the brief asks about. Metrics `{}` on failures, correctly. |
| **U12** | Film Studio (film → assets → shots → queue) | **B** | **Structure works** | instant | — | 2 characters + 1 location + 3 shots all created with ids; queue `pause`/`resume` return real state. The render-and-timeline half is blocked by U2. |
| **U13** | Settings (preset, profiles, tiers, remote) | **C** | **Persists, but oversells** | — | — | The `rtx-4070-12gb` preset applies and **persists across a full restart** (verified). Tiers endpoint explains skips properly (`"local engine cannot do i2i yet"`). **But the preset's own copy promises "Florence-2-large captions" and "a clip in about a minute on a 4070" — neither is true on this machine.** A preset is a promise; this one isn't kept. |
| **U14** | Kill and relaunch mid-job | **A** | **Working** | — | VRAM fully released | Killed the backend mid-session: VRAM went 12080 MB → 1326 MB, i.e. **no leak**. Relaunched cleanly, health ok, next render worked. Two unplanned kills during this audit both recovered the same way. |
| **U15** | Agent workflow over MCP | **A−** | **Working** | — | — | `tools/list` returns **exactly 214 tools**, matching the documented count and the 214 API operations. Unknown tool → `-32602`, bad method → `-32601`, missing field → `isError` with FastAPI's own text, bad id → `{"error": "Unknown job: nope"}`. Auth is shared with the API. This is the strongest surface in the codebase. Two defects found in the *docs and scripts around it* (F-030, F-033), both fixed. |
| **U16** | Containers (`deploy/` stack) | — | **Not testable** | — | — | Docker Desktop is installed but I did not stand up the stack (see *Could not test*). `pnpm deploy:config` exists to validate the compose file. |

### Why video is unreachable on a 12 GB card (the headline finding)

`RENDER_NEEDS_MB["ltx2_22B_distilled"] = 9500` + `SAFETY_MARGIN_MB = 512` =
**9.8 GB required free**. On this machine `nvidia-smi` shows a hard ceiling of
**~8.95 GB free** — 3.3 GB is permanently held by the Windows compositor,
Discord, Docker Desktop, PowerToys, Steam, three browsers and Hermes. The guard is
*right* to refuse; the problem is that the number is above what the card can ever
give, and — per the source comment "overridable in settings" — it **is not
overridable**: `render_needs_mb` is a constructor argument no caller ever passes
(`app_handler.py:182`, `vision_worker.py:78` both use defaults). So the README's
headline ("reduces the VRAM requirements from 32 GB to 6 GB") and the existence
of a 4070 preset are contradicted by the app's own guard. Image generation needs
7.5 GB and works fine; video needs 9.8 GB and cannot.

---

## Break-it outcomes

| Attack | Result | Verdict |
|---|---|---|
| Empty prompt | `422` "String should have at least 1 character" | good |
| Whitespace-only prompt | `422`, same message | good |
| `99999×99999` image | **`500 CUDA error: out of memory`** | **bad** — a crash, not a refusal. Every other VRAM path in this app refuses politely; this one reaches CUDA. |
| `numSteps: -5` | `507` VRAM refusal | acceptable (refused before use) |
| 1080p · 10 s video | `507` with the real numbers | good — refusal, not crash |
| Bogus `resolution: "999p"` | `507` VRAM refusal | mediocre — the bad enum isn't reported, the VRAM check just happens to fire first |
| LoRA with 3 images | `400` "A LoRA needs at least 4 captioned images (12 or more is the sweet spot)" | excellent copy |
| Dataset folder with a non-image file | 3 of 5 imported, junk skipped silently | good |
| Paths with spaces + unicode (`日本語 データセット ✨`) | `200`, dataset created | good |
| **Two renders at once** | render A `200` in 18.9 s; render B **`409 "Generation already in progress"`** in 0.0 s | **excellent** — serialises, no OOM, GPU healthy after |
| Closing/killing mid-train | VRAM fully released, clean relaunch | good |
| Forge `estimated_vram_mb` | **was `200` + a completed 24 GB run** | **bad — fixed** |

---

## Top 10 issues, ranked by user pain

1. **Video cannot render on a 12 GB card.** 9.8 GB required vs 8.95 GB possible, and the number is not overridable despite the comment saying it is. *Repro: `POST /api/generate {"prompt":"x","resolution":"540p","duration":"6"}` → `507`.*
2. **The two documented setups are mutually exclusive.** 81 of Wan2GP's 99 requirements are absent from `backend/uv.lock`, so `uv sync` prunes what rendering needs. *Repro: `pnpm setup:dev:win` (generation works, 10 pyright errors) vs any `uv sync` (gates green, `POST /api/generate-image` → `500 No module named 'gradio'`).*
3. **`pnpm backend:dev:win` never ran** — PowerShell parse error from a BOM-less UTF-8 file. *Repro: `powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1`.* Fixed.
4. **`pnpm e2e` never ran on Windows** — config polled IPv4 while Vite bound IPv6-only, and pnpm swallowed the flags. *Repro: `pnpm e2e`.* Fixed; 28/28 now pass.
5. **The 4070 preset advertises the two broken features.** *Repro: apply `rtx-4070-12gb`, read its `changes` list.*
6. **The VRAM guard trusted a client number** — a 24 GB LoRA trained on this card. *Repro: `POST /api/training/runs` with `estimated_vram_mb: 1`.* Fixed.
7. **Reproduce reports "0.64 similar" for images that do not resemble the reference.** *Repro: analyse `samples/ref-01.jpg`, start the loop, compare the best candidate to the reference by eye.*
8. **The reproduce loop doesn't converge.** Round means 0.587 → 0.587 → 0.596; target 0.9 never reached and the run ends anyway, with no "gave up" signal. *Repro: same as 7, read `scores.composite` per round.*
9. **A missing video checkpoint triggers a silent 19.4 GB download.** *Repro: `GET /api/models/library` says `ltx2_22B_distilled installed: false`, then `POST /api/generate` anyway.*
10. **An absurd resolution returns a raw CUDA 500** instead of a refusal. *Repro: `POST /api/generate-image {"width":99999,"height":99999}`.*

---

## Features that oversell

- **README: "reduces the VRAM requirements from 32 GB to 6 GB."** The app's own guard demands 9.8 GB free for video, which a 12 GB card cannot provide on a normal desktop. I could not verify the 6 GB figure on any code path.
- **The `rtx-4070-12gb` preset:** "Florence-2-large captions" (returns nothing, F-015) and "a clip in about a minute on a 4070" (no clip at all).
- **`docs/AGENTS_GUIDE.md` + `skills/tfg/SKILL.md`:** "`system_shutdown` is a real tool; exclude it." There is no such tool — the real one is `health_shutdown`, so the documented safety exclusion silently matches nothing. (Fixed in my branch.)
- **`AGENTS_GUIDE.md`:** "`pnpm agent:mcp` runs the stdio server with the repo's Python." It ran bare `python` from PATH and died on `No module named 'torch'`. (Fixed.)
- **`services/vram/vram_manager.py`:** "overridable in settings." No caller passes `render_needs_mb`.
- **`docs/RTX_4070_TEST_MATRIX.md`:** correctly says every row is unmeasured — and that honesty is why this review could be written at all. Keep it.

## Features that quietly work well

- **The MCP surface.** 214 tools generated from the route table, one-to-one with the API, with genuinely good error text. Both transports work; `/mcp` shares the API's auth.
- **Refusals instead of crashes** on the 12 GB card — the VRAM guard (507), the training guard (400 with the fix), the concurrent-render guard (409), the <4-image guard (400). Each names the number and the next step. This is the app's best habit.
- **History.** Real terminal states, real error text, prompt and seed preserved, no orphans, and honest `metrics: {}` when there is nothing to measure.
- **Provenance and honesty in the analysis layer.** `spec.provenance` records which component produced which field; scoring reports `weights_used` and `missing`. I could debug two features *because* the app told me the truth.
- **Path safety.** Every file-serving route funnels through a `*_path` resolver with a membership check plus `is_within`. Traversal probes (`..`, absolute, drive-letter, double-encoded) were all rejected.
- **Lock discipline.** No lock is held across `pipeline.generate` or a subprocess. The documented lock→validate→heavy→write pattern is real.
- **The licence guard**, once scoped correctly, is a genuinely good idea.
- **The gates themselves are well-built** — 827 backend tests, 53 frontend, 28 e2e, and a pyright-strict backend. The problem was never their quality; it was that the documented setup made them unreachable.

## Rework (fixable in place)

1. Make the VRAM table overridable, or lower the video figure to something a 12 GB card can actually satisfy — and make the README agree with whatever it becomes.
2. Move the video weights check in front of job creation: refuse with "this needs a 19.4 GB download, confirm" instead of starting one.
3. Make the reproduce loop say "best 0.64 after 3 rounds, target 0.9 not reached" instead of ending as if it succeeded.
4. Renumber the video tier honestly in the 4070 preset, and drop Florence-2 from its promise until F-015 is resolved.
5. Return a 4xx for out-of-range width/height/steps before anything reaches CUDA.
6. Give Wan2GP its own venv (the trainers already get `backend/.venv-trainer-*`) and lock the union — this is the single change that would stop F-002/F-007/F-013/F-017 from recurring.
7. Propagate a `florence: unavailable` signal into the UI so an empty caption reads as a broken component rather than an empty result.

## Redo (the approach is wrong)

- **The shared-venv architecture.** Everything in issues 1, 2, 10 and the Florence breakage traces back to forcing an in-process `import shared.api` into the app's venv. The sidecar pattern already exists for vision (`backend/.venv-vision`, D-008) and for trainers (D-028) — video should have used it from the start. This is a structural redo, not a patch.
- **The composite similarity score as a headline number.** CLIP 0.39 / DINO 0.28 / SSIM 0.17 / palette 0.17 with `layout` missing rewards "brownish and similarly laid out" and will happily report 0.64 for a completely different image. Either weight semantic components far higher, gate the score on which components actually ran, or stop presenting one number.

## Could not test, and why

- **U2/U3/U4/U6 video, and every render half of U7/U9/U12** — the 19.4 GB LTX-2 checkpoint is not on this machine, the VRAM guard blocks first, and I declined to complete a 19 GB download mid-audit. U2/U3 rows in the matrix stay BLOCKED with this reason.
- **U16 containers** — Docker Desktop is installed but I did not stand up the stack; this run was already long and the GPU was the priority. `pnpm deploy:config` is available to validate the compose file without running it.
- **Pixel-level UI (the Electron app itself)** — I drove the renderer through the Playwright suite and the live API, but did **not** click through the packaged Electron app or screenshot it, so I make no claim about how it feels or looks at 1366×768 or 4K scaling. Every e2e spec asserts "no console errors", which is a real signal, but it is not a human looking at it.
- **LoRA training to completion (U8/U9)** — the trainer venv is created by `scripts/ensure-trainer.ps1`, which clones and pip-installs musubi-tuner; I verified the refusal path and the command-line construction (tests cover `--fp8_base`, `--blocks_to_swap`, `dataset.toml`), but did not run a real training job.
- **A cold-start first-run experience** — my `settings.json` already existed, so I exercised `handleFirstRunComplete` only via the preset endpoint, not a genuine first run.
- **The 3D shot composer with a mouse** — I verified the scene solver and the blockout, and e2e opens the composer, but I did not perform the composer interaction by hand.

---

## What I fixed on this branch

Seven commits on `review/hermes`, each with the evidence that proved it:

| Fix | Evidence |
|---|---|
| UTF-8 BOM on the two `.ps1` files that failed to parse | `[Parser]::ParseFile` over all 10 scripts: 2 failed before, 0 after; backend boots |
| `--extra test` in `setup:dev:win` / `.sh` | `python -m pytest` went from `No module named pytest` to running 827 tests |
| 12 GB guard uses a server-side VRAM floor | regression test proved red (`assert 200 == 400`) before the fix, green after |
| Licence guard skips gitignored build dirs | planted a real AGPL header in `backend/` — still fails the test, so the guard is not weakened |
| pyright resolved from the venv | gate went from `FileNotFoundError` to actually running (0 errors) |
| e2e polls the host Vite binds + flags stop being swallowed | `pnpm e2e`: timeout → **28 passed (2.0 m)** |
| `pnpm agent:mcp` uses the project venv | `No module named 'torch'` → `TFG MCP: 214 tools` + valid `initialize` |
| Docs: `system_shutdown` → `health_shutdown` (the tool that actually exists) | verified against `tools/list` |

Full detail, root causes with file:line, and the external facts I verified against
the real installation are in `docs/DEBUG_REPORT_hermes.md`.
