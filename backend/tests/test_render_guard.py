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

    def test_defaults_cover_every_round4_measured_peak(self, test_state):
        """Round 4 (4070, 2026-09-27) recorded two whole-GPU peaks per render:
        the app's own History sampler and an external nvidia-smi sampler. Both
        sample at intervals, so the true peak is at least the larger one. The
        configured need (before SAFETY_MARGIN_MB) must cover the worst
        `max(History, sampler) - baseline` measured for each bucket; otherwise
        the guard admits a render into less VRAM than the card was seen to use.
          ltx2_22B_distilled  Fast on final code  6584 - 1939 = 4645
          z_image             1024^2, 8 steps     7073 - 2242 = 4831"""
        measured_worst = {"ltx2_22B_distilled": 6584 - 1939, "z_image": 7073 - 2242}
        for model_type, worst in measured_worst.items():
            assert test_state.vram.needed_mb(model_type) - SAFETY_MARGIN_MB >= worst, model_type

    def test_measured_default_admits_a_render_at_the_measured_peak(self, client, fake_services):
        """Round-4 (4070, 2026-09-27): the committed thresholds come from a real
        cold render, so a 12 GB desktop that has 8.5 GB free must be allowed to
        start it. The old blanket 8000 (+512 = 8512) refused this exact case,
        which is the "refuses every render the hardware could attempt" bug.
        Measured peak - baseline for a cold 540p 6 s Fast clip: 3966 MiB."""
        fake_services.nvml.used_mb = 12288 - 8500  # 8.5 GB free: a loaded desktop
        r = client.post("/api/vision/prepare-render", json={"model_type": "ltx2_22B_distilled"})
        assert r.status_code == 200, r.json()

    def test_posting_an_empty_override_map_keeps_stored_overrides(self, client, test_state):
        """F-053 (round 4): settings patches deep-merge, so `{}` is a no-op and
        only `0` drops an override. The set_overrides docstring now says so."""
        default = test_state.vram.needed_mb("ltx2_22B_distilled")
        client.post("/api/settings", json={"vram_render_needs_mb": {"ltx2_22B_distilled": 7000}})
        client.post("/api/settings", json={"vram_render_needs_mb": {}})
        assert test_state.vram.needed_mb("ltx2_22B_distilled") == 7000 + SAFETY_MARGIN_MB
        client.post("/api/settings", json={"vram_render_needs_mb": {"ltx2_22B_distilled": 0}})
        assert test_state.vram.needed_mb("ltx2_22B_distilled") == default

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


class TestRenderWithModelOverride:
    """A request must be able to name the image model it renders with.

    Today `WanGPBridge.generate_images` hardcodes `self._image_model_type`
    (services/wangp_bridge.py:304) and the handler's weights check and VRAM
    scope both read `config.wangp_image_model_type`, so every candidate renders
    with whatever the backend was started with. The UI admits it in its own
    copy: "Candidates always render with {job.image_model}" next to tabs for
    LTX-2, Wan 2.2, SDXL and FLUX (ImageReproduce.tsx:211).

    Measured on the 4070 with the Seedream reference, four image models are
    installed and all four render; switching between them currently means
    restarting the backend on a different WANGP_IMAGE_MODEL_TYPE:

        z_image                    best 0.7113   (12 candidates)
        z_image_nunchaku_r128_fp4  best 0.7257   (12 candidates)
        z_image_nunchaku_r256_int4 best 0.7325   (12 candidates)
        flux2_klein_4b             best 0.6996   (9 candidates)
    """

    def _enable(self, test_state, fake_services, installed=("z_image", "flux2_klein_4b")):
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions = [
            {"id": m, "name": m, "installed": True} for m in installed
        ]

    def test_a_named_model_is_the_one_actually_rendered(self, client, test_state, fake_services):
        self._enable(test_state, fake_services)
        r = client.post("/api/generate-image", json={"prompt": "x", "model": "flux2_klein_4b"})
        assert r.status_code == 200, r.text
        manifests = fake_services.wangp_bridge.manifests
        assert manifests, "nothing was rendered"
        model_types = {m.get("params", {}).get("model_type") for m in manifests[0] if isinstance(m, dict)}
        assert model_types == {"flux2_klein_4b"}, f"rendered with {model_types}, not the requested model"

    def test_no_named_model_keeps_the_configured_default(self, client, test_state, fake_services):
        self._enable(test_state, fake_services)
        r = client.post("/api/generate-image", json={"prompt": "x"})
        assert r.status_code == 200, r.text
        model_types = {m.get("params", {}).get("model_type")
                       for m in fake_services.wangp_bridge.manifests[0] if isinstance(m, dict)}
        assert model_types == {"z_image"}, f"the default must still apply, got {model_types}"

    def test_a_named_model_without_weights_is_refused_by_name(self, client, test_state, fake_services):
        # The model is known to the checkout but its weights are not on disk -
        # the real state of a model the user has not downloaded. Asking for it
        # must be refused BY NAME, not silently fall back to the default.
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions = [
            {"id": "z_image", "name": "z_image", "installed": True},
            {"id": "flux2_klein_4b", "name": "flux2_klein_4b", "installed": False},
        ]
        r = client.post("/api/generate-image", json={"prompt": "x", "model": "flux2_klein_4b"})
        assert r.status_code == 409, r.text
        assert "flux2_klein_4b" in r.json()["error"], r.json()["error"]
        assert fake_services.wangp_bridge.manifests == [], "nothing may be rendered"
