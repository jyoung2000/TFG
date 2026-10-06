# ADR 0002 — Remote backend and the WanGP server routes

**Status:** accepted (phase 9)

## Context

The 4070 is one machine; people also have a NAS or a bigger GPU elsewhere,
and Open-Generative-AI showed the appeal of "the desktop sends prompts, a
GPU box renders". WanGP's own Gradio API is undocumented for this purpose
and changes with WanGP releases.

## Decision

1. The desktop can point at **any TFG backend** (Settings → General →
   Remote backend). Electron stores URL + token in `app_state.json`, stops
   the local Python process, and `getBackend()` returns the remote pair.
   Media loads through the authenticated `/api/film/output` route; `file://`
   is never used for a remote backend.
2. The backend can hand **only the WanGP renders** to a remote:
   `RemoteWanGPBridge` subclasses the local bridge so every setting is built
   identically and only `_run_manifest` travels — uploads, submit, poll,
   download — against `/api/wangp/*` served by the same backend code on the
   container. The transport is our API, not Gradio's, so it is covered by
   `test_wangp_remote.py` end to end with fakes.
3. One image runs backend, vision sidecar and (optionally) Ollama via
   `deploy/docker-compose.yml`.

## Consequences

- Files chosen with the OS dialog are local paths; a remote backend needs
  files on its own host (documented in CONTAINERS.md).
- Manifest inputs on the server side must be uploaded files — arbitrary
  paths are refused (path policy test).
- Building and running the image needs a GPU host; recorded as BLOCKED —
  ENVIRONMENT in the 4070 matrix until run there.
