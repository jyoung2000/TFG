"""Provider fabric: Claude/Grok text providers, hosted media providers, the
Model Library and hosted film generation.

Every provider call goes through the fake HTTP client — no key and no network
is ever used, and the fake key below is deliberately not a real credential.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

from film.llm_providers import ANTHROPIC_BASE_URL, XAI_BASE_URL
from film.media_providers import FalProvider, MediaSpec, ReplicateProvider, WaveSpeedProvider
from film.media_runner import MediaRunner, suffix_for
from tests.fakes import FakeResponse

PROJECT = "provider-project"
FAKE_KEY = "test-placeholder-not-a-real-key"


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "purple").save(buffer, format="PNG")
    return buffer.getvalue()


def _anthropic_reply(text: str) -> FakeResponse:
    return FakeResponse(
        status_code=200,
        json_payload={
            "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 120, "output_tokens": 8},
        },
    )


def _scene_and_shot(client) -> tuple[str, str]:
    scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}).json()["id"]
    shot_id = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots",
        json={"title": "Shot", "description": "a beat", "duration_seconds": 3},
    ).json()["id"]
    return scene_id, shot_id


class TestAnthropicProvider:
    def _configure(self, client) -> None:
        assert client.post("/api/settings", json={"anthropicApiKey": FAKE_KEY, "directorProvider": "anthropic"}).status_code == 200

    def test_status_reports_claude_active_without_leaking_the_key(self, client):
        self._configure(client)
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "anthropic"
        assert status["anthropic_configured"] is True
        assert status["roles"][0]["model"] == "claude-sonnet-5"
        assert {p["id"] for p in status["providers"]} == {"openrouter", "anthropic", "xai", "gemini", "openai_compatible"}
        settings = client.get("/api/settings")
        assert settings.json()["hasAnthropicApiKey"] is True
        assert FAKE_KEY not in settings.text

    def test_chat_uses_the_messages_api_with_anthropic_headers(self, client, test_state):
        self._configure(client)
        test_state.http.queue("post", _anthropic_reply("ready"))
        response = client.post("/api/film/director/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 200, response.text
        call = test_state.http.calls[-1]
        assert call.url == f"{ANTHROPIC_BASE_URL}/messages"
        assert call.headers is not None
        assert call.headers["x-api-key"] == FAKE_KEY
        assert call.headers["anthropic-version"] == "2023-06-01"
        payload = call.json_payload or {}
        assert payload["model"] == "claude-sonnet-5"
        assert payload["max_tokens"] > 0
        assert isinstance(payload["system"], str) and payload["system"]
        assert response.json()["context"]["provider"] == "anthropic"
        assert response.json()["context"]["prompt_tokens"] == 120

    def test_tool_calls_and_results_round_trip_as_content_blocks(self, client, test_state):
        self._configure(client)
        test_state.http.queue(
            "post",
            FakeResponse(
                status_code=200,
                json_payload={
                    "model": "claude-sonnet-5",
                    "content": [
                        {"type": "text", "text": "Adding the scene."},
                        {"type": "tool_use", "id": "tu_1", "name": "create_scene", "input": {"title": "Rooftop"}},
                    ],
                    "stop_reason": "tool_use",
                },
            ),
        )
        test_state.http.queue("post", _anthropic_reply("Done."))
        payload = client.post(
            f"/api/film/projects/{PROJECT}/director/instruct", json={"instruction": "add a rooftop scene"}
        ).json()
        assert [r["name"] for r in payload["results"]] == ["create_scene"]
        assert payload["results"][0]["ok"] is True
        # The follow-up request carries the assistant's tool_use and a user tool_result.
        messages = (test_state.http.calls[-1].json_payload or {})["messages"]
        assistant = next(m for m in messages if m["role"] == "assistant" and any(b["type"] == "tool_use" for b in m["content"]))
        assert assistant["content"][-1]["name"] == "create_scene"
        tool_result = next(
            block for message in messages for block in message["content"] if block.get("type") == "tool_result"
        )
        assert tool_result["tool_use_id"] == "tu_1"
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["title"] == "Rooftop"

    def test_error_mapping_and_model_list(self, client, test_state):
        self._configure(client)
        test_state.http.queue("post", FakeResponse(status_code=401, text="bad key"))
        response = client.post("/api/film/director/chat", json={"messages": [{"role": "user", "content": "x"}]})
        assert response.status_code == 401 and "ANTHROPIC_KEY_INVALID" in response.text
        test_state.http.queue("post", FakeResponse(status_code=429, text="slow"))
        assert client.post("/api/film/director/chat", json={"messages": [{"role": "user", "content": "x"}]}).status_code == 429
        test_state.http.queue(
            "get",
            FakeResponse(status_code=200, json_payload={"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5"}]}),
        )
        models = client.get("/api/film/director/models/anthropic").json()["models"]
        assert models[0]["id"] == "claude-opus-5" and models[0]["supports_tools"] is True


class TestXaiProvider:
    def test_grok_talks_to_the_xai_endpoint(self, client, test_state):
        client.post("/api/settings", json={"xaiApiKey": FAKE_KEY, "xaiModel": "grok-4", "directorProvider": "xai"})
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "xai" and status["xai_configured"] is True
        test_state.http.queue(
            "post",
            FakeResponse(
                status_code=200,
                json_payload={"model": "grok-4", "choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ),
        )
        assert client.post("/api/film/director/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 200
        call = test_state.http.calls[-1]
        assert call.url == f"{XAI_BASE_URL}/chat/completions"
        assert call.headers is not None and call.headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert (call.json_payload or {})["model"] == "grok-4"

    def test_auto_falls_through_the_configured_providers(self, client):
        assert client.get("/api/film/director/status").json()["active_provider"] == "none"
        client.post("/api/settings", json={"geminiApiKey": FAKE_KEY})
        assert client.get("/api/film/director/status").json()["active_provider"] == "gemini"
        client.post("/api/settings", json={"anthropicApiKey": FAKE_KEY})
        assert client.get("/api/film/director/status").json()["active_provider"] == "anthropic"
        client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY})
        assert client.get("/api/film/director/status").json()["active_provider"] == "openrouter"
        # An explicit choice that is not configured is reported, never silently swapped.
        client.post("/api/settings", json={"directorProvider": "xai"})
        status = client.get("/api/film/director/status").json()
        assert status["active_provider"] == "none" and "Grok" in status["message"]

    def test_every_key_can_be_cleared(self, client):
        for provider, field in (
            ("anthropic", "hasAnthropicApiKey"),
            ("xai", "hasXaiApiKey"),
            ("wavespeed", "hasWavespeedApiKey"),
            ("replicate", "hasReplicateApiKey"),
        ):
            camel = {"anthropic": "anthropicApiKey", "xai": "xaiApiKey", "wavespeed": "wavespeedApiKey", "replicate": "replicateApiKey"}[provider]
            client.post("/api/settings", json={camel: FAKE_KEY})
            assert client.get("/api/settings").json()[field] is True
            assert client.delete(f"/api/settings/api-keys/{provider}").status_code == 200
            assert client.get("/api/settings").json()[field] is False


class TestMediaProviders:
    def test_fal_submit_poll_download(self, fake_services):
        http = fake_services.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r1", "status_url": "https://q/status", "response_url": "https://q/result"}))
        provider = FalProvider(http, FAKE_KEY)
        job = provider.submit(MediaSpec(model="fal-ai/ltx-video", prompt="a cat", duration_seconds=4, fps=24))
        assert job.id == "r1"
        call = http.calls[-1]
        assert call.url == "https://queue.fal.run/fal-ai/ltx-video"
        assert call.headers is not None and call.headers["Authorization"] == f"Key {FAKE_KEY}"
        assert (call.json_payload or {})["num_frames"] == 96
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "IN_QUEUE", "queue_position": 3}))
        queued = provider.poll(job)
        assert queued.state == "queued" and queued.queue_position == 3
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"video": {"url": "https://cdn/out.mp4"}}))
        done = provider.poll(job)
        assert done.state == "complete" and done.output_url == "https://cdn/out.mp4"
        http.queue("get", FakeResponse(status_code=200, content=b"bytes"))
        assert provider.download(done.output_url) == b"bytes"

    def test_wavespeed_envelope(self, fake_services):
        http = fake_services.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"code": 200, "data": {"id": "w1", "urls": {"get": "https://ws/get"}}}))
        provider = WaveSpeedProvider(http, FAKE_KEY)
        job = provider.submit(MediaSpec(model="wavespeed-ai/wan-2.2/t2v-480p", prompt="a city"))
        assert job.poll_url == "https://ws/get"
        http.queue("get", FakeResponse(status_code=200, json_payload={"data": {"status": "processing"}}))
        assert provider.poll(job).state == "running"
        http.queue("get", FakeResponse(status_code=200, json_payload={"data": {"status": "completed", "outputs": ["https://cdn/w.mp4"]}}))
        assert provider.poll(job).output_url == "https://cdn/w.mp4"
        http.queue("get", FakeResponse(status_code=200, json_payload={"data": {"status": "failed", "error": "nsfw"}}))
        failed = provider.poll(job)
        assert failed.state == "failed" and "nsfw" in failed.error

    def test_replicate_model_and_version_endpoints(self, fake_services):
        http = fake_services.http
        provider = ReplicateProvider(http, FAKE_KEY)
        http.queue("post", FakeResponse(status_code=200, json_payload={"id": "p1", "status": "starting", "urls": {"get": "https://r/p1"}}))
        provider.submit(MediaSpec(model="lightricks/ltx-video", prompt="dunes"))
        assert http.calls[-1].url == "https://api.replicate.com/v1/models/lightricks/ltx-video/predictions"
        http.queue("post", FakeResponse(status_code=200, json_payload={"id": "p2", "status": "starting", "urls": {"get": "https://r/p2"}}))
        provider.submit(MediaSpec(model="owner/name:abc123", prompt="dunes"))
        assert http.calls[-1].url == "https://api.replicate.com/v1/predictions"
        assert (http.calls[-1].json_payload or {})["version"] == "abc123"
        job = provider.submit.__self__ and None  # noqa: B018 - readability only
        http.queue("get", FakeResponse(status_code=200, json_payload={"id": "p2", "status": "succeeded", "output": ["https://cdn/r.mp4"]}))
        from film.media_providers import MediaJob

        status = provider.poll(MediaJob(provider="replicate", id="p2", poll_url="https://r/p2"))
        assert status.state == "complete" and status.output_url == "https://cdn/r.mp4"
        assert job is None

    def test_key_and_model_errors_never_echo_the_key(self, fake_services):
        provider = FalProvider(fake_services.http, "")
        try:
            provider.submit(MediaSpec(model="m", prompt="p"))
        except Exception as exc:  # noqa: BLE001 - asserting the typed message
            assert "FAL_KEY_MISSING" in str(exc)
        fake_services.http.queue("post", FakeResponse(status_code=404, text="no such model"))
        provider = FalProvider(fake_services.http, FAKE_KEY)
        try:
            provider.submit(MediaSpec(model="nope", prompt="p"))
            raise AssertionError("expected a 404")
        except Exception as exc:  # noqa: BLE001
            assert "FAL_MODEL_NOT_FOUND" in str(exc) and FAKE_KEY not in str(exc)

    def test_suffix_from_url(self):
        assert suffix_for("https://cdn/x/out.webm?token=1", "video") == ".webm"
        assert suffix_for("https://cdn/x/out", "video") == ".mp4"
        assert suffix_for("https://cdn/x/out", "image") == ".png"


class TestMediaRunner:
    def _runner(self, fake_services) -> MediaRunner:
        return MediaRunner(fake_services.http, poll_interval_seconds=0, sleep=lambda _seconds: None)

    def test_runs_to_completion(self, fake_services):
        http = fake_services.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"video": {"url": "https://cdn/a.mp4"}}))
        http.queue("get", FakeResponse(status_code=200, content=b"mp4-bytes"))
        phases: list[str] = []
        result = self._runner(fake_services).run(
            provider="fal",
            api_key=FAKE_KEY,
            spec=MediaSpec(model="m", prompt="p"),
            on_progress=lambda percent, phase: phases.append(phase),
        )
        assert result.status == "complete" and result.content == b"mp4-bytes"
        assert any("Downloading" in phase for phase in phases)

    def test_cancels_between_polls(self, fake_services):
        http = fake_services.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s"}))
        cancelled = {"value": False}

        def is_cancelled() -> bool:
            was = cancelled["value"]
            cancelled["value"] = True
            return was

        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "IN_PROGRESS"}))
        result = self._runner(fake_services).run(
            provider="fal", api_key=FAKE_KEY, spec=MediaSpec(model="m", prompt="p"), is_cancelled=is_cancelled
        )
        assert result.status == "cancelled"

    def test_missing_model_id_is_a_clear_failure(self, fake_services):
        result = self._runner(fake_services).run(provider="fal", api_key=FAKE_KEY, spec=MediaSpec(model=" ", prompt="p"))
        assert result.status == "failed" and "model id" in result.error


class TestHostedFilmGeneration:
    def _use_fal(self, client) -> None:
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "mediaProvider": "fal", "defaultVideoModel": "fal-ai/ltx-video"})

    def test_shot_renders_through_the_hosted_provider(self, client, test_state):
        self._use_fal(client)
        scene_id, shot_id = _scene_and_shot(client)
        http = test_state.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"video": {"url": "https://cdn/shot.mp4"}}))
        http.queue("get", FakeResponse(status_code=200, content=b"hosted-mp4"))
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}
        )
        assert response.status_code == 200, response.text
        shot = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]
        version = shot["versions"][0]
        assert version["status"] == "complete"
        assert version["execution_mode"] == "fal"
        assert Path(version["output_path"]).read_bytes() == b"hosted-mp4"
        submitted = next(call for call in http.calls if call.url.startswith("https://queue.fal.run"))
        assert (submitted.json_payload or {})["prompt"]

    def test_missing_key_fails_the_version_with_an_actionable_message(self, client):
        client.post("/api/settings", json={"mediaProvider": "replicate", "defaultVideoModel": "owner/model"})
        scene_id, shot_id = _scene_and_shot(client)
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        version = client.get(f"/api/film/projects/{PROJECT}").json()["project"]["scenes"][0]["shots"][0]["versions"][0]
        assert version["status"] == "failed"
        assert "REPLICATE_KEY_MISSING" in version["error"]
        assert FAKE_KEY not in version["error"]

    def test_project_setting_overrides_the_app_default(self, client, test_state):
        self._use_fal(client)
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        settings = {**project["settings"], "media_provider": "local"}
        assert client.put(f"/api/film/projects/{PROJECT}/settings", json={"settings": settings}).status_code == 200
        scene_id, shot_id = _scene_and_shot(client)
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"})
        # Local path: no hosted call was made at all.
        assert not any(call.url.startswith("https://queue.fal.run") for call in test_state.http.calls)


class TestAssetReferenceGeneration:
    def test_hosted_reference_image_is_attached_to_the_asset(self, client, test_state):
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "mediaProvider": "fal", "defaultImageModel": "fal-ai/flux/schnell"})
        asset = client.post(
            f"/api/film/projects/{PROJECT}/assets",
            json={"kind": "character", "name": "Mara", "appearance": "tall, red coat"},
        ).json()["asset"]
        http = test_state.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"images": [{"url": "https://cdn/ref.png"}]}))
        http.queue("get", FakeResponse(status_code=200, content=_png_bytes()))
        response = client.post(
            f"/api/film/projects/{PROJECT}/assets/{asset['id']}/generate-reference", json={}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["provider"] == "fal" and payload["model"] == "fal-ai/flux/schnell"
        assert "Mara" in payload["prompt"] and "red coat" in payload["prompt"]
        assert payload["asset"]["reference_images"] == [payload["reference_path"]]
        media = client.get(f"/api/film/projects/{PROJECT}/media", params={"path": payload["reference_path"]})
        assert media.status_code == 200 and media.content.startswith(b"\x89PNG")

    def test_missing_key_is_reported_before_any_call(self, client):
        client.post("/api/settings", json={"mediaProvider": "wavespeed"})
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Lamp"}).json()["asset"]
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/generate-reference", json={})
        assert response.status_code == 400 and "WAVESPEED_KEY_MISSING" in response.text


class TestModelLibrary:
    def test_search_lists_local_models_and_source_status(self, client):
        payload = client.get("/api/models/library").json()
        assert payload["total"] >= 1
        ids = {(m["provider"], m["id"]) for m in payload["models"]}
        assert ("native", "checkpoint") in ids
        sources = {s["id"]: s for s in payload["sources"]}
        assert sources["native"]["kind"] == "local"
        assert sources["openrouter"]["configured"] is False
        assert sources["fal"]["catalog_url"].startswith("https://")
        assert payload["offline_ready"] is False
        assert "offline" in payload["offline_note"].lower()

    def test_filters_by_task_source_and_query(self, client):
        text_only = client.get("/api/models/library", params={"task": "text"}).json()
        assert all(m["task"] == "text" for m in text_only["models"])
        hosted = client.get("/api/models/library", params={"source": "hosted"}).json()
        assert all(m["source"] == "hosted" for m in hosted["models"])
        flux = client.get("/api/models/library", params={"query": "flux"}).json()
        assert flux["models"] and all("flux" in m["id"].lower() or "flux" in m["name"].lower() for m in flux["models"])

    def test_hosted_media_examples_are_marked_and_need_a_key(self, client):
        payload = client.get("/api/models/library", params={"source": "hosted", "task": "video"}).json()
        fal_rows = [m for m in payload["models"] if m["provider"] == "fal"]
        assert fal_rows and all(row["curated"] and row["state"] == "needs_key" for row in fal_rows)
        assert all(row["url"].startswith("https://") for row in fal_rows)
        # With a key the same rows become usable, still flagged as examples.
        client.post("/api/settings", json={"falApiKey": FAKE_KEY})
        keyed = client.get("/api/models/library", params={"source": "hosted", "task": "video", "refresh": True}).json()
        assert all(row["state"] == "example" for row in keyed["models"] if row["provider"] == "fal")

    def test_hosted_text_models_come_from_the_provider(self, client, test_state):
        client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY})
        test_state.http.queue(
            "get",
            FakeResponse(
                status_code=200,
                json_payload={"data": [{"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5", "context_length": 200000}]},
            ),
        )
        payload = client.get("/api/models/library", params={"source": "hosted", "task": "text"}).json()
        rows = [m for m in payload["models"] if m["provider"] == "openrouter"]
        assert rows[0]["id"] == "anthropic/claude-sonnet-5" and rows[0]["context_length"] == 200000

    def test_ollama_models_are_listed_as_installed_and_pullable(self, client, test_state):
        client.post("/api/settings", json={"openaiCompatibleBaseUrl": "http://127.0.0.1:11434/v1", "openaiCompatibleModel": "qwen2.5"})
        test_state.http.queue(
            "get",
            FakeResponse(
                status_code=200,
                json_payload={"models": [{"name": "qwen2.5:7b", "size": 4_700_000_000, "details": {"quantization_level": "Q4_K_M"}}]},
            ),
        )
        payload = client.get("/api/models/library", params={"task": "text", "refresh": True}).json()
        row = next(m for m in payload["models"] if m["provider"] == "ollama")
        assert row["installed"] is True and row["quantization"] == "Q4_K_M" and row["size_gb"] == 4.7
        # Pulling a new model goes through Ollama's own API.
        test_state.http.queue("post", FakeResponse(status_code=200, json_payload={"status": "success"}))
        started = client.post("/api/models/library/download", json={"provider": "ollama", "model_id": "llama3.2:3b"})
        assert started.status_code == 200, started.text
        assert test_state.http.calls[-1].url == "http://127.0.0.1:11434/api/pull"
        status = client.get("/api/models/library/download").json()
        assert status["status"] == "complete" and status["model_id"] == "llama3.2:3b"
        assert "ollama:llama3.2:3b" in client.get("/api/settings").json()["recentModelIds"]

    def test_hosted_models_cannot_be_downloaded(self, client):
        response = client.post("/api/models/library/download", json={"provider": "fal", "model_id": "fal-ai/x"})
        assert response.status_code == 400 and "cloud" in response.text.lower()
        native = client.post("/api/models/library/download", json={"provider": "native", "model_id": "checkpoint"})
        assert native.status_code == 400 and "Models tab" in native.text

    def test_remembering_a_typed_model_id_puts_it_in_the_library(self, client):
        assert client.post("/api/models/library/remember", json={"provider": "replicate", "model_id": "owner/custom"}).status_code == 200
        payload = client.get("/api/models/library", params={"query": "owner/custom"}).json()
        assert payload["models"][0]["id"] == "owner/custom"
        assert payload["models"][0]["provider"] == "replicate"

    def test_a_broken_provider_does_not_empty_the_library(self, client, test_state):
        client.post("/api/settings", json={"openrouterApiKey": FAKE_KEY})
        test_state.http.queue("get", FakeResponse(status_code=500, text="upstream down"))
        payload = client.get("/api/models/library", params={"refresh": True}).json()
        source = next(s for s in payload["sources"] if s["id"] == "openrouter")
        assert source["error"] and source["count"] == 0
        assert payload["total"] >= 1  # local rows are still there
