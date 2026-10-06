"""MCP (Model Context Protocol) over this backend, generated from its route
table — so an agent such as Hermes Agent, Claude Code or Cursor can use
*every* feature, and a new route is a new tool with no extra wiring.

Dependency-free on purpose: MCP is JSON-RPC 2.0 with a small method set
(`initialize`, `tools/list`, `tools/call`, `ping`), and the two transports
(`tfg_mcp.py` over stdio, `POST /mcp` over HTTP) share this dispatcher. Each
tool forwards one HTTP call to the API through a `Forwarder`, which is an
in-process ASGI call for the `/mcp` route and a real HTTP client for stdio —
the same code path tests drive with the FastAPI test client.

Verified against the MCP specification revision 2025-06-18 (initialize
result shape, `tools/list` → `{tools: [{name, description, inputSchema}]}`,
`tools/call` → `{content: [{type: "text", text}], isError}`), session-notes
VF-022.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from fastapi import FastAPI
from fastapi.routing import APIRoute


class RouteLike(Protocol):
    """What `build_tools` needs from a route: FastAPI's `APIRoute` and the
    `_EffectiveRouteContext` entries newer FastAPI keeps behind included routers."""

    @property
    def path(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def methods(self) -> set[str] | None: ...

    @property
    def tags(self) -> list[Any]: ...

    @property
    def include_in_schema(self) -> bool: ...

    @property
    def endpoint(self) -> Any: ...


def iter_api_routes(app: FastAPI) -> list[RouteLike]:
    """Every API route, flattening lazily-included routers (FastAPI ≥ 0.141
    stores them as `_IncludedRouter` with `effective_candidates()`)."""
    found: list[RouteLike] = []

    def walk(entries: list[Any]) -> None:
        for entry in entries:
            if isinstance(entry, APIRoute):
                found.append(entry)
                continue
            candidates = getattr(entry, "effective_candidates", None)
            if callable(candidates):
                walk(list(cast(list[Any], candidates())))
                continue
            if all(hasattr(entry, attr) for attr in ("path", "name", "methods", "endpoint", "include_in_schema")) and hasattr(entry, "tags"):
                found.append(cast(RouteLike, entry))

    walk(list(app.routes))
    return found

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "tfg"
SERVER_VERSION = "1.0.0"

#: Paths that are not features (the MCP endpoint itself, docs, media bytes).
_SKIP_PATHS = ("/mcp", "/docs", "/redoc", "/openapi.json")
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    method: str
    path: str
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    has_body: bool
    input_schema: JsonObject
    #: True when the route serves a file (FileResponse); the tool returns metadata, not bytes.
    serves_file: bool = False


@dataclass
class ForwardResult:
    status: int
    content_type: str
    body: bytes

    def as_text(self) -> str:
        if "json" in self.content_type:
            try:
                return json.dumps(json.loads(self.body.decode("utf-8")), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        if self.content_type.startswith("text/"):
            return self.body.decode("utf-8", errors="replace")
        return json.dumps({"content_type": self.content_type, "bytes": len(self.body)})


#: (method, path, query, headers, json_body) → response. Sync or async.
Forwarder = Callable[[str, str, dict[str, str], dict[str, str], JsonObject | None], Awaitable[ForwardResult] | ForwardResult]


# ---- tool generation ----------------------------------------------------------------------


def _tool_name(route: RouteLike) -> str:
    base = route.name[len("route_") :] if route.name.startswith("route_") else route.name
    tag = str(route.tags[0]) if route.tags else ""
    tag = re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")
    name = base if not tag or base.startswith(tag) else f"{tag}_{base}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")[:64]


def _rewrite_refs(schema: Any) -> Any:
    if isinstance(schema, dict):
        out: JsonObject = {}
        for key, value in cast(JsonObject, schema).items():
            if key == "$ref" and isinstance(value, str):
                out[key] = value.replace("#/components/schemas/", "#/$defs/")
            else:
                out[key] = _rewrite_refs(value)
        return out
    if isinstance(schema, list):
        return [_rewrite_refs(item) for item in cast(list[Any], schema)]
    return schema


def _collect_refs(schema: Any, found: set[str]) -> None:
    if isinstance(schema, dict):
        for key, value in cast(JsonObject, schema).items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                found.add(value[len("#/$defs/") :])
            else:
                _collect_refs(value, found)
    elif isinstance(schema, list):
        for item in cast(list[Any], schema):
            _collect_refs(item, found)


def _needed_defs(schema: JsonObject, components: JsonObject) -> JsonObject:
    """Only the component schemas a tool actually references (transitively)."""
    needed: set[str] = set()
    _collect_refs(schema, needed)
    defs: JsonObject = {}
    pending = list(needed)
    while pending:
        name = pending.pop()
        if name in defs or name not in components:
            continue
        defs[name] = _rewrite_refs(components[name])
        more: set[str] = set()
        _collect_refs(defs[name], more)
        pending.extend(m for m in more if m not in defs)
    return defs


def build_tools(app: FastAPI) -> list[ToolSpec]:
    """One tool per API route, with an input schema of path + query + body fields."""
    openapi = app.openapi()
    paths = cast(JsonObject, openapi.get("paths", {}))
    components = cast(JsonObject, cast(JsonObject, openapi.get("components", {})).get("schemas", {}))
    tools: list[ToolSpec] = []
    seen: set[str] = set()
    for route in iter_api_routes(app):
        if route.path in _SKIP_PATHS or not route.include_in_schema:
            continue
        for method in sorted(m for m in (route.methods or set()) if m in ("GET", "POST", "PUT", "DELETE", "PATCH")):
            operation = cast(JsonObject, cast(JsonObject, paths.get(route.path, {})).get(method.lower(), {}))
            properties: JsonObject = {}
            required: list[str] = []
            path_params: list[str] = []
            query_params: list[str] = []
            for raw in cast(list[JsonObject], operation.get("parameters", [])):
                pname = str(raw.get("name", ""))
                schema = _rewrite_refs(raw.get("schema", {"type": "string"}))
                if isinstance(schema, dict):
                    schema = cast(JsonObject, schema)
                    if raw.get("description"):
                        schema["description"] = str(raw["description"])
                properties[pname] = schema
                if raw.get("in") == "path":
                    path_params.append(pname)
                    required.append(pname)
                else:
                    query_params.append(pname)
                    if raw.get("required"):
                        required.append(pname)
            has_body = False
            body = cast(JsonObject, operation.get("requestBody", {}))
            content = cast(JsonObject, body.get("content", {}))
            json_body = cast(JsonObject, content.get("application/json", {}))
            body_schema = cast(JsonObject, _rewrite_refs(json_body.get("schema", {})))
            if body_schema:
                has_body = True
                resolved = body_schema
                ref = resolved.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    resolved = cast(JsonObject, _rewrite_refs(components.get(ref[len("#/$defs/") :], {})))
                body_props = cast(JsonObject, resolved.get("properties", {}))
                if body_props:
                    for key, value in body_props.items():
                        properties.setdefault(key, value)
                    required.extend(k for k in cast(list[str], resolved.get("required", [])) if k not in required)
                else:
                    # A free-form body (dict) or a non-object: pass it whole as `body`.
                    properties["body"] = resolved or {"type": "object"}
                    if body.get("required"):
                        required.append("body")
            input_schema: JsonObject = {"type": "object", "properties": properties}
            if required:
                input_schema["required"] = required
            defs = _needed_defs(input_schema, components)
            if defs:
                input_schema["$defs"] = defs
            summary = str(operation.get("summary", "") or "")
            description = str(operation.get("description", "") or getattr(route, "description", "") or "").strip()
            text = " — ".join(p for p in (summary, description) if p) or f"{method} {route.path}"
            name = _tool_name(route)
            if method != "GET" and any(t.name == name for t in tools):
                name = f"{name}_{method.lower()}"
            if name in seen:
                name = f"{name}_{method.lower()}_{len(seen)}"
            seen.add(name)
            serves_file = "FileResponse" in str(getattr(route.endpoint, "__annotations__", {}).get("return", ""))
            tools.append(ToolSpec(name=name, description=f"{text} [{method} {route.path}]", method=method, path=route.path, path_params=tuple(path_params), query_params=tuple(query_params), has_body=has_body, input_schema=input_schema, serves_file=serves_file))
    return tools


# ---- dispatcher ---------------------------------------------------------------------------


class McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class McpDispatcher:
    tools: list[ToolSpec]
    forward: Forwarder
    initialized: bool = False
    by_name: dict[str, ToolSpec] = field(init=False)

    def __post_init__(self) -> None:
        self.by_name = {t.name: t for t in self.tools}

    async def handle(self, message: JsonObject) -> JsonObject | None:
        """One JSON-RPC message → response object (None for notifications)."""
        msg_id = message.get("id")
        method = str(message.get("method", ""))
        params = cast(JsonObject, message.get("params") or {})
        if not method:
            return self._error(msg_id, -32600, "Invalid request: missing method")
        try:
            if method == "initialize":
                result: JsonObject = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": "TFG backend: every API route is a tool. Start with `health`, `settings_get_settings` and `jobs_list_jobs`; long renders return immediately and are followed through History (`jobs_*`).",
                }
            elif method == "notifications/initialized":
                self.initialized = True
                return None
            elif method.startswith("notifications/"):
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in self.tools]}
            elif method == "tools/call":
                result = await self._call(params)
            else:
                raise McpError(-32601, f"Method not found: {method}")
        except McpError as exc:
            return self._error(msg_id, exc.code, str(exc))
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    async def _call(self, params: JsonObject) -> JsonObject:
        name = str(params.get("name", ""))
        tool = self.by_name.get(name)
        if tool is None:
            raise McpError(-32602, f"Unknown tool: {name}")
        arguments = cast(JsonObject, params.get("arguments") or {})
        path = tool.path
        for pname in tool.path_params:
            if pname not in arguments:
                raise McpError(-32602, f"Missing path parameter: {pname}")
            path = path.replace("{" + pname + "}", str(arguments[pname]))
        query = {q: _query_value(arguments[q]) for q in tool.query_params if q in arguments and arguments[q] is not None}
        body: JsonObject | None = None
        if tool.has_body:
            if "body" in arguments and not any(k in arguments for k in _body_keys(tool)):
                raw = arguments["body"]
                body = cast(JsonObject, raw) if isinstance(raw, dict) else {"value": raw}
            else:
                body = {k: v for k, v in arguments.items() if k not in tool.path_params and k not in tool.query_params}
        outcome = self.forward(tool.method, path, query, {}, body)
        result = await outcome if isinstance(outcome, Awaitable) else outcome
        text = result.as_text() if not tool.serves_file else json.dumps({"status": result.status, "content_type": result.content_type, "bytes": len(result.body), "note": "binary output; fetch it through the API with the token"})
        return {"content": [{"type": "text", "text": text}], "isError": result.status >= 400}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> JsonObject:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _body_keys(tool: ToolSpec) -> list[str]:
    props = cast(JsonObject, tool.input_schema.get("properties", {}))
    return [k for k in props if k not in tool.path_params and k not in tool.query_params and k != "body"]


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def parse_message(line: str) -> JsonObject | None:
    line = line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return {"jsonrpc": "2.0", "method": "", "id": None}
    return cast(JsonObject, parsed) if isinstance(parsed, dict) else None
