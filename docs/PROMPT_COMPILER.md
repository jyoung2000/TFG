# The model-specific prompt compiler

The same shot reads differently to different models. LTX's own guidance asks
for a chronological paragraph of natural language. Wan's asks for subject,
scene and motion. Tag-trained image checkpoints want a comma-separated
descriptor list. Writing one prompt string and sending it everywhere means it
is wrong almost everywhere.

So a shot is held once, structured, and compiled per target.

## The common cinematic representation

A `ShotBrief` is the shot before any model sees it — the fourteen sections a
director would actually specify:

| Section | Holds |
|---|---|
| `scene_intent` | What the shot is for in the story |
| `subjects` | Who and what is in frame, with their description and wardrobe |
| `action` | What happens |
| `location` | Where |
| `shot_size` | Extreme wide through extreme close-up |
| `camera` | Angle, elevation, composition |
| `lens` | Focal length, depth of field |
| `movement` | Push in, track, orbit, static |
| `lighting` | Sources, time of day, contrast |
| `style` | Palette, grade, production design |
| `audio` | Dialogue, ambience, score |
| `timeline` | Duration, frame rate, pacing |
| `continuity` | What must match the neighbouring shots |
| `negative` | Constraints |

Every field is optional, and an empty section is omitted rather than padded. A
prompt that invents a lens because the field was blank is a prompt that lies
about the shot.

**`scene_intent` is never compiled into a render prompt.** No model can act on
"establish the diner before the argument". It is carried so the director, the
UI and a human reader keep the shot's purpose with it, and the compiler does
not report dropping it — because it was never sent.

Two builders produce briefs, and after that the compiler cannot tell them
apart, so a shot recovered from an imported video gets exactly the same
treatment as one authored in the storyboard:

- `brief_from_shot(project, scene, shot)` — the storyboard's structured fields
- `brief_from_analysis(analysis, shot)` — what was measured and inferred from
  an imported video

Both read the shared vocabulary in `film/shot_vocabulary.py`, so the words a
shot is described with never drift between the prompt the host renders and the
prompt compiled for somewhere else.

## Targets

A target is a family of models plus how it wants to be addressed. What actually
differs between families is the *shape*, not the vocabulary:

| Style | Shape |
|---|---|
| `narrative` | One paragraph, in the order a viewer takes the shot in |
| `structured` | Short labelled clauses: Subject, Scene, Framing, Motion, … |
| `tagged` | Comma-separated descriptors, most load-bearing first |

Each target also declares its character budget, whether it takes a negative
prompt, whether it renders sound, and whether it renders motion at all.

| Target | Style | Basis |
|---|---|---|
| LTX Video | narrative | publisher guidance |
| Wan | structured | publisher guidance |
| HunyuanVideo | narrative | community convention |
| FLUX (stills) | narrative | publisher guidance |
| SDXL-family checkpoints (stills) | tagged | community convention |
| Veo-style hosted video | narrative | community convention |
| **General video model** (fallback) | narrative | this app's default |

The `basis` is part of the record and is shown in the UI, because "the
publisher documents this convention" and "this is our house style" are
different claims and should not look alike.

**An unrecognised model is labelled as unrecognised.** It gets the general
convention and `matched: false`, and the UI says "Not a model this app has a
convention for" rather than presenting a generic prompt as tailored. Natural
language is the fallback because a tag list sent to a model that wants prose
degrades worse than prose sent to a model that wants tags.

## Nothing is lost silently

Every compilation returns a `dropped` list with a reason for each section the
target could not carry:

```
Left out: movement — FLUX (stills) renders a still frame
Left out: audio — LTX Video renders no sound
Left out: negative constraints — FLUX (stills) takes no negative prompt
Left out: style — over the 600-character budget for SDXL-family checkpoints
```

A prompt that quietly lost the continuity constraints is worse than one that
says it did.

When a brief exceeds a target's budget, sections are given up in this order:

```
style → lens → timeline → lighting → camera → location
```

Subjects, action, shot size, movement and continuity are absent from that list
on purpose: losing any of them changes what gets rendered, so they are never
traded for length. If the brief is still too long with everything sacrificeable
gone, it is cut at a clause boundary and says so.

## Where it shows up

- **Storyboard → shot drawer → "Written for other models"**: the shot compiled
  for whatever this project could render with (its hosted model, plus the local
  LTX host). The prompt above it is what the host renders; this is what a
  different model would be sent.
- **Analyse Video → shot inspector**: the same panel for a shot recovered from
  an imported video.
- **`ReversePrompts.model_specific`**, filled during analysis for the models
  the user has configured. It used to be defined and always empty.

Both panels show the brief above the prompts, collapsed. The compiled strings
are disposable and regenerate whenever the target changes; the brief is what
was actually said about the shot.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/prompts/targets` | Every convention, with what identifies it and where it came from |
| `POST` | `/api/prompts/compile` | Compile one shot for a set of models |

`compile` takes exactly one source — an explicit `brief`, a storyboard shot
(`project_id` + `scene_id` + `shot_id`), or an analysed shot (`analysis_id` +
`analysis_shot_id`). Naming none or more than one is a 400: guessing between a
storyboard shot and an analysed shot would silently compile the wrong thing.

The response carries the brief alongside the prompts, so a caller can always
show what was said before any model saw it.

`targets` exists so the rule is inspectable, not just its output: a user who
disagrees with how their model was classified can see exactly what matched it.

## Code map

| File | Role |
|---|---|
| `backend/film/prompt_compiler.py` | `ShotBrief`, targets, `compile_prompt` — a pure function |
| `backend/film/prompt_brief.py` | Briefs from a storyboard shot and from an analysed shot |
| `backend/film/shot_vocabulary.py` | The phrase tables both prompt paths read |
| `backend/handlers/prompt_handler.py` | Finds the named shot; refuses an ambiguous request |
| `backend/_routes/prompts.py` | Routes |
| `frontend/types/prompts.ts` | Mirror of the backend types |
| `frontend/lib/prompts-api.ts` | Typed client |
| `frontend/components/CompiledPrompts.tsx` | The panel, used by both the drawer and the analysis inspector |
| `devtools/ui-mock/routes/prompts.ts` | UI-only mock: the same rules, restated |

## Tests

`backend/tests/test_prompt_compiler.py` — 25 tests covering target resolution
(including the unrecognised case and the basis of each convention), that the
same brief genuinely reads differently per family, that the action survives
into every target, that scene intent never reaches a model and is never
reported as dropped, every drop-with-reason path, budget sacrifice order,
continuity surviving truncation, both brief builders against the real app, the
routes including the ambiguous-source refusal, and that
`ReversePrompts.model_specific` is actually filled after an analysis.
