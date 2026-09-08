"""OpenRouter provider, secret handling, tool-calling director, and film building.

No real key is ever used: every remote call goes through FakeHTTPClient. The
placeholder below is deliberately not a valid OpenRouter key format.
"""

from __future__ import annotations

import json

import pytest

from film.llm_providers import OPENROUTER_AUTH_KEY_URL, OPENROUTER_CHAT_URL, OPENROUTER_MODELS_URL
from state.app_settings import OPENROUTER_API_KEY_ENV
from tests.fakes import FakeResponse

PROJECT = "openrouter-project"
FAKE_KEY = "test-placeholder-not-a-real-key"


def _or_text(text: str, *, usage: bool = True) -> FakeResponse:
    payload: dict[str, object] = {
        "id": "gen-1",
        "model": "openai/gpt-4o-mini",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 120, "completion_tokens": 30}
    return FakeResponse(status_code=200, json_payload=payload)


def _or_tool_calls(calls: list[tuple[str, dict[str, object]]]) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "model": "openai/gpt-4o-mini",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call_{index}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)},
                            }
                            for index, (name, args) in enumerate(calls)
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 200, "completion_tokens": 40},
        },
    )


def _gemini_calls(calls: list[tuple[str, dict[str, object]]]) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "candidates": [
                {"content": {"parts": [{"functionCall": {"name": name, "args": args}} for name, args in calls]}}
            ],
            "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10},
        },
    )


def _gemini_text(text: str) -> FakeResponse:
    return FakeResponse(
        status_code=200, json_payload={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def _set_openrouter_key(client, key: str = FAKE_KEY) -> None:
    response = client.post("/api/settings", json={"openrouterApiKey": key})
    assert response.status_code == 200


class TestSecretHandling:
    def test_settings_response_never_exposes_key(self, client, test_state):
        _set_openrouter_key(client)
        payload = client.get("/api/settings").json()
        assert payload["hasOpenrouterApiKey"] is True
        assert payload["openrouterKeySource"] == "settings"
        assert FAKE_KEY not in client.get("/api/settings").text
        assert "openrouterApiKey" not in payload
        # Persisted on disk in the backend settings file only.
        assert test_state.state.app_settings.openrouter_api_key == FAKE_KEY

    def test_env_var_fallback_and_source(self, client, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv(OPENROUTER_API_KEY_ENV, "env-placeholder-key")
        payload = client.get("/api/settings").json()
        assert payload["hasOpenrouterApiKey"] is True
        assert payload["openrouterKeySource"] == "env"
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "openrouter"
        assert status["openrouter_key_source"] == "env"

    def test_empty_patch_does_not_clear_but_delete_does(self, client):
        _set_openrouter_key(client)
        client.post("/api/settings", json={"openrouterApiKey": ""})
        assert client.get("/api/settings").json()["hasOpenrouterApiKey"] is True
        cleared = client.delete("/api/settings/api-keys/openrouter")
        assert cleared.status_code == 200
        assert client.get("/api/settings").json()["hasOpenrouterApiKey"] is False
        assert client.get("/api/settings").json()["openrouterKeySource"] == "none"

    def test_unknown_key_provider_404(self, client):
        assert client.delete("/api/settings/api-keys/nope").status_code == 404

    def test_key_only_travels_in_authorization_header(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue("post", _or_text('{"summary": "nothing", "commands": []}'))
        client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "hello"})
        call = test_state.http.calls[-1]
        assert call.url == OPENROUTER_CHAT_URL
        assert call.headers is not None
        assert call.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert FAKE_KEY not in json.dumps(call.json_payload)

    def test_invalid_key_reports_401_without_echoing_key(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue("post", FakeResponse(status_code=401, text='{"error":{"message":"Invalid key"}}'))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 401
        assert "OPENROUTER_KEY_INVALID" in response.text
        assert FAKE_KEY not in response.text


class TestProviderStatusAndModels:
    def test_status_without_keys(self, client):
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "none"
        assert status["openrouter_configured"] is False
        assert "AI_DIRECTOR_KEY_MISSING" in status["message"]
        assert {"create_shot", "queue_shot", "set_prompt", "check_continuity"} <= {t["name"] for t in status["tools"]}

    def test_auto_prefers_openrouter_then_gemini(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = "gemini-placeholder"
        assert client.get("/api/film/director/status").json()["active_provider"] == "gemini"
        _set_openrouter_key(client)
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "openrouter"
        roles = {r["role"]: r for r in status["roles"]}
        assert roles["director"]["model"] == "openai/gpt-4o-mini"
        # Explicit provider selection wins.
        client.post("/api/settings", json={"directorProvider": "gemini"})
        assert client.get("/api/film/director/status").json()["active_provider"] == "gemini"

    def test_role_model_preferences(self, client):
        _set_openrouter_key(client)
        response = client.post(
            "/api/settings",
            json={"openrouterModels": {"defaultModel": "anthropic/claude-3.5-haiku", "storyboard": "google/gemini-flash-1.5"}},
        )
        assert response.status_code == 200
        roles = {r["role"]: r["model"] for r in client.get("/api/film/director/status").json()["roles"]}
        assert roles["storyboard"] == "google/gemini-flash-1.5"
        assert roles["director"] == "anthropic/claude-3.5-haiku"
        assert roles["script"] == "anthropic/claude-3.5-haiku"

    def test_model_discovery_and_cache(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue(
            "get",
            FakeResponse(
                status_code=200,
                json_payload={
                    "data": [
                        {
                            "id": "openai/gpt-4o-mini",
                            "name": "GPT-4o mini",
                            "context_length": 128000,
                            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                            "supported_parameters": ["tools", "response_format"],
                        },
                        {"id": "meta/llama", "name": "Llama", "supported_parameters": ["temperature"]},
                    ]
                },
            ),
        )
        first = client.get("/api/film/director/openrouter/models").json()
        assert first["cached"] is False
        assert [m["id"] for m in first["models"]] == ["meta/llama", "openai/gpt-4o-mini"]
        by_id = {m["id"]: m for m in first["models"]}
        assert by_id["openai/gpt-4o-mini"]["supports_tools"] is True
        assert by_id["meta/llama"]["supports_tools"] is False
        assert test_state.http.calls[-1].url == OPENROUTER_MODELS_URL
        second = client.get("/api/film/director/openrouter/models").json()
        assert second["cached"] is True
        assert len(test_state.http.calls) == 1

    def test_validate_key(self, client, test_state):
        assert client.post("/api/film/director/openrouter/validate").json()["valid"] is False
        _set_openrouter_key(client)
        test_state.http.queue(
            "get", FakeResponse(status_code=200, json_payload={"data": {"label": "desktop", "usage": 0.5, "limit": 10}})
        )
        payload = client.post("/api/film/director/openrouter/validate").json()
        assert payload["valid"] is True
        assert payload["label"] == "desktop"
        assert test_state.http.calls[-1].url == OPENROUTER_AUTH_KEY_URL
        test_state.http.queue("get", FakeResponse(status_code=401, text="Unauthorized"))
        invalid = client.post("/api/film/director/openrouter/validate").json()
        assert invalid["valid"] is False
        assert "401" in invalid["message"]


class TestToolCallingDirector:
    def test_openrouter_tool_loop_mutates_project(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue(
            "post",
            _or_tool_calls([("create_scene", {"title": "Rooftop"}), ("add_character", {"name": "Mara", "wardrobe": "yellow raincoat"})]),
        )
        # Second turn: the model needs the scene id it just got back.
        test_state.http.queue("post", _or_tool_calls([("get_project", {})]))
        test_state.http.queue("post", _or_text("Created the rooftop scene and Mara."))
        response = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct",
            json={"instruction": "Set up a rooftop scene with Mara in a yellow raincoat"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["reply"] == "Created the rooftop scene and Mara."
        assert [r["name"] for r in payload["results"]] == ["create_scene", "add_character", "get_project"]
        assert all(r["ok"] for r in payload["results"])
        context = payload["context"]
        assert context["provider"] == "openrouter"
        assert context["model"] == "openai/gpt-4o-mini"
        assert context["steps"] == 3
        assert context["tool_calls"] == 3
        assert context["prompt_tokens"] == 520  # 200 + 200 + 120 across the three turns
        assert context["prompt_chars"] > 0
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        assert project["scenes"][0]["title"] == "Rooftop"
        assert project["assets"][0]["wardrobe"] == "yellow raincoat"
        # Tool results were fed back as role=tool messages with matching ids.
        second_call = test_state.http.calls[1].json_payload
        assert second_call is not None
        roles = [m["role"] for m in second_call["messages"]]
        assert roles[-3:] == ["assistant", "tool", "tool"]
        assert second_call["messages"][-2]["tool_call_id"] == "call_0"
        assert second_call["tools"][0]["type"] == "function"

    def test_tool_failure_is_reported_to_model_and_user(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue("post", _or_tool_calls([("set_framing", {"shot_id": "missing", "shot_size": "wide"})]))
        test_state.http.queue("post", _or_text("That shot does not exist."))
        payload = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "make it wide"}
        ).json()
        assert payload["results"][0]["ok"] is False
        assert "not found" in payload["results"][0]["error"].lower()
        fed_back = test_state.http.calls[1].json_payload
        assert fed_back is not None
        assert '"ok": false' in fed_back["messages"][-1]["content"]

    def test_json_plan_fallback_still_executes(self, client, test_state):
        _set_openrouter_key(client)
        plan = {"summary": "One scene.", "commands": [{"name": "create_scene", "params": {"title": "Plan"}}]}
        test_state.http.queue("post", _or_text("```json\n" + json.dumps(plan) + "\n```"))
        payload = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"}).json()
        assert payload["plan_summary"] == "One scene."
        assert payload["results"][0]["ok"] is True
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["title"] == "Plan"

    def test_step_cap_stops_runaway_loops(self, client, test_state):
        _set_openrouter_key(client)
        for _ in range(12):
            test_state.http.queue("post", _or_tool_calls([("get_project", {})]))
        payload = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "loop"}).json()
        assert payload["results"][-1]["name"] == "director"
        assert "12 tool steps" in payload["results"][-1]["error"]

    def test_gemini_function_calling_path(self, client, test_state):
        test_state.state.app_settings.gemini_api_key = "gemini-placeholder"
        test_state.http.queue("post", _gemini_calls([("create_scene", {"title": "Gemini scene"})]))
        test_state.http.queue("post", _gemini_text("Done."))
        payload = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"}).json()
        assert payload["context"]["provider"] == "gemini"
        assert payload["results"][0]["ok"] is True
        request = test_state.http.calls[0].json_payload
        assert request is not None
        assert "functionDeclarations" in request["tools"][0]
        follow_up = test_state.http.calls[1].json_payload
        assert follow_up is not None
        assert "functionResponse" in json.dumps(follow_up["contents"][-1])

    def test_history_is_forwarded(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue("post", _or_text("ok"))
        client.post(
            f"/api/film/projects/{PROJECT}/director/instruct",
            json={
                "instruction": "now make it wide",
                "history": [{"role": "user", "content": "add a shot"}, {"role": "assistant", "content": "added"}],
            },
        )
        messages = test_state.http.calls[0].json_payload["messages"]  # type: ignore[index]
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]

    def test_new_commands(self, client, test_state):
        scene = client.post(f"/api/film/projects/{PROJECT}/director/command", json={"name": "create_scene", "params": {}}).json()
        scene_id = scene["results"][0]["result"]["id"]
        shot = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "create_shot", "params": {"scene_id": scene_id, "description": "a beat"}},
        ).json()["results"][0]["result"]
        prompt = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "set_prompt", "params": {"shot_id": shot["id"], "visual_prompt": "custom prompt"}},
        ).json()["results"][0]
        assert prompt["ok"] and prompt["result"]["prompt_locked"] is True
        gen = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={
                "name": "set_generation_settings",
                "params": {"shot_id": shot["id"], "quality_preset": "quality", "seed": 7, "resolution": "720p"},
            },
        ).json()["results"][0]
        assert gen["ok"], gen["error"]
        assert gen["result"]["generation"]["seed"] == 7
        cont = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "check_continuity", "params": {"shot_id": shot["id"]}},
        ).json()["results"][0]
        assert cont["ok"] and isinstance(cont["result"], list)
        script = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "set_script", "params": {"content": "INT. ROOM - DAY\n\nA beat."}},
        ).json()["results"][0]
        assert script["ok"]
        deleted = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "delete_shot", "params": {"shot_id": shot["id"]}},
        ).json()["results"][0]
        assert deleted["ok"]
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"] == []


class TestChatAndRefine:
    def test_quick_mode_chat_returns_prompt_suggestion(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue(
            "post",
            _or_text(
                json.dumps(
                    {
                        "reply": "How about a foggy harbor at dawn?",
                        "prompt": "A lone fisherman rows through thick fog at dawn...",
                        "negative_prompt": "blurry, text",
                        "duration_seconds": 5,
                    }
                )
            ),
        )
        payload = client.post(
            "/api/film/director/chat",
            json={"messages": [{"role": "user", "content": "something moody at sea"}], "model_hint": "ltx-2"},
        ).json()
        assert payload["reply"].startswith("How about")
        assert payload["suggested_prompt"].startswith("A lone fisherman")
        assert payload["suggested_duration_seconds"] == 5
        assert payload["context"]["role"] == "prompt_refinement"
        request = test_state.http.calls[0].json_payload
        assert request is not None
        assert request["response_format"] == {"type": "json_object"}
        assert "tools" not in request

    def test_chat_tolerates_plain_text(self, client, test_state):
        _set_openrouter_key(client)
        test_state.http.queue("post", _or_text("Just a plain answer."))
        payload = client.post(
            "/api/film/director/chat", json={"messages": [{"role": "user", "content": "hi"}]}
        ).json()
        assert payload["reply"] == "Just a plain answer."
        assert payload["suggested_prompt"] == ""

    def test_chat_requires_key(self, client):
        response = client.post("/api/film/director/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 400

    def test_refine_prompt_locks_new_prompt(self, client, test_state):
        _set_openrouter_key(client)
        scene = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "S"}).json()
        shot = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots", json={"description": "a woman waits"}
        ).json()
        old_prompt = shot["visual_prompt"]
        test_state.http.queue(
            "post", _or_text(json.dumps({"prompt": "A refined cinematic prompt.", "negative_prompt": "cartoon"}))
        )
        payload = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/refine-prompt",
            json={"guidance": "more dramatic"},
        ).json()
        assert payload["previous_prompt"] == old_prompt
        assert payload["shot"]["visual_prompt"] == "A refined cinematic prompt."
        assert payload["shot"]["negative_prompt"] == "cartoon"
        assert payload["shot"]["prompt_locked"] is True
        sent = test_state.http.calls[0].json_payload
        assert sent is not None
        assert "more dramatic" in sent["messages"][-1]["content"]


class TestBuildFilm:
    def test_heuristic_build_plan_and_apply(self, client):
        response = client.post(
            f"/api/film/projects/{PROJECT}/build",
            json={
                "idea": "A courier races across a flooded city. She finds the package is empty. She laughs.",
                "target_scenes": 2,
                "target_shots_per_scene": 3,
                "use_llm": False,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["used_llm"] is False
        plan = payload["plan"]
        assert len(plan["scenes"]) == 2
        assert all(len(s["shots"]) == 3 for s in plan["scenes"])
        assert plan["scenes"][0]["shots"][0]["shot_size"] == "wide"
        assert "INT." in plan["script"]
        # Nothing persisted until applied.
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"] == []
        # The user edits the plan before applying.
        plan["scenes"][0]["title"] = "Flooded streets"
        plan["characters"] = [{"name": "Courier", "appearance": "short hair", "wardrobe": "orange jacket"}]
        plan["scenes"][0]["shots"][1]["characters"] = ["Courier"]
        applied = client.post(f"/api/film/projects/{PROJECT}/build/apply", json={"plan": plan}).json()
        assert applied["status"] == "applied"
        assert applied["scenes_created"] == 2
        assert applied["shots_created"] == 6
        assert applied["characters_created"] == 1
        project = applied["project"]
        assert project["scenes"][0]["title"] == "Flooded streets"
        assert project["assets"][0]["wardrobe"] == "orange jacket"
        shot = project["scenes"][0]["shots"][1]
        assert shot["characters"][0]["asset_id"] == project["assets"][0]["id"]
        assert "orange jacket" in shot["visual_prompt"]
        assert project["script"]["content"].startswith("A COURIER")
        assert project["name"] != ""

    def test_apply_conflicts_without_replace(self, client):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Manual"})
        plan = {"scenes": [{"title": "New", "shots": [{"description": "x"}]}]}
        assert client.post(f"/api/film/projects/{PROJECT}/build/apply", json={"plan": plan}).status_code == 409
        replaced = client.post(
            f"/api/film/projects/{PROJECT}/build/apply", json={"plan": plan, "replace_existing": True}
        ).json()
        assert [s["title"] for s in replaced["project"]["scenes"]] == ["New"]

    def test_llm_build_plan(self, client, test_state):
        _set_openrouter_key(client)
        plan = {
            "title": "Tide",
            "logline": "A courier and the sea.",
            "characters": [{"name": "Mara", "appearance": "tall", "wardrobe": "yellow raincoat"}],
            "locations": [{"name": "Harbor", "environment": "wet docks", "lighting": "dawn"}],
            "scenes": [
                {
                    "title": "Arrival",
                    "location": "Harbor",
                    "characters": ["Mara"],
                    "shots": [
                        {
                            "description": "Mara steps onto the wet dock as fog rolls in",
                            "shot_size": "wide",
                            "camera_move": "push_in",
                            "duration_seconds": 6,
                            "characters": ["Mara"],
                            "location": "Harbor",
                        }
                    ],
                }
            ],
        }
        test_state.http.queue("post", _or_text(json.dumps(plan)))
        response = client.post(
            f"/api/film/projects/{PROJECT}/build", json={"idea": "a courier at sea", "use_llm": True}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["used_llm"] is True
        assert payload["context"]["role"] == "script"
        assert payload["plan"]["script"].startswith("TIDE")
        applied = client.post(f"/api/film/projects/{PROJECT}/build/apply", json={"plan": payload["plan"]}).json()
        project = applied["project"]
        assert applied["locations_created"] == 1
        scene = project["scenes"][0]
        location = next(a for a in project["assets"] if a["kind"] == "location")
        assert scene["location_id"] == location["id"]
        assert scene["shots"][0]["location_id"] == location["id"]
        assert scene["shots"][0]["camera_move"] == "push_in"
        assert "yellow raincoat" in scene["shots"][0]["visual_prompt"]

    def test_build_requires_idea(self, client):
        assert client.post(f"/api/film/projects/{PROJECT}/build", json={"idea": "  "}).status_code == 400
