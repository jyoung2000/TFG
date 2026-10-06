"""Model manager: search Hugging Face, list a repo's weights, download by link or by repo file."""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from _routes._errors import HTTPError
from handlers.base import StateHandlerBase
from services.http_client.http_client import StreamingHTTPClient
from services.hub_search import HubApi, HubFile, HubModel
from services.job_store.job_models import Job, JobKind
from services.model_downloader.model_downloader import ModelDownloader
from services.task_runner.task_runner import TaskRunner
from state.app_state_types import AppState

WEIGHT_EXTENSIONS: tuple[str, ...] = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin")
MAX_SEARCH_RESULTS = 50
CHUNK_BYTES = 1024 * 1024

_HF_RESOLVE = re.compile(r"^https://huggingface\.co/(?P<repo>[^/]+/[^/]+)/resolve/(?P<rev>[^/]+)/(?P<path>.+)$")


class _JobsLike(Protocol):
    """The part of handlers.jobs_handler.JobsHandler a download uses."""

    def start(self, kind: JobKind, *, title: str = "", model: str = "", inputs: dict[str, Any] | None = None) -> Job: ...

    def progress(self, job_id: str, progress: float, phase: str = "") -> None: ...

    def complete(self, job_id: str, outputs: Sequence[str] = ()) -> Job: ...

    def fail(self, job_id: str, error: str) -> Job: ...

    def mark_cancelled(self, job_id: str, *, reason: str = "Cancelled") -> Job: ...


class _Cancelled(Exception):
    """Raised inside a transfer when the user cancelled it."""


def _has_weight_extension(name: str) -> bool:
    return name.lower().endswith(WEIGHT_EXTENSIONS)


def _check_relative_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned or cleaned.startswith("/") or "\\" in cleaned or ".." in cleaned.split("/"):
        raise HTTPError(400, f"Unsafe file path: {path[:80]}")
    return cleaned


class ModelSearchHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        *,
        hub: HubApi,
        downloader: ModelDownloader,
        http: StreamingHTTPClient,
        jobs: _JobsLike,
        task_runner: TaskRunner,
        destinations: dict[str, Path],
    ) -> None:
        super().__init__(state, lock)
        self._hub = hub
        self._downloader = downloader
        self._http = http
        self._jobs = jobs
        self._task_runner = task_runner
        self._destinations = dict(destinations)
        self._cancel_flags: dict[str, threading.Event] = {}
        self._active_targets: set[Path] = set()

    # ---- search ----------------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[HubModel]:
        query = query.strip()
        if not query:
            return []
        return self._hub.list_models(query, max(1, min(int(limit), MAX_SEARCH_RESULTS)))

    def files(self, repo_id: str) -> list[HubFile]:
        repo_id = repo_id.strip()
        if not repo_id:
            raise HTTPError(400, "A repository id is required")
        weights = [f for f in self._hub.list_files(repo_id) if _has_weight_extension(f.path)]
        return sorted(weights, key=lambda f: f.size_bytes, reverse=True)

    # ---- download --------------------------------------------------------

    def download(self, *, url: str = "", repo_id: str = "", path: str = "", destination: str) -> str:
        url, repo_id, path = url.strip(), repo_id.strip(), path.strip()
        folder = self._destinations.get(destination)
        if folder is None:
            raise HTTPError(400, f"Unknown destination: {destination}")
        if bool(url) == bool(repo_id or path) or (not url and not (repo_id and path)):
            raise HTTPError(400, "Give either a link, or a repository and a file path")

        plain_url = ""
        if url:
            match = _HF_RESOLVE.match(url.split("?", 1)[0].split("#", 1)[0])
            if match:
                repo_id, path = match.group("repo"), unquote(match.group("path"))
            else:
                plain_url = url
        if plain_url:
            parsed = urlparse(plain_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise HTTPError(400, "Only https:// links are accepted")
            relative = _check_relative_path(unquote(Path(parsed.path).name))
        else:
            relative = _check_relative_path(path)
        if not _has_weight_extension(relative):
            raise HTTPError(400, f"Only model weight files are accepted ({', '.join(WEIGHT_EXTENSIONS)})")

        target = folder / relative
        with self.lock:
            if target.exists() or target in self._active_targets:
                raise HTTPError(409, f"{relative} already exists in {destination}")
            self._active_targets.add(target)
        try:
            job = self._jobs.start(
                "download",
                title=Path(relative).name,
                model=repo_id or (urlparse(plain_url).hostname or ""),
                inputs={"url": plain_url, "repo_id": repo_id, "path": relative, "destination": destination},
            )
        except Exception:
            with self.lock:
                self._active_targets.discard(target)
            raise
        job_id = job.id
        flag = threading.Event()
        with self.lock:
            self._cancel_flags[job_id] = flag

        def run() -> None:
            self._run(job_id, flag, target, folder, repo_id, relative, plain_url)

        def on_error(exc: Exception) -> None:
            self._finish_failed(job_id, target, str(exc))

        self._task_runner.run_background(run, task_name=f"model-download-{job_id}", on_error=on_error)
        return job_id

    def cancel(self, job_id: str) -> None:
        with self.lock:
            flag = self._cancel_flags.get(job_id)
        if flag is None:
            raise HTTPError(404, f"No running download: {job_id}")
        flag.set()

    # ---- transfer --------------------------------------------------------

    def _run(
        self,
        job_id: str,
        flag: threading.Event,
        target: Path,
        folder: Path,
        repo_id: str,
        relative: str,
        plain_url: str,
    ) -> None:
        part = target.with_name(target.name + ".part")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if plain_url:
                saved = self._fetch_plain(job_id, flag, plain_url, target, part)
            else:
                saved = self._fetch_hub(job_id, flag, repo_id, relative, folder)
            self._jobs.complete(job_id, [str(saved)])
        except _Cancelled:
            part.unlink(missing_ok=True)
            self._jobs.mark_cancelled(job_id)
        except Exception as exc:  # noqa: BLE001 - report on the job, never crash the worker
            part.unlink(missing_ok=True)
            self._jobs.fail(job_id, str(exc) or exc.__class__.__name__)
        finally:
            self._forget(job_id, target)

    def _fetch_hub(self, job_id: str, flag: threading.Event, repo_id: str, relative: str, folder: Path) -> Path:
        def on_progress(done: int, total: int) -> None:
            if total > 0:
                self._jobs.progress(job_id, done / total * 100, f"Downloading {Path(relative).name}")
            if flag.is_set():
                raise _Cancelled()

        return self._downloader.download_file(
            repo_id=repo_id, filename=relative, local_dir=str(folder), on_progress=on_progress
        )

    def _fetch_plain(self, job_id: str, flag: threading.Event, url: str, target: Path, part: Path) -> Path:
        def on_chunk(written: int, total: int) -> None:
            if total > 0:
                self._jobs.progress(job_id, written / total * 100, f"Downloading {target.name}")
            if flag.is_set():
                raise _Cancelled()

        # Streamed to disk: a multi-GB checkpoint never sits in memory whole.
        self._http.download_to(url, part, on_chunk, timeout=60, chunk_bytes=CHUNK_BYTES)
        if flag.is_set():
            raise _Cancelled()
        part.replace(target)
        return target

    def _finish_failed(self, job_id: str, target: Path, error: str) -> None:
        target.with_name(target.name + ".part").unlink(missing_ok=True)
        self._jobs.fail(job_id, error)
        self._forget(job_id, target)

    def _forget(self, job_id: str, target: Path) -> None:
        with self.lock:
            self._cancel_flags.pop(job_id, None)
            self._active_targets.discard(target)
