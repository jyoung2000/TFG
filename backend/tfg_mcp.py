"""MCP stdio server for TFG — what Hermes Agent, Claude Code or Cursor spawn.

    TFG_BACKEND_URL=http://127.0.0.1:8000 TFG_AUTH_TOKEN=… python backend/tfg_mcp.py

Reads newline-delimited JSON-RPC on stdin, forwards every tool call to the
running backend over HTTP (the desktop's local backend or the container),
writes responses to stdout. Tools are generated from the backend's route
table (`agent/mcp_core.py`), so this file never needs to know a feature.

The backend's route table is loaded in-process to build the tool list; no
model, GPU or heavy import runs here — `app_factory` only registers routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.mcp_core import ForwardResult, JsonObject, McpDispatcher, build_tools, parse_message  # noqa: E402

logger = logging.getLogger("tfg_mcp")


def _http_forwarder(base_url: str, token: str):  # noqa: ANN202 - Forwarder closure
    import requests

    session = requests.Session()

    def forward(method: str, path: str, query: dict[str, str], headers: dict[str, str], body: JsonObject | None) -> ForwardResult:
        merged = {"Accept": "application/json", **headers}
        if token:
            merged["Authorization"] = f"Bearer {token}"
        url = f"{base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        response = session.request(method, url, headers=merged, json=body, timeout=3600)
        return ForwardResult(status=response.status_code, content_type=response.headers.get("content-type", ""), body=response.content)

    return forward


def build_dispatcher(base_url: str, token: str) -> McpDispatcher:
    """The route table comes from a throwaway app with no handler behind it."""
    from app_factory import create_app_routes_only

    app = create_app_routes_only()
    return McpDispatcher(tools=build_tools(app), forward=_http_forwarder(base_url, token))


async def serve(dispatcher: McpDispatcher, stdin: Any = None, stdout: Any = None) -> None:
    reader = stdin or sys.stdin
    writer = stdout or sys.stdout
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, reader.readline)
        if not line:
            return
        message = parse_message(line)
        if message is None:
            continue
        response = await dispatcher.handle(message)
        if response is not None:
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    base_url = os.environ.get("TFG_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("TFG_AUTH_TOKEN", "") or os.environ.get("LTX_AUTH_TOKEN", "")
    dispatcher = build_dispatcher(base_url, token)
    logger.info("TFG MCP: %d tools → %s", len(dispatcher.tools), base_url)
    asyncio.run(serve(dispatcher))


if __name__ == "__main__":
    main()
