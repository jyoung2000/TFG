"""Faces that match the photo: the style sheet, the angle set and the LoRA dataset.

User, 2026-10-02: "The face of the LoRA is not consistent to the first uploaded
image ... Use the style sheet or build a style sheet as reference first."
MEASURED (OpenCV SFace cosine vs. Raven's photo; 0.363 = same person): the
sheet views 0.55-0.71, the 3D-studio angle set 0.25-0.43, the LoRA close-up
0.24. Composing each angle from a face close-up of the photo raised the angle
shots from ~0.34 to ~0.47 on average; with the full photo alone the face was
~200 px tall. Now every view is composed from the photo AND its face crop, the
best of several candidates (by face match) is kept, and the LoRA dataset leaves
out generated images that are not the same person.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from services.vision.protocol import VisionRegion
from tests.test_asset_angles import FLUX2, _image_params, _png
from tests.test_training import PROJECT

FACE = [0.40, 0.06, 0.18, 0.10]


def _raven(client, test_state, fake_services) -> dict:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    fake_services.vision.regions_override = [VisionRegion(label="face", bbox=FACE, score=0.9)]
    asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Raven"}).json()["asset"]
    buffer = io.BytesIO()
    Image.new("RGB", (1125, 2000), (90, 60, 50)).save(buffer, format="PNG")
    photo = base64.b64encode(buffer.getvalue()).decode()
    return client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": photo, "name_hint": "photo"}).json()["asset"]


def test_an_angle_is_composed_from_the_photo_and_its_face(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    shot = {"name": "closeup-front", "view": "close-up portrait of the head and shoulders", "guide_base64": _png((90, 90, 90))}
    assert client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": [shot], "seed": 5}).status_code == 200
    params = _image_params(fake_services)[-1]
    assert params["video_prompt_type"] == "KI"
    assert len(params["image_refs"]) == 3, "the pose guide, the photo, and the photo's face close-up"
    assert "face" in params["prompt"] and "third image" in params["prompt"]


def test_the_best_matching_face_of_several_candidates_is_kept(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    matcher = fake_services.face_matcher
    matcher.enabled = True
    # the identity photo, then three candidates: a stranger, the same face, close
    matcher.queue = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.6, 0.8]]
    shot = {"name": "closeup-front", "view": "close-up portrait", "guide_base64": _png((90, 90, 90))}
    before = len(_image_params(fake_services))
    result = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": [shot], "seed": 5}).json()
    assert len(_image_params(fake_services)) - before == 2, "a perfect match ends the search: the third is never rendered"
    assert result["face_scores"] == [1.0]
    assert len(result["asset"]["reference_images"]) == 2, "only the best is kept"


def test_the_sheet_also_keeps_the_best_face(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.queue = [[1.0, 0.0], [0.0, 1.0], [0.8, 0.6], [0.0, 1.0]]
    result = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/reference-sheet", json={"views": ["front view"], "seed": 9}).json()
    assert result["face_scores"] == [0.8]
    params = _image_params(fake_services)[-1]
    assert len(params["image_refs"]) == 2, "the photo and its face close-up"


def test_the_lora_dataset_leaves_out_strangers(client, test_state, fake_services, create_fake_model_files):
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    base = f"/api/film/projects/{PROJECT}/assets/{asset['id']}"
    for name in ("Raven-closeup-front", "Raven-full-back", "Raven-medium-34-left"):
        client.post(f"{base}/references", json={"image_base64": _png((1, 2, 3)), "name_hint": name})
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.vectors = {"closeup-front": [0.9, 0.436], "full-back": [], "medium-34-left": [0.1, 0.995]}
    dataset = client.post(f"{base}/dataset", json={}).json()
    files = [i["file"] for i in dataset["items"]]
    assert any("closeup-front" in f for f in files)
    assert any("full-back" in f for f in files), "no face to judge (a back view): kept"
    assert not any("medium-34-left" in f for f in files), "a different person: left out"


def test_the_lora_dataset_records_each_face_score(client, test_state, fake_services, create_fake_model_files):
    """Each item carries its face match for the Train screen. MEASURED 2026-10-02:
    weighting the photo, crops and sheet 3x (close angles 2x) scored 0.331 vs 0.354
    unweighted and lost the outfit, so every image trains once per epoch; the
    `repeats` mechanism stays for datasets built by hand."""
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    base = f"/api/film/projects/{PROJECT}/assets/{asset['id']}"
    for name in ("Raven-front-view", "Raven-closeup-front", "Raven-full-back", "Raven-full-profile-left"):
        client.post(f"{base}/references", json={"image_base64": _png((1, 2, 3)), "name_hint": name})
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.vectors = {"front-view": [0.8, 0.6], "closeup-front": [0.9, 0.436], "full-back": [], "full-profile-left": [0.5, 0.866]}
    dataset = client.post(f"{base}/dataset", json={}).json()
    by_name = {i["file"].split("Raven-")[-1].split(".")[0] if "Raven-" in i["file"] else i["file"]: i for i in dataset["items"]}
    assert by_name["front-view"]["face_score"] == 0.8 and by_name["closeup-front"]["face_score"] == 0.9
    assert by_name["full-back"]["face_score"] is None and by_name["full-profile-left"]["face_score"] == 0.5
    # Full-body views carry the outfit: twice per epoch, so the face close-ups do
    # not crowd it out (MEASURED 2026-10-03: with close-ups and no doubling, the
    # trigger alone rendered a bikini at 180-240 steps).
    assert by_name["full-back"]["repeats"] == 2 and by_name["full-profile-left"]["repeats"] == 2
    assert all(i["repeats"] == 1 for i in dataset["items"] if "-full-" not in i["file"])
    photos = [i for i in dataset["items"] if "-photo" in i["file"]]
    assert photos and all(i["face_score"] == 1.0 for i in photos)


def _big_png() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (768, 1024), (80, 70, 60)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_the_lora_dataset_adds_a_face_close_up_of_each_matching_view(client, test_state, fake_services, create_fake_model_files):
    """User, 2026-10-03: "the LoRA faces still aren't consistent and aren't
    styleguide quality". The faces in the full-body and medium views are too
    small at 512 px to teach; each generated view whose face matches the photo
    well (>= 0.6) now also gives a head-and-shoulders crop, kept only when the
    crop itself still matches."""
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    base = f"/api/film/projects/{PROJECT}/assets/{asset['id']}"
    for name in ("Raven-front-view", "Raven-full-34-left", "Raven-full-profile-left", "Raven-medium-front"):
        client.post(f"{base}/references", json={"image_base64": _big_png(), "name_hint": name})
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.vectors = {
        "front-view-facecrop": [0.96, 0.28], "34-left-facecrop": [0.3, 0.954],
        "front-view": [0.8, 0.6], "full-34-left": [0.7, 0.714], "full-profile-left": [0.5, 0.866], "medium-front": [0.75, 0.661],
    }
    matcher.boxes = {"front-view": (330.0, 100.0, 120.0, 150.0), "full-34-left": (330.0, 100.0, 120.0, 150.0), "full-profile-left": (330.0, 100.0, 120.0, 150.0), "medium-front": (350.0, 80.0, 60.0, 80.0)}
    dataset = client.post(f"{base}/dataset", json={}).json()
    crops = {i["file"].split("Raven-")[-1].split(".")[0]: i for i in dataset["items"] if "facecrop" in i["file"]}
    assert set(crops) == {"front-view-facecrop"}, "34-left's crop no longer matches; the profile is under 0.6; medium-front's face is too small"
    assert crops["front-view-facecrop"]["face_score"] == 0.96, "the crop's own match, shown on the Train screen"
    assert sum("front-view" in i["file"] for i in dataset["items"]) == 2, "the view itself stays: it carries the outfit"


def test_the_lora_dataset_judges_a_side_face_by_its_view(client, test_state, fake_services, create_fake_model_files):
    """MEASURED 2026-10-04 (r75, Qwen-Image-Edit-2511 angles of one photo, all
    visibly the same woman): SFace scored the profiles 0.25 and 0.28 and two
    three-quarter views 0.355/0.356 against SAME_PERSON 0.363, so the dataset lost
    four of eight angles. SFace is a frontal-face matcher: a profile keeps its
    score but is not filtered (as a back view); a three-quarter view needs 0.30."""
    create_fake_model_files(include_zit=True)
    asset = _raven(client, test_state, fake_services)
    base = f"/api/film/projects/{PROJECT}/assets/{asset['id']}"
    for name in ("Raven-full-profile-left", "Raven-full-34-left", "Raven-closeup-34-right", "Raven-full-34-right", "Raven-closeup-front"):
        client.post(f"{base}/references", json={"image_base64": _png((1, 2, 3)), "name_hint": name})
    matcher = fake_services.face_matcher
    matcher.enabled = True
    matcher.vectors = {
        "full-profile-left": [0.25, 0.968],  # 0.25: a side face
        "full-34-left": [0.355, 0.935],
        "closeup-34-right": [0.1, 0.995],  # a stranger even for a three-quarter view
        "full-34-right": [0.416, 0.909],
        "closeup-front": [0.33, 0.944],  # a front view below SAME_PERSON: left out
    }
    files = [i["file"] for i in client.post(f"{base}/dataset", json={}).json()["items"]]
    assert any("full-profile-left" in f for f in files)
    assert any("full-34-left" in f for f in files) and any("full-34-right" in f for f in files)
    assert not any("closeup-34-right" in f for f in files)
    assert not any("closeup-front" in f for f in files)
