# Deleting a take

A shot accumulates takes. Some are worth keeping and some are 400MB of a
render that went wrong, and there was no way to get rid of one without
deleting the whole shot.

The risk in adding one is not that a version fails to disappear. It is that
deleting a take quietly undoes a decision the user already made, or removes a
file that was never this app's to remove. So most of the design is about what
deletion refuses to do.

## What it refuses

**The approved take.** If the shot is approved and the take is the one it is
approved on, deletion is refused outright — `force` does not override it.
Throwing away the render that was signed off is not an edit, it is a loss. The
UI disables the button and says why: *"This is the approved take — approve a
different one, or set the shot back to review, first."*

**The current take, without saying so.** Deleting the take a shot is on
returns 409 unless the caller passes `force=true`. The UI asks first, and the
question names the consequence: the shot will fall back to the newest take
that still has media.

**A take that is still rendering.** Refused: the worker would write its output
into a file this call just removed.

**A take already deleted.** Refused rather than silently repeated, so a
double-click is not mistaken for success.

## What survives

The record. A deleted take becomes a tombstone — `status: "deleted"`,
`deleted_at` set, `output_path` cleared — and everything that explains it stays:

- prompt and negative prompt
- model, resolution, fps, duration, seed
- the wardrobe snapshot and the full shot snapshot it was rendered from

So a deleted take can still be read ("v2 was the one with the 35mm and the
push-in") and re-rendered from exactly what produced it. The number is never
reused, so v3 always means the third thing that was tried.

## What happens to the media

The output file is deleted — but **only from inside this app's own outputs
directory**. A version that came from Quick Mode or an analysed clip points at
a file the user owns somewhere else on their disk. Deleting that because they
tidied up a take would be destroying their own media, so it is left alone and
reported as `kept`.

The response says which of three things happened:

| `media` | Means |
|---|---|
| `removed` | The file was inside `<film project>/outputs` and is gone |
| `kept` | The file lives outside this app's outputs and was left alone |
| `missing` | There was no file to remove |

`removed_path` comes back too, so the renderer can find any timeline clip whose
asset pointed at that file and mark it, rather than leaving a clip whose media
has silently gone.

## What happens to the shot

If the deleted take was the current one, the shot falls back to the newest take
that still has media. If none is left, `current_version` becomes `null` and a
shot sitting in review, approved or rejected drops back to `ready` (if it has a
composition capture) or `draft` — a shot in review with nothing to review is
not in review.

## It is remembered

Deletion is recorded to the knowledge engine as a `version_deleted` event, so
a model whose takes keep getting thrown away shows it. As everywhere else, the
recording happens outside the lock and after the save: failing to remember a
deletion can never be the reason the deletion did not stick, and turning
learning off does not change the delete.

## API

```
DELETE /api/film/projects/{project}/scenes/{scene}/shots/{shot}/versions/{number}?force=true
```

```json
{
  "status": "deleted",
  "number": 2,
  "media": "removed",
  "removed_path": "/…/film_projects/my-film/outputs/shot-1-2-v2.mp4",
  "current_version": 1,
  "remaining_versions": 1
}
```

## Where it is

| File | Role |
|---|---|
| `backend/handlers/film_handler.py` | `delete_version`, `_remove_version_media` |
| `backend/film/film_models.py` | `ShotVersion.deleted_at` / `deleted_media`, the `"deleted"` status |
| `backend/film/film_api_types.py` | `DeleteVersionResponse` |
| `backend/_routes/film.py` | The route |
| `frontend/views/film/useShotWorkflow.ts` | `deleteVersion`, with the confirmation |
| `frontend/views/film/ShotDetailDrawer.tsx` | The button, its disabled state, and the tombstone row |
| `devtools/ui-mock/routes/film.ts` | The same refusals, offline |

## Tests

`backend/tests/test_film_version_deletion.py` — 14 tests: every refusal
(approved, current-without-force, still rendering, already deleted, unknown
number), the media rules including the file outside the outputs directory that
must survive, the tombstone keeping prompt/model/seed/snapshot, numbers never
being reused, the fallback to the newest surviving take, the shot dropping out
of review when nothing is left, and that the deletion still happens with
learning switched off.
