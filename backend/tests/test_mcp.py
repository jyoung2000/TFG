"""MCP over the API (phase 9, agent access): every route becomes a tool, the
HTTP transport runs calls in-process under the same auth, and the stdio
server speaks newline-delimited JSON-RPC. No MCP SDK, no network."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

from agent.mcp_core import ForwardResult, McpDispatcher, build_tools, iter_api_routes, parse_message
from app_factory import create_app_routes_only
from tfg_mcp import serve


def _rpc(client, message: dict[str, Any], token: str = "") -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.post("/mcp", json=message, headers=headers)
    return response


class TestToolGeneration:
    def test_every_api_route_is_a_tool(self):
        app = create_app_routes_only()
        tools = build_tools(app)
        api_routes = [r for r in iter_api_routes(app) if r.include_in_schema]
        assert len(api_routes) > 150, "the flattened route table must cover the whole API"
        assert len(tools) == sum(len([m for m in (r.methods or set()) if m in ("GET", "POST", "PUT", "DELETE", "PATCH")]) for r in api_routes)
        names = {t.name for t in tools}
        assert len(names) == len(tools), "tool names must be unique"
        assert {"health", "generation_generate", "image_generate_image", "jobs_list_jobs", "training_start", "settings_apply_preset"} <= names

    def test_input_schema_flattens_path_query_and_body(self):
        tools = {t.name: t for t in build_tools(create_app_routes_only())}
        start = tools["training_start"]
        assert start.method == "POST" and start.path == "/api/training/runs"
        assert "dataset_id" in start.input_schema["properties"] and "dataset_id" in start.input_schema["required"]
        assert "TrainingConfig" in start.input_schema["$defs"]
        media = tools["training_dataset_media"]
        assert media.path_params == ("dataset_id",) and media.query_params == ("path",) and media.serves_file
        assert set(media.input_schema["required"]) == {"dataset_id", "path"}
        loras = tools["training_list_loras"]
        assert set(loras.query_params) == {"target", "model"} and "required" not in loras.input_schema

    def test_parse_message_tolerates_garbage(self):
        assert parse_message("") is None and parse_message("[1]") is None
        assert parse_message("not json") == {"jsonrpc": "2.0", "method": "", "id": None}


class TestHttpTransport:
    def test_handshake_list_and_call(self, client):
        init = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "hermes", "version": "0.4"}}}).json()
        assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["serverInfo"]["name"] == "tfg"
        assert init["result"]["capabilities"]["tools"] == {"listChanged": False}
        assert _rpc(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        listed = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
        assert any(t["name"] == "settings_get_settings" for t in listed)
        assert all("inputSchema" in t and "description" in t for t in listed)
        called = _rpc(client, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "settings_get_settings", "arguments": {}}}).json()
        assert called["result"]["isError"] is False
        payload = json.loads(called["result"]["content"][0]["text"])
        assert payload["mediaProvider"] == "local"

    def test_call_with_body_path_and_query(self, client):
        created = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "training_create_dataset", "arguments": {"name": "Agent set", "preset": "style", "trigger": "agentstyle"}}}).json()
        dataset = json.loads(created["result"]["content"][0]["text"])
        assert dataset["name"] == "Agent set" and dataset["preset"] == "style"
        fetched = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "training_get_dataset", "arguments": {"dataset_id": dataset["id"]}}}).json()
        assert json.loads(fetched["result"]["content"][0]["text"])["id"] == dataset["id"]
        listed = _rpc(client, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "training_list_loras", "arguments": {"model": "z_image_turbo"}}}).json()
        assert json.loads(listed["result"]["content"][0]["text"]) == {"loras": []}
        preset = _rpc(client, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "settings_apply_preset", "arguments": {"preset_id": "rtx-4070-12gb"}}}).json()
        assert json.loads(preset["result"]["content"][0]["text"])["hardwarePreset"] == "rtx-4070-12gb"

    def test_api_errors_and_protocol_errors_are_distinct(self, client):
        missing = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "training_get_dataset", "arguments": {"dataset_id": "nope"}}}).json()
        assert missing["result"]["isError"] is True and "not found" in missing["result"]["content"][0]["text"].lower()
        unknown = _rpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}}).json()
        assert unknown["error"]["code"] == -32602
        bad_method = _rpc(client, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}).json()
        assert bad_method["error"]["code"] == -32601
        assert client.get("/mcp").status_code == 405
        batch = _rpc(client, [{"jsonrpc": "2.0", "id": 4, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}]).json()
        assert batch == [{"jsonrpc": "2.0", "id": 4, "result": {}}]

    def test_auth_token_is_enforced_on_mcp_and_forwarded_to_tools(self, test_state):
        from app_factory import create_app
        from starlette.testclient import TestClient

        app = create_app(handler=test_state, allowed_origins=["*"], auth_token="s3cret")
        with TestClient(app) as secured:
            assert secured.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
            ok = _rpc(secured, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "health", "arguments": {}}}, token="s3cret").json()
            assert ok["result"]["isError"] is False and json.loads(ok["result"]["content"][0]["text"])["status"] == "ok"


class TestStdioTransport:
    def test_serve_reads_lines_and_writes_responses(self):
        calls: list[tuple[str, str]] = []

        def forward(method: str, path: str, query: dict[str, str], headers: dict[str, str], body: dict[str, Any] | None) -> ForwardResult:
            calls.append((method, path))
            return ForwardResult(status=200, content_type="application/json", body=json.dumps({"status": "ok"}).encode())

        dispatcher = McpDispatcher(tools=build_tools(create_app_routes_only()), forward=forward)
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "health", "arguments": {}}}) + "\n"
        )
        stdout = io.StringIO()
        asyncio.run(serve(dispatcher, stdin=stdin, stdout=stdout))
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        assert [line["id"] for line in lines] == [1, 2]
        assert calls == [("GET", "/health")] and dispatcher.initialized is True
