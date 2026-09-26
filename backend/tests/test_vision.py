"""The local vision stack, the VRAM manager, and their wiring into the
analyzers and render paths — all through the FastAPI app with FakeVision
and FakeNvml. A model that is not consulted, a render that does not free
the card, or a settings slot that still reaches the Director is a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from services.vision.deterministic import kmeans_palette, measure_image, snap_aspect
from services.vision.florence2 import clean_caption, parse_boxes
from services.vram.vram_manager import FakeNvml, VramError, VramManager
from tests.fakes.services import FakeHTTPClient, FakeResponse


def _png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (96, 54)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


class TestDeterministic:
    def test_measurements_are_deterministic_and_sensible(self):
        image = Image.new("RGB", (640, 360), (0, 0, 0))
        for x in range(320):
            for y in range(360):
                image.putpixel((x, y), (250, 250, 250))
        first = measure_image(image)
        second = measure_image(image)
        assert first == second
        assert first.aspect == "16:9"
        assert 0.4 < first.luminance < 0.6
        assert first.contrast > 0.4, "half black, half white is high contrast"
        assert first.edge_density > 0, "the vertical boundary is an edge"
        assert {e.hex for e in first.palette} >= {"#000000", "#fafafa"} or len(first.palette) == 2
        assert abs(sum(e.share for e in first.palette) - 1.0) < 0.01

    def test_aspect_snapping(self):
        assert snap_aspect(1920, 1080) == "16:9"
        assert snap_aspect(1080, 1920) == "9:16"
        assert snap_aspect(1000, 1000) == "1:1"
        assert snap_aspect(997, 1003) == "1:1"

    def test_palette_is_ordered_by_share(self):
        import numpy as np

        rgb = np.concatenate([np.tile([[1.0, 0.0, 0.0]], (90, 1)), np.tile([[0.0, 0.0, 1.0]], (10, 1))])
        palette = kmeans_palette(rgb, k=2)
        assert palette[0].hex.startswith("#ff") or palette[0].share > palette[1].share
        assert palette[0].share > 0.8


class TestFlorencePostProcessing:
    def test_boxes_are_normalised(self):
        parsed = {"<OD>": {"bboxes": [[10.0, 20.0, 110.0, 120.0]], "labels": ["person"]}}
        regions = parse_boxes(parsed, "od", 200, 200)
        assert regions[0].label == "person"
        assert regions[0].bbox == [0.05, 0.1, 0.5, 0.5]

    def test_caption_cleanup(self):
        assert clean_caption("<s><MORE_DETAILED_CAPTION>A dog  on grass.</s><pad>") == "A dog on grass."


class TestVramManager:
    def test_prepare_unloads_lowest_priority_first_and_keeps_florence_when_it_fits(self):
        nvml = FakeNvml(total_mb=12288, used_mb=12288 - 6000)  # 6 GB free
        manager = VramManager(nvml)
        unloaded: list[str] = []
        manager.register("dino", "S", 200, lambda: unloaded.append("dino"), priority=20)
        manager.register("clip", "M", 1000, lambda: unloaded.append("clip"), priority=40)
        manager.register("florence", "M", 1700, lambda: unloaded.append("florence"), priority=80)
        # needs 9.5 GB + margin; 6 GB free → dino + clip (7.2) still short → florence goes too (8.9) → still short
        with pytest.raises(VramError) as excinfo:
            manager.prepare_for_render("ltx2_22B_distilled")
        assert unloaded == ["dino", "clip", "florence"]
        assert "Free" in str(excinfo.value) and "GB" in str(excinfo.value)

        nvml = FakeNvml(total_mb=12288, used_mb=12288 - 9000)  # 9 GB free
        manager = VramManager(nvml)
        unloaded.clear()
        manager.register("dino", "S", 200, lambda: unloaded.append("dino"), priority=20)
        manager.register("clip", "M", 1000, lambda: unloaded.append("clip"), priority=40)
        manager.register("florence", "M", 1700, lambda: unloaded.append("florence"), priority=80)
        plan = manager.prepare_for_render("ltx2_22B_distilled")
        assert unloaded == ["dino", "clip"], "florence survives once the headroom is there"
        assert plan.unloaded == ["dino", "clip"]
        assert [m.name for m in manager.loaded()] == ["florence"]

    def test_prepare_releases_the_ollama_vlm(self):
        http = FakeHTTPClient()
        http.queue("post", FakeResponse(200, {"done": True}))
        manager = VramManager(FakeNvml(used_mb=4000), http=http)
        manager.set_ollama("http://127.0.0.1:11434", "qwen2.5vl:3b")
        plan = manager.prepare_for_render("z_image")
        assert plan.ollama_released == "qwen2.5vl:3b"
        call = http.calls[-1]
        assert call.url.endswith("/api/generate")
        assert call.json_payload == {"model": "qwen2.5vl:3b", "keep_alive": 0}

    def test_no_gpu_means_no_arbitration(self):
        nvml = FakeNvml()
        nvml.available = False
        manager = VramManager(nvml)
        manager.register("clip", "M", 1000, lambda: None)
        plan = manager.prepare_for_render("ltx2_22B_distilled")
        assert plan.free_before_mb is None and plan.unloaded == []

    def test_render_scope_reports_peak(self):
        nvml = FakeNvml(used_mb=2000)
        manager = VramManager(nvml, sample_interval_s=0.01)
        with manager.render_scope("z_image") as scope:
            nvml.used_mb = 9800
        assert scope.peak_mb == 9800


class TestVisionApi:
    def test_status_lists_components_and_vram(self, client):
        r = client.get("/api/vision/status")
        assert r.status_code == 200, r.text
        payload = r.json()
        names = {c["name"] for c in payload["vision"]["components"]}
        assert {"stats", "florence", "clip", "depth", "dino"} <= names
        assert payload["vram"]["total_mb"] == 12288

    def test_analyze_returns_every_component_and_caches_by_content(self, client, test_state, fake_services, tmp_path):
        image = _png(tmp_path / "ref-01.png", (210, 30, 30))
        r = client.post("/api/vision/analyze", json={"path": str(image)})
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["measured"]["aspect"] == "16:9"
        assert "red" in payload["caption"]["text"]
        assert payload["regions"][0]["label"] == "person"
        assert payload["regions"][0]["depth_median"] is not None
        assert [t["term"] for t in payload["tags"]["tags"]][:1] == ["photograph"]
        depth_png = Path(payload["depth"]["depth_png"])
        assert depth_png.is_file()
        with Image.open(depth_png) as depth:
            assert depth.mode in ("I;16", "I") and depth.size == (96, 54)
        calls_before = len(fake_services.vision.calls)
        again = client.post("/api/vision/analyze", json={"path": str(image)}).json()
        assert again["content_hash"] == payload["content_hash"]
        assert len(fake_services.vision.calls) == calls_before, "second call is served from the cache"
        # A different image is a different hash and is analysed again.
        other = _png(tmp_path / "ref-02.png", (30, 30, 210))
        different = client.post("/api/vision/analyze", json={"path": str(other)}).json()
        assert different["content_hash"] != payload["content_hash"]
        assert "blue" in different["caption"]["text"]

    def test_disabled_component_leaves_a_note_instead_of_failing(self, client, fake_services, tmp_path):
        fake_services.vision.disabled.add("clip")
        image = _png(tmp_path / "ref.png", (10, 200, 10))
        payload = client.post("/api/vision/analyze", json={"path": str(image), "use_cache": False}).json()
        assert payload["tags"] is None
        assert "clip" in payload["notes"]["tags"]
        assert payload["caption"]["text"]

    def test_unload_reports_what_was_loaded(self, client, fake_services, tmp_path):
        image = _png(tmp_path / "ref.png", (10, 200, 10))
        client.post("/api/vision/analyze", json={"path": str(image)})
        r = client.post("/api/vision/unload")
        assert set(r.json()["unloaded"]) == {"clip", "depth", "florence"}

    def test_settings_vision_section_round_trips(self, client):
        r = client.get("/api/settings").json()
        assert r["vision"]["enabled"] is True
        assert r["vision"]["florenceModel"] == "florence-2-large"
        assert r["vision"]["vlmKeepAlive"] == "0"
        update = client.post("/api/settings", json={"vision": {"vlmProvider": "ollama", "vlmModel": "qwen2.5vl:3b", "florenceEnabled": False}})
        assert update.status_code == 200, update.text
        after = client.get("/api/settings").json()["vision"]
        assert after["vlmProvider"] == "ollama" and after["vlmModel"] == "qwen2.5vl:3b"
        assert after["florenceEnabled"] is False and after["clipEnabled"] is True

    def test_vlm_slot_is_independent_of_the_director(self, client, test_state):
        assert test_state.vision.optional_vlm(None) is None, "director fallback with no director"
        client.post("/api/settings", json={"vision": {"vlmProvider": "ollama", "vlmModel": "qwen2.5vl:3b", "vlmBaseUrl": "http://127.0.0.1:11434"}})
        provider = test_state.vision.optional_vlm(None)
        assert provider is not None
        assert provider.name == "ollama" and provider.model == "qwen2.5vl:3b"
        assert provider.base_url == "http://127.0.0.1:11434/v1"
        client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
        assert test_state.vision.optional_vlm(None) is None

    def test_settings_change_reaches_the_vram_manager(self, client, test_state):
        client.post("/api/settings", json={"vision": {"vlmProvider": "ollama", "vlmModel": "qwen3-vl:4b"}})
        assert client.get("/api/vision/status").json()["vram"]["ollama_model"] == "qwen3-vl:4b"

    def test_prepare_render_is_actionable_when_the_card_is_full(self, client, fake_services):
        fake_services.nvml.used_mb = 12288 - 1024  # 1 GB free
        r = client.post("/api/vision/prepare-render", json={"model_type": "ltx2_22B_distilled"})
        assert r.status_code == 507
        assert "Free" in r.json()["error"]


class TestRenderPaths:
    def test_video_render_records_peak_vram_and_frees_the_card_first(self, client, test_state, fake_services, create_fake_model_files, tmp_path):
        from tests.test_generation import _enable_local_text_encoding

        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        # Something vision-ish is loaded and the card is otherwise fine.
        fake_services.nvml.used_mb = 3000
        released: list[str] = []
        test_state.vram.register("clip", "M", 1000, lambda: released.append("clip"), priority=40)
        fake_services.nvml.used_mb = 12288 - 9100  # 9.1 GB free: short of 9.5 + 0.5 margin until clip (1 GB) goes
        r = client.post("/api/generate", json={"prompt": "peak", "duration": "2"})
        assert r.status_code == 200, r.text
        assert released == ["clip"]
        job = client.get("/api/jobs").json()["jobs"][0]
        assert job["metrics"]["peak_vram_mb"] >= 0

    def test_render_refuses_with_an_actionable_message_instead_of_oom(self, client, test_state, fake_services, create_fake_model_files):
        from tests.test_generation import _enable_local_text_encoding

        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        fake_services.nvml.used_mb = 12288 - 2000
        r = client.post("/api/generate", json={"prompt": "too big", "duration": "2"})
        assert r.status_code == 507, r.text
        assert "Free" in r.json()["error"]
        job = client.get("/api/jobs").json()["jobs"][0]
        assert job["status"] == "failed" and "Free" in job["error"]


class TestAnalyzerWiring:
    def test_image_analysis_works_offline_from_the_local_stack(self, client, tmp_path, fake_services):
        source = _png(tmp_path / "reference.png", (230, 45, 45))
        client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
        imported = client.post("/api/image-analysis/import", json={"path": str(source)}).json()
        analyzed = client.post(f"/api/image-analysis/{imported['id']}/analyze")
        assert analyzed.status_code == 200, analyzed.text
        payload = analyzed.json()
        assert payload["vision_model"] == "local-stack"
        assert "red" in payload["prompt"] and "person" in payload["prompt"]
        assert payload["tags"][:1] == ["photograph"]
        assert payload["measured"]["aspect"] == "16:9"
        assert payload["regions"][0]["label"] == "person"
        assert payload["depth_path"].endswith(".png")
        assert ("florence", str(Path(imported["id"]).name)) not in fake_services.vision.calls  # sanity: calls are per file path
        assert any(component == "florence" for component, _ in fake_services.vision.calls)

    def test_text_only_director_no_longer_breaks_image_analysis(self, client, tmp_path, test_state, monkeypatch):
        class _TextOnly:
            name = "ollama"
            model = "llama3"

            def chat(self, messages, **kwargs):  # noqa: ANN001
                raise RuntimeError("this model does not accept images")

        monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _TextOnly())
        source = _png(tmp_path / "reference.png", (30, 200, 30))
        imported = client.post("/api/image-analysis/import", json={"path": str(source)}).json()
        analyzed = client.post(f"/api/image-analysis/{imported['id']}/analyze")
        assert analyzed.status_code == 200, analyzed.text
        payload = analyzed.json()
        assert payload["vision_model"] == "local-stack"
        assert "does not accept images" in payload["vision_notes"]["vlm"]
        assert payload["prompt"]

    def test_vlm_receives_the_grounded_context(self, client, tmp_path, test_state, monkeypatch):
        seen: list[str] = []

        class _Vlm:
            name = "ollama"
            model = "qwen2.5vl:3b"

            def chat(self, messages, **kwargs):  # noqa: ANN001
                seen.append(messages[-1].content)
                from film.llm_providers import LLMReply

                return LLMReply(text=json.dumps({"prompt": "a green field, photograph", "confidence": 0.8}), tool_calls=[], model="qwen2.5vl:3b")

        monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _Vlm())
        source = _png(tmp_path / "reference.png", (30, 200, 30))
        imported = client.post("/api/image-analysis/import", json={"path": str(source)}).json()
        payload = client.post(f"/api/image-analysis/{imported['id']}/analyze").json()
        assert payload["prompt"] == "a green field, photograph"
        assert "Detected caption" in seen[0] and "Detected subjects" in seen[0] and "Measured" in seen[0]

    def test_video_analysis_subjects_come_from_detection(self, client, video, fake_services):
        from tests.test_video_analysis import _import

        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        r = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={"offline_only": True})
        assert r.status_code == 200, r.text
        shots = r.json()["shots"]
        assert shots, "shots were detected"
        for shot in shots:
            assert shot["visual"]["subjects"] == ["person"], shot["visual"]
            assert shot["visual"]["description"]
            assert shot["visual"]["palette"]
            assert shot["provenance"] == "measured"
        assert any(component == "florence" for component, _ in fake_services.vision.calls)

    def test_model_library_lists_vision_models_and_downloads_them_as_jobs(self, client, test_state):
        r = client.get("/api/models/library", params={"task": "vision"})
        assert r.status_code == 200, r.text
        models = [m for m in r.json()["models"] if m["provider"] == "vision"]
        ids = {m["id"] for m in models}
        assert {"florence-2-large", "florence-2-base", "openai/clip-vit-large-patch14", "depth-anything-v2-small", "dinov2-small"} <= ids
        assert all(m["task"] == "vision" for m in models)
        started = client.post("/api/models/library/download", json={"provider": "vision", "model_id": "depth-anything-v2-small"})
        assert started.status_code == 200, started.text
        jobs = client.get("/api/jobs", params={"kind": "download"}).json()["jobs"]
        assert jobs and jobs[0]["provider"] == "vision" and jobs[0]["status"] == "complete"
        snapshot = [c for c in test_state.model_downloader.calls if c["kind"] == "snapshot"][-1]
        assert snapshot["repo_id"] == "depth-anything/Depth-Anything-V2-Small-hf"
        assert "models--depth-anything--Depth-Anything-V2-Small-hf" in snapshot["local_dir"]
