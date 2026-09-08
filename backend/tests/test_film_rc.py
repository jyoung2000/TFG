"""Release-candidate behaviours: OpenAI-compatible endpoints, OpenRouter
failure handling, queue reordering, version telemetry, package host-project
round trips and WanGP model discovery from the checkout's own definitions.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

from film.llm_providers import OPENROUTER_CHAT_URL
from services.http_client.http_client import HttpTimeoutError
from services.wangp_bridge import WanGPBridge
from tests.fakes import FakeResponse

PROJECT = "rc-project"
TARGET = "rc-target"
FAKE_KEY = "test-placeholder-not-a-real-key"
LOCAL_BASE = "http://127.0.0.1:1234/v1"


def _png_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 18), "green").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _text(text: str) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "model": "local/model",
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        },
    )


def _enable_local(test_state, create_fake_model_files) -> None:
    create_fake_model_files()
    test_state.state.app_settings.use_local_text_encoder = True


def _scene_with_shots(client, count: int, *, capture: bool = False) -> tuple[str, list[str]]:
    scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}).json()["id"]
    shot_ids: list[str] = []
    for index in range(count):
        shot = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots",
            json={"title": f"Shot {index}", "description": f"beat {index}", "duration_seconds": 3},
        ).json()
        shot_ids.append(shot["id"])
        if capture:
            client.post(
                f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot['id']}/capture",
                json={"image_base64": _png_base64(), "composition": {"objects": [], "camera": None}},
            )
    return scene_id, shot_ids


def _get_shot(client, shot_id: str) -> dict:
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    for scene in project["scenes"]:
        for shot in scene["shots"]:
            if shot["id"] == shot_id:
                return shot
    raise AssertionError(shot_id)


class TestOpenAICompatibleProvider:
    def _configure(self, client, *, key: str = "") -> None:
        payload: dict[str, object] = {
            "openaiCompatibleBaseUrl": LOCAL_BASE + "/",
            "openaiCompatibleModel": "qwen2.5-7b-instruct",
            "directorProvider": "openai_compatible",
        }
        if key:
            payload["openaiCompatibleApiKey"] = key
        response = client.post("/api/settings", json=payload)
        assert response.status_code == 200, response.text

    def test_status_and_settings_flags(self, client):
        status = client.get("/api/film/director/status").json()
        assert status["openai_compatible_configured"] is False
        self._configure(client, key=FAKE_KEY)
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "openai_compatible"
        assert status["openai_compatible_configured"] is True
        assert status["roles"][0]["model"] == "qwen2.5-7b-instruct"
        settings = client.get("/api/settings")
        assert settings.json()["hasOpenaiCompatibleApiKey"] is True
        assert settings.json()["openaiCompatibleBaseUrl"] == LOCAL_BASE + "/"
        assert FAKE_KEY not in settings.text
        assert client.delete("/api/settings/api-keys/openai-compatible").status_code == 200
        assert client.get("/api/settings").json()["hasOpenaiCompatibleApiKey"] is False

    def test_models_route_hits_configured_base_url(self, client, test_state):
        assert client.get("/api/film/director/openai-compatible/models").status_code == 400
        self._configure(client)
        test_state.http.queue(
            "get",
            FakeResponse(status_code=200, json_payload={"data": [{"id": "qwen2.5-7b-instruct"}, {"id": "llama-3.1-8b"}]}),
        )
        payload = client.get("/api/film/director/openai-compatible/models").json()
        assert [m["id"] for m in payload["models"]] == ["llama-3.1-8b", "qwen2.5-7b-instruct"]
        call = test_state.http.calls[-1]
        assert call.url == f"{LOCAL_BASE}/models"
        assert call.headers is not None and "Authorization" not in call.headers  # no key: no header

    def test_chat_without_key_and_with_key(self, client, test_state):
        self._configure(client)
        test_state.http.queue("post", _text('{"summary": "ok", "commands": []}'))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "hi"})
        assert response.status_code == 200, response.text
        assert response.json()["context"]["provider"] == "openai_compatible"
        call = test_state.http.calls[-1]
        assert call.url == f"{LOCAL_BASE}/chat/completions"
        assert call.headers is not None and "Authorization" not in call.headers
        self._configure(client, key=FAKE_KEY)
        test_state.http.queue("post", _text("done"))
        client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "hi"})
        headers = test_state.http.calls[-1].headers
        assert headers is not None and headers["Authorization"] == f"Bearer {FAKE_KEY}"

    def test_error_mapping(self, client, test_state):
        self._configure(client)
        test_state.http.queue("post", FakeResponse(status_code=401, text="nope"))
        assert client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"}).status_code == 401
        test_state.http.queue("post", FakeResponse(status_code=404, text="model missing"))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 404 and "MODEL_NOT_FOUND" in response.text
        test_state.http.queue("post", ConnectionError("refused"))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 502 and "unreachable" in response.text


class TestOpenRouterFailureModes:
    def _key(self, client) -> None:
        assert client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY}).status_code == 200

    def test_rate_limit(self, client, test_state):
        self._key(client)
        test_state.http.queue("post", FakeResponse(status_code=429, text="slow down"))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 429
        assert "OPENROUTER_RATE_LIMITED" in response.text

    def test_timeout(self, client, test_state):
        self._key(client)
        test_state.http.queue("post", HttpTimeoutError("timed out"))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 504
        assert FAKE_KEY not in response.text

    def test_malformed_tool_arguments_are_tolerated(self, client, test_state):
        self._key(client)
        test_state.http.queue(
            "post",
            FakeResponse(
                status_code=200,
                json_payload={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {"id": "c1", "type": "function", "function": {"name": "create_scene", "arguments": "{not json"}},
                                    {"id": "c2", "type": "function", "function": {"name": "", "arguments": "{}"}},
                                ],
                            }
                        }
                    ]
                },
            ),
        )
        test_state.http.queue("post", _text("recovered"))
        payload = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"}).json()
        # Unparseable arguments become an empty param set (create_scene tolerates it); the nameless call is dropped.
        assert [r["name"] for r in payload["results"]] == ["create_scene"]
        assert payload["results"][0]["ok"] is True
        assert payload["reply"] == "recovered"

    def test_no_choices_and_error_object(self, client, test_state):
        self._key(client)
        test_state.http.queue("post", FakeResponse(status_code=200, json_payload={"choices": []}))
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 502 and "no choices" in response.text
        test_state.http.queue(
            "post", FakeResponse(status_code=200, json_payload={"error": {"message": "context length exceeded"}, "choices": []})
        )
        response = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"})
        assert response.status_code == 502 and "context length exceeded" in response.text

    def test_unknown_tool_name_is_reported_not_crashed(self, client, test_state):
        self._key(client)
        test_state.http.queue(
            "post",
            FakeResponse(
                status_code=200,
                json_payload={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "rm_rf", "arguments": "{}"}}],
                            }
                        }
                    ]
                },
            ),
        )
        test_state.http.queue("post", _text("sorry"))
        payload = client.post(f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "x"}).json()
        assert payload["results"][0]["ok"] is False
        assert "Unknown" in payload["results"][0]["error"] or "unknown" in payload["results"][0]["error"]
        assert test_state.http.calls[0].url == OPENROUTER_CHAT_URL


class TestQueueMove:
    def test_move_reorders_pending_jobs(self, client, test_state, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shots = _scene_with_shots(client, 3)
        client.post("/api/film/queue/pause")
        for shot_id in shots:
            client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        moved = client.post(f"/api/film/queue/{shots[0]}/move", json={"index": 2}).json()
        assert moved["status"] == "moved"
        assert [j["shot_id"] for j in moved["queue"]["pending"]] == [shots[1], shots[2], shots[0]]
        moved = client.post(f"/api/film/queue/{shots[2]}/move", json={"index": 0}).json()
        assert [j["shot_id"] for j in moved["queue"]["pending"]] == [shots[2], shots[1], shots[0]]
        # Out-of-range indexes clamp; unknown shots 404.
        clamped = client.post(f"/api/film/queue/{shots[1]}/move", json={"index": 99}).json()
        assert [j["shot_id"] for j in clamped["queue"]["pending"]][-1] == shots[1]
        assert client.post("/api/film/queue/unknown/move", json={"index": 0}).status_code == 404
        client.post("/api/film/queue/resume")


class TestVersionTelemetry:
    def test_version_records_snapshot_and_telemetry(self, client, test_state, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shots = _scene_with_shots(client, 1, capture=True)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}",
            json={"framing": {"shot_size": "closeup"}, "camera_move": "push_in"},
        )
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}/generate", json={"kind": "preview"}
        )
        assert response.status_code == 200, response.text
        version = _get_shot(client, shots[0])["versions"][0]
        assert version["status"] == "complete"
        assert version["execution_mode"] == "local"
        assert version["generation_seconds"] is not None and version["generation_seconds"] >= 0
        assert isinstance(version["gpu_name"], str)
        assert version["seed"] is not None
        snapshot = version["shot_snapshot"]
        assert snapshot["framing"]["shot_size"] == "closeup"
        assert snapshot["camera_move"] == "push_in"
        assert "visual_prompt" in snapshot
        # Later edits do not rewrite what was rendered.
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}",
            json={"framing": {"shot_size": "wide"}},
        )
        assert _get_shot(client, shots[0])["versions"][0]["shot_snapshot"]["framing"]["shot_size"] == "closeup"


class TestPackageHostProject:
    def test_host_project_round_trip_and_output_map(self, client, test_state, create_fake_model_files, tmp_path: Path):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shots = _scene_with_shots(client, 1, capture=True)
        generated = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}/generate", json={"kind": "preview"}
        )
        assert generated.status_code == 200
        original_output = _get_shot(client, shots[0])["versions"][0]["output_path"]
        host_project = {
            "name": "Host project",
            "assets": [{"id": "a1", "path": original_output, "filmRef": {"shotId": shots[0]}}],
            "timelines": [{"clips": [{"assetId": "a1"}]}],
            "settings": {"apiKey": FAKE_KEY, "nested": {"openrouter_api_key": FAKE_KEY, "keep": 1}},
        }
        destination = tmp_path / "with-host.ltxfilm"
        exported = client.post(
            f"/api/film/projects/{PROJECT}/export",
            json={"destination_path": str(destination), "include_outputs": True, "host_project": host_project},
        )
        assert exported.status_code == 200, exported.text
        with zipfile.ZipFile(destination) as archive:
            raw = archive.read("host_project.json").decode()
            manifest = json.loads(archive.read("manifest.json"))
        assert FAKE_KEY not in raw
        stored = json.loads(raw)
        assert stored["settings"] == {"nested": {"keep": 1}}
        assert stored["timelines"] == host_project["timelines"]
        assert manifest["has_host_project"] is True
        assert original_output in manifest["output_media"].values()

        imported = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination)})
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        assert payload["host_project"]["name"] == "Host project"
        assert FAKE_KEY not in imported.text
        new_path = payload["output_path_map"][original_output]
        assert Path(new_path).is_file()
        assert new_path != original_output
        assert payload["project"]["scenes"][0]["shots"][0]["versions"][0]["output_path"] == new_path

    def test_package_without_host_project_imports_cleanly(self, client, tmp_path: Path):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Only"})
        destination = tmp_path / "bare.ltxfilm"
        assert client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": str(destination)}).status_code == 200
        payload = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination)}).json()
        assert payload["host_project"] is None
        assert payload["output_path_map"] == {}


class TestInterShotGaps:
    def test_scene_and_shot_gap_overrides(self, client):
        scene_id, shots = _scene_with_shots(client, 2)
        scene = client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}", json={"inter_shot_gap_seconds": 0.5}).json()
        assert scene["inter_shot_gap_seconds"] == 0.5
        shot = client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[1]}", json={"gap_before_seconds": 1.25}
        ).json()
        assert shot["gap_before_seconds"] == 1.25
        cleared = client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[1]}", json={"clear_gap": True}
        ).json()
        assert cleared["gap_before_seconds"] is None
        scene = client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}", json={"clear_gap": True}).json()
        assert scene["inter_shot_gap_seconds"] is None


class TestWanGPModelDiscovery:
    def _bridge(self, root: Path) -> WanGPBridge:
        return WanGPBridge(
            enabled=True,
            root=root,
            python_executable=None,
            config_dir=root / "cfg",
            output_dir=root / "out",
            video_model_type="ltx2_22B_distilled",
            image_model_type="z_image",
            camera_motion_prompts={},
            extra_args=(),
        )

    def test_definitions_come_from_defaults_and_ckpts(self, tmp_path: Path):
        root = tmp_path / "Wan2GP"
        (root / "defaults").mkdir(parents=True)
        (root / "ckpts").mkdir()
        (root / "defaults" / "ltx2_22B_distilled.json").write_text(
            json.dumps(
                {
                    "model": {
                        "name": "LTX 2 22B Distilled",
                        "architecture": "ltx2_22B",
                        "description": "Fast LTX-2",
                        "URLs": ["https://example.invalid/ltx2_22B_distilled_quanto_bf16_int8.safetensors"],
                    },
                    "resolution": "1280x720",
                    "num_inference_steps": 8,
                }
            )
        )
        (root / "defaults" / "wan_t2v.json").write_text(
            json.dumps({"model": {"name": "Wan T2V", "architecture": "t2v", "URLs": "https://example.invalid/wan_t2v_fp8.safetensors"}})
        )
        (root / "defaults" / "broken.json").write_text("{not json")
        (root / "defaults" / "no_model.json").write_text(json.dumps({"foo": 1}))
        (root / "ckpts" / "wan_t2v_fp8.safetensors").write_bytes(b"\x00")
        definitions = {d["id"]: d for d in self._bridge(root).list_model_definitions()}
        assert set(definitions) == {"ltx2_22B_distilled", "wan_t2v"}
        ltx = definitions["ltx2_22B_distilled"]
        assert ltx["name"] == "LTX 2 22B Distilled"
        assert ltx["installed"] is False
        assert ltx["quantized_variants"] == ["int8"]
        assert ltx["default_resolution"] == "1280x720"
        assert ltx["default_steps"] == 8
        wan = definitions["wan_t2v"]
        assert wan["installed"] is True
        assert wan["quantized_variants"] == ["fp8"]

    def test_missing_root_or_defaults_is_empty(self, tmp_path: Path):
        assert self._bridge(tmp_path / "nowhere").list_model_definitions() == []
        bridge = WanGPBridge(
            enabled=False,
            root=None,
            python_executable=None,
            config_dir=tmp_path,
            output_dir=tmp_path,
            video_model_type="x",
            image_model_type="y",
            camera_motion_prompts={},
            extra_args=(),
        )
        assert bridge.list_model_definitions() == []

    def test_capabilities_expose_paths_and_ram(self, client, test_state):
        payload = client.get("/api/film/capabilities").json()
        assert payload["models_path"] == str(test_state.config.models_dir)
        assert payload["cuda_available"] in (True, False)
        assert payload["system_ram_gb"] is None or payload["system_ram_gb"] > 0
        for row in payload["models"]:
            assert row["state"] in ("active", "installed", "available", "downloading", "update_available", "incompatible", "not_downloaded")


class TestReplaceProject:
    def test_snapshot_restore_round_trip(self, client):
        scene_id, shots = _scene_with_shots(client, 2)
        before = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}", json={"title": "Renamed"})
        client.delete(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[1]}")
        assert len(client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"]) == 1
        # Restore the earlier snapshot (undo): id/created_at are pinned to the route.
        tampered = {**before, "id": "someone-else", "created_at": 1}
        restored = client.put(f"/api/film/projects/{PROJECT}", json={"project": tampered})
        assert restored.status_code == 200, restored.text
        project = restored.json()["project"]
        assert project["id"] == PROJECT
        assert project["created_at"] == before["created_at"]
        assert [s["title"] for s in project["scenes"][0]["shots"]] == ["Shot 0", "Shot 1"]
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["title"] == "Shot 0"

    def test_invalid_snapshot_rejected(self, client):
        response = client.put(f"/api/film/projects/{PROJECT}", json={"project": {"scenes": "nope"}})
        assert response.status_code == 422

    def test_refused_while_shot_is_queued(self, client, test_state, create_fake_model_files):
        _enable_local(test_state, create_fake_model_files)
        scene_id, shots = _scene_with_shots(client, 1)
        snapshot = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        client.post("/api/film/queue/pause")
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shots[0]}/generate", json={"kind": "preview"})
        refused = client.put(f"/api/film/projects/{PROJECT}", json={"project": snapshot})
        assert refused.status_code == 409
        client.post("/api/film/queue/resume")
        allowed = client.put(f"/api/film/projects/{PROJECT}", json={"project": snapshot})
        assert allowed.status_code == 200, allowed.text


class TestVisualReview:
    def _two_rendered_shots(self, client, test_state, create_fake_model_files) -> tuple[str, list[str]]:
        _enable_local(test_state, create_fake_model_files)
        scene_id, shots = _scene_with_shots(client, 2, capture=True)
        for shot_id in shots:
            response = client.post(
                f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}
            )
            assert response.status_code == 200, response.text
        for shot_id in shots:
            assert _get_shot(client, shot_id)["versions"][0]["status"] == "complete"
        return scene_id, shots

    def test_unavailable_without_provider_or_renders(self, client, test_state, create_fake_model_files):
        scene_id, shots = _scene_with_shots(client, 2)
        first = client.post(f"/api/film/projects/{PROJECT}/continuity/{shots[0]}/visual-review").json()
        assert first["available"] is False and "first shot" in first["reason"]
        second = client.post(f"/api/film/projects/{PROJECT}/continuity/{shots[1]}/visual-review").json()
        assert second["available"] is False and "no rendered version" in second["reason"]
        _, rendered = self._two_rendered_shots(client, test_state, create_fake_model_files)
        no_key = client.post(f"/api/film/projects/{PROJECT}/continuity/{rendered[1]}/visual-review").json()
        assert no_key["available"] is False and "AI_DIRECTOR_KEY_MISSING" in no_key["reason"]
        assert client.post(f"/api/film/projects/{PROJECT}/continuity/nope/visual-review").status_code == 404
        del scene_id

    def test_review_sends_two_frames_and_maps_category(self, client, test_state, create_fake_model_files):
        _, shots = self._two_rendered_shots(client, test_state, create_fake_model_files)
        assert client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY}).status_code == 200
        test_state.http.queue(
            "post",
            _text(json.dumps({"category": "Minor Drift", "summary": "Jacket colour shifts slightly.", "issues": ["jacket hue", "lamp moved"]})),
        )
        response = client.post(f"/api/film/projects/{PROJECT}/continuity/{shots[1]}/visual-review")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["available"] is True
        assert payload["category"] == "minor_drift"
        assert payload["issues"] == ["jacket hue", "lamp moved"]
        assert payload["previous_shot_id"] == shots[0]
        assert payload["context"]["role"] == "continuity"
        # Two inline images travelled as OpenAI content parts, JSON mode requested.
        sent = test_state.http.calls[-1].json_payload
        assert sent is not None
        user_message = sent["messages"][-1]
        parts = user_message["content"]
        assert isinstance(parts, list)
        assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert sent["response_format"] == {"type": "json_object"}
        # The compared frames are saved beside the captures and served by the media route.
        for rel in (payload["previous_frame_path"], payload["current_frame_path"]):
            media = client.get(f"/api/film/projects/{PROJECT}/media", params={"path": rel})
            assert media.status_code == 200
            assert media.content.startswith(b"jpeg:")
        assert FAKE_KEY not in response.text

    def test_review_tolerates_provider_and_parse_failures(self, client, test_state, create_fake_model_files):
        _, shots = self._two_rendered_shots(client, test_state, create_fake_model_files)
        client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY})
        test_state.http.queue("post", FakeResponse(status_code=400, text="model does not support images"))
        failed = client.post(f"/api/film/projects/{PROJECT}/continuity/{shots[1]}/visual-review").json()
        assert failed["available"] is False and "could not review" in failed["reason"]
        test_state.http.queue("post", _text("I cannot tell."))
        unparsed = client.post(f"/api/film/projects/{PROJECT}/continuity/{shots[1]}/visual-review").json()
        assert unparsed["available"] is False and "recognised category" in unparsed["reason"]
        assert unparsed["summary"] == "I cannot tell."

    def test_gemini_encodes_images_inline(self):
        from film.llm_providers import GeminiProvider, LLMMessage

        _, contents = GeminiProvider._encode_contents(  # pyright: ignore[reportPrivateUsage]
            [LLMMessage(role="user", content="compare", images=["data:image/jpeg;base64,QUJD"])]
        )
        parts = contents[0]["parts"]  # type: ignore[index]
        assert parts[0] == {"text": "compare"}
        assert parts[1] == {"inline_data": {"mime_type": "image/jpeg", "data": "QUJD"}}


class TestSettingsSyncPayload:
    def test_frontend_sync_payload_roundtrips(self, client):
        """The renderer POSTs its whole settings object (minus has_* flags) on
        every change; one unknown key would 422 the entire sync, so the
        response shape must be accepted verbatim — role ids included."""
        current = client.get("/api/settings").json()
        payload = {k: v for k, v in current.items() if not k.startswith("has") and k != "openrouterKeySource"}
        payload["openrouterModels"]["prompt_refinement"] = "openai/gpt-4o-mini"
        payload["directorProvider"] = "openai_compatible"
        payload["openaiCompatibleBaseUrl"] = "http://127.0.0.1:1234/v1"
        payload["openaiCompatibleModel"] = "local-model"
        response = client.post("/api/settings", json=payload)
        assert response.status_code == 200, response.text
        after = client.get("/api/settings").json()
        assert after["openrouterModels"]["prompt_refinement"] == "openai/gpt-4o-mini"
        assert after["directorProvider"] == "openai_compatible"
        assert after["openaiCompatibleModel"] == "local-model"
        assert set(after["openrouterModels"]) == {"defaultModel", "script", "storyboard", "director", "continuity", "prompt_refinement"}
