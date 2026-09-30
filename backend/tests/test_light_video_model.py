"""A light video model for a 32 GB machine.

LTX-2 22B distilled needs ~39 GB of weights (transformer 18.5 GB, Gemma text
encoder 12.6 GB, ...). MEASURED on the RTX 4070 / 32 GB box (2026-09-30):
free RAM hit 0 MB during every 2 s 540p render and it took 491-586 s however
WanGP was configured. Wan 2.2 TI2V FastWan 5B (5 GB int8 + the umt5 encoder
already installed, 3 steps) fits in RAM. It takes a start image but no end
frame and no control video, so:

- a "fast" render uses FastWan when it is installed, unless the request needs
  an end frame or a control/depth video (those stay on the configured model);
- a request may name its WanGP model explicitly;
- FastWan renders with its own 3 steps, not the 8 the app asks LTX-2 for;
- FastWan's definition points at `ti2v_2_2` for its weights ("URLs":
  "ti2v_2_2"), so the catalog resolves that reference instead of reporting a
  model that is on disk as missing.
"""

from __future__ import annotations

import json
from pathlib import Path

_T2V = {"prompt": "test", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24"}
_FAST = "ti2v_2_2_fastwan"


def _enable(test_state, fake_services, *, fastwan_installed: bool = True) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions = [
        {"id": "ltx2_22B_distilled", "name": "LTX-2", "installed": True, "default_steps": 8},
        {"id": _FAST, "name": "FastWan 5B", "installed": fastwan_installed, "default_steps": 3},
    ]


def _last_params(fake_services) -> dict:
    params = fake_services.wangp_bridge.manifests[-1][0]["params"]
    assert isinstance(params, dict)
    return params


class TestFastRendersUseTheLightModel:
    def test_a_fast_render_uses_fastwan_with_its_own_steps(self, client, test_state, fake_services):
        _enable(test_state, fake_services)
        r = client.post("/api/generate", json=_T2V)
        assert r.status_code == 200, r.text
        params = _last_params(fake_services)
        assert params["model_type"] == _FAST
        assert params["num_inference_steps"] == 3
        assert "sliding_window_size" not in params, "an LTX-2-only setting"

    def test_without_fastwan_the_configured_model_renders(self, client, test_state, fake_services):
        _enable(test_state, fake_services, fastwan_installed=False)
        client.post("/api/generate", json=_T2V)
        assert _last_params(fake_services)["model_type"] == "ltx2_22B_distilled"

    def test_an_end_frame_keeps_the_model_that_supports_it(self, client, test_state, fake_services, tmp_path):
        from PIL import Image

        _enable(test_state, fake_services)
        end = tmp_path / "end.png"
        Image.new("RGB", (64, 64)).save(end)
        client.post("/api/generate", json={**_T2V, "endFramePath": str(end)})
        assert _last_params(fake_services)["model_type"] == "ltx2_22B_distilled"

    def test_a_named_model_wins(self, client, test_state, fake_services):
        _enable(test_state, fake_services)
        client.post("/api/generate", json={**_T2V, "model": "pro", "wangpModel": _FAST})
        assert _last_params(fake_services)["model_type"] == _FAST


class TestReferenceDefinitionsResolve:
    def test_a_definition_that_names_another_model_uses_its_files(self, tmp_path: Path):
        from services.wangp_bridge import WanGPBridge

        root = tmp_path / "Wan2GP"
        (root / "defaults").mkdir(parents=True)
        (root / "ckpts").mkdir()
        (root / "defaults" / "ti2v_2_2.json").write_text(json.dumps({"model": {"name": "5B", "architecture": "ti2v_2_2", "URLs": [
            "https://huggingface.co/DeepBeepMeep/Wan2.2/resolve/main/wan2.2_text2video_5B_mbf16.safetensors",
            "https://huggingface.co/DeepBeepMeep/Wan2.2/resolve/main/wan2.2_text2video_5B_quanto_mbf16_int8.safetensors",
        ]}, "num_inference_steps": 50}))
        (root / "defaults" / "ti2v_2_2_fastwan.json").write_text(json.dumps({"model": {"name": "FastWan 5B", "architecture": "ti2v_2_2", "URLs": "ti2v_2_2"}, "num_inference_steps": 3}))
        (root / "ckpts" / "wan2.2_text2video_5B_quanto_mbf16_int8.safetensors").write_bytes(b"w")
        bridge = WanGPBridge(enabled=True, root=root, python_executable=None, config_dir=tmp_path / "cfg", output_dir=tmp_path / "out",
                             video_model_type="ltx2_22B_distilled", image_model_type="z_image", camera_motion_prompts={}, extra_args=())
        fast = next(d for d in bridge.list_model_definitions() if d["id"] == "ti2v_2_2_fastwan")
        assert fast["installed"] is True
        assert all(str(u).startswith("https://") for u in fast["urls"]) and len(fast["urls"]) == 2
        assert fast["default_steps"] == 3


class TestVaceTakesTheFramesAndTheGuide:
    """VACE 1.3B (the 1.3B Wan 2.1 base + a 1.4 GB VACE module) renders the
    reproduce rungs FastWan cannot - an end frame, the reference clip as a
    guide. MEASURED on the RTX 4070 (3 s of the reference clip, 832x480):
    raw guide 0.924 at 10 steps (169 s incl. load), 0.922 at 15 steps (143 s
    warm) vs LTX-2's 20-30 min per round on the 10 s shot. VACE takes no start
    image: frames are injected by position ("FI" + image_refs +
    frames_positions) and the guide is raw ("V")."""

    def _enable(self, test_state, fake_services):
        _enable(test_state, fake_services)
        fake_services.wangp_bridge.definitions.append({"id": "vace_1.3B", "name": "Vace 1.3B", "installed": True})

    def test_an_end_frame_renders_with_vace_frames_by_position(self, client, test_state, fake_services, tmp_path):
        from PIL import Image

        self._enable(test_state, fake_services)
        start, end = tmp_path / "start.png", tmp_path / "end.png"
        Image.new("RGB", (64, 64)).save(start)
        Image.new("RGB", (64, 64)).save(end)
        r = client.post("/api/generate", json={**_T2V, "imagePath": str(start), "endFramePath": str(end)})
        assert r.status_code == 200, r.text
        params = _last_params(fake_services)
        assert params["model_type"] == "vace_1.3B"
        assert "image_start" not in params and "image_end" not in params
        assert [Path(p).name for p in params["image_refs"]] == ["start.png", "end.png"]
        assert params["frames_positions"] == f"1 {params['video_length']}"
        assert "FI" in params["video_prompt_type"]
        assert params["resolution"] == "832x480"
        assert "sliding_window_size" not in params

    def test_a_guide_video_renders_raw_with_vace(self, client, test_state, fake_services, tmp_path):
        self._enable(test_state, fake_services)
        guide = tmp_path / "guide.mp4"
        guide.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        client.post("/api/generate", json={**_T2V, "controlVideoPath": str(guide), "controlStrength": 0.8})
        params = _last_params(fake_services)
        assert params["model_type"] == "vace_1.3B"
        assert params["video_guide"] == str(guide.resolve())
        assert "V" in params["video_prompt_type"] and "G" not in params["video_prompt_type"]

    def test_a_pro_render_keeps_ltx2(self, client, test_state, fake_services, tmp_path):
        self._enable(test_state, fake_services)
        guide = tmp_path / "guide.mp4"
        guide.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        client.post("/api/generate", json={**_T2V, "model": "pro", "controlVideoPath": str(guide), "controlStrength": 0.8})
        assert _last_params(fake_services)["model_type"] == "ltx2_22B_distilled"
