# Continuity

Continuity is built on reusable project assets: define a character, location
or prop once, reference it from scenes and shots, and the prompt synthesizer
injects the same description/appearance/wardrobe/lighting text everywhere —
so consistency comes from shared state, not from retyping.

## Levels

Every shot has a continuity **level**, the worst severity among its warnings:

| Level | Meaning | Storyboard card |
|---|---|---|
| `good` | no warnings | no marker |
| `minor` | cosmetic bookkeeping (cast/props not declared on the scene, composed but not captured) | amber dot |
| `significant` | something the render will get wrong (location differs from the scene, wardrobe changed since the previous shot was rendered, continue-from-previous has no source) | orange dot |
| `broken` | the shot cannot render as specified (dangling asset reference, duration ≤ 0) | red dot |

`GET /api/film/projects/{id}/continuity/{shotId}` → `{level, warnings[]}`;
`GET /api/film/projects/{id}/continuity` → project summary (`level`, per-shot
levels, counts per level) which the storyboard uses for the card markers.

## Warnings and fixes

Each warning carries `severity`, a human `fix` suggestion, `auto_fixable`,
and the `subject_id` it concerns. `POST …/continuity/{shotId}/fix`
`{kind, subject_id?}` applies the built-in repair — always the same mutation
the user could make by hand:

| Kind | Severity | Fires when | Auto-fix |
|---|---|---|---|
| `missing_asset` | broken | a shot references a deleted character/location/prop | remove the dangling reference |
| `duration_invalid` | broken | duration ≤ 0 | set 4 s |
| `location_mismatch` | significant | the shot's location differs from its scene's | use the scene's location |
| `missing_previous_output` | significant | continue-from-previous is on, but the previous shot has no output | turn continue-from-previous off |
| `wardrobe_change` | significant | a character's wardrobe changed since the previous shot's current version was generated (compared against that version's wardrobe snapshot) | **none** — regenerate the earlier shot or restore the wardrobe (creative decision) |
| `character_not_in_scene` | minor | a shot character isn't in the scene's declared cast | add to the scene's cast |
| `prop_not_in_scene` | minor | a shot prop isn't in the scene's declared props | add to the scene's props |
| `missing_capture` | minor | the shot was composed in 3D but never captured, and generation expects the capture | generate from text only |
| `screen_direction` | significant | the shot camera is on the other side of the line between the two shared characters compared with the previous shot of the scene (180° rule), computed from the composer's camera and figure positions | **none** — move the camera or add a neutral shot (creative decision) |
| `jump_cut` | minor | same subject, same shot size, angle, elevation and camera move as the previous shot | none — change size by two steps or the angle |
| `framing_jump` | minor | extreme size jump on the same axis (e.g. extreme wide → extreme close-up, same angle) | none — add an intermediate size or change the angle |

The three screen-direction checks are deterministic (no model involved) and
are warnings by design: filmmakers break them on purpose.

## Optional AI visual review

`POST /api/film/projects/{id}/continuity/{shotId}/visual-review` compares the
**last frame of the previous shot's current version** with the **first frame
of this shot's current version** through the configured multimodal provider
(`continuity` role). The frames are saved as
`captures/<shot>-review-prev.jpg` / `-cur.jpg` and shown in the drawer. The
answer is one of **Good / Minor drift / Review recommended / Likely
continuity break** plus a one-line summary and specific observations.

It is advisory only: it never changes the deterministic level, never blocks
generation, and returns `available: false` with a plain reason when there is
no provider, the provider cannot see images, either shot has no render, or
the model does not answer in the expected format. Keys never appear in the
request body (images travel as data URLs inside the message content).

An uncomposed draft is *not* flagged for a missing capture — it simply
generates from text — so new shots start `good`.

Every generated version snapshots each character's wardrobe at generation
time (`ShotVersion.wardrobe_snapshot`), which is what makes the wardrobe
check a real "differs from what was actually rendered" comparison rather
than a guess. The shot drawer shows the level, each warning, its suggested
fix and a one-click **Fix** where possible.

## Strict mode

`settings.strict_continuity` (off by default; toggle in the storyboard's
*Project render defaults*) turns warnings into a 409 that blocks queueing
until resolved. Deleting an asset scrubs its references from all
scenes/shots so nothing dangles.

## Previous-shot continuation

Per shot, `continue_from_previous` extracts the last frame of the previous
shot's current output (via the video-processor service), saves it beside the
captures as `<shot>-continue.jpg` (visible, traceable), and uses it as the
image conditioning reference when no capture reference is in play.
