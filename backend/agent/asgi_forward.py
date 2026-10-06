"""Forward an MCP tool call to this same FastAPI app without a network hop:
build an ASGI scope and run the app in-process. The `/mcp` route uses it so
the container's MCP endpoint works behind the same auth token and the test
client exercises exactly the production path."""

from __future__ import annotations

import json
from typing import Any, cast

from starlette.types import Message, Receive, Scope, Send
from urllib.parse import urlencode

from fastapi import FastAPI

from agent.mcp_core import ForwardResult, JsonObject


def make_asgi_forwarder(app: FastAPI, base_headers: dict[str, str]):  # noqa: ANN201 - returns a Forwarder closure
    async def forward(method: str, path: str, query: dict[str, str], headers: dict[str, str], body: JsonObject | None) -> ForwardResult:
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        merged = {**base_headers, **headers}
        if body is not None:
            merged["content-type"] = "application/json"
        merged["content-length"] = str(len(payload))
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "root_path": "",
            "query_string": urlencode(query).encode("utf-8"),
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in merged.items()],
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 0),
        }
        sent = False
        status = 500
        content_type = ""
        chunks: list[bytes] = []

        async def receive() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(message: Message) -> None:
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = int(message["status"])
                for key, value in cast(list[tuple[bytes, bytes]], message.get("headers", [])):
                    if key.lower() == b"content-type":
                        content_type = value.decode("latin-1")
            elif message["type"] == "http.response.body":
                chunks.append(cast(bytes, message.get("body", b"")))

        asgi_scope: Scope = scope
        asgi_receive: Receive = receive
        asgi_send: Send = send
        await app(asgi_scope, asgi_receive, asgi_send)
        return ForwardResult(status=status, content_type=content_type, body=b"".join(chunks))

    return forward
