# ADR 0004 — MCP generated from the route table

**Status:** accepted (phase 9)

## Context

Agents (Hermes Agent, Claude Code, Cursor) should be able to use every TFG
feature, and a hand-maintained tool list would drift from the API.

## Decision

`backend/agent/mcp_core.py` generates one MCP tool per API route from the
FastAPI route table and OpenAPI schema (path + query + body flattened into
one input schema, only the `$defs` each tool needs). Two transports share
the dispatcher: `tfg_mcp.py` over stdio (forwards over HTTP to the running
backend) and `POST /mcp` in the app (forwards in-process through ASGI under
the same auth middleware). No MCP SDK dependency; JSON-RPC 2.0 with the
tools-only method set of spec revision 2025-06-18.

## Consequences

- A new route is a new tool; `test_mcp.py` asserts the count matches.
- File-serving routes return metadata over MCP, bytes over HTTP.
- `health_shutdown` (from `POST /api/system/shutdown`, tagged `health`) is a tool; the skill tells clients to exclude it. (Originally written as `system_shutdown`, which matched nothing — see the Hermes review, F-030.)
