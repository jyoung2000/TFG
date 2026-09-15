# Editing the timeline

## The timeline is the film

There is no second data structure. The timeline is the scenes in order, the
shots in order within them, each with a duration, a gap before it and a
transition either side. Editing the timeline edits the storyboard, which is
what makes an edit survive into the render rather than living only in a
preview.

What the API returns as a "timeline view" is computed from that, never stored:
absolute start times, total running length, and how many shots actually have a
render. It cannot drift out of sync with the film because there is nothing to
drift from.

## One path for every edit

```
snapshot → apply a pure operation → save → record
```

That shape is where the guarantees come from.

**Undo is exact.** The snapshot is the whole project as it was immediately
before the edit, so undo restores it rather than trying to invert an operation.
A hand-written inverse can drift out of step with the operation it inverts; a
snapshot cannot. A film project is a small JSON document, and correctness here
is worth more than the bytes.

**A refused edit changes nothing.** The operations in `film/timeline_ops.py`
raise rather than returning a failure, and nothing is written until one
returns. Splitting a shot outside its own duration, reordering with a shot from
another scene, putting an unrendered take on the timeline — each is refused
with a reason, and the film is exactly as it was. The e2e suite asserts this by
comparing the whole timeline before and after a refusal.

**The history survives.** Actions are persisted beside the project in
`timeline_history.json`, so "why does the film look like this?" is answerable
after a restart. That matters more than usual here, because some of the edits
were made by a model.

The operations themselves are pure functions over a `FilmProject` — no locks,
no IO, no clock beyond what the models supply — so each is testable on its own
and the handler stays down to those four steps.

## The edits

| Action | Does |
|---|---|
| `split_shot` | Cuts one shot in two, dividing its duration |
| `trim_shot` | Changes a duration. Nothing after it moves |
| `ripple_trim` | Changes a duration and holds the running time by taking the difference out of the gaps that follow |
| `move_shot` | Moves a shot within its scene or into another |
| `reorder_shots` | Sets a scene's running order |
| `insert_shot` | Adds an empty shot at a position |
| `replace_shot` | Gives a shot another's content, keeping its place |
| `replace_with_version` | Puts a different completed take on the timeline |
| `duplicate_shot` | Copies a shot in place |
| `delete_shot` | Removes it from the running order |
| `set_transition` | Cut, dissolve, fade in/out, wipe, dip to black |
| `set_duration` / `set_gap` | Length, and the pause before |
| `build_montage` | Short, evenly timed, no gaps |
| `add_opening` / `add_ending` | A shot at the front that fades in, or the end that fades out |
| `insert_broll` | A cutaway after a shot, in the same location |
| `align_durations` | One length for a whole scene |
| `normalize_timeline` | Consistent gaps, contiguous ordering, durations in range |

Three decisions inside those are worth stating, because they are the ones that
would be wrong the other way:

**A new shot never inherits a render.** Split, duplicate and replace all
produce something that has not been made yet. Showing it the original's take
would be a lie about what exists, so versions, captures and status are cleared.

**A montage only changes rhythm.** Duration, gap and transition. What each shot
*is* stays exactly as it was, because a montage is an editing decision, not a
licence to rewrite anyone's prompts.

**Normalising is conservative.** It fixes what is inconsistent — gaps, ordering,
out-of-range durations — and does not reshape how long shots run. How long a
shot runs is a decision, not a defect.

Under length pressure, `ripple_trim` reports what the gaps could not absorb
rather than silently doing something else:

> Ripple trimmed to 10s, 4.5s the gaps could not absorb

## The AI Director edits the same timeline

Every action above is registered as a director command with a tool spec, so a
model can call it — and every one of those calls goes through the same
`TimelineHandler.apply`. There is no separate "AI timeline". There is one edit,
and two things that can change it.

The consequences are the point:

- A model's edit is **snapshotted and undoable** exactly like a person's.
- The history records **who made each edit**, and the UI shows it: an `AI` badge
  against the director's, `YOU` against yours.
- The director can undo its own edit with `undo_timeline_edit`.

## Where it is

**Timeline tab** in the film workspace: the running order with absolute times,
gaps, transitions and render state; per-shot edits for the selected shot;
whole-film actions; an undo button that says how many edits are still undoable;
and the edit history with its AI/you attribution, undone entries struck
through.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/film/projects/{id}/timeline` | The running order, computed |
| `GET` | `/api/film/projects/{id}/timeline/history` | Every edit, with who made it |
| `POST` | `/api/film/projects/{id}/timeline/actions` | Apply one edit |
| `POST` | `/api/film/projects/{id}/timeline/undo` | Restore the state before the last undoable edit |

`actions` takes `{action, params, actor}` where `actor` is `user` or
`director`. The response carries the timeline after the edit, so no second call
is needed.

The undo snapshot never travels over the API — it is a copy of the whole
project, and the caller already has the current one. The 25 most recent actions
keep their snapshot; older ones stay in the history as a record without one, so
the file cannot grow without bound. 200 actions are retained in total.

## Code map

| File | Role |
|---|---|
| `backend/film/timeline_models.py` | `DirectorAction`, `TimelineView`, the action names |
| `backend/film/timeline_ops.py` | Every operation, as a pure function |
| `backend/handlers/timeline_handler.py` | Snapshot/apply/save/record, undo, the view |
| `backend/film/timeline_api_types.py` | Request/response models |
| `backend/_routes/timeline.py` | Routes |
| `backend/handlers/film_director_handler.py` | Tool specs + `_timeline_command` bridge |
| `backend/film/film_models.py` | `ShotTransition` on the shot |
| `frontend/types/timeline.ts` | Mirror of the backend types |
| `frontend/lib/timeline-api.ts` | Typed client |
| `frontend/views/film/TimelinePanel.tsx` | The Timeline tab |
| `devtools/ui-mock/routes/timeline.ts` | UI-only mock: the same rules restated |

## Tests

`backend/tests/test_timeline.py` — 43 tests. The load-bearing ones are in
`TestUndo`: that undo restores the timeline to exactly what it was, that it
walks back one edit at a time, that the same edit cannot be undone twice, and
that a refused edit leaves nothing behind — not in the film, and not in the
history, because it never happened. `TestTheDirectorCanDriveIt` checks that
every action is a director command, that a model's edit is recorded as the
director's, and that the director can undo its own work.
