# Final report

**Branch:** `claude/ltx-filmmaking-integration-75pnwq`
**Assessed:** 2026-09-15, by running the gates, not by reading earlier reports.

## Final status

**PRODUCTION READY — ENVIRONMENT VALIDATION REMAINS**

Every product capability in the brief is implemented, persisted, reachable in
the UI, tested and verified end to end. Two things cannot be closed from this
environment and are recorded as blocked rather than claimed as passing.

## The five features this pass delivered

Each was previously `NOT_IMPLEMENTED` in `docs/RELEASE_MATRIX.json`.

### PF2 knowledge engine (§13–16, 35, 40)

TFG now remembers what happened when it rendered your shots and says what that
history suggests — from your own runs, on your own machine, in a file you can
export or delete.

The design problem was honesty, not storage. "Failed 4 of 5 renders" is
arithmetic; "overanimates static shots" is a guess from a handful of examples.
Stored the same way, the second borrows the authority of the first. So three
layers stay apart: events (what happened), observations (what they suggest,
each labelled `fact` / `observed_pattern` / `user_preference` /
`model_recommendation` / `hypothesis`), and profiles. Confidence is
`n / (n + 5)`, so nothing reaches certainty, and it is never shown without the
sample beside it.

Learning can be switched off wholesale or per category, and the switch is
honoured at write time — disabling it stops collection rather than hiding what
is still being gathered.

`docs/KNOWLEDGE_ENGINE.md` · 32 tests

### Model-specific prompt compiler (§16)

`ReversePrompts.model_specific` existed and was always empty, because filling it
needs a compiler and a compiler needs something to compile from. A shot is now
held once as a `ShotBrief` — the fourteen sections a director specifies — and
compiled per target. LTX gets a chronological paragraph, Wan gets labelled
clauses, tag-trained checkpoints get descriptors.

Two refusals are the point: an unrecognised model is labelled unrecognised
rather than served a generic prompt dressed as tailored, and nothing is lost
silently — motion to a still model, audio to a silent one, negatives to a model
that takes none, sections given up to a budget all come back with a reason.

`docs/PROMPT_COMPILER.md` · 25 tests

### Per-version deletion (§19)

A shot accumulates takes, some of which are 400MB of a render that went wrong,
and there was no way to remove one short of deleting the whole shot.

Most of the design is what deletion refuses: the approved take outright, the
current take without an explicit force, a take still rendering, a take already
deleted. What survives is the record — a tombstone keeping prompt, model, seed
and snapshot, so a deleted take can still be explained and re-rendered. Media
is removed only from inside the app's own outputs; a take imported from
elsewhere points at the user's own file and is left alone.

`docs/VERSION_DELETION.md` · 14 tests

### Cross-project shot library (§18)

The obvious design is a reference into a project, and it fails immediately: the
project gets renamed, or the take gets deleted, and the entry points at nothing.

So an item is a copy — settings snapshotted, preview file copied into the
library's own directory outside any project. Tests assert an entry still
resolves and serves its preview after its source take is deleted and after the
source project's directory is removed from disk. Archive is the reversible
hide; delete is permanent, and the dialog says so.

`docs/SHOT_LIBRARY.md` · 32 tests

### AI timeline editing (§17)

Nineteen operations — split, trim, ripple trim, move, reorder, insert, replace,
replace-with-version, duplicate, delete, transitions, duration, gap, montage,
opening, ending, B-roll, align, normalize — each a pure function, each applied
through one path: snapshot, apply, save, record.

Undo is exact because the snapshot is the project as it was, not an inverse
that could drift. A refused edit changes nothing, and the suite asserts the
whole timeline is identical afterwards and that the refusal is absent from the
history. Every action is also an AI Director tool going through that same path,
so a model's edit is snapshotted and undoable like a person's, and the history
shows which of them made it.

`docs/TIMELINE_EDITING.md` · 43 tests

## Gates

| Gate | Status | Evidence |
|---|---|---|
| Backend tests | PASS | 642 passed (pytest, mock-free — `test_no_mock_usage.py` enforces it) |
| Frontend tests | PASS | 33 passed (vitest) |
| Type checking | PASS | `tsc --noEmit`, ui-mock `tsc`, pyright strict: 0 errors |
| Production build | PASS | `pnpm build:frontend`; checked for eight mock markers in `dist/`, none present |
| E2E, browser-only UI | PASS | `verify-ui-only.mjs` 80/80 on the dev server **and** on the standalone HTML file |
| Windows installer | BLOCKED — ENVIRONMENT | No Windows machine here |
| GPU qualification | BLOCKED — ENVIRONMENT | No CUDA GPU; `cuda_available=false` |
| Live provider calls | BLOCKED — ENVIRONMENT | No real API keys; every provider path exercised against the fake HTTP client |

## What the blocked gates mean

These are not unknowns being papered over. They are specific claims this
environment cannot support:

- **No render has been produced.** Every generation in these tests failed with
  "Models not downloaded", which the knowledge engine correctly recorded as a
  recurring failure. The queue, the version lifecycle and the outcome recording
  are all exercised; the pixels are not.
- **No VRAM or timing figure is real.** Anything the UI shows for peak VRAM or
  render seconds comes from the fake GPU service here.
- **No hosted provider has been called.** fal, WaveSpeed, Replicate, Claude,
  Grok, Gemini and OpenRouter are all wired and tested against the fake HTTP
  client. Their wire formats are implemented from their documented shapes and
  have not been confirmed against a live endpoint.
- **The Windows installer is unbuilt.** The electron-builder config is present
  and the macOS/Linux paths build; Windows needs a Windows machine.

## Security audit

Checked against the surface listed in the brief. Two findings, both fixed in
`db6219a`:

1. **Path traversal via a hand-edited `library.json`.** An entry naming a path
   outside the previews directory was followed into a read and, on delete, into
   `unlink`. Stored names are minted by the store and never contain a
   separator, so anything else is now refused. Parametrised tests cover parent
   traversal, absolute paths, nested names, `.`/`..` and blanks, plus one that
   puts a real file outside the directory and asserts it survives.
2. **The library preview would have 401'd in the packaged app.** A `<video>`
   cannot send an Authorization header, so a narrow set of read-only GETs take
   a query token — and the new route was not in it. Fixed, with a test that the
   allowance does not extend to listing, editing or deleting.

Confirmed unchanged: no secret, key or token in any new module; the new
handlers touch app settings only for the learning switches; no subprocess,
shell or eval anywhere in them; the only filesystem deletes are bounded (the
version media to the app's outputs, the library preview to its own directory);
Electron keeps `sandbox`, `contextIsolation` and `nodeIntegration: false`; and
text extracted from an imported video stays data that is never routed into a
tool call.

## Where to look

| | |
|---|---|
| Machine-readable state | `docs/RELEASE_MATRIX.json` |
| Knowledge engine | `docs/KNOWLEDGE_ENGINE.md` |
| Prompt compiler | `docs/PROMPT_COMPILER.md` |
| Version deletion | `docs/VERSION_DELETION.md` |
| Shot library | `docs/SHOT_LIBRARY.md` |
| Timeline editing | `docs/TIMELINE_EDITING.md` |
| Video intelligence | `docs/VIDEO_ANALYSIS.md` |
| Browser-only UI | `docs/UI_ONLY_MODE.md` |
| Architecture | `docs/FILMMAKING_INTEGRATION_ARCHITECTURE.md`, `backend/architecture.md` |

## Reproducing the gates

```bash
pnpm typecheck                              # tsc + ui-mock tsc + pyright strict
pnpm backend:test                           # 642 backend tests
pnpm test:frontend                          # 33 frontend tests
pnpm build:frontend                         # production bundle
pnpm build:ui                               # ui-preview/ltx-desktop-ui.html

# End to end, both UI-only modes (needs playwright):
pnpm dev:ui &
node scripts/verify/verify-ui-only.mjs
UI_ONLY_URL=file://$PWD/ui-preview/ltx-desktop-ui.html node scripts/verify/verify-ui-only.mjs
```

`pnpm typecheck:py` re-syncs dependencies through `uv` and needs network access
to the PyTorch index. Where that is unavailable, run pyright directly against
the existing environment: `cd backend && ./.venv/bin/python -m pyright`.
