"""A live preview of the photo as the 3D model is edited.

Asked 2026-10-01 (with a screenshot of the composer: the Woman's left leg
raised in 3D while the photo still showed her standing): when the user
edits the 3D model, show the image as they edited it, keep the original
photo in view, and keep the preview live as they edit.

The composer sends the viewfinder (the posed mannequin) with the original
photo; FLUX.2 composes the person from the photo into the pose and framing
of the mannequin. Previews are throwaway: no History job, nothing added to
the project or the asset.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from tests.test_asset_angles import FLUX2, _png
from tests.test_training import PROJECT


def _photo(client) -> str:
    asset = client.post(f"/api/film/projects/{PROJECT}/assets", json={"kind": "character", "name": "Woman"}).json()["asset"]
    asset = client.post(f"/api/film/projects/{PROJECT}/assets/{asset['id']}/references", json={"image_base64": _png((30, 30, 30)), "name_hint": "photo"}).json()["asset"]
    return asset["reference_images"][0]


def _wangp(test_state, fake_services, *, flux: bool = True) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    if flux:
        fake_services.wangp_bridge.definitions.append(FLUX2)


class TestPosePreview:
    def test_the_edited_pose_is_rendered_from_the_viewfinder_and_the_photo(self, client, test_state, fake_services, create_fake_model_files, tmp_path):
        create_fake_model_files(include_zit=True)
        _wangp(test_state, fake_services)
        photo = _photo(client)
        outputs = tmp_path / "outputs"
        outputs_before = {f for f in outputs.rglob("*") if f.is_file()}
        jobs_before = len(client.get("/api/jobs").json()["jobs"])
        project_before = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        response = client.post(
            f"/api/film/projects/{PROJECT}/preview-render",
            json={"guide_base64": _png((200, 90, 40)), "reference_path": photo, "prompt": "a woman in a black leather jacket", "width": 576, "height": 1024},
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["image"].startswith("data:image/")
        Image.open(io.BytesIO(base64.b64decode(preview["image"].split(",", 1)[1]))).verify()
        params = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" in m[0]["params"]][-1]
        assert params["model_type"] == "flux2_klein_4b" and params["video_prompt_type"] == "KI"
        assert len(params["image_refs"]) == 2, "the viewfinder first, then the photo"
        assert "black leather jacket" in params["prompt"]
        # Throwaway: no History entry, the project untouched, and no image
        # left in the outputs folder (MEASURED: every live preview left one).
        assert len(client.get("/api/jobs").json()["jobs"]) == jobs_before
        assert {f for f in outputs.rglob("*") if f.is_file()} == outputs_before
        assert client.get(f"/api/film/projects/{PROJECT}").json()["project"]["assets"] == project_before["assets"]

    def test_the_edit_is_spelled_out_and_the_photo_keeps_its_background(self, client, test_state, fake_services, create_fake_model_files):
        # Live in r34: shown only the mannequin, FLUX.2 copied the photo's pose
        # unchanged; told the edit in words it followed it, but took the
        # mannequin's grey studio for the background until told not to.
        create_fake_model_files(include_zit=True)
        _wangp(test_state, fake_services)
        photo = _photo(client)
        pose = "the person's left arm (on the right side of the picture) raised straight up above the head"
        response = client.post(
            f"/api/film/projects/{PROJECT}/preview-render",
            json={"guide_base64": _png((200, 90, 40)), "reference_path": photo, "prompt": "a woman", "pose": pose},
        )
        assert response.status_code == 200, response.text
        prompt = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_mode" in m[0]["params"]][-1]["prompt"]
        assert pose in prompt
        assert prompt.index(pose) < prompt.index("a woman"), "the edit leads, ahead of the shot description"
        assert "not the grey 3D studio" in prompt

    def test_a_photo_outside_the_project_is_refused(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        _wangp(test_state, fake_services)
        response = client.post(f"/api/film/projects/{PROJECT}/preview-render", json={"guide_base64": _png((1, 2, 3)), "reference_path": "../../secrets.png"})
        assert response.status_code in (400, 404)

    def test_without_a_model_that_composes_it_says_what_is_missing(self, client, test_state, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        _wangp(test_state, fake_services, flux=False)
        photo = _photo(client)
        response = client.post(f"/api/film/projects/{PROJECT}/preview-render", json={"guide_base64": _png((1, 2, 3)), "reference_path": photo})
        assert response.status_code == 400 and "FLUX.2" in response.text
