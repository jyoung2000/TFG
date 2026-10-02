"""Multi-angle character shots good enough to train a LoRA, from the Assets tab.

Asked 2026-10-01: the camera should generate accurate multiple-angle shots
of high enough quality to train a LoRA, and the 3D composer should work in
the Assets tab to make consistent assets and character LoRAs.

Found: the reference sheet rendered each view text-to-image with a shared
seed and no image conditioning, so the person drifted between angles; and
nothing turned an asset's images into a training dataset. MEASURED with the
installed FLUX.2 Klein 4B composing from the asset's reference image
("image_refs"): front, three-quarter, profile and back kept the face, hair
and outfit, ~7.6 s per angle on the RTX 4070.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from tests.test_training import PROJECT

FLUX2 = {"id": "flux2_klein_4b", "name": "Flux 2 Klein 4B", "installed": True}


def _png(color: tuple[int, int, int]) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _character(client, test_state, fake_services) -> dict:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara", "appearance": "black hair", "wardrobe": "black leather jacket"}).json()["asset"]
    return client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": _png((200, 40, 40)), "name_hint": "front"}).json()["asset"]


def _image_params(fake_services) -> list[dict]:
    return [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" in m[0]["params"]]


class TestAngleSet:
    def test_each_angle_is_composed_from_the_composer_guide_and_the_identity(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        asset = _character(client, test_state, fake_services)
        identity = asset["reference_images"][0]
        shots = [
            {"name": "profile-left", "view": "seen in profile from her left side, full body", "guide_base64": _png((90, 90, 90))},
            {"name": "back", "view": "seen from behind, full body", "guide_base64": _png((60, 60, 60))},
        ]
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": shots, "seed": 5})
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["reference_paths"]) == 2
        assert len(result["asset"]["reference_images"]) == 3, "the angles join the asset's references"
        params = _image_params(fake_services)
        assert [p["model_type"] for p in params] == ["flux2_klein_4b"] * 2
        for p in params:
            assert p["video_prompt_type"] == "KI", "the guide is the scene, the identity image the person"
            refs = [Path(r) for r in p["image_refs"]]
            assert len(refs) == 2 and refs[1].name == Path(identity).name
        assert "profile from her left side" in params[0]["prompt"] and "black leather jacket" in params[0]["prompt"]

    def test_without_a_guide_the_angle_comes_from_the_identity_alone(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        asset = _character(client, test_state, fake_services)
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": [{"name": "front", "view": "seen from the front"}]})
        assert response.status_code == 200, response.text
        params = _image_params(fake_services)[-1]
        assert params["video_prompt_type"] == "I" and len(params["image_refs"]) == 1

    def test_an_asset_without_an_image_is_told_what_it_needs(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True
        fake_services.wangp_bridge.definitions.append(FLUX2)
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Nobody"}).json()["asset"]
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": [{"name": "front", "view": "front"}]})
        assert response.status_code == 400 and "reference image" in response.text

    def test_the_reference_sheet_now_keeps_the_person_from_their_image(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        asset = _character(client, test_state, fake_services)
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/reference-sheet", json={"views": ["front view", "back view"], "seed": 9})
        assert response.status_code == 200, response.text
        params = _image_params(fake_services)
        assert len(params) == 2 and all(p.get("image_refs") for p in params), "each view conditioned on the asset's image"


    def test_a_character_view_frames_the_whole_figure_head_to_feet(self, client, test_state, fake_services, create_fake_model_files):
        # QA pass 2026-10-02 (a standing full-length photo): every view of the
        # sheet cut off the head and the feet - a 3:4 frame and "full body"
        # alone made the model fill the frame with the torso. A LoRA trained on
        # faceless views learns no face.
        create_fake_model_files(include_zit=True)
        asset = _character(client, test_state, fake_services)
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/reference-sheet", json={"views": ["front view"], "seed": 9})
        assert response.status_code == 200, response.text
        params = _image_params(fake_services)[-1]
        width, height = (int(v) for v in params["resolution"].split("x"))
        assert height / width >= 1.7, "a standing figure needs a tall frame"
        assert "head to feet" in params["prompt"] and "whole head" in params["prompt"]

class TestAssetStudioAndDataset:
    def test_an_asset_keeps_its_3d_studio_scene(self, client, test_state, fake_services):
        asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Mara"}).json()["asset"]
        composition = {"objects": [{"id": "fig-1", "name": "Mara", "type": "figure", "pose": {"l_arm": [0, 0, 40]}}], "duration_seconds": 3.0}
        saved = client.put(f"/api/film/projects/{PROJECT}/assets/{asset['id']}", json={"composition": composition}).json()["asset"]
        assert saved["composition"]["objects"][0]["pose"]["l_arm"] == [0, 0, 40]

    def test_an_assets_images_become_a_character_dataset_with_its_trigger(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        asset = _character(client, test_state, fake_services)
        client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/angle-set", json={"shots": [{"name": "front", "view": "front"}, {"name": "back", "view": "back"}]})
        response = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/dataset", json={})
        assert response.status_code == 200, response.text
        dataset = response.json()
        assert dataset["preset"] == "character" and dataset["trigger"] == "mara"
        assert len(dataset["items"]) == 3
