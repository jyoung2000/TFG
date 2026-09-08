# OpenRouter (AI Director provider)

OpenRouter is the first-class LLM provider for every AI feature in the
filmmaking layer: the AI Director bar (tool calling), *Build Film with AI*,
*AI Storyboard*, shot prompt refinement, and the Quick Mode idea chat. Gemini
remains available as an alternative provider through the same abstraction.

## Setup

1. Create a key at <https://openrouter.ai/keys>.
2. **Settings → API Keys → OpenRouter**: paste the key and press *Save Key*.
   The app immediately validates it (`GET /api/v1/auth/key`) and loads the
   model list.
3. Pick models per role (or leave everything on the default).

Alternatively export `OPENROUTER_API_KEY` in the environment that launches
the app; the Settings panel then shows *Key from OPENROUTER_API_KEY*. A key
saved in Settings takes precedence over the environment variable.

## Where the secret lives

| Store | Used? | Notes |
|---|---|---|
| Backend settings file (`<userData>/settings.json`, field `openrouter_api_key`) | **yes** | Same store the host already uses for the LTX, FAL and Gemini keys. Written by the Python backend only. |
| `OPENROUTER_API_KEY` environment variable | **yes (fallback)** | Never persisted by the app. |
| Frontend `localStorage` / project files | **no** | The renderer never receives the key. `GET /api/settings` returns only `hasOpenrouterApiKey` + `openrouterKeySource`. Film project JSON never contains provider settings. |
| Electron `safeStorage` | no | Not used by the host for any existing key; adopting it only for OpenRouter would split secret handling across two stores. Documented limitation: the settings file is plaintext on disk, protected by OS user permissions (identical to the pre-existing LTX/FAL/Gemini keys). |

Guarantees enforced by tests (`backend/tests/test_film_openrouter.py`):

- the key never appears in any API response body;
- it only travels in the `Authorization: Bearer` header of requests to
  `https://openrouter.ai/api/v1/*`;
- a `401` from OpenRouter is surfaced as `OPENROUTER_KEY_INVALID` without
  echoing the key, and *Remove* (`DELETE /api/settings/api-keys/openrouter`)
  clears it cleanly (an empty string in the normal settings patch is ignored,
  so clearing is an explicit action);
- no test or fixture contains a real key.

The backend never logs the key; HTTP errors are logged with the remote status
text only.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /api/film/director/status` | Active provider (`openrouter` / `gemini` / `none`), key source, model per role, tool catalog. |
| `GET /api/film/director/openrouter/models[?refresh=true]` | Model discovery from `GET https://openrouter.ai/api/v1/models`; cached for 10 minutes. Each entry carries `supports_tools` / `supports_json` derived from `supported_parameters`. |
| `POST /api/film/director/openrouter/validate` | Validates the configured key against `GET https://openrouter.ai/api/v1/auth/key`; returns label / usage / limit, never the key. |
| `POST /api/settings` with `openrouterApiKey`, `directorProvider`, `openrouterModels` | Save the key / choose provider / role models. |
| `DELETE /api/settings/api-keys/openrouter` | Remove the stored key. |

Chat completions go to `POST https://openrouter.ai/api/v1/chat/completions`
(OpenAI-compatible payload with `tools` for the director role or
`response_format: json_object` for the JSON roles). The app also sends the
public attribution headers OpenRouter asks for (`HTTP-Referer`, `X-Title`).

## Provider selection and roles

`directorProvider` is `auto` (OpenRouter when a key exists, else Gemini),
`openrouter`, or `gemini`. With OpenRouter, `openrouterModels` maps each role
to a model id (`''` = `defaultModel`, which defaults to `openai/gpt-4o-mini`):

| Role | Used by |
|---|---|
| `director` | AI Director bar — needs a model with tool support (models without it fall back to the JSON-plan protocol automatically). |
| `script` | Build Film with AI (idea → screenplay + shot plan). |
| `storyboard` | AI Storyboard (script → cinematographed shots). |
| `prompt_refinement` | *Refine with AI* on a shot, Quick Mode idea chat. |
| `continuity` | Continuity explanations (reserved for the continuity assistant). |

## Errors you may see

| Message | Meaning / fix |
|---|---|
| `AI_DIRECTOR_KEY_MISSING` | No provider configured — add a key in Settings or set `OPENROUTER_API_KEY`. |
| `OPENROUTER_KEY_INVALID` | OpenRouter answered 401 — remove the key and add a valid one. |
| `OPENROUTER_CREDITS` | 402 — top up credits or choose a free model. |
| `OPENROUTER_MODEL_NOT_FOUND` | The role's model id is wrong or retired — pick another from the list. |
| `OPENROUTER_RATE_LIMITED` | 429 — retry shortly. |
| `OpenRouter request timed out` | 90 s timeout; try a faster model. |

## Context efficiency

Every AI call returns `context` (provider, model, role, model turns, tool
calls, characters sent, project-summary size, prompt/completion tokens when
the provider reports usage, and a one-line *scope*). The UI shows it under
*context details*. The director sends a compact project summary (no 3D
compositions, no version history) and, when the user has a scene selected,
expands only that scene. Tool results fed back to the model are capped at
6 kB each and the loop stops after 12 model turns.
