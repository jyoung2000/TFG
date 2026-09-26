# Using TFG from an agent (Hermes, Claude Code, Cursor, anything with MCP)

TFG's backend is a FastAPI app, and every route on it is also an **MCP
tool**. Nothing is hand-listed: `backend/agent/mcp_core.py` walks the route
table at start-up, turns path + query + body fields into one JSON input
schema per route, and forwards calls to the API. A new endpoint is a new
tool the moment it exists. Two transports share that dispatcher:

| Transport | Entry point | When |
|---|---|---|
| stdio | `python backend/tfg_mcp.py` (env `TFG_BACKEND_URL`, `TFG_AUTH_TOKEN`) | the agent runs on the same machine as the desktop app |
| HTTP (Streamable HTTP, POST only) | `POST <backend>/mcp` with `Authorization: Bearer <token>` | the container stack, a remote backend, or any client that prefers a URL |

`pnpm agent:mcp` runs the stdio server with the repo's Python. The skill in
`skills/tfg/SKILL.md` (agentskills.io format, so Hermes' `hermes skills
install`, Claude Code and Cursor all read it) documents the workflows and
the tool names for each.

## Hermes Agent

Hermes (Nous Research) has a native MCP client configured in
`~/.hermes/config.yaml` — verified against its docs (`user-guide/features/mcp`):

```yaml
mcp_servers:
  tfg:
    command: "/path/to/TFG/backend/.venv/bin/python"
    args: ["/path/to/TFG/backend/tfg_mcp.py"]
    env:
      TFG_BACKEND_URL: "http://127.0.0.1:8000"
      TFG_AUTH_TOKEN: "<token>"
    tools:
      exclude: [health_shutdown]
```

or, against the container stack (`docs/CONTAINERS.md`):

```yaml
mcp_servers:
  tfg:
    url: "http://unraid.local:8000/mcp"
    headers:
      Authorization: "Bearer <LTX_AUTH_TOKEN>"
```

Then `hermes mcp test tfg` and, for the workflow notes,
`hermes skills install <path-or-url-to>/skills/tfg`. Hermes' per-server
`tools.include` / `tools.exclude` filters narrow the 214 tools to a task.

**Starting a backend for an agent.** `pnpm backend:dev` (`backend:dev:win`)
runs the backend headless with no Electron: data in `~/.local/share/tfg`
(`%LOCALAPPDATA%\tfg`), WanGP from `./Wan2GP` or `WANGP_ROOT`, no token on
loopback unless `LTX_AUTH_TOKEN` is set. It prints the MCP command and URL.

**Where the token comes from.** The desktop backend gets a random token
per session from Electron (`LTX_AUTH_TOKEN` in the backend's environment;
Settings → About shows it). Set `LTX_OPEN_API=1` when starting the backend
by hand to run it without a token on loopback. The container's token is
`LTX_AUTH_TOKEN` in `deploy/.env`.

## Claude Code / Cursor

```bash
claude mcp add tfg -e TFG_BACKEND_URL=http://127.0.0.1:8000 -e TFG_AUTH_TOKEN=<token> -- python backend/tfg_mcp.py
```

Cursor and other clients take the same `command`/`args`/`env` or the
`/mcp` URL with the bearer header.

## What the tools look like

```json
{
  "name": "training_start",
  "description": "… [POST /api/training/runs]",
  "inputSchema": {
    "type": "object",
    "properties": { "dataset_id": {"type": "string"}, "name": {…}, "config": {"$ref": "#/$defs/TrainingConfig"}, "resume_run_id": {…} },
    "required": ["dataset_id"],
    "$defs": { "TrainingConfig": {…} }
  }
}
```

- Path parameters (`{dataset_id}`) and query parameters are top-level
  properties; body fields are flattened alongside them; a free-form body is
  passed as `body`.
- Results come back as the API's JSON (pretty-printed text content);
  `isError` mirrors an HTTP 4xx/5xx and the text carries the API's
  `{"error": …}`.
- File-serving routes (`*_media`, `film_output`, `*_frame`) return metadata
  over MCP (`content_type`, `bytes`); fetch bytes over HTTP with the token
  when needed.
- `health_shutdown` is a real tool (`POST /api/system/shutdown`); exclude it in
  the client config unless the agent should be able to stop the backend. Note
  the name: the tool is generated as `<tag>_<route>`, and that route is tagged
  `health`, so it is **not** called `system_shutdown`.

## Protocol

JSON-RPC 2.0; `initialize` (protocol `2025-06-18`), `notifications/initialized`,
`ping`, `tools/list`, `tools/call`. Prompts and resources are not
advertised. The HTTP transport answers each POST with one JSON response
(notifications → 202) and batches with an array; there is no
server-initiated SSE stream, which every MCP client tolerates for
tools-only servers.

## Tests

`backend/tests/test_mcp.py`: every API route becomes a uniquely named tool;
schemas flatten path/query/body with only the `$defs` they need; the HTTP
transport runs calls in-process under the same auth token (401 without it);
API errors and protocol errors are distinct; the stdio loop reads
newline-delimited JSON-RPC.
