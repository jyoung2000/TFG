# Analyse Video — turning an existing clip into a storyboard

The reverse of the filmmaking flow:

```
video → detect shots → analyse → review → create storyboard → edit → generate
```

Reachable from **Home → Analyse video**.

## What runs where

| Stage | Needs | Notes |
|---|---|---|
| Import | nothing | Reads container metadata with PyAV — no ffmpeg binary, no subprocess |
| Detect shots | nothing | Deterministic; re-runs instantly when you change sensitivity |
| Extract frames | nothing | One still per shot, three on *Detailed* |
| Analyse | a multimodal provider | Without one, measurable fields are still filled |
| Create storyboard | nothing | Produces an ordinary film project |

Only the analyse stage talks to a model. Everything before it works with no
provider, no key and no network, which is why importing a video and seeing its
shots is an offline capability rather than a hosted one.

## How the shots are found

Frames are sampled (2–8/s by depth), reduced to a 64×36 greyscale histogram,
and compared. The cut threshold floats with the material — the median change
plus a multiple of the median absolute deviation — because a fixed number
cannot serve both a static interview and a music video. Sensitivity moves that
multiple.

A dissolve through black is caught separately as a luma trough. Cuts closer
together than the minimum shot length are collapsed, keeping the stronger one.

**When nothing is found**, the video is split evenly and every boundary is
labelled `uniform` with zero confidence. The UI shows those as *arbitrary*.
A continuous take is never reported as a series of detected cuts.

You can split, merge and drag boundaries. An edited boundary is pinned: a
later re-detect says how many it replaced instead of silently discarding them,
and shots whose span did not move keep the analysis they already had.

## Measured versus inferred

The schema keeps these apart, and so does the UI:

- **Measured** — duration, frame rate, codec, cut type, rhythm, the beat. From
  the file. Shown as *measured*.
- **Inferred** — framing, camera language, narrative purpose. From a model.
  Each group carries its own confidence, shown in words.

Every reading keeps the frames that produced it and the raw model reply, so
**Why did the AI write this?** has a real answer. When no model ran, it says
so rather than implying one did.

## Prompts

Each shot gets a storyboard prompt, a video prompt, and cinematography,
environment, character, motion and negative prompts. Edit any of them and it
is marked as yours — re-analysing will not overwrite it.

> `model_specific` is defined in the schema but not yet populated. Per-model
> prompt compilation is not implemented; see `docs/RELEASE_MATRIX.json`.

## The reconstructed project

Not a special kind of project — the same `FilmProject` the storyboard authors,
so the composer, queue, continuity, versions and export all work on it. Each
shot carries `source_ref` back to the analysis and the exact span of the
source, so evidence stays reachable after reconstruction.

## Security

Imported media is untrusted input. Paths are checked (absolute, existing,
known video suffix) before anything opens them; frames are served only from
inside the analysis directory; decoding goes through PyAV's library bindings
rather than a shell, so there is no command line to escape. Text extracted
from a video is data for the schema and never reaches a tool-calling loop.

## API

`/api/video-analysis` — `import`, `detect`, `analyze`, `cancel`,
`shots/{id}/split|merge|boundary|prompts`, `reconstruct`, `frame`, and
list/get/delete. Request and response shapes mirror
`frontend/types/video-analysis.ts`.
