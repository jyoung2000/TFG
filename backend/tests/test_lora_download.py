"""LoRA downloads from a pasted link (Hugging Face / Civitai / direct URL):
URL parsing is pure and tested exhaustively; the fetch runs behind
`FakeLoraFetcher` as a History `download` job that lands in the registry.
The API key is used once and must never be persisted anywhere."""

from __future__ import annotations

from pathlib import Path

import pytest

from film.training_models import LORA_TARGETS
from services.lora_fetcher import parse_lora_url, safe_lora_filename

FAKE_KEY = "test-placeholder-not-a-real-key"


class TestParseUrl:
    def test_huggingface_blob_becomes_resolve(self):
        source = parse_lora_url("https://huggingface.co/ostris/loras/blob/main/styles/neon.safetensors")
        assert source.kind == "huggingface" and source.filename == "neon.safetensors"
        assert source.download_url == "https://huggingface.co/ostris/loras/resolve/main/styles/neon.safetensors?download=true"

    def test_huggingface_resolve_is_kept(self):
        source = parse_lora_url("https://hf.co/o/r/resolve/main/a.safetensors")
        assert source.download_url.startswith("https://huggingface.co/o/r/resolve/main/a.safetensors")

    def test_huggingface_repo_page_is_rejected_with_guidance(self):
        with pytest.raises(ValueError, match="file itself"):
            parse_lora_url("https://huggingface.co/ostris/loras")
        with pytest.raises(ValueError, match="safetensors"):
            parse_lora_url("https://huggingface.co/o/r/blob/main/model.ckpt")

    def test_civitai_model_page_with_and_without_version(self):
        source = parse_lora_url("https://civitai.com/models/12345/neon-style?modelVersionId=67890")
        assert source.kind == "civitai" and source.civitai_model_id == "12345" and source.civitai_version_id == "67890"
        bare = parse_lora_url("https://www.civitai.com/models/12345")
        assert bare.civitai_model_id == "12345" and bare.civitai_version_id == ""

    def test_civitai_direct_download_link(self):
        source = parse_lora_url("https://civitai.com/api/download/models/67890")
        assert source.civitai_version_id == "67890" and source.download_url.endswith("/67890")

    def test_direct_safetensors_and_rejections(self):
        assert parse_lora_url("https://example.com/files/thing.safetensors").kind == "direct"
        for bad in ("http://civitai.com/models/1", "https://example.com/thing.zip", "not a url", "https://civitai.com/images/9"):
            with pytest.raises(ValueError):
                parse_lora_url(bad)

    def test_safe_filename(self):
        assert safe_lora_filename("../..\\evil name!.safetensors") == "evil name-.safetensors"
        assert safe_lora_filename("model.ckpt") == ""
        assert safe_lora_filename("ok-1.0.safetensors") == "ok-1.0.safetensors"


def _download(client, url: str, **overrides) -> dict:
    payload = {"url": url, "target": "z_image", "trigger": "neon_v1", **overrides}
    response = client.post("/api/training/loras/download", json=payload)
    assert response.status_code == 200, response.text
    return client.get(f"/api/jobs/{response.json()['job_id']}").json()["job"]


class TestDownloadFlow:
    def test_huggingface_link_lands_in_registry_with_progress(self, client, fake_services, test_state):
        job = _download(client, "https://huggingface.co/o/r/blob/main/neon.safetensors", api_key=FAKE_KEY)
        assert job["status"] == "complete" and job["provider"] == "huggingface" and job["kind"] == "download"
        assert job["title"] == "LoRA · neon.safetensors" and job["progress"] == 100
        assert job["inputs"]["lora_url"].startswith("https://huggingface.co/")
        # The key was used for the request and stored nowhere.
        assert fake_services.lora_fetcher.resolves[0][1] == FAKE_KEY
        assert FAKE_KEY not in str(job)
        (path,) = [o["path"] for o in job["outputs"]]
        assert Path(path).read_bytes() == fake_services.lora_fetcher.content
        assert Path(path).parent.name == LORA_TARGETS["z_image"] and Path(path).name == "neon.safetensors"
        loras = client.get("/api/training/loras").json()["loras"]
        assert [l["name"] for l in loras] == ["neon"] and loras[0]["trigger"] == "neon_v1" and loras[0]["imported"] is True
        # Compatible pickers see it immediately.
        assert client.get("/api/training/loras", params={"model": "z_image_turbo"}).json()["loras"]
        # The staging folder is gone.
        assert not (Path(path).parent / ".downloading").exists()

    def test_civitai_page_resolves_a_filename(self, client, fake_services):
        fake_services.lora_fetcher.civitai_filename = "mara-style-v2.safetensors"
        job = _download(client, "https://civitai.com/models/555?modelVersionId=777", name="Mara style")
        assert job["status"] == "complete" and job["provider"] == "civitai"
        source = fake_services.lora_fetcher.resolves[0][0]
        assert source.civitai_model_id == "555" and source.civitai_version_id == "777"
        entry = client.get("/api/training/loras").json()["loras"][0]
        assert entry["name"] == "Mara style" and entry["file"].endswith("mara-style-v2.safetensors")

    def test_redownload_replaces_the_entry_not_duplicates(self, client):
        _download(client, "https://huggingface.co/o/r/blob/main/neon.safetensors")
        _download(client, "https://huggingface.co/o/r/blob/main/neon.safetensors", trigger="neon_v2")
        loras = client.get("/api/training/loras").json()["loras"]
        assert len(loras) == 1 and loras[0]["trigger"] == "neon_v2"

    def test_bad_url_is_refused_before_any_job(self, client):
        response = client.post("/api/training/loras/download", json={"url": "https://example.com/notalora.zip"})
        assert response.status_code == 400 and "safetensors" in response.json()["error"]
        assert client.post("/api/training/loras/download", json={"url": "https://civitai.com/models/1", "target": "nope"}).status_code == 400
        assert client.get("/api/jobs", params={"kind": "download"}).json()["jobs"] == []

    def test_resolve_and_download_failures_fail_the_job_honestly(self, client, fake_services):
        fake_services.lora_fetcher.fail_resolve = "Civitai answered 404 for models/555"
        job = _download(client, "https://civitai.com/models/555")
        assert job["status"] == "failed" and "404" in job["error"]
        fake_services.lora_fetcher.fail_resolve = ""
        fake_services.lora_fetcher.fail_download = "The host refused the download (401/403)"
        job = _download(client, "https://huggingface.co/o/r/blob/main/neon.safetensors")
        assert job["status"] == "failed" and "401/403" in job["error"]
        assert client.get("/api/training/loras").json()["loras"] == []

    def test_wrong_resolved_filetype_fails(self, client, fake_services):
        fake_services.lora_fetcher.resolve_to = "actually-a-checkpoint.ckpt"
        job = _download(client, "https://civitai.com/api/download/models/9")
        assert job["status"] == "failed" and "not a .safetensors" in job["error"]

    def test_cancel_mid_download_leaves_nothing_behind(self, client, fake_services, test_state):
        fake_services.lora_fetcher.cancel_mid_download = True
        job = _download(client, "https://huggingface.co/o/r/blob/main/neon.safetensors")
        assert job["status"] == "cancelled"
        assert client.get("/api/training/loras").json()["loras"] == []
        folder = Path(test_state.config.settings_file).parent / "loras" / LORA_TARGETS["z_image"]
        assert not folder.exists() or list(folder.iterdir()) == []
        # Once finished, the canceller no longer claims the job.
        assert test_state.training.cancel_lora_download(job["id"]) is False
