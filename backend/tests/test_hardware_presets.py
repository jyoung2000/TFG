"""Hardware presets (phase 8): the RTX 4070 12 GB preset is recommended for
that card, applies through the normal settings path, and never sets a
default the card cannot run."""

from __future__ import annotations

from state.hardware_presets import PRESETS, RTX_4070_12GB, VIDEO_PROFILES, recommended_preset


class TestRecommendation:
    def test_4070_is_recommended_by_name_or_by_12gb(self):
        assert recommended_preset("NVIDIA GeForce RTX 4070", 12) is RTX_4070_12GB
        assert recommended_preset("NVIDIA GeForce RTX 3080", 10) is RTX_4070_12GB  # name marker
        assert recommended_preset("NVIDIA GeForce RTX 3060", 12) is RTX_4070_12GB  # 12 GB NVIDIA
        assert recommended_preset("NVIDIA GeForce RTX 4090", 24) is None
        assert recommended_preset(None, None) is None
        assert recommended_preset("Apple M2", 12) is None

    def test_route_reports_recommendation_and_applied_state(self, client, fake_services):
        fake_services.gpu_info.gpu_name = "NVIDIA GeForce RTX 4070"
        fake_services.gpu_info.vram_gb = 12
        data = client.get("/api/settings/presets").json()
        assert data["gpu_name"] == "NVIDIA GeForce RTX 4070" and data["gpu_vram_gb"] == 12
        assert data["applied"] == ""
        preset = data["presets"][0]
        assert preset["id"] == "rtx-4070-12gb" and preset["recommended"] is True and preset["applied"] is False
        assert [p["id"] for p in preset["video_profiles"]] == ["fast", "balanced"]
        assert preset["changes"]


class TestApply:
    def test_apply_sets_every_default_within_12gb(self, client, test_state):
        response = client.post("/api/settings/presets/rtx-4070-12gb/apply")
        assert response.status_code == 200, response.text
        settings = response.json()
        assert settings["hardwarePreset"] == "rtx-4070-12gb"
        assert settings["defaultVideoModel"] == "ltx2_22B_distilled" and settings["defaultImageModel"] == "z_image"
        assert settings["videoProfile"] == "fast" and settings["imageSteps"] == 8
        assert settings["useLocalTextEncoder"] is True and settings["mediaProvider"] == "local"
        vision = settings["vision"]
        assert vision["florenceModel"] == "florence-2-large" and vision["clipModel"] == "openai/clip-vit-large-patch14"
        assert vision["depthModel"] == "depth-anything-v2-small" and vision["dinoModel"] == "dinov2-small"
        assert vision["vlmProvider"] == "off" and vision["vlmKeepAlive"] == "0"
        # Persisted like any other change, and reported as applied.
        assert test_state.state.app_settings.gpu_vram_budget_gb == 12.0
        assert client.get("/api/settings/presets").json()["applied"] == "rtx-4070-12gb"
        # Keys and unrelated settings are untouched.
        assert settings["hasLtxApiKey"] is False

    def test_apply_keeps_a_persons_later_edits_until_reapplied(self, client, test_state):
        client.post("/api/settings/presets/rtx-4070-12gb/apply")
        client.post("/api/settings", json={"videoProfile": "balanced"})
        assert client.get("/api/settings").json()["videoProfile"] == "balanced"
        client.post("/api/settings/presets/rtx-4070-12gb/apply")
        assert client.get("/api/settings").json()["videoProfile"] == "fast"

    def test_unknown_preset_is_404(self, client):
        assert client.post("/api/settings/presets/rtx-9090/apply").status_code == 404

    def test_profiles_fit_the_card(self):
        # The fast profile is the default; balanced never exceeds 720p / 8 s on the distilled model.
        assert VIDEO_PROFILES["fast"].resolution == "540p" and VIDEO_PROFILES["fast"].duration_seconds == 6
        assert VIDEO_PROFILES["balanced"].resolution == "720p" and VIDEO_PROFILES["balanced"].duration_seconds <= 8
        for preset in PRESETS.values():
            assert preset.patch["gpu_vram_budget_gb"] <= 12.0
            assert preset.patch["vision"]["vlm_provider"] == "off"
