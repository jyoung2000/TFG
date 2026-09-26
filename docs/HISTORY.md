# History

Every piece of work the app does on your behalf — image and video renders,
film-queue shots, image/video reproduce runs, analyses, model downloads and
(from phase 7) training runs — is a **job**. Jobs live in one SQLite store,
and the History tab reads nothing else. If a job is not in History, it did
not happen as far as the app is concerned.

## Where

- Store: `<app-data>/jobs.sqlite` (WAL mode, numbered migrations in
  `backend/services/job_store/sqlite_job_store.py`).
- Thumbnails: `<outputs>/jobs/thumbs/<hash>.jpg` — PIL for images, the media
  probe's first frame for videos. Served through the authenticated
  `/api/film/output` route like every other output.
- Handler: `backend/handlers/jobs_handler.py`; route: `backend/_routes/jobs.py`.
- Frontend: `frontend/views/history/*`, client in `frontend/lib/jobs-api.ts`,
  types in `frontend/types/jobs.ts` (mirror of `job_models.py`).

## Job record

`id, kind, status, progress (0..100), phase, title, created_at, updated_at,
started_at, finished_at, model, provider, seed, prompt, negative_prompt, spec,
params, inputs, outputs[{path, kind, width, height, duration, thumb}],
metrics{seconds, peak_vram_mb, scores…}, parent_job_id, project_id, shot_id,
error`.

Kinds: `image_gen · video_gen · image_reproduce · video_reproduce · analysis ·
scene_build · training · download`. Statuses: `queued · running · complete ·
failed · cancelled`.

## Who writes it

| Path | Where the job is opened | Lineage |
|---|---|---|
| Playground / Gen Space / Quick video | `VideoGenerationHandler.generate()` | — |
| Image generation | `ImageGenerationHandler.generate()` | — |
| Film queue (per shot version) | `FilmGenerationHandler.queue_shot()` → reused by the render | `project_id`, `shot_id` |
| Retake, IC-LoRA | their handlers | — |
| Video analysis detect / analyze | `VideoAnalysisHandler` | `inputs.analysis_id` |
| Image reproduce render / refine | `ImageRecreation` | child `image_gen` jobs per candidate |
| Model downloads (bundled + library) | `DownloadHandler`, `ModelLibraryHandler` | — |
| Re-run from History | `JobsHandler.rerun()` | `parent_job_id` = the original |

Progress flows through the single generation state machine
(`GenerationHandler`), which forwards every transition to the job **after**
releasing the app lock; thumbnails are made outside the lock too.

## API

```
GET    /api/jobs?kind&status(active|queued|running|complete|failed|cancelled)&project&q&limit&cursor
GET    /api/jobs/{id}            → { job, lineage[], children[] }
DELETE /api/jobs/{id}?files=true → removes the record and, only inside the outputs dir, its files
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/rerun      → a new queued job, same params and seed, parent = {id}
POST   /api/jobs/import          → one-time import of the old localStorage Quick history
GET    /api/jobs/events?since=N  → server-sent events: job / deleted / reset
```

The renderer subscribes with `EventSource` (query-token authenticated). If
the stream never opens it polls the list every two seconds; the UI-only mock
polls from the start because it cannot stream.

## Startup

Jobs still `queued`/`running` when the process starts belong to a dead
process and are marked `failed` with "Interrupted: the app was restarted".
The film queue then re-queues its own interrupted versions as new jobs.
