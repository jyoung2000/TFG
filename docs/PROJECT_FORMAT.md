# Project format and packages

## On disk

A host project (name, assets, timelines) lives in the renderer's
`localStorage` (`ltx-projects`), unchanged from upstream LTX Desktop. Its
**film facet** — script, assets, scenes, shots, versions, poses, settings —
is owned by the Python backend and persisted as:

```
<app data>/outputs/film_projects/<project-id>/
  project.json     FilmProject, schema-versioned (schema_version: 1)
  captures/        <shot-id>.png + <shot-id>.json composition snapshots,
                   <shot-id>-continue.jpg previous-frame references
  references/      uploaded asset reference images
  outputs/         media extracted from imported packages
```

Generated renders themselves stay where the host writes them
(`<app data>/outputs/ltx2_video_*.mp4`); `ShotVersion.output_path` is the
absolute path. Writes are atomic (temp file + rename); a corrupt
`project.json` is preserved as `project.corrupt-<ts>.json` and replaced by
an empty facet.

The schema is `backend/film/film_models.py` (mirrored 1:1 by
`frontend/types/film.ts`). `FilmStore.migrate()` upgrades older payloads in
steps (v0 → v1 wraps bare shots into a scene). Fields added since v1 are
defaulted on load, so no version bump was needed:
`settings.default_quality_preset`, `generation.quality_preset = "project"`,
`ShotFraming.ots_shoulder` / `camera_mode`, `CompositionObject.locked`,
`FilmScene.inter_shot_gap_seconds`, `FilmShot.gap_before_seconds`, and the
per-version telemetry `ShotVersion.shot_snapshot` (framing, cast, prompt and
generation settings as rendered), `generation_seconds`, `gpu_name`,
`peak_vram_gb` (estimate), `execution_mode`.

`PUT /api/film/projects/{id}` replaces the whole facet with a validated
`FilmProject` (the storyboard's undo/redo); the id, schema version and
creation time are pinned to the route and it is refused (`409`) while any
shot of the project is queued or rendering.

## `.ltxfilm` packages

A package is a zip with this layout:

```
manifest.json    {"format": "ltx-film-package", "format_version": 1,
                  "exported_at_ms", "schema_version", "project_id",
                  "project_name", "includes_outputs", "has_host_project",
                  "media": [...], "output_media": {member: original path}}
project.json     FilmProject exactly as on disk, except every
                 version.output_path is package-relative ("outputs/…")
host_project.json  (optional) the host project — name, assets, timelines —
                 as the renderer holds it, with any credential-looking key
                 stripped recursively; API keys never live here
captures/…       copied verbatim (includes review frames)
references/…     copied verbatim
outputs/…        <shot-id>-v<n>.<ext> — current renders (optional)
```

**Compact vs Complete**: *Compact* (`include_outputs: false`) carries the
project, captures and references only; *Complete* adds every current render.
Both may carry `host_project.json` so the timeline travels with the film.

### Export — `POST /api/film/projects/{id}/export`

`{destination_path, include_outputs, host_project?}` → `PackageSummary`
(`scenes, shots, assets, media_files, total_bytes, warnings, path`). The
`.ltxfilm` suffix is enforced (a directory or a non-absolute destination is
refused); parent folders are created; the archive is written to a temp name
and renamed. Renders whose file has gone missing are dropped from
the package with the version marked (`error` set) rather than failing the
export. Storyboard → **Export** uses the native save dialog and reveals the
result in the file manager.

### Inspect — `GET /api/film/packages/inspect?package_path=…`

Returns the same summary without writing anything; the UI shows it in the
confirmation before importing.

### Import — `POST /api/film/projects/{id}/import`

`{package_path, replace}` → `{summary, project, host_project,
output_path_map}` — `output_path_map` maps each original render path to its
extracted location so timeline clips can be re-linked. Validation runs
**completely before anything is written**:

| Check | Failure |
|---|---|
| file exists and is a zip | `400 Not a film package` |
| `manifest.json` + `project.json` present, `format == ltx-film-package` | `400` |
| `format_version` ≤ 1 | `400 Unsupported package format version` |
| `project.json` parses, passes `migrate()` + `FilmProject` validation | `400 project.json failed schema validation at <field>: <reason>` |
| project `schema_version` ≤ app's | `400 … newer than this app supports` |
| every other member: relative, no `..`/absolute/backslash, under `captures/`, `references/` or `outputs/`, allowed extension (`png jpg jpeg webp json mp4 webm mov m4v`) | `400 Unsafe path / File type not allowed / outside the media folders` |
| ≤ 5000 members, ≤ 4 GB per file, ≤ 64 GB total | `400` |
| target project empty, or `replace=true` | `409` |

Media references (`capture_path`, `reference_images`, `output_path`) that
point at files missing from the package are cleared (complete versions get
an explanatory `error`). On import the project id becomes the target id,
previous media in the target folder is removed, members are streamed to
`captures/`, `references/`, `outputs/` (re-checked against the resolved
project directory), and `output_path` becomes the absolute extracted path —
which lives under the app's outputs directory, so `/api/film/output` serves
it.

Storyboard → **Import** picks the file, shows the inspection summary, warns
when it would replace existing content, then imports and refreshes.

Tests: `backend/tests/test_film_package.py` (round-trip incl. media,
no-outputs export, replace guard, validation and traversal rejection, v0
migration on import, dangling media cleanup).
