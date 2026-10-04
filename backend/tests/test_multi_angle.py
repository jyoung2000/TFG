"""Multi-angle model prompts (user, 2026-10-04: "Add support for these models to
help make accurate multiple angles and to produce accurate styleguides and
loras ... ensure both models are installed in the software and is the default
model for multiple angles").

Qwen-Image-Edit-2511 with fal's Multiple-Angles LoRA takes a camera position as
`<sks> [azimuth] [elevation] [distance]` from fixed words (8 azimuths, 4
elevations, 3 distances). Every angle-set shot name and style-sheet view maps
onto them.
"""

from __future__ import annotations

from pathlib import Path

from film.multi_angle import ANGLES_LORA_FILE, ANGLES_LORA_FOLDER, LIGHTNING_LORA_FILE, LORA_ANGLE_SHOTS, QWEN_EDIT_2511, angle_prompt, sheet_angle_prompt
from tests.test_asset_angles import FLUX2, _character, _image_params, _png
from tests.test_training import PROJECT


def test_each_angle_set_shot_names_its_camera() -> None:
    assert angle_prompt("full-front") == "<sks> front view eye-level shot wide shot"
    assert angle_prompt("full-34-left") == "<sks> front-left quarter view eye-level shot wide shot"
    assert angle_prompt("full-profile-left") == "<sks> left side view eye-level shot wide shot"
    assert angle_prompt("full-back-34-left") == "<sks> back-left quarter view eye-level shot wide shot"
    assert angle_prompt("full-back") == "<sks> back view eye-level shot wide shot"
    assert angle_prompt("full-back-34-right") == "<sks> back-right quarter view eye-level shot wide shot"
    assert angle_prompt("full-profile-right") == "<sks> right side view eye-level shot wide shot"
    assert angle_prompt("full-34-right") == "<sks> front-right quarter view eye-level shot wide shot"
    assert angle_prompt("medium-34-left") == "<sks> front-left quarter view eye-level shot medium shot"
    assert angle_prompt("closeup-profile-left") == "<sks> left side view eye-level shot close-up"
    assert angle_prompt("full-high") == "<sks> front view elevated shot wide shot"
    assert angle_prompt("full-low") == "<sks> front view low-angle shot wide shot"


def test_an_unknown_shot_is_a_front_medium_shot() -> None:
    assert angle_prompt("my-custom-angle") == "<sks> front view eye-level shot medium shot"


def test_the_style_sheet_views_are_real_turns_at_full_length() -> None:
    """The FLUX.2 sheet's "three-quarter" and "profile" views came back facing the
    camera (2026-10-03); the LoRA names the camera position instead."""
    assert sheet_angle_prompt("front view") == "<sks> front view eye-level shot wide shot"
    assert sheet_angle_prompt("three-quarter view") == "<sks> front-left quarter view eye-level shot wide shot"
    assert sheet_angle_prompt("profile view") == "<sks> left side view eye-level shot wide shot"
    assert sheet_angle_prompt("back view") == "<sks> back view eye-level shot wide shot"
    assert sheet_angle_prompt("something else") is None


# ---- which model makes the angles ------------------------------------------------

QWEN = {"id": QWEN_EDIT_2511, "name": "Qwen Image Edit Plus (2511) 20B", "installed": True}


def _install_qwen_angles(test_state, fake_services) -> Path:
    fake_services.wangp_bridge.definitions.append(QWEN)
    lora = test_state.config.settings_file.parent / "loras" / ANGLES_LORA_FOLDER / ANGLES_LORA_FILE
    lora.parent.mkdir(parents=True, exist_ok=True)
    lora.write_bytes(b"0" * 64)
    return lora


SHOTS = [
    {"name": "full-profile-left", "view": "seen in profile from their left side, full body", "guide_base64": _png((90, 90, 90))},
    {"name": "full-back", "view": "seen from behind, full body", "guide_base64": _png((60, 60, 60))},
]


def test_qwen_2511_with_the_angles_lora_makes_a_characters_angle_set(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    lora = _install_qwen_angles(test_state, fake_services)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["prompts"] == ["<sks> left side view eye-level shot wide shot", "<sks> back view eye-level shot wide shot"]
    params = _image_params(fake_services)[before:]
    assert len(params) == 2 and all(p["model_type"] == QWEN_EDIT_2511 for p in params)
    assert all(p["video_prompt_type"] == "KI" and len(p["image_refs"]) == 1 for p in params), "the photo alone: the LoRA turns the camera, no mannequin guide"
    assert all(Path(p["activated_loras"][0]) == lora.resolve() and p["loras_multipliers"] == "0.9" for p in params)
    assert all(p["num_inference_steps"] >= 20 for p in params)


def test_without_the_angles_lora_the_angle_set_falls_back_to_flux2(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    fake_services.wangp_bridge.definitions.append(QWEN)  # the model, but not its LoRA
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    params = _image_params(fake_services)[before:]
    assert params and all(p["model_type"] == FLUX2["id"] for p in params)


def test_the_style_sheet_turns_with_qwen_2511(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    _install_qwen_angles(test_state, fake_services)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/reference-sheet",
                           json={"views": ["front view", "three-quarter view", "profile view", "back view"], "seed": 9})
    assert response.status_code == 200, response.text
    assert response.json()["prompts"] == [
        "<sks> front view eye-level shot wide shot", "<sks> front-left quarter view eye-level shot wide shot",
        "<sks> left side view eye-level shot wide shot", "<sks> back view eye-level shot wide shot",
    ]
    params = _image_params(fake_services)[before:]
    assert len(params) == 4 and all(p["model_type"] == QWEN_EDIT_2511 for p in params)


def test_zero123pp_makes_an_objects_turnaround(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    _install_qwen_angles(test_state, fake_services)
    fake_services.multiview.enabled = True
    prop = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Lantern"}).json()["asset"]
    prop = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/references", json={"image_base64": _png((10, 120, 200)), "name_hint": "front"}).json()["asset"]
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(fake_services.multiview.calls) == 1 and len(result["reference_paths"]) == 6, "Zero123++'s six views, whatever shots were asked"
    assert result["prompts"][0] == "Zero123++: front-right raised (azimuth 30, elevation 20)"
    assert len(result["asset"]["reference_images"]) == 7
    assert len(_image_params(fake_services)) == before, "no WanGP render for an object's turnaround"


def test_an_object_without_zero123pp_uses_qwen_2511(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    _install_qwen_angles(test_state, fake_services)
    prop = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Lantern"}).json()["asset"]
    prop = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/references", json={"image_base64": _png((10, 120, 200)), "name_hint": "front"}).json()["asset"]
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert [p["model_type"] for p in _image_params(fake_services)[before:]] == [QWEN_EDIT_2511, QWEN_EDIT_2511]


def test_the_angle_models_report_what_is_installed(client, test_state, fake_services) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    status = client.get("/api/film/multi-angle/status").json()
    assert (status["characters"], status["objects"]) == ("", "")
    _install_qwen_angles(test_state, fake_services)
    fake_services.wangp_bridge.definitions.append(FLUX2)
    fake_services.multiview.enabled = True
    status = client.get("/api/film/multi-angle/status").json()
    assert status["characters"] == "Qwen-Image-Edit-2511 + Multiple-Angles LoRA"
    assert status["objects"] == "Zero123++ v1.2"
    assert [c["id"] for c in status["choices"]] == ["", "qwen_image_edit_plus2_20B", "zero123plus", "flux2_klein_4b"]
    assert all(c["installed"] for c in status["choices"])


def test_settings_choose_the_angle_model_for_characters_and_objects(client, test_state, fake_services, create_fake_model_files) -> None:
    """User, 2026-10-04: "In the settings let the user choose which AI model renders
    multiple angles for characters and which ai model renders multiple angles for objects"."""
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    _install_qwen_angles(test_state, fake_services)
    fake_services.multiview.enabled = True
    assert client.post("/api/settings", json={"characterAngleModel": "flux2_klein_4b", "objectAngleModel": "qwen_image_edit_plus2_20B"}).status_code == 200
    status = client.get("/api/film/multi-angle/status").json()
    assert (status["characters"], status["objects"]) == ("FLUX.2 Klein (flux2_klein_4b)", "Qwen-Image-Edit-2511 + Multiple-Angles LoRA")
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert [p["model_type"] for p in _image_params(fake_services)[before:]] == ["flux2_klein_4b", "flux2_klein_4b"]
    prop = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Lantern"}).json()["asset"]
    prop = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/references", json={"image_base64": _png((10, 120, 200)), "name_hint": "front"}).json()["asset"]
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert [p["model_type"] for p in _image_params(fake_services)[before:]] == [QWEN_EDIT_2511, QWEN_EDIT_2511]
    assert fake_services.multiview.calls == [], "Zero123++ installed, but the user picked Qwen for objects"


def test_a_chosen_model_that_is_not_installed_falls_back(client, test_state, fake_services) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    client.post("/api/settings", json={"characterAngleModel": "qwen_image_edit_plus2_20B"})
    assert client.get("/api/film/multi-angle/status").json()["characters"] == "FLUX.2 Klein (flux2_klein_4b)"


def test_qwen_renders_each_angle_once(client, test_state, fake_services, create_fake_model_files) -> None:
    """MEASURED 2026-10-04 on the RTX 4070 (32 GB RAM): Qwen-Image-Edit-2511 int8 at
    30 steps takes ~8 minutes an image; three seeds per angle (FLUX.2's face
    re-roll) made four angles run past 90 minutes. Qwen renders each angle once."""
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    _install_qwen_angles(test_state, fake_services)
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.vectors = {"-front": [1.0, 0.0]}  # the identity photo
    matcher.default = [0.3, 0.954]  # every render a weak match (0.3): FLUX.2 would try 3 seeds
    before = len(_image_params(fake_services))
    client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert len(_image_params(fake_services)) - before == 2, "two angles, one render each"


def test_with_the_lightning_lora_qwen_renders_each_angle_in_8_steps(client, test_state, fake_services, create_fake_model_files) -> None:
    """MEASURED 2026-10-04: 30 steps at CFG 4 came back black (NaN) after ~10 minutes
    an angle; the Lightning 8-step LoRA rendered a clean side view in 148 s."""
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    angles = _install_qwen_angles(test_state, fake_services)
    lightning = angles.parent / LIGHTNING_LORA_FILE
    lightning.write_bytes(b"0" * 64)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5})
    assert response.status_code == 200, response.text
    params = _image_params(fake_services)[before:]
    assert len(params) == 2
    assert all([Path(p).resolve() for p in q["activated_loras"]] == [angles.resolve(), lightning.resolve()] for q in params)
    assert all(q["num_inference_steps"] == 8 and q["guidance_scale"] == 1.0 for q in params)


# ---- style guides and LoRAs from the angle models -----------------------------
# User, 2026-10-04: "can we use qwen to make multiple angles for styleguides and for
# z-image turbo LoRA's to create consistent characters, use zero123 for object
# styleguide and loras".


def _prop(client) -> dict:
    prop = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "prop", "name": "Ship Lantern"}).json()["asset"]
    return client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/references", json={"image_base64": _png((10, 120, 200)), "name_hint": "front"}).json()["asset"]


def test_an_objects_style_sheet_is_the_zero123pp_turnaround(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    fake_services.multiview.enabled = True
    prop = _prop(client)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/reference-sheet", json={})
    assert response.status_code == 200, response.text
    assert len(fake_services.multiview.calls) == 1 and len(response.json()["reference_paths"]) == 6
    assert len(_image_params(fake_services)) == before, "FLUX.2 drew the object from words; Zero123++ turns the photo"
    again = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/reference-sheet", json={}).json()
    assert len(again["asset"]["reference_images"]) == 7, "a new turnaround replaces the old one (the name has a space)"


def test_a_characters_dataset_renders_its_qwen_lora_angles_first(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    _install_qwen_angles(test_state, fake_services)
    before = len(_image_params(fake_services))
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/dataset", json={"angles": True})
    assert response.status_code == 200, response.text
    params = _image_params(fake_services)[before:]
    assert [p["prompt"] for p in params] == [angle_prompt(name) for name in LORA_ANGLE_SHOTS]
    assert all(p["model_type"] == QWEN_EDIT_2511 and p["resolution"] == "1024x1024" for p in params), "~1 MP: the LoRA trains at 384-512 px"
    names = [Path(item["origin"] or item["file"]).name for item in response.json()["items"]]
    assert all(any(n.endswith(f"-{shot}.png") for n in names) for shot in LORA_ANGLE_SHOTS)
    # A second dataset renders only the angles that are missing: none.
    client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/dataset", json={"angles": True})
    assert len(_image_params(fake_services)) == before + len(LORA_ANGLE_SHOTS)


def test_a_dataset_without_angles_renders_nothing(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    _install_qwen_angles(test_state, fake_services)
    before = len(_image_params(fake_services))
    assert client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/dataset").status_code == 200
    assert len(_image_params(fake_services)) == before


def test_an_objects_dataset_uses_the_zero123pp_turnaround(client, test_state, fake_services, create_fake_model_files) -> None:
    create_fake_model_files(include_zit=True)
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.multiview.enabled = True
    prop = _prop(client)
    response = client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/dataset", json={"angles": True})
    assert response.status_code == 200, response.text
    assert len(fake_services.multiview.calls) == 1 and len(response.json()["items"]) == 7
    client.post(f"/api/film/projects/{PROJECT}/assets/{prop['id']}/dataset", json={"angles": True})
    assert len(fake_services.multiview.calls) == 1, "the turnaround is there already"


def test_a_re_rendered_angle_replaces_the_old_one_whatever_the_name(client, test_state, fake_services, create_fake_model_files) -> None:
    """r74 QA: "Raven QA (your photo)" is saved as "Raven-QA--your-photo-"; the old
    angle was never matched and the angles piled up."""
    create_fake_model_files(include_zit=True)
    asset = _character(client, test_state, fake_services)
    client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"name": "Raven QA (your photo)"})
    _install_qwen_angles(test_state, fake_services)
    for _ in range(2):
        result = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": SHOTS, "seed": 5}).json()
    assert len(result["asset"]["reference_images"]) == 3

