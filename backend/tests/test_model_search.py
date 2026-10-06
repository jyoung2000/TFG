"""ModelSearchHandler: Hugging Face search, repo file listing and direct-link downloads."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, cast

import pytest

from _routes._errors import HTTPError
from handlers.model_search_handler import ModelSearchHandler
from services.hub_search import HubFile, HubModel
from services.job_store.job_models import Job
from tests.fakes.fake_hub_api import FakeHubApi
from tests.fakes.services import FakeHTTPClient, FakeModelDownloader, FakeResponse, FakeTaskRunner


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.progress_calls: list[tuple[str, float, str]] = []
        self.outputs: dict[str, list[str]] = {}

    def start(self, kind: Any, *, title: str = "", model: str = "", inputs: dict[str, Any] | None = None) -> Job:
        job = Job(kind=kind, status="running", title=title)
        self.jobs[job.id] = job
        return job

    def progress(self, job_id: str, progress: float, phase: str = "") -> None:
        self.progress_calls.append((job_id, progress, phase))

    def complete(self, job_id: str, outputs: Any = ()) -> Job:
        self.outputs[job_id] = list(outputs)
        self.jobs[job_id].status = "complete"
        return self.jobs[job_id]

    def fail(self, job_id: str, error: str) -> Job:
        self.jobs[job_id].status = "failed"
        self.jobs[job_id].error = error
        return self.jobs[job_id]

    def mark_cancelled(self, job_id: str, *, reason: str = "Cancelled") -> Job:
        self.jobs[job_id].status = "cancelled"
        return self.jobs[job_id]


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.hub = FakeHubApi()
        self.downloader = FakeModelDownloader()
        self.http = FakeHTTPClient()
        self.jobs = FakeJobs()
        self.runner = FakeTaskRunner()
        self.ckpts = tmp_path / "ckpts"
        self.loras = tmp_path / "loras"
        self.handler = ModelSearchHandler(
            cast(Any, None),
            RLock(),
            hub=self.hub,
            downloader=self.downloader,
            http=self.http,
            jobs=cast(Any, self.jobs),
            task_runner=self.runner,
            destinations={"checkpoints": self.ckpts, "loras": self.loras},
        )

    def only_job(self) -> Job:
        assert len(self.jobs.jobs) == 1
        return next(iter(self.jobs.jobs.values()))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _model(repo: str, downloads: int = 1) -> HubModel:
    return HubModel(repo_id=repo, downloads=downloads, likes=2, pipeline_tag="text-to-image", license="mit", last_modified="2026-01-01")


# ---- search -----------------------------------------------------------------


def test_search_empty_query_returns_nothing_without_calling_hub(rig: Rig) -> None:
    rig.hub.models = [_model("a/b")]
    assert rig.handler.search("   ") == []
    assert rig.hub.search_calls == []


def test_search_filters_by_query_and_applies_limit(rig: Rig) -> None:
    rig.hub.models = [_model("org/flux-dev"), _model("org/flux-schnell"), _model("org/sdxl")]
    result = rig.handler.search("flux", limit=1)
    assert [m.repo_id for m in result] == ["org/flux-dev"]
    assert rig.hub.search_calls == [("flux", 1)]


def test_search_caps_limit_at_50_and_floors_at_1(rig: Rig) -> None:
    rig.hub.models = [_model("org/x")]
    rig.handler.search("x", limit=500)
    rig.handler.search("x", limit=0)
    assert rig.hub.search_calls == [("x", 50), ("x", 1)]


# ---- files ------------------------------------------------------------------


def test_files_keeps_only_weights_largest_first(rig: Rig) -> None:
    rig.hub.files = {
        "org/m": [
            HubFile("README.md", 10),
            HubFile("small.safetensors", 100),
            HubFile("config.json", 5),
            HubFile("big/model.gguf", 5000),
            HubFile("mid.ckpt", 900),
        ]
    }
    assert [f.path for f in rig.handler.files("org/m")] == ["big/model.gguf", "mid.ckpt", "small.safetensors"]


def test_files_requires_repo(rig: Rig) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.files(" ")
    assert exc.value.status_code == 400


# ---- download: Hugging Face -------------------------------------------------


def test_hf_resolve_url_goes_through_model_downloader(rig: Rig) -> None:
    job_id = rig.handler.download(
        url="https://huggingface.co/org/repo/resolve/main/sub/model.safetensors?download=true",
        destination="checkpoints",
    )
    assert rig.downloader.calls[0]["repo_id"] == "org/repo"
    assert rig.downloader.calls[0]["filename"] == "sub/model.safetensors"
    assert rig.downloader.calls[0]["local_dir"] == str(rig.ckpts)
    assert rig.jobs.jobs[job_id].status == "complete"
    assert rig.jobs.outputs[job_id] == [str(rig.ckpts / "sub" / "model.safetensors")]
    assert rig.jobs.progress_calls  # the fake downloader reports progress


def test_repo_and_path_use_the_downloader(rig: Rig) -> None:
    job_id = rig.handler.download(repo_id="org/repo", path="lora.safetensors", destination="loras")
    assert rig.downloader.calls[0]["repo_id"] == "org/repo"
    assert rig.downloader.calls[0]["local_dir"] == str(rig.loras)
    assert rig.jobs.jobs[job_id].status == "complete"


def test_downloader_error_fails_the_job(rig: Rig) -> None:
    rig.downloader.fail_next = RuntimeError("boom")
    job_id = rig.handler.download(repo_id="org/repo", path="m.safetensors", destination="checkpoints")
    job = rig.jobs.jobs[job_id]
    assert job.status == "failed"
    assert "boom" in job.error


# ---- download: plain https --------------------------------------------------


def test_plain_https_url_is_written_to_the_folder(rig: Rig) -> None:
    rig.http.queue("get", FakeResponse(status_code=200, content=b"abc" * 1000, headers={"Content-Length": "3000"}))
    job_id = rig.handler.download(url="https://example.com/files/cool.gguf", destination="checkpoints")
    target = rig.ckpts / "cool.gguf"
    assert target.read_bytes() == b"abc" * 1000
    assert not (rig.ckpts / "cool.gguf.part").exists()
    assert rig.jobs.jobs[job_id].status == "complete"
    assert rig.jobs.outputs[job_id] == [str(target)]
    assert rig.http.calls[0].url == "https://example.com/files/cool.gguf"


def test_plain_https_http_error_fails_and_leaves_no_part_file(rig: Rig) -> None:
    rig.http.queue("get", FakeResponse(status_code=404, content=b""))
    job_id = rig.handler.download(url="https://example.com/cool.safetensors", destination="checkpoints")
    assert rig.jobs.jobs[job_id].status == "failed"
    assert not list(rig.ckpts.glob("*"))


def test_plain_https_network_exception_fails_the_job(rig: Rig) -> None:
    rig.http.queue("get", RuntimeError("offline"))
    job_id = rig.handler.download(url="https://example.com/cool.pt", destination="loras")
    assert rig.jobs.jobs[job_id].status == "failed"
    assert not list(rig.loras.glob("*"))


# ---- rejections -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.safetensors",
        "ftp://example.com/a.safetensors",
        "file:///etc/a.safetensors",
        "https://example.com/readme.txt",
        "https://example.com/model.zip",
        "https://example.com/",
        "",
    ],
)
def test_bad_urls_are_rejected_before_a_job_starts(rig: Rig, url: str) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.download(url=url, destination="checkpoints")
    assert exc.value.status_code == 400
    assert rig.jobs.jobs == {}


@pytest.mark.parametrize("path", ["../evil.safetensors", "a/../../evil.safetensors", "/abs.safetensors", "a\\b.safetensors"])
def test_path_traversal_is_rejected(rig: Rig, path: str) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.download(repo_id="org/repo", path=path, destination="checkpoints")
    assert exc.value.status_code == 400
    assert rig.jobs.jobs == {}


def test_bad_extension_on_repo_path_is_rejected(rig: Rig) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.download(repo_id="org/repo", path="README.md", destination="checkpoints")
    assert exc.value.status_code == 400


def test_unknown_destination_is_rejected(rig: Rig) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.download(repo_id="org/repo", path="m.safetensors", destination="desktop")
    assert exc.value.status_code == 400


def test_exactly_one_of_url_or_repo_and_path(rig: Rig) -> None:
    for kwargs in (
        {},
        {"url": "https://example.com/a.pt", "repo_id": "o/r", "path": "a.pt"},
        {"repo_id": "o/r"},
        {"path": "a.pt"},
    ):
        with pytest.raises(HTTPError) as exc:
            rig.handler.download(destination="checkpoints", **kwargs)
        assert exc.value.status_code == 400


def test_existing_target_is_a_409(rig: Rig) -> None:
    rig.ckpts.mkdir(parents=True)
    (rig.ckpts / "m.safetensors").write_bytes(b"x")
    with pytest.raises(HTTPError) as exc:
        rig.handler.download(repo_id="org/repo", path="m.safetensors", destination="checkpoints")
    assert exc.value.status_code == 409
    assert rig.jobs.jobs == {}
    assert rig.downloader.calls == []


# ---- cancellation -----------------------------------------------------------


def test_cancel_stops_a_plain_download_between_chunks(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    import handlers.model_search_handler as module

    monkeypatch.setattr(module, "CHUNK_BYTES", 10)
    rig.http.queue("get", FakeResponse(status_code=200, content=b"x" * 100))
    original_progress = rig.jobs.progress

    def cancel_on_first_progress(job_id: str, progress: float, phase: str = "") -> None:
        original_progress(job_id, progress, phase)
        rig.handler.cancel(job_id)

    rig.jobs.progress = cancel_on_first_progress  # type: ignore[method-assign]
    job_id = rig.handler.download(url="https://example.com/m.safetensors", destination="checkpoints")
    assert rig.jobs.jobs[job_id].status == "cancelled"
    assert not list(rig.ckpts.glob("*"))


def test_cancel_stops_a_hub_download(rig: Rig) -> None:
    original_progress = rig.jobs.progress

    def cancel_on_first_progress(job_id: str, progress: float, phase: str = "") -> None:
        original_progress(job_id, progress, phase)
        rig.handler.cancel(job_id)

    rig.jobs.progress = cancel_on_first_progress  # type: ignore[method-assign]
    job_id = rig.handler.download(repo_id="org/repo", path="m.safetensors", destination="checkpoints")
    assert rig.jobs.jobs[job_id].status == "cancelled"


def test_cancel_unknown_job_is_a_404(rig: Rig) -> None:
    with pytest.raises(HTTPError) as exc:
        rig.handler.cancel("job_nope")
    assert exc.value.status_code == 404


def test_a_plain_link_streams_to_disk_instead_of_holding_the_file_in_memory(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """A direct link to a multi-GB checkpoint must not be read into RAM whole
    (this 32 GB machine has crashed under memory pressure): it is written in chunks."""
    import handlers.model_search_handler as module

    monkeypatch.setattr(module, "CHUNK_BYTES", 10)
    rig.http.queue("get", FakeResponse(status_code=200, content=b"y" * 35))
    job_id = rig.handler.download(url="https://example.com/big.safetensors", destination="checkpoints")
    assert rig.jobs.jobs[job_id].status == "complete"
    assert [c.method for c in rig.http.calls] == ["download_to"], "streamed, never get().content"
    assert (rig.ckpts / "big.safetensors").read_bytes() == b"y" * 35

