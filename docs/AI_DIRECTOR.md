# AI Director

The AI Director is a native action layer over the film store — the same
persisted state the UI reads and writes. There is no AI-only scene database.
The design follows Open Media's MCP-bridge principle: every command maps 1:1
onto an operation the app already performs, and no command invents a
capability the UI lacks.

## Structured commands — `POST /api/film/projects/{id}/director/command`

`{"name": "...", "params": {...}}` executes one command and returns
`{results: [{name, ok, result|error}]}`. Commands:

`get_project · get_scene · get_shot · get_shot_composition ·
list_framing_options · create_scene · update_scene · create_shot ·
update_shot · set_framing · set_camera_motion · set_duration ·
add_character · add_location · add_prop · update_asset · assign_character ·
set_location · apply_pose · generate_shot`

Conventions:

- `add_character`/`add_location`/`add_prop` reuse an existing asset when the
  name matches (case-insensitive) instead of duplicating it.
- `assign_character`/`apply_pose`/`set_location` accept either `asset_id` or
  a `name` resolved against existing assets.
- Errors are reported per command (`ok: false` + message), never as a 500.
- `generate_shot` only queues; it never renders more than asked.

## Natural language — `POST /api/film/projects/{id}/director/instruct`

The instruction, a compact project summary and the command catalog go to
Gemini (the host's existing Gemini pattern via the fakeable `HTTPClient`
service; requires `gemini_api_key` in Settings). Gemini returns a JSON plan
(`summary` + `commands`) which is validated and executed through the same
registry, stopping at the first failure. The system prompt forbids
`generate_shot` unless the user explicitly asked to render.

The storyboard's bottom bar is this endpoint: e.g. *"Create a six second
medium OTS shot — Sarah foreground left, looking toward John, slow push-in"*
becomes `create_shot` + `assign_character`×2 + `set_framing(medium/ots)` +
`set_duration(6)` + `set_camera_motion(push_in)`, and the resulting shot
appears on the storyboard in a review state.

## Script → storyboard — `POST /api/film/projects/{id}/storyboard/generate`

- `use_llm: false` (default): the deterministic screenplay parser
  (`film/script_parser.py`) — works completely offline.
- `use_llm: true`: Gemini produces fully-cinematographed shots (size, angle,
  elevation, composition, camera move, duration, characters) using the
  BlueFish-derived output contract.

Both paths create **draft** shots and extract characters into assets; a
project that already has scenes requires `replace_existing: true`. Nothing
is auto-rendered — the user reviews the draft storyboard first.
