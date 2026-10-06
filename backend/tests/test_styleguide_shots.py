"""Shots that look like the style guide (user, 2026-10-04: "ensure the videos are
accurate to the styleguide and have an easy way to reference assets from
styleguides in the prompts so the software can generate accurate images / videos";
Wan 2.2 Image2video 14B Enhanced Lightning v2 for "consistent fast but quality videos").

Image-to-video takes the character from its first frame, so the storyboard frame is
composed by Qwen-Image-Edit from the cast's style-guide images, an end frame pins
the end of the shot to the same people, and the video starts (and ends) on them.
"""

from __future__ import annotations

from pathlib import Path

from film.multi_angle import LIGHTNING_LORA_FILE, QWEN_EDIT_2511
from handlers.film_generation_handler import lora_fits
from tests.test_multi_angle import _install_qwen_angles
from tests.test_asset_angles import FLUX2, _image_params, _png
from tests.test_training import PROJECT

WAN = "i2v_2_2_Enhanced_Lightning_v2"


def _raven(client, test_state, fake_services) -> dict:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Raven", "appearance": "black wavy hair"}).json()["asset"]
    return client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": _png((90, 60, 50)), "name_hint": "photo"}).json()["asset"]


def _install_qwen(test_state, fake_services) -> None:
    angles = _install_qwen_angles(test_state, fake_services)
    (angles.parent / LIGHTNING_LORA_FILE).write_bytes(b"0" * 64)


def _shot(client, action: str) -> tuple[str, str]:
    scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Docks"}).json()["id"]
    shot_id = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json={"title": "Shot", "duration_seconds": 5.0, "action": action}).json()["id"]
    return scene_id, shot_id


def _find_shot(client, shot_id: str) -> dict:
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    return next(s for scene in project["scenes"] for s in scene["shots"] if s["id"] == shot_id)


def test_a_mentioned_character_is_composed_into_the_frame_from_the_style_guide(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    raven = _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    scene_id, shot_id = _shot(client, "@Raven walks along the pier")
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
    assert response.status_code == 200, response.text
    start, end = _image_params(fake_services)[before:]
    assert start["model_type"] == QWEN_EDIT_2511 and start["resolution"] == "1360x768"
    assert [Path(p).name for p in start["image_refs"]] == [Path(raven["reference_images"][0]).name]
    assert "@" not in start["prompt"] and "Raven walks along the pier" in start["prompt"] and "picture 1" in start["prompt"]
    assert [Path(p).name for p in start["activated_loras"]] == [LIGHTNING_LORA_FILE], "no camera-angle LoRA in a story frame"
    # The end of the shot: the start frame is the scene, the photo the person.
    assert end["video_prompt_type"] == "KI" and len(end["image_refs"]) == 2
    assert Path(end["image_refs"][0]).name.endswith("-frame.png") and "picture 2" in end["prompt"]
    shot = _find_shot(client, shot_id)
    assert shot["frame_path"].endswith("-frame.png") and shot["end_frame_path"].endswith("-frame-end.png")


def test_a_shot_with_no_action_gets_no_end_frame(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    scene_id, shot_id = _shot(client, "")
    client.put(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}", json={"visual_prompt": "@Raven on the pier at night", "prompt_locked": True})
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
    assert len(_image_params(fake_services)) - before == 1
    assert _find_shot(client, shot_id)["end_frame_path"] == ""


def test_the_video_starts_and_ends_on_the_style_guide_frames(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    fake_services.wangp_bridge.definitions.append({"id": WAN, "name": "Wan2.2 Image2video Enhanced Lightning v2 14B", "installed": True, "default_steps": 4})
    client.post("/api/settings", json={"defaultVideoModel": WAN})
    scene_id, shot_id = _shot(client, "@Raven walks along the pier")
    client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/frame", json={})
    response = client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "final"})
    assert response.status_code == 200, response.text
    video = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" not in m[0]["params"]][-1]
    assert video["model_type"] == WAN
    assert Path(video["image_start"]).name.endswith("-frame.png") and Path(video["image_end"]).name.endswith("-frame-end.png")
    assert "@" not in video["prompt"]


def test_an_image_to_video_shot_without_a_frame_gets_one_first(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    _raven(client, test_state, fake_services)
    _install_qwen(test_state, fake_services)
    fake_services.wangp_bridge.definitions.append({"id": WAN, "name": "Wan2.2 Image2video Enhanced Lightning v2 14B", "installed": True, "default_steps": 4})
    client.post("/api/settings", json={"defaultVideoModel": WAN})
    scene_id, shot_id = _shot(client, "@Raven walks along the pier")
    client.post(f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "final"})
    video = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" not in m[0]["params"]][-1]
    assert Path(video["image_start"]).name.endswith("-frame.png")
    assert _find_shot(client, shot_id)["frame_path"], "the frame is kept on the storyboard"


def test_a_lora_goes_only_to_the_model_family_it_was_trained_for() -> None:
    assert lora_fits("z_image", "z_image") and lora_fits("z_image", "z_image_turbo")
    assert not lora_fits("z_image", "ltx2_22B_distilled") and not lora_fits("z_image", WAN)
    assert lora_fits("wan22", WAN) and lora_fits("wan22", "t2v_2_2") and not lora_fits("wan22", "ltx2_22B_distilled")
    assert lora_fits("ltx2", "ltx2_22B_distilled") and lora_fits("ltx2", "ltx2-fast")
    assert not lora_fits("z_image", ""), "an unknown model gets no LoRA it might not take"
