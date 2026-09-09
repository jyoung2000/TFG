# AI providers and the Model Library

Every AI capability in LTX Desktop — the AI Director, script and storyboard
planning, prompt refinement, and image/video generation itself — runs through
one of two pluggable layers:

| Layer | What it does | Code |
|---|---|---|
| **Text providers** | The AI Director bar, *Build Film with AI*, AI Storyboard, prompt refinement, Quick-mode idea chat. Tool calling and JSON mode where the vendor supports it. | `backend/film/llm_providers.py` |
| **Media providers** | Actually rendering a shot or an asset reference image. | `backend/film/media_providers.py`, `backend/film/media_runner.py` |

Both layers sit on the same fakeable `HTTPClient` service, so every provider
is covered by tests that run with no network and no keys
(`backend/tests/test_model_providers.py`).

The app is usable with **no provider at all**: the offline planner, the
screenplay parser, the Shot Composer, continuity, the queue, versions and
export/import never call out. Providers add capability; they are never a
prerequisite.

---

## Text providers (AI Director)

| Provider | Setting id | Default model | Endpoint | Tool calling |
|---|---|---|---|---|
| OpenRouter | `openrouter` | `openai/gpt-4o-mini` | `https://openrouter.ai/api/v1` | yes |
| Claude (Anthropic) | `anthropic` | `claude-sonnet-5` | `https://api.anthropic.com/v1` | yes |
| Grok (xAI) | `xai` | `grok-4` | `https://api.x.ai/v1` (OpenAI-compatible) | yes |
| Gemini (Google) | `gemini` | `gemini-2.0-flash` | Generative Language API | yes |
| Local / OpenAI-compatible | `openai_compatible` | whatever the server serves | your `base URL` (LM Studio, Ollama, vLLM, llama.cpp…) | model-dependent |

**Choosing one.** *Settings → API Keys* has a card per provider: paste the
key, press *Save Key* (the app validates it immediately), then pick a model
from the live list the provider returns. The **AI Director provider**
selector chooses which one the app uses; left on **Auto** it takes the first
configured provider in this order:

```
openrouter → anthropic → xai → gemini → openai_compatible
```

Selecting a provider explicitly that has no key is not silently ignored — the
director status names that provider and tells you which key is missing.

Per-role model overrides (director / planner / refiner) still work for
OpenRouter exactly as before (`OPENROUTER.md`); the other providers use one
model per provider, resolved by `AppSettings.director_model_for()`.

`GET /api/film/director/status` reports every provider's configured state,
the active one, and a human-readable reason when nothing is usable.
`GET /api/film/director/models?provider=…&refresh=1` returns the provider's
live model list.

### Local text, fully offline

Point the **Local / OpenAI-compatible** card at any server that speaks
`POST /v1/chat/completions`:

```
Base URL   http://127.0.0.1:11434/v1     # Ollama
           http://127.0.0.1:1234/v1      # LM Studio
           http://127.0.0.1:8000/v1      # vLLM
API key    (usually blank; sent as a bearer token when set)
Model      llama3.1:8b, qwen2.5:14b, …
```

Nothing leaves the machine. A server that is down fails with a typed,
key-free `502` (`openai_compatible unreachable: …`) instead of a crash.

---

## Media providers (image and video generation)

| Provider | Setting id | API | Notes |
|---|---|---|---|
| **Local** (default) | `local` | — | The host's own engine: WanGP bridge, LTX cloud API, or the local LTX pipeline, exactly as `GENERATION_PIPELINE.md` describes. |
| fal.ai | `fal` | `https://queue.fal.run` | Queue API, `Authorization: Key …` |
| WaveSpeed AI | `wavespeed` | `https://api.wavespeed.ai/api/v3` | Submit → poll → download |
| Replicate | `replicate` | `https://api.replicate.com/v1` | Model predictions, or `version` for a pinned build |

All three hosted providers have the same shape — **submit a job, poll until
it finishes, download the file** — so `MediaProvider` exposes exactly that
and one loop in `MediaRunner` drives all of them.

**What stays the same when you render on a hosted provider.** The film queue
is still the single queue: one job at a time, pause/resume, per-job cancel
and prioritize, live progress, versions appended the same way, the same
restart recovery, the same telemetry (with `execution_mode` set to the
provider name). The downloaded file lands in the same outputs directory and
behaves identically in the timeline, the editor and `.ltxfilm` export. The
film layer never becomes a parallel engine.

**Conditioning images** (image-to-video, image-to-image) are sent inline as
`data:` URLs. Nothing is uploaded to a third-party file host.

**Errors** are typed and never echo the key: a missing key fails the job with
a message naming the provider and the setting to fill in; provider `401`s
surface as an invalid-key error; timeouts fail the job rather than hanging
the queue.

---

## The Model Library

*Storyboard → **Models** tab → **Model Library*** is one searchable catalog
over everything this app can use, local and hosted side by side, so the same
screen answers both "what can I run offline?" and "what can I reach with a
key?".

`GET /api/models/library?query=&task=all|video|image|text&source=all|local|hosted&only_compatible=&refresh=`

| Source | Kind | What appears | Downloadable here |
|---|---|---|---|
| `wangp` | local | The WanGP checkout's own model definitions (`defaults/*.json`) | **yes** — weights hosted on Hugging Face |
| `native` | local | The native LTX pipeline's files | no — use the *Installed & GPU* view's download pipeline |
| `ollama` | local | Models an Ollama server already has (`/api/tags`) | **yes** — `POST /api/pull` |
| `openai_compatible` | local | Whatever your local server lists at `/models` | no (the server owns them) |
| `openrouter`, `anthropic`, `xai`, `gemini` | hosted | The provider's live text-model list | no |
| `fal`, `wavespeed`, `replicate` | hosted | Media models — see honesty note below | no |

Each row carries a state chip: `installed`, `available`, `downloading`,
`active`, `incompatible` (won't fit the detected GPU), `needs_key` (hosted,
no key saved) or `example`. Rows show size on disk, estimated minimum VRAM,
whether they fit this GPU, context length, family and quantization where the
source provides them.

**Downloads.** `POST /api/models/library/download` starts one download at a
time; `GET` polls files done / bytes / percent; `POST /download/cancel`
stops it. WanGP weights are fetched with the existing
`HuggingFaceDownloader`, so they land where WanGP already looks for them.

**Search is resilient.** Every source is independent: a provider that is
unreachable adds one error line to `sources` and the rest of the library
still lists. One dead endpoint never empties the page.

### Honest catalogs

fal and WaveSpeed publish no public catalog API. Rather than pretend
otherwise, the app ships a small list of **clearly labelled example ids**
(`curated: true`, rendered as *example* with a link to the provider's own
catalog). Replicate does have a discovery API, so its rows come from
Replicate's collections. **Any model id you paste is accepted** — the custom
id row takes a provider plus an id, uses it immediately, and remembers it
(`POST /api/models/library/remember`) so it shows up in the library next
time.

### Offline readiness

`ModelSearchResponse.offline_ready` is true when at least one local
video/image model **and** one local text model are installed — everything a
fully offline film needs. The library shows this as a banner with a note
saying what is still missing.

A complete offline setup:

1. **Video/image** — WanGP bridge configured (`WANGP_ROOT`) with a model
   downloaded from the library, or the native LTX pipeline's models
   downloaded in *Installed & GPU*.
2. **Text** — Ollama (or LM Studio / vLLM) running locally, its model pulled
   from the library, and the Local / OpenAI-compatible card pointed at it
   with **AI Director provider = Local**.
3. **Media provider = Local.**

From there nothing in the filmmaking workflow makes a network request.

---

## Picking models from the chat

The AI Director bar carries three chips — **Director**, **Video**, **Image** —
so the model in use is visible and switchable without opening Settings:

- **Director** picks the text provider (and, for local/hosted providers with
  a live list, the model) used for the next reply.
- **Video** and **Image** pick the media provider + model. The choice is
  written to the **film project** when one is open (so a project keeps its
  look), and otherwise to the app defaults (`default_video_model`,
  `default_image_model`).

Resolution order for a render is: the project's `media_provider` /
`video_model` / `image_model`, then the app settings, then `local`.

Assets can be given an AI-generated reference image the same way — *Assets →
Generate with AI* uses the selected image model (locally when the project
generates locally, otherwise on the chosen hosted provider) and attaches the
result as a normal reference image.

---

## Where the secrets live

Identical rules for every provider (`OPENROUTER.md` documents the reasoning
in full):

| Store | Used? |
|---|---|
| Backend settings file (`<userData>/settings.json`) | **yes** — written by the Python backend only |
| `OPENROUTER_API_KEY` environment variable | **yes**, for OpenRouter only (never persisted) |
| Frontend `localStorage`, film project JSON, `.ltxfilm` exports | **no** |

Guarantees enforced by tests:

- `GET /api/settings` returns only `hasAnthropicApiKey`, `hasXaiApiKey`,
  `hasWavespeedApiKey`, `hasReplicateApiKey`, … — never a key;
- a key travels only in the auth header of a request to that provider's own
  host;
- `DELETE /api/settings/api-keys/{provider}` clears it (an empty string in a
  normal settings patch is ignored, so clearing is always explicit);
- keys are masked in the UI and redacted from logs
  (`backend/logging_policy.py`);
- no test or fixture contains a real key.

Supported ids for the key routes: `openrouter`, `gemini`, `anthropic`,
`xai`, `openai-compatible`, `ltx`, `fal`, `wavespeed`, `replicate`.

---

## Adding another provider

1. Text: subclass the provider protocol in `film/llm_providers.py`
   (OpenAI-compatible vendors usually only need a base URL and a name).
   Media: implement submit/poll/download in `film/media_providers.py`.
2. Add the key + model fields to `state/app_settings.py`, the mirror flags to
   `SettingsResponse`, and the id to `_CLEARABLE_KEYS` / `_KEY_FIELDS`.
3. Register it in `handlers/film_director_handler.py` (`_PROVIDER_LABELS`,
   `_AUTO_ORDER`) or `media_provider()`, and in
   `handlers/model_library_handler.py` so it appears in the library.
4. Frontend: `types/models.ts` labels + `components/AiProviderSettings.tsx`.
5. Test it with `FakeHTTPClient` queues — no mocks, no network, no key.
