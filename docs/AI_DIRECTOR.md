# AI Director

The AI Director is a native action layer over the film store — the same
persisted state the UI reads and writes. There is no AI-only scene database.
The design follows Open Media's MCP-bridge principle: every command maps 1:1
onto an operation the app already performs, and no command invents a
capability the UI lacks. The LLM never mutates anything directly: it can only
call the registry below, and every call is validated like a UI request.

Providers: **OpenRouter** (first-class, see `docs/OPENROUTER.md`), Gemini,
or any **OpenAI-compatible endpoint** (LM Studio, vLLM, Ollama's OpenAI API —
fully offline). All are driven through one `LLMProvider` contract
(`backend/film/llm_providers.py`) over the fakeable `HTTPClient` service, so
all tests run without network or keys. Without any provider, the offline
builder, the script parser, continuity and the composer keep working.

### Safety boundaries

- The model can only call registry commands; there is no filesystem, shell
  or network tool. Every argument is validated (ids must exist, enums must be
  valid, numbers are range-checked) and a bad call is reported back to the
  model as `{ok: false, error}` instead of failing the request.
- Loops are bounded (12 model turns, tool results truncated to 6 kB).
- Locked composer objects refuse `position/rotate/scale_object`.
- Keys never enter prompts, tool results or logs (redaction filter in
  `logging_policy.py`).

## Structured commands — `POST /api/film/projects/{id}/director/command`

`{"name": "...", "params": {...}}` executes one command and returns
`{results: [{name, ok, result|error}]}`. The same registry is exposed to the
model as tools (JSON-schema parameters; list them via
`GET /api/film/director/status`):

| Read | Structure | Framing / camera | Composer (3D) | Assets & cast | Prompt & generation |
|---|---|---|---|---|---|
| `get_project` | `create_scene` | `set_framing` | `position_object` (x/y/z or hint: *foreground left*, *center*, …) | `add_character` | `set_prompt` |
| `list_assets` | `update_scene` | `set_shot_type` | `rotate_object` (yaw) | `add_location` | `set_negative_prompt` |
| `get_scene` | `delete_scene` | `set_camera_angle` | `scale_object` | `add_prop` | `set_generation_settings` |
| `get_shot` | `create_shot` | `set_camera_elevation` | `update_pose` (joint → [x,y,z]°) / `apply_pose` (library) | `update_asset` / `update_character` / `update_location` / `update_prop` | `set_script` |
| `get_composition` / `get_shot_composition` | `update_shot` | `set_composition` | `set_ots` (foreground, subject, shoulder) | `assign_character` / `assign_prop` | `check_continuity` |
| `list_framing_options` | `delete_shot` / `duplicate_shot` | `set_camera_motion` | `set_camera` (manual position, look_at, fov → manual mode) | `set_location` / `assign_location` | `generate_shot` / `queue_shot` |
| | `reorder_shots` | `set_duration` | `add_keyframe` / `update_keyframe` / `delete_keyframe` (camera or object) | | `generate_preview` / `generate_final` |
| | | | `capture_shot` (reports capture state — the director cannot render the viewport) | | |

All composer tools edit the shot's single composition record (the same one
the Shot Composer saves), seeding it from the cast when the shot has never
been opened in the composer. See `backend/tests/test_film_invariants.py`.

Conventions:

- `add_character`/`add_location`/`add_prop` reuse an existing asset when the
  name matches (case-insensitive) instead of duplicating it.
- `assign_character`/`apply_pose`/`set_location` accept either `asset_id` or
  a `name` resolved against existing assets, and keep the scene's cast /
  location in sync.
- Errors are reported per command (`ok: false` + message), never as a 500.
- `generate_shot` / `queue_shot` only queue; they never render more than asked.
- `set_prompt` locks the prompt (the synthesizer won't overwrite it);
  *Unlock & re-synthesize* in the shot drawer reverses that.

## Natural language — `POST /api/film/projects/{id}/director/instruct`

Request: `{instruction, scene_id?, shot_id?, history?: [{role, content}]}`.

The handler runs a tool-calling loop:

1. System prompt + compact project summary (assets, scenes, shots with
   framing; compositions and version history omitted; only the focused scene
   expanded when `scene_id` is given) + optional prior turns + instruction.
2. The model answers with tool calls → each is executed through the
   registry and its `{ok, result|error}` is fed back as a tool message, so
   the model can correct itself (e.g. after "shot not found").
3. When the model answers with text, the loop ends. If that text is a JSON
   `{"summary", "commands": [...]}` plan (models without tool support), the
   plan is executed the same way, stopping at the first failure.
4. Hard cap: 12 model turns; tool results are truncated to 6 kB.

Response: `{reply, plan_summary, results: [...], context}` where `context`
is the *context details* disclosure (provider, model, role, turns, tool
calls, chars sent, summary size, tokens in/out, scope). The storyboard's
bottom bar keeps a local transcript and forwards it as `history`.

Example: *"Create a six second medium OTS shot — Sarah foreground left,
looking toward John, slow push-in"* becomes `create_shot` +
`assign_character`×2 + `set_framing(medium/ots)` + `set_duration(6)` +
`set_camera_motion(push_in)`, and the resulting shot appears on the
storyboard as a draft.

## Build Film with AI — `POST /api/film/projects/{id}/build` → `/build/apply`

`{idea, target_scenes, target_shots_per_scene, style?, use_llm}` returns an
**editable plan** (`title, logline, style, script, characters[], locations[],
scenes[{…, shots[]}]`) and persists nothing. With `use_llm: false` a
deterministic planner splits the idea into beats and applies standard
coverage (wide → medium → close-up …), so the feature works with no key.
`/build/apply` (`{plan, replace_existing}`) creates location and character
assets, scenes (with location + cast), draft shots (framing, camera move,
duration, cast, location), sets the script, synthesizes prompts, and returns
the project. A project that already has scenes needs `replace_existing`.

## Prompt refinement — `POST …/shots/{shot_id}/refine-prompt`

Uses the `prompt_refinement` role to rewrite the shot's prompt from its
structured facts (framing, camera move, cast with wardrobe, scene, action,
dialogue, current prompt, optional `guidance`) and stores it locked. Returns
the shot, the previous prompt and `context`.

## Assistant chat — `POST /api/film/director/chat`

Project-less chat for Quick Mode: `{messages[], role?, model_hint?,
duration_seconds?}` → `{reply, suggested_prompt, suggested_negative_prompt,
suggested_duration_seconds, context}`.

## Script → storyboard — `POST /api/film/projects/{id}/storyboard/generate`

- `use_llm: false` (default): the deterministic screenplay parser
  (`film/script_parser.py`) — works completely offline.
- `use_llm: true`: the `storyboard` role produces fully-cinematographed shots
  (size, angle, elevation, composition, camera move, duration, characters)
  using the BlueFish-derived output contract.

Both paths create **draft** shots and extract characters into assets; a
project that already has scenes requires `replace_existing: true`. Nothing
is auto-rendered — the user reviews the draft storyboard first.
