# Final hardening audit

Audit of the `jyoung2000/TFG` repository at the end of the hardening pass
(branch `claude/ltx-filmmaking-integration-75pnwq`). Status words are used
strictly: **verified** = exercised by an automated test or a real UI run in
this environment; **implemented** = code exists and typechecks/tests pass
but the exact user flow was not exercised end to end here; **not done** =
absent or blocked.

Environment used for verification: Linux container, no GPU (`execution_mode`
= `api`), no network access to model/LLM providers, Electron under Xvfb
driven over CDP. Anything requiring a GPU, a paid API key, Windows, or
macOS is marked accordingly.

## 1. Repository shape

| Layer | Location | State |
|---|---|---|
| Host app (LTX Desktop WanGP) | `electron/`, `frontend/`, `backend/` | upstream baseline `deepbeepmeep/LTX-Desktop-WanGP@4abb4a5` + film layer |
| Film backend | `backend/film/*`, `backend/handlers/film*.py`, `backend/_routes/film*.py` | domain model v1 + additive fields, store, prompt synthesis, continuity, script parser, LLM providers, packages |
| Film frontend | `frontend/views/film/*`, `frontend/views/QuickMode.tsx`, `frontend/contexts/FilmContext.tsx`, `frontend/types/film.ts` | storyboard, composer, assets, script, models, director, build film, package menu, quick mode |
| Installers | `electron-builder.yml`, `electron-builder-signed.yml`, `scripts/*` | Windows NSIS (unsigned default), Linux AppImage + deb, macOS DMG |
| Tests | `backend/tests/` (28 files, 367 tests + pyright strict test) | all green in this environment |
| Docs | `docs/*.md`, `README.md` | see §9 |

CI equivalent run locally: `tsc --noEmit` clean, `pyright` 0 errors, `pytest`
367 passed, Vite production build succeeds.

## 2. Feature matrix

| Mission | Status | Evidence / notes |
|---|---|---|
| Home: "What do you want to make?" (Quick video / Filmmaker Studio), getting-started strip | **verified (UI)** | `Home.tsx`; E2E run §10 |
| Quick Mode: idea chat, prompt, settings, generate, result actions, history | **implemented**; view verified in UI; generation itself needs GPU/API key | `QuickMode.tsx`, uses the same `use-generation` hook/`/api/generate` as Gen Space |
| Edit in Film Maker (Quick → Scene 1/Shot 1/v1 preserving prompt, model, params, seed, output, duration, resolution) | **verified (tests + API run)** | `POST /api/film/projects/{id}/import-generation`; `test_film_quick_mode.py`; `/api/generate` now returns `seed` |
| Build Film with AI → editable plan → apply | **verified (tests + UI, offline planner)**; LLM path verified with fake HTTP only | `build_film`/`apply_build`, `BuildFilmDialog.tsx`, `test_film_openrouter.py::TestBuildFilm` |
| OpenRouter as first-class provider: key storage, validation, model discovery, role preferences, env var | **verified (tests + UI with placeholder key)**; never called the real service | `llm_providers.py`, `OpenRouterSettings.tsx`, `docs/OPENROUTER.md` |
| Gemini provider parity through the same abstraction | **verified (tests, fake HTTP)** | function calling + JSON fallback |
| AI Director tool calling (registry as tools, loop, tool results fed back, JSON-plan fallback, 12-turn cap, context details) | **verified (tests)**; UI transcript verified without a provider | `film_director_handler.py`, `DirectorBar.tsx` |
| New director commands (`list_assets, delete_scene, delete_shot, reorder_shots, set_prompt, set_generation_settings, set_script, check_continuity, queue_shot`) | **verified (tests)** | |
| Shot Composer (presets, OTS/POV, poses, motion keyframes, capture) | **verified in earlier UI runs**; unchanged this pass | `docs/SHOT_COMPOSER.md` |
| FilmShot ↔ composition ↔ assets sync | **implemented** (capture syncs framing/camera move; director/asset edits re-synthesize prompts) | |
| Character/location/prop systems + reference images | **verified (tests)** | |
| Structured prompt synthesis with lock/unlock + AI refine | **verified (tests)**; refine UI button verified disabled without key | `refine-prompt` route |
| Generation through the real host pipeline (WanGP/API/local) | **verified (tests with fake pipeline)**; real GPU generation **not possible here** | queue delegates to `VideoGenerationHandler.generate` |
| Remake/edit prior generations | **verified (tests)** — imported shot regenerates with preserved seed; Quick history remake in UI implemented | |
| Continuity levels GOOD/MINOR/SIGNIFICANT/BROKEN + fixes | **verified (tests + UI)** | `film_continuity.py`, drawer Fix button, card dots |
| Versioning (append-only, promote, retry) | **verified (tests)** | |
| Production queue: pause/cancel/retry/prioritize, progress, no stuck "generating" after restart | **verified (tests + API/UI for pause)** | `recover_interrupted_jobs()` runs at startup |
| Model management: installed/available/compatible/download/remove | **verified (tests + UI panel)**; "update" = remove + re-download | `DELETE /api/models/{type}` |
| Quality profiles incl. RTX 4070-class recommendation | **verified (tests)**; UI picker verified | 12 GB → Balanced |
| Timeline integration (Send to Timeline, gap default 0) | **verified in earlier UI run**; default gap 0 confirmed in model | |
| AI auto-editing chat | **not done** beyond the director's structural commands (no timeline-editing tools) | see §7 |
| Simple vs advanced UI | **verified (UI)** | `ui-mode.ts` |
| Shot library / duplicate / reuse | duplicate verified; cross-project shot library **not done** | |
| Project export/import `.ltxfilm` with schema validation | **verified (tests + API round-trip in UI run)**; native dialogs not automatable | `film_package.py`, `docs/PROJECT_FORMAT.md` |
| Installer P0 (Windows) | **not verifiable here** — pipeline fixed, unsigned default; needs a Windows machine | `docs/INSTALLER.md` § Verification status |
| Linux installers | **verified**: AppImage + deb built and AppImage runtime-tested (runtime-only Python bundle) | |
| First-run experience | **verified (UI)**: getting-started strip; upstream FirstRunSetup unchanged | |
| Actionable errors | **implemented + UI**: `describeError()` mapping with actions; wired into dialog, director, build, quick | |
| Security hardening | see §5 | |
| Accessibility | **implemented**: keyboard-operable cards, roles, labels; screen-reader pass not performed | |
| Performance | not measured this pass; lazy composer chunk, compact director context (summary sizes reported) | |
| OpenRouter tests with no real key | **verified**: `test_film_openrouter.py` uses `test-placeholder-not-a-real-key` | |
| Docs | §9 | |

## 3. Architectural invariants (checked)

1. One host, one runtime — film generation calls `VideoGenerationHandler.generate`; no second engine (`film_generation_handler.py`).
2. Backend film store is the single source of truth; the UI never keeps a parallel copy (`FilmContext.refresh`).
3. Every AI mutation is a registry command validated like a UI request (`FilmDirectorHandler._execute`).
4. Secrets live only in the backend settings store / env; API responses expose `has_*` flags (`to_settings_response`, tests).
5. Media served only from the outputs directory / project directory with traversal guards (`/api/film/output`, `resolve_media_path`, package import).
6. Composition math ported from Open Media keeps attribution headers (`composer/shotSolver.ts`, `INTEGRATED_UPSTREAMS.md`).
7. Schema is versioned; additive fields default; packages validate through `migrate()`.
8. Queue state is persisted before work starts; restart recovery exists.
9. Electron renderer: `contextIsolation`, `nodeIntegration: false`, `sandbox: true`; all path IPC goes through `validatePath`.
10. No mocks in backend tests (`test_no_mock_usage.py`); fakes only.

## 4. Test inventory (backend)

| File | Covers |
|---|---|
| `test_film_store.py` | ids, migration, atomic save, corrupt preservation |
| `test_film_api.py` | CRUD, capture, poses, continuity |
| `test_film_generation.py` | queue → real pipeline path, previews/finals, strict continuity, promote, batch, capabilities |
| `test_film_director.py` | commands, instruct (JSON plan), storyboard generation |
| `test_film_openrouter.py` | secret handling, env fallback, clear, discovery/cache, validate, tool loop (both providers), history, chat, refine, build |
| `test_film_quick_mode.py` | import-generation conversion, regenerate with preserved seed, seed reporting |
| `test_film_hardening.py` | continuity levels + fixes, queue pause/resume/cancel/prioritize, restart recovery, quality profiles, model removal, additive schema |
| `test_film_package.py` | export/import round-trip incl. media, validation, traversal, v0 migration |
| `test_film_acceptance.py` | 2-scene / 5-shot end-to-end film through the API |
| `test_auth.py` (media token), `test_settings.py`, host suites | unchanged host coverage |

Frontend: no unit tests exist in the host (documented); UI verified by CDP
scripts in the scratchpad (`verify-ui.mjs`, `check-appimage.mjs`,
`verify-hardening.mjs`).

## 5. Security review

| Area | Finding | Action |
|---|---|---|
| Electron IPC | `show-item-in-folder`, `search-directory-for-files`, `check-files-exist`, `set-project-assets-path` accepted arbitrary paths | now validated against allowed roots / dialog-approved paths |
| Renderer flags | sandbox relied on Electron default | `sandbox: true` stated explicitly; `webSecurity` off only in dev |
| Secrets | LTX/FAL/Gemini keys already plaintext in backend settings file | OpenRouter follows the same store (documented limitation in `OPENROUTER.md`); env var alternative; never in responses/logs/project files; explicit clear route |
| Media/file routes | `/api/film/output` restricted to outputs dir; project media to project dir | package import re-checks every extracted path against the resolved project dir; extension allowlist; size caps |
| Package export/import | reads/writes user-chosen absolute paths | export forces `.ltxfilm` suffix; import validates fully before writing; only local, token-protected API |
| Auth | bearer token; media GETs accept `?token=` for `<img>/<video>` | unchanged, documented |
| Error bodies | 500 handler returns `str(exc)` (may include paths) | unchanged host behavior; noted |

## 6. Installer status

See `docs/INSTALLER.md` § Verification status. Summary: Linux built and
runtime-tested (runtime-only Python bundle because the container cannot
reach the PyTorch index); Windows pipeline made buildable without signing
credentials but **not built or installed here** (no Wine); macOS untouched
and unverified. Do not declare the Windows installer done until the
`RELEASE_CHECKLIST.md` § 2 steps are performed on Windows.

## 7. Known gaps / not done

- **AI auto-editing of the timeline** (cut/trim/reorder clips by chat): not
  implemented; the director's tools cover the storyboard, not the editor.
- **Cross-project shot library**: shots can be duplicated within a project;
  no global library.
- **Real generation, real LLM calls, Windows/macOS installers**: not
  exercisable in this environment.
- **Electron safeStorage for keys**: not adopted (would split secret
  handling from the host's existing keys); plaintext settings file remains
  the documented limitation.
- **Frontend unit tests**: none (host convention); coverage is backend
  integration tests + CDP UI runs.
- **Performance budgets**: not measured.
- **Continuity "continuity" AI role**: reserved in settings; no dedicated
  continuity assistant endpoint yet (fixes are deterministic).

## 8. Data / schema changes this pass

Additive only, no `schema_version` bump: `FilmProjectSettings.default_quality_preset`
(default `balanced`), `ShotGenerationSettings.quality_preset` gains `project`
(new default), `ContinuityWarning` gains `severity/fix/auto_fixable/subject_id`,
`FilmQueueResponse` gains `paused/progress/phase`, `FilmCapabilitiesResponse`
gains `profiles`, `GenerateVideoResponse` gains `seed`, app settings gain
`openrouter_api_key`, `director_provider`, `openrouter_models`.

## 9. Documentation delivered

`README.md` (entry points, OpenRouter, installers, docs list) ·
`docs/FILMMAKING.md` · `docs/STORYBOARD.md` · `docs/SHOT_COMPOSER.md` ·
`docs/AI_DIRECTOR.md` · `docs/OPENROUTER.md` · `docs/GENERATION_PIPELINE.md` ·
`docs/CONTINUITY.md` · `docs/PROJECT_FORMAT.md` · `docs/INSTALLER.md` ·
`docs/RELEASE_CHECKLIST.md` · `docs/FILMMAKING_INTEGRATION_ARCHITECTURE.md` ·
`docs/INTEGRATED_UPSTREAMS.md` · this audit.

## 10. End-to-end UI verification (this pass)

Script: `scripts/verify/verify-hardening.mjs` (Playwright over CDP) against
the dev Electron app under Xvfb. Runtime detected the sibling `Wan2GP`
checkout (WanGP mode) on a machine with no GPU and without the bridge's
Python packages, so the generation attempt fails fast — which is exactly the
failure path being checked. No AI provider was reachable; the OpenRouter
steps use a placeholder key and only verify storage/masking/clear behaviour.

**Result: 33/33 passed** (2026-09-08).

| # | Check | Result |
|---|---|---|
| 1 | Home shows "What do you want to make?" + getting-started strip | pass |
| 2 | Quick video view renders prompt/model/resolution/duration/aspect; explains how to enable the assistant | pass |
| 3 | Filmmaker Studio → new film opens on the Storyboard tab with *Build Film with AI* | pass |
| 4 | Build Film (offline planner) → editable plan → scene title edit → apply → 9 shot cards | pass |
| 5 | Shot drawer via keyboard (Enter on a focused card): continuity GOOD, quality profile picker, *Refine with AI* disabled without provider | pass |
| 6 | Location mismatch (scene vs shot) → drawer SIGNIFICANT, card dot, one-click **Fix** → GOOD | pass |
| 7 | Preview attempt → version recorded as `failed: No module named 'mmgp'`; shot back to `composed` (not stuck) | pass |
| 8 | Queue payload carries `paused/progress/phase`; pause shows **Resume** in the header | pass |
| 9 | Simple mode hides Script tab; Advanced restores | pass |
| 10 | Models tab: quality profiles + project render defaults | pass |
| 11 | Settings → API Keys: OpenRouter section, masked input, save placeholder → backend reports `hasOpenrouterApiKey` without the value, validation feedback shown, director status active, **Remove** clears | pass |
| 12 | Director bar links to Settings when no provider | pass |
| 13 | `import-generation` (Quick → Film) creates Scene 1 / Shot 1 / v1 with seed and output preserved | pass |
| 14 | Export `.ltxfilm` → inspect → import into a new project | pass |

Not covered by this run (environment): real generation output, real LLM
replies, native file dialogs (export/import buttons call them; the API path
was exercised instead), Windows/macOS installers.
