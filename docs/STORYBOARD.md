# Storyboard

The Storyboard tab (between Gen Space and Video Editor inside a project) is
the center of the filmmaking workflow. Its data lives in a versioned film
project stored by the backend at
`<outputs>/film_projects/<project-id>/project.json` — one facet per LTX
Desktop project, created automatically on first open. Existing projects are
untouched; the tab simply appears. Home's **Filmmaker Studio** card creates a
project and opens it here directly; Quick video's **Edit in Film Maker**
arrives here with the clip as Scene 1 / Shot 1.

## Structure

- **Scenes** are horizontal rows, ordered, each with title (double-click to
  rename), duration/shot counts, per-scene batch generation, and delete.
- **Shot cards** inside a scene show: scene.shot number, a continuity dot
  (amber minor / orange significant / red broken; none when good),
  thumbnail (current generated version → composition capture →
  placeholder), title, duration, framing summary (shot size · angle),
  characters, location, and a status badge (`draft → composed → ready →
  queued → generating → review → approved/rejected`). Cards drag-and-drop
  to reorder within a scene and are keyboard-operable (focus, Enter/Space to
  open, `c` to compose).
- Card hover actions: **Compose** (opens the Shot Composer), duplicate
  (copies the composition but resets captures/versions), delete.
- Clicking a card opens the **shot drawer**: capture preview + Compose
  button, the continuity level with each warning's suggested fix and a
  one-click **Fix** where possible, title/action/dialogue/duration/camera
  move, the auto-synthesized visual prompt (editing it locks synthesis;
  **Refine with AI** rewrites it with the AI Director; *Unlock &
  re-synthesize* returns to the structured fields), the quality profile for
  final renders, Generate Preview / Generate Final, the full version history
  (compare, set current, retry with the error shown), review actions
  (Approve/Reject) and **Send to Timeline**.
- The **timing strip** between cards shows the configured inter-shot gap
  (`settings.inter_shot_gap_seconds`, default 0); shot durations are always
  explicit.
- The bottom bar is the **AI Director** chat (see `AI_DIRECTOR.md`): a
  transcript with per-reply *context details*, enabled by an OpenRouter or
  Gemini key, otherwise a link to Settings.

## Toolbar

`Build with AI` (idea → editable plan → draft storyboard; offline planner
without a key) · `Scene` · `Generate all` · `Export` / `Import` `.ltxfilm`
packages (`PROJECT_FORMAT.md`) · **Simple / Advanced** toggle (simple hides
the Script and Models tabs, export/import, quality profiles and context
details) · queue status with Pause/Resume, pending list (per-job cancel /
prioritize) and live progress.

## Sub-tabs

- **Script** — the screenplay editor. `Generate Storyboard` uses the
  deterministic offline parser (INT./EXT. headings → scenes; action blocks →
  shots; ALL-CAPS cues → dialogue with speaker attribution and character
  extraction). `AI Storyboard` sends the script to the AI Director model for
  fully-cinematographed shot suggestions. Both create **draft** shots only —
  nothing is rendered without review.
- **Assets** — reusable characters, locations, props and styles (see
  `CONTINUITY.md`). Reference images upload into the film store.
- **Models** — the GPU/VRAM-aware model manager (see
  `GENERATION_PIPELINE.md`): compatibility verdict, per-model fit, download
  and remove, quality profiles recommended for the GPU, and the project's
  render defaults (default profile, preview size, gap, strict continuity).

## Batch generation

`Generate all` (toolbar), `Generate scene` (scene row) and per-shot buttons
all queue jobs into one sequential film queue that respects the host's
single-generation slot. Job state is persisted per shot version, so a
restart never loses a shot's history; jobs interrupted by a crash are marked
failed on the next start instead of staying "generating".
