# Filmmaking in LTX Desktop — overview

LTX Desktop is one local application with two entry points that share the
same engine, projects and settings:

| Entry | What it is | Where it leads |
|---|---|---|
| **Quick video** | Describe an idea (optionally with the assistant), pick model/length, generate one clip. | *Edit in Film Maker* turns the clip into a film project (Scene 1 / Shot 1 / version 1 with prompt, seed, model, resolution, duration and output preserved); *Save to project* / *Open in Video Editor* keep it as a regular asset. |
| **Filmmaker Studio** | A project's **Storyboard** tab: script, assets, scenes, shots, 3D Shot Composer, continuity, AI Director, production queue, versions, then the Video Editor timeline. | Final cut exported from the Video Editor. |

Nothing in the film layer has its own inference engine: every render goes
through the host's `VideoGenerationHandler` (WanGP bridge, LTX API or the
local LTX pipeline — whichever the machine is configured for), or, when a
hosted media provider is selected, through the same single film queue against
fal / WaveSpeed / Replicate. See `GENERATION_PIPELINE.md` and
`AI_PROVIDERS.md`.

## The workflow

1. **Start** — Home → *Filmmaker Studio* (or promote a quick video).
2. **Build the world** — *Assets*: characters (appearance, wardrobe),
   locations (environment, lighting), props, style. Reference images attach
   to assets. These are the single source of truth continuity is checked
   against (`CONTINUITY.md`).
3. **Break the story into shots** — three ways, all producing *draft* shots:
   - *Build Film with AI*: idea → editable plan (title, logline, characters,
     locations, scenes, shots with framing/move/duration) → apply. Works
     offline with the deterministic planner, better with an AI key.
   - *Script* tab → *Generate Storyboard* (offline parser) or *AI Storyboard*.
   - By hand: *Scene*, *Add shot*, and the **AI Director** bar
     ("make shot 2 a six-second OTS on Sarah, slow push-in") — see
     `AI_DIRECTOR.md`.
4. **Compose** — *Compose Shot* opens the native 3D Shot Composer
   (`SHOT_COMPOSER.md`): shot size / angle / elevation / composition presets
   solved geometrically, OTS/POV relationships, posable figures with a pose
   library, camera-move keyframes, then **Capture** to produce the reference
   frame and stamp the shot `ready`.
5. **Check continuity** — each card carries a level (good / minor /
   significant / broken); the drawer lists warnings with one-click fixes.
   *Strict continuity* can block rendering until clean.
6. **Generate** — *Preview* (fast, small) or *Final* (quality profile:
   Fast Preview / Balanced / Quality / Custom, recommended per GPU). Jobs run
   through one production queue with pause/resume, per-job cancel and
   prioritize, live progress, and restart recovery. Every attempt is a
   **version**; promote any completed version to current, retry failures.
7. **Review and cut** — Approve/Reject, *Send to Timeline*, edit and export
   in the Video Editor.
8. **Share** — *Export* writes a portable `.ltxfilm` package (project +
   captures + references + renders); *Import* validates it before anything
   is written (`PROJECT_FORMAT.md`).

## AI, optional by design

Every AI feature is powered by the AI Director provider layer: **OpenRouter**,
**Claude**, **Grok**, **Gemini**, or any **local OpenAI-compatible server**
(LM Studio, Ollama, vLLM). Without a key the app is fully usable: offline
planner, screenplay parser, composer, continuity, generation, queue,
export/import. With a provider you get Build Film with AI, AI Storyboard, the
director bar (tool calling against the same project state the UI edits),
prompt refinement, and the Quick-video assistant — each reply discloses
exactly what context was sent ("context details").

Rendering is equally pluggable: **Local** (the host engine) by default, or
**fal**, **WaveSpeed**, **Replicate** with a key. The AI Director bar carries
*Director* / *Video* / *Image* chips so the models in use are visible and
switchable without leaving the chat.

**Fully offline** is a first-class path, not a fallback: local weights for
video/image plus a local text server covers the whole workflow with no
network at all. *Storyboard → Models → Model Library* is one searchable
catalog of every model — local and hosted — with downloads for the ones that
run on this machine, and it states plainly whether the offline set is
complete. See `AI_PROVIDERS.md`.

## Where things live

- Film data: `<app data>/outputs/film_projects/<project-id>/` (`PROJECT_FORMAT.md`)
- Renders: `<app data>/outputs/`
- Settings and API keys: the backend settings file (`AI_PROVIDERS.md` / `OPENROUTER.md` for the secret-handling rules)
- Simple vs advanced UI: toggle in the storyboard header (hides script/models tabs, export/import, quality profiles, context details)

## Documentation map

`STORYBOARD.md` · `SHOT_COMPOSER.md` · `AI_DIRECTOR.md` · `AI_PROVIDERS.md` ·
`OPENROUTER.md` · `GENERATION_PIPELINE.md` · `CONTINUITY.md` · `PROJECT_FORMAT.md` ·
`INSTALLER.md` · `RELEASE_CHECKLIST.md` · `FILMMAKING_INTEGRATION_ARCHITECTURE.md` ·
`INTEGRATED_UPSTREAMS.md` · `FINAL_HARDENING_AUDIT.md`
