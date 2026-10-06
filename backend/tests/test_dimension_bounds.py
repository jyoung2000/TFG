"""Round 3, F-034: absurd dimensions must be refused before any CUDA work.

Round 2 sent width=height=99999 to POST /api/generate-image and got a raw
500 CUDA OOM after the card had already tried; every other VRAM path in the
app refuses politely up front.
"""

from __future__ import annotations


class TestImageDimensionBounds:
    def test_absurd_dimensions_get_a_400_not_a_render_attempt(self, client, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        r = client.post("/api/generate-image", json={"prompt": "test", "width": 99999, "height": 99999})
        assert r.status_code == 400, r.text
        assert "4096" in r.json()["error"]
        assert fake_services.image_generation_pipeline.generate_calls == []

    def test_tiny_dimensions_are_refused_too(self, client, fake_services, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        r = client.post("/api/generate-image", json={"prompt": "test", "width": 8, "height": 8})
        assert r.status_code == 400, r.text
        assert fake_services.image_generation_pipeline.generate_calls == []

    def test_the_top_of_the_range_still_renders(self, client, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        r = client.post("/api/generate-image", json={"prompt": "test", "width": 4096, "height": 64})
        assert r.status_code == 200, r.text
