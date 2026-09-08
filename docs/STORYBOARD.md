# Storyboard

The Storyboard tab (between Gen Space and Video Editor inside a project) is
the center of the filmmaking workflow. Its data lives in a versioned film
project stored by the backend at
`<outputs>/film_projects/<project-id>/project.json` — one facet per LTX
Desktop project, created automatically on first open. Existing projects are
untouched; the tab simply appears.

## Structure

- **Scenes** are horizontal rows, ordered, each with title (double-click to
  rename), duration/shot counts, per-scene batch generation, and delete.
- **Shot cards** inside a scene show: scene.shot number, thumbnail (current
  generated version → composition capture → placeholder), title, duration,
  framing summary (shot size · angle), characters, location, and a status
  badge (`draft → composed → ready → queued → generating → review →
  approved/rejected`). Cards drag-and-drop to reorder within a scene.
- Card hover actions: **Compose** (opens the Shot Composer), duplicate
  (copies the composition but resets captures/versions), delete.
- Clicking a card opens the **shot drawer**: capture preview + Compose
  button, continuity warnings, title/action/dialogue/duration/camera move,
  the auto-synthesized visual prompt (editing it locks synthesis for that
  shot), Generate Preview / Generate Final, the full version history
  (compare, set current, retry), review actions (Approve/Reject) and **Send
  to Timeline**.
- The **timing strip** between cards shows the configured inter-shot gap
  (`settings.inter_shot_gap_seconds`); shot durations are always explicit.
- The bottom bar is the **AI Director** input (see `AI_DIRECTOR.md`).

## Sub-tabs

- **Script** — the screenplay editor. `Generate Storyboard` uses the
  deterministic offline parser (INT./EXT. headings → scenes; action blocks →
  shots; ALL-CAPS cues → dialogue with speaker attribution and character
  extraction). `AI Storyboard` sends the script to Gemini (needs a key in
  Settings) for fully-cinematographed shot suggestions. Both create **draft**
  shots only — nothing is rendered without review.
- **Assets** — reusable characters, locations, props and styles (see
  `CONTINUITY.md`). Reference images upload into the film store.
- **Models** — the GPU/VRAM-aware model manager (see
  `GENERATION_PIPELINE.md`).

## Batch generation

`Generate all` (toolbar), `Generate scene` (scene row) and per-shot buttons
all queue jobs into one sequential film queue that respects the host's
single-generation slot; the queue bar shows the active job and pending count
with a cancel action. Job state is persisted per shot version, so a restart
never loses a shot's history.
