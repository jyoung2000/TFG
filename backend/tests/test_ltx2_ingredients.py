"""A film shot rendered on an LTX2 model sends its cast as reference images:
WanGP's Ingredients IC-LoRA keeps their identity through the whole clip (user,
2026-10-06: "remakes the character, prop, or location consistently"). Wan models
keep the old behavior: two LoRA-less characters at most."""

from __future__ import annotations

from pathlib import Path

from tests.test_asset_angles import _png
from tests.test_styleguide_shots import WAN, _install_qwen, _raven, _shot
from tests.test_training import PROJECT

LTX2 = "ltx2_22B_distilled"


def _video_params(fake_services) -> list[dict]:
    return [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" not in m[0]["params"]]


def _cast_shot(client, test_state, fake_services) -> tuple[str, str, dict, dict]:
    raven = _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    prop = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Lantern"}).json()["asset"]
    prop = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/references",
                       json={"image_base64": _png((200, 180, 40)), "name_hint": "lantern"}).json()["asset"]
    scene_id, shot_id = _shot(client, "@Raven lifts the @Lantern on the pier")
    return scene_id, shot_id, raven, prop


def test_an_ltx2_render_takes_the_cast_as_ingredients(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    scene_id, shot_id, raven, prop = _cast_shot(client, test_state, fake_services)
    client.post("/api/settings", json={"defaultVideoModel": LTX2})
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "final"})
    assert response.status_code == 200, response.text
    video = _video_params(fake_services)[-1]
    assert video["model_type"] == LTX2
    names = [Path(p).name for p in video["image_refs"]]
    assert names == [Path(raven["reference_images"][0]).name, Path(prop["reference_images"][0]).name]
    assert video["video_prompt_type"].endswith("I")


def test_a_wan_render_keeps_the_old_reference_behavior(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    scene_id, shot_id, raven, prop = _cast_shot(client, test_state, fake_services)
    fake_services.wangp_bridge.definitions.append({"id": WAN, "name": "Wan2.2 I2V Lightning", "installed": True, "default_steps": 4})
    client.post("/api/settings", json={"defaultVideoModel": WAN})
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "final"})
    assert response.status_code == 200, response.text
    video = _video_params(fake_services)[-1]
    assert video["model_type"] == WAN
    refs = [Path(p).name for p in video.get("image_refs", [])]
    assert Path(prop["reference_images"][0]).name not in refs, "props are an LTX2 ingredients thing"
