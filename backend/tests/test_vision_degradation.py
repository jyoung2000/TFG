"""Round 3, task 2 (F-015 and the VLM routing gap).

Round 2 saw `description`/`subjects`/`composition`/`lighting` come back
silently empty with `vision_model: "local-stack"` while a VLM was configured
and Florence-2 was broken ("BartTokenizerFast has no attribute image_token").
Two separate defects:

- The original `microsoft/Florence-2-*` repos carry pre-native-port
  processor/tokenizer configs; transformers' native `Florence2Processor`
  reads `tokenizer.image_token` (processing_florence2.py:121 in the locked
  4.57.6), which those tokenizers do not define. Loading now falls back to
  the checkpoints converted for the native port, and a double failure names
  both attempts.
- When the analysis degrades (no VLM reaches the path, no caption), the
  response must SAY so — the effective provider, why the VLM was skipped,
  and that the result is CLIP-tag-grade — never silently empty fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from services.vision.florence2 import NATIVE_CONVERSIONS, load_with_native_fallback


def _png(path: Path, color=(30, 30, 220)) -> Path:
    Image.new("RGB", (128, 72), color).save(path)
    return path


class TestFlorenceNativeFallback:
    def test_pre_port_repo_falls_back_to_the_native_conversion(self):
        attempts: list[str] = []

        def loader(repo: str) -> str:
            attempts.append(repo)
            if repo.startswith("microsoft/"):
                raise AttributeError("'BartTokenizerFast' object has no attribute 'image_token'")
            return f"loaded:{repo}"

        artifacts, used = load_with_native_fallback("microsoft/Florence-2-large", loader)
        assert used == NATIVE_CONVERSIONS["microsoft/Florence-2-large"]
        assert artifacts == f"loaded:{used}"
        assert attempts == ["microsoft/Florence-2-large", used]

    def test_repo_without_a_known_conversion_propagates_the_original_error(self):
        def loader(repo: str) -> str:
            raise AttributeError("'BartTokenizerFast' object has no attribute 'image_token'")

        with pytest.raises(AttributeError, match="image_token"):
            load_with_native_fallback("MiaoshouAI/Florence-2-large-PromptGen-v2.0", loader)

    def test_double_failure_names_both_repos(self):
        def loader(repo: str) -> str:
            raise OSError(f"cannot reach {repo}")

        with pytest.raises(RuntimeError) as excinfo:
            load_with_native_fallback("microsoft/Florence-2-base", loader)
        message = str(excinfo.value)
        assert "microsoft/Florence-2-base" in message
        assert NATIVE_CONVERSIONS["microsoft/Florence-2-base"] in message

    def test_a_healthy_repo_loads_first_try(self):
        artifacts, used = load_with_native_fallback("microsoft/Florence-2-large", lambda repo: f"ok:{repo}")
        assert used == "microsoft/Florence-2-large" and artifacts == "ok:microsoft/Florence-2-large"


class TestExplicitDegradation:
    """A broken Florence + no usable VLM must announce itself in the response."""

    def test_image_analysis_names_the_skipped_vlm_and_the_missing_caption(self, client, fake_services, tmp_path):
        fake_services.vision.disabled.add("florence")
        client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
        source = _png(tmp_path / "reference.png")
        analysis_id = client.post("/api/image-analysis/import", json={"path": str(source)}).json()["id"]
        payload = client.post(f"/api/image-analysis/{analysis_id}/analyze").json()
        assert payload["vision_model"] == "local-stack"
        notes = payload["vision_notes"]
        assert "VLM skipped" in notes.get("vlm", ""), notes
        assert "off" in notes["vlm"], notes
        assert "CLIP tags only" in notes.get("degraded", ""), notes
        assert "captioning unavailable" in notes["degraded"], notes

    def test_image_analysis_names_an_unconfigured_director_slot(self, client, fake_services, tmp_path):
        """The round-2 shape: vlmProvider left on its "director" default while
        the Director has no usable provider — the reason must say which knob."""
        fake_services.vision.disabled.add("florence")
        client.post("/api/settings", json={"vision": {"vlmProvider": "director"}})
        source = _png(tmp_path / "reference.png")
        analysis_id = client.post("/api/image-analysis/import", json={"path": str(source)}).json()["id"]
        notes = client.post(f"/api/image-analysis/{analysis_id}/analyze").json()["vision_notes"]
        assert "VLM skipped" in notes.get("vlm", ""), notes
        assert "Director" in notes["vlm"], notes

    def test_reproduce_analyze_carries_the_same_degradation_evidence(self, client, fake_services, create_fake_model_files, tmp_path):
        create_fake_model_files(include_zit=True)
        fake_services.vision.disabled.add("florence")
        client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
        source = _png(tmp_path / "reference.png")
        job_id = client.post("/api/reproduce/import", json={"path": str(source)}).json()["id"]
        job = client.post(f"/api/reproduce/{job_id}/analyze").json()
        assert job["vision_model"] == "local-stack"
        assert "VLM skipped" in job["why"].get("vlm", ""), job["why"]
        assert "CLIP tags only" in job["why"].get("caption_degraded", ""), job["why"]
        assert "captioning unavailable" in job["message"], job["message"]
