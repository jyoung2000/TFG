# The cross-project shot library

A shot that worked is worth more than the film it was made for. The library is
where one gets kept so it can be used again somewhere else.

## Why it has to be a copy

The obvious design is a reference: the library points at a shot in a project.
It fails immediately. That project gets renamed, or archived, or the very take
that made the shot worth keeping gets deleted — and the library entry becomes a
broken pointer to something that no longer exists.

So a library item is a **copy**:

- the shot's settings are snapshotted at save time (prompt, framing, camera
  move, duration, model, resolution, fps, seed, aspect ratio, style)
- the preview media is **copied** into the library's own directory

An entry keeps working after the take it came from is deleted, after the whole
project is deleted, after the user moves to a new film entirely. Tests cover
exactly those cases, because they are the ones that make the feature worth
having.

The lineage travels with it — project, scene, shot, version, when it was
captured — but as a **record, not a dependency**. It tells you where a shot
came from; it is never followed to load anything.

Applying works the same way. It writes the item's settings onto a shot and
leaves no link behind, so editing the new shot never changes the library entry
and editing the entry never changes shots made from it.

## Where it lives

```
<outputs>/shot_library/library.json
<outputs>/shot_library/previews/<item-id>.<ext>
```

Outside any project, because it belongs to the person, not the film. JSON
rather than SQLite — unlike the knowledge engine, whose access pattern is the
opposite: this is a curated list a person reads and edits by hand, it is small,
it wants to be readable, and rewriting it whole costs nothing at this size. It
is written via a temp file and renamed, so a crash mid-write cannot lose it.

## Archive and delete are different

| | What it does | Reversible |
|---|---|---|
| **Archive** | Hides it from the default listing and from the tag counts | Yes — **restore** |
| **Delete** | Removes the entry and its copied preview | No |

Archive is the one the UI offers first; delete asks for confirmation and says
in the dialog that archiving is the reversible alternative. Making both soft
would make archive pointless, so only one of them is.

## Curating

- **Tags** are normalised on the way in — trimmed, lowercased, deduplicated —
  so "Night", "night " and "night" are one tag. Filtering requires **all** the
  selected tags, not any, because narrowing is what a tag filter is for.
- **Rating** is 0–5, where 0 means unrated rather than rated zero.
- **Favourites** sort to the top of whatever order is selected.
- **Editing is partial**: only the fields sent are changed, so setting a rating
  cannot blank the notes.
- **Duplicating** copies the preview too, and the copy starts its own history —
  no use count, not a favourite, not archived — because it is a new thing to
  vary, not a second view of the old one.

## Where it shows up

- **Settings → Shot Library**: the whole library, searchable and filterable.
  It is in Settings rather than inside a film because it spans films.
- **Storyboard → shot drawer → "Save to Shot Library"**: keeps the shot you are
  looking at.
- `ShotLibraryPicker` renders the same panel inside a film, with **Use** wired
  to add the item as a new shot in the scene you are on.

A shot with no rendered take can still be saved — the settings are the reusable
part — and the entry simply has no preview, which the card says.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/shot-library` | Search and filter; returns items plus every tag with its count |
| `GET` | `/api/shot-library/{id}` | One item |
| `GET` | `/api/shot-library/{id}/preview` | The copied preview |
| `POST` | `/api/shot-library` | Save a shot into the library |
| `PUT` | `/api/shot-library/{id}` | Edit title, notes, tags, rating, favourite |
| `POST` | `/api/shot-library/{id}/duplicate` | Copy an entry, preview and all |
| `POST` | `/api/shot-library/{id}/apply` | Write its settings onto a shot, or a new one |
| `POST` | `/api/shot-library/{id}/archive` | Hide it |
| `POST` | `/api/shot-library/{id}/restore` | Bring it back |
| `DELETE` | `/api/shot-library/{id}` | Permanent |

`GET /api/shot-library` takes `q`, repeated `tags`, `favorite`, `archived`,
`model` and `sort` (`recent`, `rating`, `used`, `title`). `archived` is a
switch rather than a filter value: archived items are out of the way by
default, and asking for them gets only them.

The preview endpoint resolves the file from the **item's own stored name**,
never from anything the caller sends, so there is no path for a request to walk
out of the previews directory.

`apply` with an empty `shot_id` adds a new shot to the scene instead of
overwriting one. An applied prompt sets `prompt_locked`, because choosing a
library item is an explicit choice and synthesis must not quietly replace it.

## Code map

| File | Role |
|---|---|
| `backend/film/shot_library_models.py` | `LibraryShot`, `LibraryLineage`, `LibraryIndex` |
| `backend/film/shot_library_store.py` | JSON index, preview copying, atomic write |
| `backend/handlers/shot_library_handler.py` | Save, apply, search, curate, archive, delete |
| `backend/film/shot_library_api_types.py` | Request/response models |
| `backend/_routes/shot_library.py` | Routes |
| `frontend/types/shot-library.ts` | Mirror of the backend types |
| `frontend/lib/shot-library-api.ts` | Typed client + preview URL |
| `frontend/views/film/ShotLibraryPanel.tsx` | The panel and the in-film picker |
| `devtools/ui-mock/routes/shot-library.ts` | UI-only mock: the same rules restated |

## Tests

`backend/tests/test_shot_library.py` — 25 tests. The ones that matter most are
the survival tests: an entry still resolves its prompt and serves its preview
after the take it came from is deleted, and after the source project's whole
directory is removed from disk. Plus: tag normalisation, the copy-not-link
behaviour of apply (editing the applied shot leaves the entry alone), search
across titles/prompts/notes/tags, all-tags filtering, favourites sorting first,
partial editing, duplication copying the preview, archive/restore, permanent
delete taking the preview with it, and a fresh handler over the same directory
reading everything back.
