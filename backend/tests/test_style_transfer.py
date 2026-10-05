"""Saved art styles (user, 2026-10-05: "reverse engineer artstyle from an image ...
save the art style to an asset to use later and also use those styles to transform
an image from 1 art style to another accurately and efficiently"; "reference assets
in prompts and use the character, artstyle, prop, or location consistently like a
LoRA without being a lora").

A style asset's pictures go to the image model with the picture to restyle: FLUX.1
USO Dev when installed, else FLUX.2 Klein. `@Style` in a shot draws its frame in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from film.film_models import FilmAsset, FilmAssetStyleGuide
from film.llm_providers import LLMReply
from film.style_transfer import USO_MODEL, USO_STEPS, pick_style_images, style_text, transfer_mode, transfer_prompt
from services.wangp_bridge import WanGPBridge
from tests.test_asset_angles import FLUX2, _image_params, _png
from tests.test_styleguide_shots import _find_shot, _install_qwen, _raven, _shot
from tests.test_training import PROJECT

USO = {"id": USO_MODEL, "name": "Flux 1 USO Dev 12B", "installed": True}


def _style(client, name: str = "Ghibli Watercolor", colors=((200, 220, 180), (90, 140, 200))) -> dict:
    asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={
        "kind": "style", "name": name, "style_prompt": "soft watercolor, hand-drawn ink outlines, pastel palette",
    }).json()["asset"]
    for i, color in enumerate(colors):
        asset = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references",
                            json={"image_base64": _png(color), "name_hint": f"style-{i}"}).json()["asset"]
    return asset


def _local(client, test_state, fake_services, *models: dict) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.extend(models)


# ---- pure ------------------------------------------------------------------


def test_the_style_in_words_is_its_prompt_then_its_guide() -> None:
    style = FilmAsset(kind="style", name="Noir", style_prompt="high-contrast ink noir", style_guide=FilmAssetStyleGuide(
        key_traits=["Medium: ink wash", "high-contrast ink noir"], color_palette=["black", "#d9d0c1"], mood="brooding"))
    text = style_text(style)
    assert text.startswith("high-contrast ink noir") and "Medium: ink wash" in text
    assert text.count("high-contrast ink noir") == 1, "a trait the prompt already says is not repeated"
    assert "palette: black, #d9d0c1" in text and "mood: brooding" in text
    assert style_text(FilmAsset(kind="style", name="Bare")) == "Bare"


def test_uso_takes_the_picture_then_two_styles_klein_one() -> None:
    assert transfer_mode(USO_MODEL, has_content=True) == "KI" and transfer_mode(USO_MODEL, has_content=False) == "IJ"
    assert transfer_mode("flux2_klein_4b", has_content=True) == "KI"
    klein = transfer_prompt("flux2_klein_4b", "pastel watercolor")
    assert "picture 1" in klein and "picture 2: pastel watercolor" in klein and "not its content" in klein
    uso = transfer_prompt(USO_MODEL, "pastel watercolor", subject="a girl on a pier")
    assert uso == "a girl on a pier. Art style: pastel watercolor."


def test_graded_style_pictures_lead_and_rejected_ones_never_go() -> None:
    picked = pick_style_images(["a", "b", "c"], rejected=lambda p: p == "a", liked=lambda p: p == "c", count=2)
    assert picked == ["c", "b"]


def test_the_bridge_finds_weights_in_the_configs_other_checkpoint_folders(tmp_path: Path) -> None:
    """FLUX.1 USO lives on D: (2026-10-05, C: is full): WanGP's `checkpoints_paths`."""
    root = tmp_path / "Wan2GP"
    (root / "defaults").mkdir(parents=True)
    (root / "ckpts").mkdir()
    (root / "defaults" / "flux.json").write_text(json.dumps({"model": {"name": "Flux 1 Dev", "URLs": [
        "https://x/flux1-dev_bf16.safetensors", "https://x/flux1-dev_quanto_bf16_int8.safetensors"]}}), encoding="utf-8")
    (root / "defaults" / "flux_dev_uso.json").write_text(json.dumps({"model": {"name": "USO", "URLs": "flux"}}), encoding="utf-8")
    elsewhere = tmp_path / "D" / "flux-ckpts"
    elsewhere.mkdir(parents=True)
    config_dir = tmp_path / "bridge"
    config_dir.mkdir()
    bridge = WanGPBridge(enabled=True, root=root, python_executable=None, config_dir=config_dir, output_dir=tmp_path / "out",
                         video_model_type="ltx2_22B_distilled", image_model_type="z_image", camera_motion_prompts={}, extra_args=())
    assert bridge.weights_installed(USO_MODEL) is False
    (elsewhere / "flux1-dev_quanto_bf16_int8.safetensors").write_bytes(b"0")
    (config_dir / "wgp_config.json").write_text(json.dumps({"checkpoints_paths": ["ckpts", str(elsewhere), "."]}), encoding="utf-8")
    assert bridge.weights_installed(USO_MODEL) is True


# ---- restyling a picture ---------------------------------------------------


def test_a_picture_is_redrawn_in_the_style_by_uso_from_its_pictures(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _local(client, test_state, fake_services, FLUX2, USO)
    style = _style(client)
    raven = _raven(client, test_state, fake_services)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/apply-style",
                           json={"image_path": raven["reference_images"][0], "target_asset_id": raven["id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    (params,) = _image_params(fake_services)[before:]
    assert params["model_type"] == USO_MODEL and params["video_prompt_type"] == "KI"
    assert params["num_inference_steps"] == USO_STEPS, "FLUX.1 Dev is not a 4-step model"
    refs = [Path(p).name for p in params["image_refs"]]
    assert refs[0] == Path(raven["reference_images"][0]).name and len(refs) == 2, "USO reads only the last reference as the style"
    assert "soft watercolor" in params["prompt"]
    assert body["model"] == USO_MODEL and body["image_path"].startswith("captures/") and "ghibli-watercolor" in body["image_path"]
    assert body["asset"]["reference_images"][-1] == body["image_path"], "kept as the character drawn in the style"


def test_without_uso_klein_redraws_it_from_one_style_picture(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _local(client, test_state, fake_services, FLUX2)
    style = _style(client)
    raven = _raven(client, test_state, fake_services)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/apply-style", json={"image_path": raven["reference_images"][0]})
    assert response.status_code == 200, response.text
    (params,) = _image_params(fake_services)[before:]
    assert params["model_type"] == "flux2_klein_4b" and len(params["image_refs"]) == 2
    assert "picture 2" in params["prompt"]


def test_a_style_picture_graded_down_is_not_used(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _local(client, test_state, fake_services, FLUX2)
    style = _style(client)
    raven = _raven(client, test_state, fake_services)
    client.post("/api/taste/vote", json={"kind": "style_guide", "subject": style["reference_images"][0], "project_id": PROJECT, "vote": -1})
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/apply-style", json={"image_path": raven["reference_images"][0]})
    (params,) = _image_params(fake_services)[before:]
    assert Path(params["image_refs"][1]).name == Path(style["reference_images"][1]).name


def test_only_a_style_asset_restyles_and_only_with_a_model(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    raven = _raven(client, test_state, fake_services)
    fake_services.wangp_bridge.definitions.remove(FLUX2)
    style = _style(client)
    path = raven["reference_images"][0]
    assert client.post(f"/api/film/projects/{PROJECT}/assets/{raven['id']}/apply-style", json={"image_path": path}).status_code == 400
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/apply-style", json={"image_path": path})
    assert response.status_code == 400 and "USO" in response.json()["error"]


# ---- @Style in a shot ------------------------------------------------------


def test_a_mentioned_style_draws_the_shot_frame_in_it(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    raven = _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    fake_services.wangp_bridge.definitions.append(USO)
    style = _style(client)
    scene_id, shot_id = _shot(client, "@Raven walks along the pier, @Ghibli_Watercolor")
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
    assert response.status_code == 200, response.text
    start, end, restyle_start, restyle_end = _image_params(fake_services)[before:]
    assert "photorealistic" not in start["prompt"] and "art style: soft watercolor" in start["prompt"]
    assert Path(start["image_refs"][0]).name == Path(raven["reference_images"][0]).name
    for restyle, frame in ((restyle_start, "-frame.png"), (restyle_end, "-frame-end.png")):
        assert restyle["model_type"] == USO_MODEL and Path(restyle["image_refs"][0]).name.endswith(frame)
        assert [Path(p).name for p in restyle["image_refs"][1:]] == [Path(style["reference_images"][0]).name]
    assert _find_shot(client, shot_id)["frame_path"].endswith("-frame.png")


def test_a_shot_frame_is_restyled_in_place_keeping_the_original(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    style = _style(client)
    scene_id, shot_id = _shot(client, "@Raven walks along the pier")
    client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/apply-style", json={"shot_id": shot_id})
    assert response.status_code == 200, response.text
    shot = _find_shot(client, shot_id)
    assert shot["frame_path"] == response.json()["image_path"] and "ghibli-watercolor" in shot["frame_path"]
    assert "ghibli-watercolor" in shot["end_frame_path"], "the end frame too: the video ends in the style"


# ---- reverse-engineering a style --------------------------------------------


class _StyleReader:
    model = "qwen2.5vl:7b"

    def __init__(self) -> None:
        self.seen: list = []

    def chat(self, messages, **kwargs):
        self.seen = messages
        return LLMReply(text=json.dumps({
            "medium": "watercolor on cold-press paper", "line_work": "thin sepia ink outlines", "shading": "soft wet-on-wet washes",
            "texture": "", "key_traits": ["visible paper grain"], "color_palette": ["sage", "sky blue"], "mood": "gentle",
            "recommended_prompt": "watercolor illustration, thin sepia ink outlines, soft washes, sage and sky-blue palette",
        }), tool_calls=[], model=self.model)


def test_a_style_is_reverse_engineered_from_its_pictures(client, test_state, monkeypatch):
    reader = _StyleReader()
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: reader)
    style = _style(client, colors=((1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{style['id']}/style-guide")
    assert response.status_code == 200, response.text
    asset = response.json()["asset"]
    assert len(reader.seen[-1].images) == 3, "what three pictures share is the style"
    assert "never WHAT they show" in reader.seen[0].content
    traits = asset["style_guide"]["key_traits"]
    assert traits[:3] == ["medium: watercolor on cold-press paper", "line work: thin sepia ink outlines", "shading: soft wet-on-wet washes"]
    assert "visible paper grain" in traits and not any(t.startswith("texture") for t in traits)
    assert asset["style_prompt"] == "watercolor on cold-press paper, thin sepia ink outlines, soft wet-on-wet washes, palette of sage, sky blue"
    assert asset["style_guide"]["recommended_prompt"].startswith("watercolor illustration")
