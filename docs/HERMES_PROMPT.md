# Hermes: test TFG like a user and grade it

Paste everything below the line into Hermes Agent as the task. The only
other thing it needs is the repository:
`https://github.com/jyoung2000/TFG` (branch **`hermes-review`**, the frozen snapshot cut for this review).

---

You are the first real user of **TFG**, a local AI image/video studio for an
RTX 4070 (12 GB): Create (images and clips), Reproduce (an image or a video
→ analysed, rendered, scored and refined until it matches), a 3D storyboard
with a shot composer, Train (LoRAs from a folder, a video or earlier
results), History (every job, live), a Film Studio, containers, a remote
backend and an MCP server that exposes every feature to you.

Your job: **set it up from the repository alone, use every feature the way
a filmmaker or hobbyist would, and write an honest review** — what works,
what is broken, what should be reworked or thrown away — with a grade per
feature and overall. You are a critical customer, not a contributor:
report, do not fix (file precise findings instead). Never claim something
worked that you did not observe; if you could not test a feature, say why.

## 1. Set up (Windows with the RTX 4070; the app is Windows-first)

```powershell
git clone https://github.com/jyoung2000/TFG.git
cd TFG
git checkout hermes-review
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line must say ok
corepack enable; corepack prepare pnpm@latest --activate   # Node 18+ required
pnpm setup:dev:win        # installs deps, backend venv (uv), clones Wan2GP into .\Wan2GP
```

Read `README.md` ("Windows WanGP Quick Start", "What do you want to make?"),
`docs/AGENTS_GUIDE.md`, `skills/tfg/SKILL.md`, and skim `session-notes.md`
(the builder's own log of what was verified and what is BLOCKED).

Then start a **headless backend** for yourself (no Electron needed for the
API and MCP):

```powershell
pnpm backend:dev:win      # prints the URL, data folder, WanGP root and the MCP command
```

Connect your MCP client (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  tfg:
    command: "<repo>\\backend\\.venv\\Scripts\\python.exe"
    args: ["<repo>\\backend\\tfg_mcp.py"]
    env:
      TFG_BACKEND_URL: "http://127.0.0.1:8000"
    tools:
      exclude: [system_shutdown]
```

`hermes mcp test tfg` must list ~214 tools. Install the skill from your
clone: `hermes skills install <repo>\skills\tfg` (the GitHub shortcut
`jyoung2000/TFG/skills/tfg` reads the repository's default branch, which
does not carry this snapshot yet — use the local path). If anything in this setup step fails or is unclear,
that is your **first finding** — a user hits it before anything else.

Also launch the desktop app once (`pnpm dev`) and note the first-run
experience: does the *RTX 4070 · 12 GB* preset apply, does Home load
without console errors, is the four-verb front door understandable?

## 2. Use every feature (through MCP, the API, and the app)

Do each scenario as a user would, then grade it. Record timings and peak
VRAM from History (`jobs_get_job` → `metrics`) and from `nvidia-smi`.

| # | Scenario | What a user expects |
|---|---|---|
| U1 | **Create an image**: "a rain-soaked neon alley, cinematic" (Z-Image, 8 steps) | a good still in < 30 s after warm-up; History shows it with prompt and seed |
| U2 | **Create a video, Fast**: same prompt, 540p · 6 s | a clip in about a minute; progress visible; cancel works mid-render and frees VRAM |
| U3 | **Create a video, Balanced**: 720p · 8 s | fits in 12 GB; visibly sharper; roughly 3× slower |
| U4 | **Image-to-video** from U1's still, with an end frame and one reference image | motion from the still; the end frame honoured |
| U5 | **Reproduce image**: three references (a portrait, a landscape, a product shot) → Analyse → Start loop (6 per round, 3 rounds, target 0.9) | the evidence panel is believable; candidates improve round over round; the best one actually resembles the reference; pin and the fix canvas do what they say |
| U6 | **Reproduce video**: a 10 s clip with one cut and a pan → Detect → Analyse → Start (2 candidates) → pick → stitch | the two shots are found; the pan shows up in the spec; candidates match framing; stitched clip plays |
| U7 | **3D storyboard** from U6: Build 3D storyboard → open a shot in the composer → move a figure, change the camera → Deliver → render | blockout thumbnails match the shots; the composer is usable with a mouse; the render follows the delivered camera/depth |
| U8 | **Train a LoRA**: 8–12 photos of one subject → auto-caption → Z-Image, character preset → train | captions carry the trigger; the run fits 12 GB; loss curve and samples update live; cancel then resume works; the LoRA appears in the registry |
| U9 | **Apply the LoRA** in U1 and in a Film character (Consistency Kit: bind, seed lock, reference sheet) | the subject is recognisable; the reference sheet is consistent across angles; a film shot inherits the LoRA and trigger |
| U10 | **Video LoRA attempt**: pick Wan 2.2 or LTX-2 as the training target | refused *before* anything starts, with a reason that makes sense |
| U11 | **History**: run U2 while History is open; re-run a job; delete one | live updates without refresh; lineage correct; delete removes what it says |
| U12 | **Film Studio**: new film → two characters, a location → three shots → queue previews → timeline | the queue renders in order, pause/resume works, versions land on the shots |
| U13 | **Settings**: hardware preset card, video profile, fallback tiers, vision stack toggles, remote backend card (test against your own backend URL) | every change persists after restart; the tiers editor explains why a tier is skipped |
| U14 | **Kill and relaunch**: kill the backend during U3, start it again | the job is marked failed with a clear message; nothing is stuck; the next render works |
| U15 | **Agent workflow**: do U1, U2, U5 and U8 purely through your MCP tools | every tool call has a sensible schema and error text; long jobs are followable via `jobs_*`; nothing needs the GUI |
| U16 | **Containers** (only if you have Docker with an NVIDIA GPU): `deploy/` stack up, `/health`, desktop Remote backend switch | documented steps work as written |

Also try to break it: empty prompts, a 1080p · 10 s render, a LoRA with 3
images, a video with no cuts, a dataset folder with a non-image file, a
path with spaces and unicode, two renders at once, closing the app
mid-train.

## 3. Grade like a user

For each scenario give:

- **Grade** A–F: A = works and feels finished; B = works with rough edges;
  C = works only with workarounds; D = mostly broken; F = unusable or
  misleading.
- **Verdict**: *Working* / *Broken* / *Needs rework* / *Should be redone*
  (rework = fixable in place; redone = the approach is wrong).
- **What happened** (exact steps, the numbers, the error text) and **what
  you expected**.
- **User-experience notes**: was it discoverable, did the copy tell the
  truth, did errors say what to do next, did it respect the 12 GB card
  (refusals vs. crashes), how long did it take, would you wait again.

Then an overall section:

- **Would you keep using it?** One paragraph, blunt.
- **Top 10 issues**, ranked by how much they hurt a user, each with a
  one-line reproduction.
- **Features that oversell**: anything the UI, README or docs claim that
  the software did not deliver.
- **Features that quietly work well** (users notice these too).
- **Rework list**: what to fix in place. **Redo list**: what should be
  rebuilt with a different approach, and why.

## 4. Report

Write `docs/HERMES_REVIEW.md` in the repository (commit on a branch
`review/hermes` and open a PR into `hermes-review`; do not merge). Structure:

1. Setup experience (with what failed, if anything).
2. Scenario table (U1–U16: grade, verdict, seconds, peak VRAM, notes).
3. Break-it attempts and outcomes.
4. Overall verdict, top 10, oversell list, quiet wins, rework/redo lists.
5. "Could not test" — each with the reason (no GPU, no Docker, no time).
6. Environment: GPU/driver, OS build, commit SHA, WanGP commit, Hermes version.

Rules: one review per run; every claim tied to something you did; numbers
from History or `nvidia-smi`, never estimates; do not soften findings —
the builder wants the truth, not encouragement.
