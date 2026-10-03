"""Face lock (user, 2026-10-03: "The face in the latest LoRA is better but still
not consistent with the original face or styleguide. How can we use the
styleguide to create a consistent face for the LoRA").

A render made with a character LoRA has its face re-composed from the style
sheet's front face (FLUX.2 Klein: the render's head is the guide, the sheet's
head the person), aligned by landmarks and blended over the face oval; kept
only when the face matches the photo better than before.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from film.face_lock import blend_face, head_square, yaw
from tests.test_asset_angles import FLUX2, _image_params
from tests.test_training import _dataset

POINTS = [(24.0, 26.0), (40.0, 26.0), (32.0, 34.0), (26.0, 44.0), (38.0, 44.0)]
BOX = (16.0, 14.0, 32.0, 40.0)


def test_a_head_square_frames_the_face_inside_the_image() -> None:
    assert head_square((330.0, 100.0, 120.0, 150.0), 768, 1024) == (195, 17, 390)
    assert head_square((0.0, 0.0, 120.0, 150.0), 768, 1024) == (0, 0, 390), "clamped, not shrunk"
    assert head_square((10.0, 10.0, 30.0, 40.0), 64, 64) == (0, 0, 64), "never larger than the image"
    assert head_square((10.0, 10.0, 12.0, 16.0), 768, 1024) is None, "too few pixels to re-compose"


def test_the_face_oval_takes_the_new_face_and_the_rest_stays() -> None:
    image = np.full((64, 64, 3), 10, np.uint8)
    head = np.full((64, 64, 3), 250, np.uint8)
    out = blend_face(image, head, (0, 0), POINTS, POINTS, BOX)
    assert out is not None
    assert out[34, 32].tolist() == [250, 250, 250], "the face centre is the re-composed face"
    assert out[2, 2].tolist() == [10, 10, 10] and out[62, 62].tolist() == [10, 10, 10], "hair, background and body are the render's own"


def test_the_new_face_is_moved_onto_the_render_landmarks() -> None:
    image = np.full((96, 96, 3), 10, np.uint8)
    head = np.full((64, 64, 3), 10, np.uint8)
    head[30:38, 28:36] = 250  # a mark on the nose of the re-composed head
    shifted = [(x + 20, y + 10) for x, y in POINTS]
    out = blend_face(image, head, (0, 0), POINTS, shifted, (BOX[0] + 20, BOX[1] + 10, BOX[2], BOX[3]))
    assert out is not None
    assert out[44, 52].tolist() == [250, 250, 250], "the nose mark follows the render's nose"


def _lora_with_style_sheet(client, test_state, fake_services, tmp_path: Path) -> dict:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    dataset = _dataset(client, tmp_path, count=4, trigger="rvnx")
    sheet = tmp_path / "sheet" / "Raven-front-view.png"
    sheet.parent.mkdir()
    Image.new("RGB", (64, 64), (90, 80, 70)).save(sheet)
    dataset = client.post(f"/api/training/datasets/{dataset['id']}/import", json={"image_paths": [str(sheet)]}).json()
    lora = tmp_path / "raven.safetensors"
    lora.write_bytes(b"0" * 64)
    entry = client.post("/api/training/loras/import", json={"path": str(lora), "name": "Raven", "target": "z_image", "trigger": "rvnx"}).json()
    client.put(f"/api/training/loras/{entry['id']}", json={"dataset_id": dataset["id"]})
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.points = {"wangp-fake": (BOX, POINTS), "front-view": (BOX, POINTS)}
    return {"lora": str(lora), "sheet": sheet}


def test_a_lora_render_gets_the_style_sheet_face(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    made = _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    fake_services.face_matcher.vectors = {"facelock": [0.96, 0.28], "wangp-fake": [0.5, 0.866]}
    before = len(_image_params(fake_services))
    response = client.post("/api/generate-image", json={"prompt": "rvnx, woman, medium shot", "width": 64, "height": 64, "loras": [{"name": made["lora"], "multiplier": 1.0}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["face_scores"] == [0.96], "the locked face, scored against the photo"
    params = _image_params(fake_services)[before:]
    assert len(params) >= 2, "the LoRA render, then a face pass"
    face_pass = params[1]
    refs = [str(r) for r in face_pass.get("image_refs", [])]
    assert len(refs) == 2 and "front-view" in refs[1], "the render's head is the guide, the style sheet's head the person"
    with Image.open(body["image_paths"][0]) as locked:
        assert locked.size == (64, 64), "the render keeps its size and place"
    assert not any("facelock" in p.name for p in Path(body["image_paths"][0]).parent.iterdir()), "no candidate files left behind"


def test_a_face_pass_that_matches_worse_is_dropped(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    made = _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    fake_services.face_matcher.vectors = {"facelock": [0.1, 0.995], "wangp-fake": [0.5, 0.866]}
    response = client.post("/api/generate-image", json={"prompt": "rvnx, woman", "width": 64, "height": 64, "loras": [{"name": made["lora"], "multiplier": 1.0}]})
    body = response.json()
    assert body["face_scores"] == [0.5], "the render as it came: the pass made the face worse"
    with Image.open(body["image_paths"][0]) as kept:
        assert kept.getpixel((32, 34)) == (20, 200, 120), "untouched"


def test_face_lock_can_be_switched_off(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    made = _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    before = len(_image_params(fake_services))
    body = client.post("/api/generate-image", json={"prompt": "rvnx, woman", "width": 64, "height": 64, "faceLock": False, "loras": [{"name": made["lora"], "multiplier": 1.0}]}).json()
    assert len(_image_params(fake_services)) - before == 1 and body["face_scores"] is None


def test_a_render_without_a_character_lora_is_left_alone(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    before = len(_image_params(fake_services))
    body = client.post("/api/generate-image", json={"prompt": "a lighthouse", "width": 64, "height": 64}).json()
    assert len(_image_params(fake_services)) - before == 1 and body["face_scores"] is None


def test_the_lora_preview_shows_the_face_locked_renders(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    matcher = fake_services.face_matcher
    matcher.vectors = {"facelock": [0.96, 0.28], "wangp-fake": [0.5, 0.866], "previews": [0.5, 0.866]}
    matcher.points["previews"] = (BOX, POINTS)
    entry = client.get("/api/training/loras").json()["loras"][0]
    before = len(_image_params(fake_services))
    updated = client.post(f"/api/training/loras/{entry['id']}/preview").json()
    assert updated["preview_scores"] == [0.96] * 4, "what a render with the LoRA gives"
    assert len(_image_params(fake_services)) - before == 8, "four views, each with one face pass (0.96 is good enough)"


TURNED = [(24.0, 26.0), (40.0, 26.0), (36.0, 34.0), (28.0, 44.0), (40.0, 44.0)]  # nose 0.25 eye-widths right
PROFILE = [(24.0, 26.0), (40.0, 26.0), (42.0, 34.0), (30.0, 44.0), (42.0, 44.0)]  # nose 0.62 eye-widths right


def test_yaw_reads_the_head_turn_from_the_landmarks() -> None:
    assert yaw(POINTS) == 0.0
    assert yaw(TURNED) == 0.25
    assert yaw(PROFILE) == 0.625
    assert yaw([(40.0, 26.0), (24.0, 26.0), (28.0, 34.0), (26.0, 44.0), (38.0, 44.0)]) == -0.25, "the sign says which way"


def test_the_blend_stays_inside_the_recomposed_head() -> None:
    image = np.full((96, 96, 3), 10, np.uint8)
    head = np.full((40, 40, 3), 250, np.uint8)
    points = [(x - 12, y - 4) for x, y in POINTS]
    out = blend_face(image, head, (12, 4), points, POINTS, (8.0, 4.0, 48.0, 60.0))
    assert out is not None
    assert out[24, 32].tolist() == [250, 250, 250], "inside the head: the new face"
    assert out[60, 32].tolist() == [10, 10, 10], "inside the face oval but below the head square: the render's own"


def test_a_profile_is_left_as_it_is(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    """In-app 2026-10-03: the profile preview came back facing the camera on a
    side-on body - the style sheet only has a front face."""
    create_fake_model_files(include_zit=True)
    made = _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    fake_services.face_matcher.points["wangp-fake"] = (BOX, PROFILE)
    fake_services.face_matcher.vectors = {"facelock": [0.96, 0.28], "wangp-fake": [0.5, 0.866]}
    before = len(_image_params(fake_services))
    body = client.post("/api/generate-image", json={"prompt": "rvnx, woman, profile view", "width": 64, "height": 64, "loras": [{"name": made["lora"], "multiplier": 1.0}]}).json()
    assert len(_image_params(fake_services)) - before == 1, "no face pass"
    assert body["face_scores"] == [0.5]


def test_a_turned_head_keeps_its_angle(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    made = _lora_with_style_sheet(client, test_state, fake_services, tmp_path)
    matcher = fake_services.face_matcher
    matcher.points = {"-head": (BOX, POINTS), "wangp-fake": (BOX, TURNED), "front-view": (BOX, POINTS)}
    matcher.vectors = {"facelock": [0.96, 0.28], "wangp-fake": [0.5, 0.866]}
    before = len(_image_params(fake_services))
    body = client.post("/api/generate-image", json={"prompt": "rvnx, woman, three-quarter view", "width": 64, "height": 64, "loras": [{"name": made["lora"], "multiplier": 1.0}]}).json()
    passes = _image_params(fake_services)[before + 1:]
    assert passes and all("head angle" in p["prompt"] for p in passes), "the prompt that keeps the turn"
    assert body["face_scores"] == [0.5], "both re-composed heads faced the camera: dropped, the render kept"
