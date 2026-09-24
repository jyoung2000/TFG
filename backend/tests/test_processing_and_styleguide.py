from __future__ import annotations

from pathlib import Path

from PIL import Image
from starlette.testclient import TestClient

from film.llm_providers import LLMReply


class _StyleVision:
    model = "qwen2.5vl:7b"

    def chat(self, messages, **kwargs):
        assert len(messages[-1].images) == 1
        return LLMReply(
            text='''{"key_traits":["brass body","round face"],"color_palette":["#b88a42","charcoal"],"mood":"weathered","recommended_prompt":"A worn brass compass","appearance":"Circular brass casing","wardrobe":"not applicable","description":"An antique compass"}''',
            tool_calls=[], model=self.model,
        )


def _png_base64() -> str:
    import base64
    import io
    image = Image.new("RGB", (32, 24), (150, 100, 50))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_asset_style_guide_uses_reference_and_persists(client, test_state, monkeypatch):
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _StyleVision())
    create = client.post("/api/film/projects/style-test/assets", json={"kind":"prop","name":"Compass"})
    assert create.status_code == 200
    asset_id = create.json()["asset"]["id"]
    added = client.post(f"/api/film/projects/style-test/assets/{asset_id}/references", json={"image_base64":_png_base64(),"name_hint":"compass"})
    assert added.status_code == 200
    result = client.post(f"/api/film/projects/style-test/assets/{asset_id}/style-guide")
    assert result.status_code == 200, result.text
    asset = result.json()["asset"]
    assert asset["style_guide"]["key_traits"] == ["brass body", "round face"]
    assert asset["style_guide"]["recommended_prompt"] == "A worn brass compass"
    assert asset["appearance"] == "Circular brass casing"
    saved = client.get("/api/film/projects/style-test").json()["project"]["assets"][0]
    assert saved["style_guide"]["mood"] == "weathered"


def test_asset_style_guide_requires_reference_image(client, test_state, monkeypatch):
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _StyleVision())
    client.post("/api/film/projects/style-empty/assets", json={"kind":"character","name":"Mara"})
    created = client.get("/api/film/projects/style-empty").json()["project"]["assets"][0]
    result = client.post(f"/api/film/projects/style-empty/assets/{created['id']}/style-guide")
    assert result.status_code == 400


def test_asset_style_guide_normalizes_small_model_json_shapes(client, test_state, monkeypatch):
    class OddVision(_StyleVision):
        def chat(self, messages, **kwargs):
            return LLMReply(
                text='{"key_traits":"square body","color_palette":["brass", "black"],"mood":["quiet","worn"],"recommended_prompt":["A brass box"]}',
                tool_calls=[], model=self.model,
            )

    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: OddVision())
    client.post("/api/film/projects/shape-test/assets", json={"kind":"prop","name":"Box"})
    asset = client.get("/api/film/projects/shape-test").json()["project"]["assets"][0]
    client.post(f"/api/film/projects/shape-test/assets/{asset['id']}/references", json={"image_base64":_png_base64(),"name_hint":"box"})
    result = client.post(f"/api/film/projects/shape-test/assets/{asset['id']}/style-guide")
    assert result.status_code == 200, result.text
    guide = result.json()["asset"]["style_guide"]
    assert guide["key_traits"] == ["square body"]
    assert guide["mood"] == "quiet; worn"
    assert guide["recommended_prompt"] == "A brass box"


def test_generation_queue_returns_recent_media(client, test_state):
    import time
    output = test_state.config.outputs_dir / "queue-smoke.png"
    Image.new("RGB", (16,16), (10,20,30)).save(output)
    result = client.get("/api/generation/queue")
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["active"]["status"] == "idle"
    assert payload["recent"][0]["path"] == str(output)
    assert payload["recent"][0]["type"] == "image"
    assert payload["recent"][0]["size_mb"] > 0


def test_asset_style_guide_prompt_is_reused_for_future_generation():
    from film.film_models import FilmAsset, FilmAssetStyleGuide, FilmProject, FilmScene, FilmShot, ShotCharacter
    from film.film_prompt import synthesize_prompt

    asset = FilmAsset(
        kind="character", name="Mara", appearance="short dark hair",
        style_guide=FilmAssetStyleGuide(recommended_prompt="orange harness, cold blue rim light"),
    )
    project = FilmProject(id="style-project", assets=[asset])
    scene = FilmScene(title="Interior")
    shot = FilmShot(title="Mara", characters=[ShotCharacter(asset_id=asset.id)], action="checks the radio")
    prompt = synthesize_prompt(project, scene, shot)
    assert "orange harness, cold blue rim light" in prompt
