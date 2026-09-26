---
name: tfg
description: Drive TFG (local AI image/video studio) end to end through its MCP tools — create images and videos, reproduce a reference image or video, build 3D storyboards, train and apply LoRAs, and follow every job in History. Use when a task mentions TFG, LTX Desktop, WanGP renders, LoRA training or film storyboards.
version: 1.0.0
metadata:
  hermes:
    tags: [video, image, generation, lora, storyboard, mcp]
    category: media
    requires_toolsets: [mcp]
    config:
      - key: tfg.backend_url
        description: "TFG backend URL (desktop: http://127.0.0.1:8000; container: http://<host>:8000)"
        default: "http://127.0.0.1:8000"
      - key: tfg.auth_token
        description: "LTX_AUTH_TOKEN of that backend (the desktop prints its per-session token in Settings → About; the container uses deploy/.env)"
        default: ""
---

# TFG for agents

TFG exposes **every feature as an MCP tool** (one per API route, generated
from the backend's route table — 214 tools at the time of writing). Connect
once, then work through the workflows below. Tool names are
`<area>_<action>` (`generation_generate`, `training_start`,
`jobs_list_jobs`). Every tool's `inputSchema` is the API's own schema, so
`tools/list` is the authoritative reference.

## Connect

**Local stdio server** (spawns a tiny process that forwards to the running
backend; needs the backend's Python venv):

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  tfg:
    command: "/path/to/TFG/backend/.venv/bin/python"   # Windows: backend\.venv\Scripts\python.exe
    args: ["/path/to/TFG/backend/tfg_mcp.py"]
    env:
      TFG_BACKEND_URL: "http://127.0.0.1:8000"
      TFG_AUTH_TOKEN: "<token>"
```

**Remote HTTP server** (the container stack or a remote backend; nothing to
install locally):

```yaml
mcp_servers:
  tfg:
    url: "http://unraid.local:8000/mcp"
    headers:
      Authorization: "Bearer <LTX_AUTH_TOKEN>"
    tools:
      exclude: [health_shutdown]
```

`hermes mcp test tfg` should list the tools. Claude Code: `claude mcp add
tfg -- python backend/tfg_mcp.py` (same env vars). Cursor and other clients
take the same stdio command or the `/mcp` URL.

## Orientation calls

1. `health` — backend alive, GPU name, whether models are loaded.
2. `settings_get_settings` — video profile (fast/balanced), image steps,
   media provider, fallback tiers, vision stack.
3. `settings_list_presets` / `settings_apply_preset` (`rtx-4070-12gb`) —
   size every default to a 12 GB card in one call.
4. `jobs_list_jobs` (`kind`, `status`, `limit`) — History: every image,
   video, analysis, download and training run with prompt, seed, params,
   outputs and metrics. `jobs_get_job` gives lineage and children.

Long renders return when they finish (the tool call blocks), but the same
job is visible in History while it runs; `generation_generation_progress`
reports phase/percent for the active video render and `generation_generate_cancel`
stops it.

## Workflows

**Create an image** — `image_generate_image` `{prompt, width, height,
numSteps: 8, numImages: 1, loras: [{name, multiplier}]}` → `image_paths`.
The paths are on the backend's disk; fetch bytes with
`film_generation_film_output` (`path`) when the backend is remote.

**Create a video** — `generation_generate` `{prompt, model: "fast",
resolution: "540p", duration: "6", fps: "24", aspectRatio: "16:9",
cameraMotion: "none", imagePath?, loras?, referenceImagePaths?,
endFramePath?}` → `video_path`, `seed`. Balanced quality: `720p`, `8`.
A local failure falls through the configured tiers (`settings_route_tiers`).

**Reproduce an image** — `reproduce_import` `{path}` → `reproduce_analyze`
(vision stack reads it into an editable ShotSpec) → optionally
`reproduce_update_spec` / `reproduce_set_prompt` → `reproduce_start`
`{budget: {candidates_per_round, max_rounds, target_score}, seed, loras}` →
poll `reproduce_get` until `status` is `complete`; `best_candidate_id` and
per-candidate scores explain the pick; `reproduce_pin`, `reproduce_fix`.

**Reproduce a video** — `video_analysis_import` `{path, title}` →
`video_analysis_detect` (shots) → `video_analysis_analyze` (framing, camera
language, motion) → `video_reproduce_start` `{candidates_per_shot, rounds,
seed}` → poll `video_reproduce_get`; `video_reproduce_pick` / `_redo` /
`_stitch` produce the final clip. `video_analysis_storyboard3d` builds the
3D scene layout per shot; `scene_*` tools edit it and `film_deliver` renders
clean/depth passes that become control videos for the render.

**Train a LoRA** — `training_create_dataset` `{name, preset:
character|style|object, trigger}` → `training_import_items` `{folder |
image_paths | video_path | job_ids | analysis_id | reproduce_id}` →
`training_caption_dataset` (Florence captions + trigger) → review with
`training_update_item` → `training_suggest` `{dataset_id, target}` (12 GB-safe
config) → `training_start` `{dataset_id, name, config}`; progress lives on
the run (`training_get_run`: step, loss_history, samples, eta) and in History.
`training_cancel`, resume with `training_start` `{resume_run_id}`. The LoRA
lands in `training_list_loras` (`model` filter returns only compatible ones).
`training_download_lora` `{url, target, name?, trigger?, api_key?}` pulls one
from a Hugging Face file link, a Civitai model page/download link, or any
direct `.safetensors` URL as a History `download` job (the optional key is
used once for that fetch and never stored). Any registered LoRA
can be passed as `loras: [{name: <file>, multiplier}]` to Create,
Reproduce and film shots; `film_update_asset` binds one to a character
(`lora_id`, `lora_trigger`, `seed_lock`) so every shot inherits it, and
`film_reference_sheet` renders a multi-angle sheet with one seed.

**Film Studio** — `film_create_project` → `film_create_scene` /
`film_create_shot` → `film_generation_generate_shot` `{kind: preview|final}`
→ versions on the shot; `film_generation_queue` shows the render queue.

## Rules of thumb

- Never exceed the card: `settings_list_presets` says what fits; the
  backend refuses a LoRA target or model that cannot run on 12 GB and says
  why — pass that reason on instead of retrying.
- Prefer `jobs_*` for status; do not poll faster than every 2 s.
- Paths in results belong to the backend host. For a remote backend use the
  `*_media` / `film_output` tools to fetch bytes.
- `health_shutdown` stops the backend; exclude it unless the user asked. (The
  tool is named after the route's tag, so `POST /api/system/shutdown` is exposed
  as `health_shutdown`, not `system_shutdown`.)
