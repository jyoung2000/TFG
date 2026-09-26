"""Contract tests for the native image-to-prompt-to-render loop."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from PIL import Image
from film.llm_providers import LLMReply
from api_types import GenerateImageResponse


def _png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (80, 48)) -> None:
    Image.new("RGB", size, color).save(path)


class _Vision:
    name = "openai_compatible"
    model = "qwen2.5vl:7b"
    def chat(self, messages, **kwargs):
        # The discrepancy round sees TWO images; the first vision pass sees one.
        if len(messages[-1].images) == 2:
            return LLMReply(text='{"differences":"The candidate is too blue; use warm red","revised_prompt":"A centered warm red square on a muted background"}', tool_calls=[], model=self.model)
        return LLMReply(text='{"description":"A centered warm red square on a muted background","prompt":"A centered red square, flat light, muted background","subjects":"one red square","composition":"centered","colors":"warm red and gray","lighting":"flat","style":"minimal","confidence":0.9}', tool_calls=[], model=self.model)


def test_image_recreation_analyze_render_refine_and_best_retention(client, test_state, tmp_path, monkeypatch):
    source = tmp_path / "reference.png"
    _png(source, (230, 45, 45))
    monkeypatch.setattr(test_state.film_director, "optional_provider", lambda role: _Vision())
    result = client.post("/api/image-analysis/import", json={"path": str(source)})
    assert result.status_code == 200, result.text
    job = result.json()
    assert (job["width"], job["height"]) == (80, 48)
    assert job["source_path"] == "reference.png"
    image = client.get(f"/api/image-analysis/{job['id']}/media", params={"path":"reference.png"})
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/png")
    assert client.get(f"/api/image-analysis/{job['id']}/media", params={"path":"../settings.json"}).status_code == 400
    analyzed = client.post(f"/api/image-analysis/{job['id']}/analyze")
    assert analyzed.status_code == 200, analyzed.text
    assert "red square" in analyzed.json()["prompt"]
    assert analyzed.json()["vision_model"] == "qwen2.5vl:7b"
    render_number = 0
    def render(req):
        nonlocal render_number
        render_number += 1
        output = test_state.config.outputs_dir / f"render-{render_number}.png"
        _png(output, (200, 45, 45) if render_number == 1 else (0, 0, 255))
        return GenerateImageResponse(status="complete", image_paths=[str(output)])
    monkeypatch.setattr(test_state.image_generation, "generate", render)
    first = client.post(f"/api/image-analysis/{job['id']}/render", json={"candidates":1,"rounds":1})
    assert first.status_code == 200, first.text
    best = first.json()["best_candidate_id"]
    assert best and len(first.json()["candidates"]) == 1
    second = client.post(f"/api/image-analysis/{job['id']}/refine", json={"candidates":1})
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["best_candidate_id"] == best
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][1]["score"] < payload["candidates"][0]["score"]
    assert payload["revisions"][-1]["differences"]
    assert client.get(f"/api/image-analysis/{job['id']}").status_code == 200
    assert len(client.get("/api/image-analysis").json()["analyses"]) == 1


def test_bad_image_and_bounded_budget(client, test_state, tmp_path, monkeypatch):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert client.post("/api/image-analysis/import", json={"path":str(bad)}).status_code == 400
    good = tmp_path / "good.png"
    _png(good, (4, 5, 6))
    imported = client.post("/api/image-analysis/import", json={"path":str(good)}).json()
    # Without any vision model (local stack off, no VLM) there is nothing to analyse with.
    client.post("/api/settings", json={"vision": {"enabled": False, "vlmProvider": "off"}})
    assert client.post(f"/api/image-analysis/{imported['id']}/analyze").status_code == 400
    client.post("/api/settings", json={"vision": {"enabled": True, "vlmProvider": "director"}})
    assert client.post(f"/api/image-analysis/{imported['id']}/render",json={"candidates":9,"rounds":9}).status_code == 422
    assert client.post("/api/image-analysis/import",json={"path":"relative.png"}).status_code == 400
    assert client.get("/api/image-analysis/no-such-id").status_code == 400


def test_comparison_is_spatial_not_just_average_color():
    from film.image_recreation import score_images
    ref = Image.new("RGB", (64, 64), "#191928")
    good = ref.copy()
    bad = ref.copy()
    for y in range(0, 32):
        for x in range(0, 32):
            ref.putpixel((x,y), (255,0,0))
            good.putpixel((x,y), (230,0,0))
            bad.putpixel((x+32,y+32), (255,0,0))
    assert score_images(ref, good) > score_images(ref, bad)
    assert score_images(ref, ref) == 1.0


def test_refine_accepts_structured_differences_from_small_vision_models():
    """qwen2.5vl:7b returns differences as a nested object; that must still refine."""
    from film.image_recreation import describe_differences

    structured = {
        "object_count": {"reference": {"globe": 1}, "candidate": {"globe": 1}},
        "position": {"reference": {"globe": "centered"}, "candidate": {"globe": "slightly off-center to the right"}},
        "lighting": {"reference": {"globe": "even lighting"}, "candidate": {"globe": "slightly dimmer lighting"}},
    }
    text = describe_differences(structured)
    assert "position" in text and "centered" in text and "off-center" in text
    assert "lighting" in text and "dimmer" in text
    # identical sub-fields are not reported as differences
    assert "object_count" not in text
    assert describe_differences("  plain text  ") == "plain text"
    assert describe_differences(["a", "b"]) == "a; b"
    assert describe_differences(None) == ""
