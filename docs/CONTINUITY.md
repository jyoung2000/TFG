# Continuity

Continuity is built on reusable project assets: define a character, location
or prop once, reference it from scenes and shots, and the prompt synthesizer
injects the same description/appearance/wardrobe/lighting text everywhere —
so consistency comes from shared state, not from retyping.

## Warnings — `GET /api/film/projects/{id}/continuity/{shotId}`

Non-blocking by default; surfaced in the shot drawer as amber notices:

| Kind | Fires when |
|---|---|
| `missing_asset` | a shot references a deleted character/location/prop |
| `location_mismatch` | the shot's location differs from its scene's |
| `character_not_in_scene` | a shot character isn't in the scene's declared cast |
| `prop_not_in_scene` | a shot prop isn't in the scene's declared props |
| `missing_capture` | generation is set to use the capture, but none exists |
| `missing_previous_output` | continue-from-previous is on, but the previous shot has no output |
| `wardrobe_change` | a character's wardrobe changed since the previous shot's current version was generated (compared against that version's wardrobe snapshot) |
| `duration_invalid` | duration ≤ 0 |

Every generated version snapshots each character's wardrobe at generation
time (`ShotVersion.wardrobe_snapshot`), which is what makes the wardrobe
check a real "differs from what was actually rendered" comparison rather
than a guess.

## Strict mode

`settings.strict_continuity` (off by default) turns warnings into a 409 that
blocks queueing until resolved. Deleting an asset scrubs its references from
all scenes/shots so nothing dangles.

## Previous-shot continuation

Per shot, `continue_from_previous` extracts the last frame of the previous
shot's current output (via the video-processor service), saves it beside the
captures as `<shot>-continue.jpg` (visible, traceable), and uses it as the
image conditioning reference when no capture reference is in play.
