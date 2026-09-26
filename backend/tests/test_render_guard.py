"""RTX 4070 audit fixes: the render guard must be attainable on a 12 GB
card and settings-driven, and a local WanGP render with missing weights is
refused toward the Models tab instead of silently downloading a checkpoint.
"""

from __future__ import annotations

from services.vram.vram_manager import SAFETY_MARGIN_MB

#: The realistic free-VRAM ceiling on a 12 GB desktop card (the OS and
#: compositor keep the rest) — measured at 8.95 GB free on the 4070 audit.
_ATTAINABLE_FREE_MB = 8900

_T2V = {"prompt": "test", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24"}


class TestVramGuardSettings:
    def test_default_video_thresholds_are_attainable_on_12gb(self, test_state):
        """A guard the target hardware can never satisfy refuses every render
        the card could attempt; the 12 GB-class defaults must be reachable."""
        for model_type in ("ltx2_22B_distilled", "ltx2-fast", "wan2_2_ti2v_5B", "z_image"):
            assert test_state.vram.needed_mb(model_type) <= _ATTAINABLE_FREE_MB, model_type
        # The non-distilled 22B genuinely does not fit a 12 GB card.
        assert test_state.vram.needed_mb("ltx2_22B") > 11000

    def test_settings_override_reaches_the_guard_and_zero_restores(self, client, test_state):
        default = test_state.vram.needed_mb("ltx2_22B_distilled")
        r = client.post("/api/settings", json={"vram_render_needs_mb": {"ltx2_22B_distilled": 7000}})
        assert r.status_code == 200
        assert test_state.vram.needed_mb("ltx2_22B_distilled") == 7000 + SAFETY_MARGIN_MB
        # Round-trips (camelCase on the wire) so an agent can read back what it set.
        assert client.get("/api/settings").json()["vramRenderNeedsMb"] == {"ltx2_22B_distilled": 7000}
        # Patches deep-merge, so 0 (not deletion) restores the default.
        client.post("/api/settings", json={"vram_render_needs_mb": {"ltx2_22B_distilled": 0}})
        assert test_state.vram.needed_mb("ltx2_22B_distilled") == default

    def test_override_changes_a_live_prepare_render_verdict(self, client, fake_services):
        fake_services.nvml.used_mb = 12288 - 8700  # 8.7 GB free: default fits
        assert client.post("/api/vision/prepare-render", json={"model_type": "ltx2_22B_distilled"}).status_code == 200
        client.post("/api/settings", json={"vram_render_needs_mb": {"ltx2_22B_distilled": 9500}})
        r = client.post("/api/vision/prepare-render", json={"model_type": "ltx2_22B_distilled"})
        assert r.status_code == 507 and "Free" in r.json()["error"]


class TestWanGPWeightsPrecheck:
    def _enable_wangp(self, test_state, fake_services, *, installed: bool):
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions = [
            {"id": "ltx2_22B_distilled", "name": "LTX-2 22B distilled", "installed": installed},
            {"id": "z_image", "name": "Z-Image", "installed": installed},
        ]

    def test_video_render_refuses_when_weights_are_absent(self, client, test_state, fake_services):
        self._enable_wangp(test_state, fake_services, installed=False)
        r = client.post("/api/generate", json=_T2V)
        assert r.status_code == 409
        assert "Models tab" in r.json()["error"] and "ltx2_22B_distilled" in r.json()["error"]
        # Nothing reached the bridge — no render, no silent checkpoint download.
        assert fake_services.wangp_bridge.manifests == []

    def test_video_render_runs_once_weights_are_installed(self, client, test_state, fake_services):
        self._enable_wangp(test_state, fake_services, installed=True)
        r = client.post("/api/generate", json=_T2V)
        assert r.status_code == 200 and r.json()["status"] == "complete"
        assert len(fake_services.wangp_bridge.manifests) == 1

    def test_image_render_refuses_when_weights_are_absent(self, client, test_state, fake_services):
        self._enable_wangp(test_state, fake_services, installed=False)
        r = client.post("/api/generate-image", json={"prompt": "test"})
        assert r.status_code == 409 and "z_image" in r.json()["error"]
        assert fake_services.wangp_bridge.manifests == []

    def test_unknown_presence_does_not_refuse(self, client, test_state, fake_services):
        """None means "cannot tell" (remote bridge) — never a refusal."""
        self._enable_wangp(test_state, fake_services, installed=True)
        fake_services.wangp_bridge.definitions = []
        r = client.post("/api/generate", json=_T2V)
        assert r.status_code == 200 and r.json()["status"] == "complete"


class TestCaptionFailuresAreLoud:
    def test_caption_pass_fails_loudly_instead_of_writing_trigger_only_captions(self, client, tmp_path, fake_services):
        from tests.test_training import _dataset

        dataset = _dataset(client, tmp_path, count=3)
        fake_services.vision.disabled.add("florence")
        r = client.post(f"/api/training/datasets/{dataset['id']}/caption", json={})
        assert r.status_code == 502
        assert "Florence-2" in r.json()["error"] and "disabled" in r.json()["error"]
        # No fabricated captions: the items are untouched.
        items = client.get(f"/api/training/datasets/{dataset['id']}").json()["items"]
        assert all(item["caption"] == "" for item in items)
