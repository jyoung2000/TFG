"""The app-wide style library (user, 2026-10-05: "Add a new option on the home menu to
save style from image and in the playground, image and video generator add a tab for
style to let the user set the style for the image / video")."""

from __future__ import annotations

import json
from pathlib import Path

from api_types import GenerateVideoRequest, GenerateVideoResponse
from film.llm_providers import LLMReply
from film.style_transfer import USO_MODEL, USO_STEPS
from tests.test_asset_angles import FLUX2, _image_params, _png
from tests.test_style_transfer import USO

WATERCOLOR = "watercolor illustration, thin sepia ink outlines, soft washes, sage and sky-blue palette"


class _Reader:
    model = "qwen2.5vl:7b"

    def __init__(self) -> None:
        self.images = 0

    def chat(self, messages, **kwargs):
        self.images = len(messages[-1].images)
        return LLMReply(text=json.dumps({"medium": "watercolor", "line_work": "thin sepia ink", "color_palette": ["sage"],
                                         "recommended_prompt": WATERCOLOR}), tool_calls=[], model=self.model)


def _save(client, test_state, monkeypatch, pictures: int = 2) -> dict:
    reader = _Reader()
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: reader)
    response = client.post("/api/styles", json={"name": "Seaside Watercolor", "images_base64": [_png((10 * i, 90, 120)) for i in range(pictures)]})
    assert response.status_code == 200, response.text
    return response.json()


def _local(test_state, fake_services, *models: dict) -> None:
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.extend(models)


def test_a_style_is_saved_from_pictures_and_read_by_the_vision_ai(client, test_state, monkeypatch):
    style = _save(client, test_state, monkeypatch, pictures=4)
    assert style["style_prompt"] == "watercolor, thin sepia ink, palette of sage", "built from the facets, never the subject"
    assert style["style_guide"]["recommended_prompt"] == WATERCOLOR and style["style_guide"]["key_traits"][:2] == ["medium: watercolor", "line work: thin sepia ink"]
    assert len(style["images"]) == 4
    listed = client.get("/api/styles").json()["styles"]
    assert [s["id"] for s in listed] == [style["id"]]
    picture = client.get(f"/api/styles/{style['id']}/images/0")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
    assert client.delete(f"/api/styles/{style['id']}").status_code == 200
    assert client.get("/api/styles").json()["styles"] == []
    assert client.get(f"/api/styles/{style['id']}/images/0").status_code == 404


def test_without_a_vision_ai_the_pictures_alone_are_the_style(client, test_state, monkeypatch):
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: None)
    response = client.post("/api/styles", json={"name": "Ink", "images_base64": [_png((1, 2, 3))]})
    assert response.status_code == 200 and response.json()["style_prompt"] == ""
    assert client.post("/api/styles", json={"name": "Bad", "images_base64": ["bm90IGFuIGltYWdl"]}).status_code == 400
    assert client.post("/api/styles", json={"name": "", "images_base64": [_png((1, 2, 3))]}).status_code == 400


def test_an_image_in_a_style_is_drawn_by_uso_from_its_pictures(client, test_state, fake_services, create_fake_model_files, monkeypatch):
    create_fake_model_files(include_zit=True)
    _local(test_state, fake_services, FLUX2, USO)
    style = _save(client, test_state, monkeypatch)
    before = len(_image_params(fake_services))
    response = client.post("/api/generate-image", json={"prompt": "a lighthouse at dusk", "width": 1024, "height": 576, "styleId": style["id"]})
    assert response.status_code == 200, response.text
    (params,) = _image_params(fake_services)[before:]
    assert params["model_type"] == USO_MODEL and params["video_prompt_type"] == "IJ", "style pictures only; the canvas is the request size"
    assert len(params["image_refs"]) == 2 and params["num_inference_steps"] == USO_STEPS
    assert params["prompt"].startswith("a lighthouse at dusk. Art style: watercolor, thin sepia ink")


def test_without_uso_the_image_is_rendered_then_redrawn_by_klein(client, test_state, fake_services, create_fake_model_files, monkeypatch):
    create_fake_model_files(include_zit=True)
    _local(test_state, fake_services, FLUX2)
    style = _save(client, test_state, monkeypatch)
    before = len(_image_params(fake_services))
    response = client.post("/api/generate-image", json={"prompt": "a lighthouse at dusk", "styleId": style["id"]})
    assert response.status_code == 200, response.text
    render, redraw = _image_params(fake_services)[before:]
    assert "Art style: watercolor, thin sepia ink" in render["prompt"]
    assert redraw["model_type"] == "flux2_klein_4b" and redraw["video_prompt_type"] == "KI" and len(redraw["image_refs"]) == 2


def test_a_video_in_a_style_starts_on_a_frame_drawn_in_it(client, test_state, fake_services, create_fake_model_files, monkeypatch):
    create_fake_model_files(include_zit=True)
    _local(test_state, fake_services, FLUX2, USO)
    style = _save(client, test_state, monkeypatch)
    seen: list[GenerateVideoRequest] = []

    def capture(req: GenerateVideoRequest) -> GenerateVideoResponse:
        seen.append(req)
        return GenerateVideoResponse(status="complete", video_path="x.mp4")

    monkeypatch.setattr(test_state.video_generation, "generate", capture)
    before = len(_image_params(fake_services))
    response = client.post("/api/generate", json={"prompt": "waves on the rocks", "aspectRatio": "9:16", "styleId": style["id"]})
    assert response.status_code == 200, response.text
    (frame,) = _image_params(fake_services)[before:]
    assert frame["model_type"] == USO_MODEL and frame["resolution"] == "576x1024"
    (req,) = seen
    assert req.imagePath and Path(req.imagePath).is_file(), "the video starts on the styled frame"
    assert "Art style: watercolor, thin sepia ink" in req.prompt and req.styleId == ""


def test_a_video_from_an_image_starts_on_that_image_redrawn(client, test_state, fake_services, create_fake_model_files, monkeypatch, tmp_path: Path):
    create_fake_model_files(include_zit=True)
    _local(test_state, fake_services, FLUX2, USO)
    style = _save(client, test_state, monkeypatch)
    seen: list[GenerateVideoRequest] = []

    def capture(req: GenerateVideoRequest) -> GenerateVideoResponse:
        seen.append(req)
        return GenerateVideoResponse(status="complete", video_path="x.mp4")

    monkeypatch.setattr(test_state.video_generation, "generate", capture)
    from PIL import Image
    start = tmp_path / "start.png"
    Image.new("RGB", (640, 360), (5, 6, 7)).save(start)
    before = len(_image_params(fake_services))
    client.post("/api/generate", json={"prompt": "waves", "imagePath": str(start), "styleId": style["id"]})
    (redraw,) = _image_params(fake_services)[before:]
    assert redraw["video_prompt_type"] == "KI" and Path(redraw["image_refs"][0]).name == "start.png"
    assert seen[0].imagePath != str(start)
