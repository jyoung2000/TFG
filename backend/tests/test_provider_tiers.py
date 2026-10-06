"""Tiered fallback (phase 9): per-task capability checks, the fallback runner,
and the real paths — Create video, a film shot and an asset reference image —
falling from a failing local engine to a hosted provider, all with fakes."""

from __future__ import annotations

from pathlib import Path

from film.media_runner import MediaRunResult
from film.provider_tiers import Tier, plan, run_with_fallback
from tests.fakes import FakeResponse

FAKE_KEY = "test-placeholder-not-a-real-key"
PROJECT = "tiers-project"


def _keys(provider: str) -> str:
    return FAKE_KEY if provider in ("fal", "wavespeed") else ""


def _models(provider: str, task: str) -> str:
    return {"fal": "fal-ai/ltx-video", "wavespeed": "wavespeed-ai/wan-2.2/t2v-480p"}.get(provider, "")


class TestPlan:
    def test_local_first_then_configured_hosted(self):
        result = plan("t2v", order=["local", "fal", "replicate", "wavespeed"], local_available=True, keys=_keys, models=_models)
        assert [t.provider for t in result.usable] == ["local", "fal", "wavespeed"]
        replicate = next(t for t in result.tiers if t.provider == "replicate")
        assert replicate.skip_reason == "REPLICATE_KEY_MISSING"

    def test_local_engine_limits_are_honest(self):
        result = plan("edit", order=["local"], local_available=True, keys=_keys, models=_models)
        assert result.usable == [] and "cannot do edit" in result.tiers[0].skip_reason
        assert plan("t2v", order=["local"], local_available=False, keys=_keys, models=_models).usable == []

    def test_catalog_rejects_a_model_that_cannot_do_the_task(self):
        # flux-dev is a text-to-image family in the capability catalog.
        result = plan("t2v", order=["fal"], local_available=True, keys=_keys, models=lambda _p, _t: "fal-ai/flux-dev")
        assert result.usable == [] and "capability catalog" in result.tiers[0].skip_reason
        # An unknown id is not refused — the provider decides.
        assert plan("t2v", order=["fal"], local_available=True, keys=_keys, models=lambda _p, _t: "fal-ai/brand-new-model").usable

    def test_duplicates_and_blanks_are_ignored(self):
        result = plan("t2i", order=["fal", "", "fal", "local"], local_available=True, keys=_keys, models=_models)
        assert [t.provider for t in result.tiers] == ["fal", "local"]


class TestRunner:
    def test_moves_on_after_a_failure_and_records_attempts(self):
        calls: list[str] = []

        def attempt(tier: Tier) -> MediaRunResult:
            calls.append(tier.provider)
            return MediaRunResult(status="failed", error="boom") if tier.provider == "local" else MediaRunResult(status="complete", content=b"x")

        outcome = run_with_fallback([Tier("local", "local"), Tier("fal", "m"), Tier("wavespeed", "w")], attempt)
        assert calls == ["local", "fal"] and outcome.provider == "fal" and outcome.fell_back
        assert outcome.note() == "fell back to fal after local: boom"

    def test_cancel_stops_the_chain(self):
        def attempt(tier: Tier) -> MediaRunResult:
            return MediaRunResult(status="cancelled", error="Cancelled")

        outcome = run_with_fallback([Tier("local", "local"), Tier("fal", "m")], attempt)
        assert outcome.result.status == "cancelled" and outcome.provider == "local" and not outcome.attempts

    def test_nothing_usable_says_why(self):
        outcome = run_with_fallback([Tier("fal", "", "FAL_KEY_MISSING")], lambda _t: MediaRunResult(status="complete"))
        assert outcome.result.status == "failed" and "FAL_KEY_MISSING" in outcome.result.error


def _queue_fal_video(http, url: str = "https://cdn/fallback.mp4") -> None:
    http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"}))
    http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
    http.queue("get", FakeResponse(status_code=200, json_payload={"video": {"url": url}}))
    http.queue("get", FakeResponse(status_code=200, content=b"mp4-from-fal"))


class TestCreateFallback:
    def test_local_failure_falls_back_to_fal_and_lands_in_history(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "defaultVideoModel": "fal-ai/ltx-video", "mediaTiers": {"t2v": ["local", "fal"]}})
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")
        _queue_fal_video(fake_services.http)
        r = client.post("/api/generate", json={"prompt": "A sunset", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24", "cameraMotion": "none"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "complete" and Path(data["video_path"]).read_bytes() == b"mp4-from-fal"
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 1}).json()["jobs"][0]
        assert job["status"] == "complete" and job["provider"] == "fal" and job["model"] == "fal-ai/ltx-video"
        assert "local: CUDA out of memory" in job["metrics"]["fallback"]

    def test_no_hosted_tier_keeps_the_local_error(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")
        r = client.post("/api/generate", json={"prompt": "A sunset", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24", "cameraMotion": "none"})
        assert r.status_code == 500 and "CUDA out of memory" in r.json()["error"]
        assert fake_services.http.calls == []

    def test_every_tier_failing_reports_each_reason(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "defaultVideoModel": "fal-ai/ltx-video", "mediaTiers": {"t2v": ["local", "fal"]}})
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")
        fake_services.http.queue("post", FakeResponse(status_code=500, text="fal is down"))
        r = client.post("/api/generate", json={"prompt": "A sunset", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24", "cameraMotion": "none"})
        assert r.status_code == 502
        assert "local: CUDA out of memory" in r.json()["error"] and "fal" in r.json()["error"]
        job = client.get("/api/jobs", params={"kind": "video_gen", "limit": 1}).json()["jobs"][0]
        assert job["status"] == "failed"

    def test_tier_preview_explains_skips(self, client):
        client.post("/api/settings", json={"mediaTiers": {"t2v": ["local", "fal"]}})
        tiers = client.get("/api/settings/tiers").json()
        assert [t["provider"] for t in tiers["t2v"]] == ["local", "fal"]
        assert tiers["t2v"][1]["skip_reason"] == "FAL_KEY_MISSING"
        assert tiers["edit"][0]["skip_reason"]


class TestFilmFallback:
    def _shot(self, client) -> tuple[str, str]:
        scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}).json()["id"]
        shot_id = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json={"title": "Shot", "duration_seconds": 4.0, "action": "walks"}).json()["id"]
        return scene_id, shot_id

    def test_shot_renders_on_fal_when_local_fails(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files()
        test_state.state.app_settings.use_local_text_encoder = True
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "defaultVideoModel": "fal-ai/ltx-video", "mediaTiers": {"t2v": ["local", "fal"]}})
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")
        _queue_fal_video(fake_services.http)
        scene_id, shot_id = self._shot(client)
        assert client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}).status_code == 200
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        version = project["scenes"][0]["shots"][0]["versions"][0]
        assert version["status"] == "complete", version
        assert Path(version["output_path"]).read_bytes() == b"mp4-from-fal"

    def test_reference_image_falls_back_to_fal(self, client, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        client.post("/api/settings", json={"falApiKey": FAKE_KEY, "defaultImageModel": "fal-ai/flux/schnell", "mediaTiers": {"t2i": ["local", "fal"]}})
        fake_services.image_generation_pipeline.raise_on_generate = RuntimeError("no VRAM")
        http = fake_services.http
        http.queue("post", FakeResponse(status_code=200, json_payload={"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"status": "COMPLETED"}))
        http.queue("get", FakeResponse(status_code=200, json_payload={"images": [{"url": "https://cdn/ref.png"}]}))
        from PIL import Image
        import io
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), "purple").save(buffer, format="PNG")
        http.queue("get", FakeResponse(status_code=200, content=buffer.getvalue()))
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara"}).json()["asset"]
        r = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/generate-reference", json={})
        assert r.status_code == 200, r.text
        assert r.json()["provider"] == "fal" and r.json()["model"] == "fal-ai/flux/schnell"
        assert len(r.json()["asset"]["reference_images"]) == 1
