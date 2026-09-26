"""Fetch a LoRA from a link: Hugging Face, Civitai, or any direct
``.safetensors`` URL. Pure URL parsing lives here so it is unit-testable;
the network work sits behind the :class:`LoraFetcher` Protocol with a real
implementation (`requests_fetcher.py`) and a fake (`fake_lora_fetcher.py`).

Accepted links (``parse_lora_url``):

- ``https://huggingface.co/<owner>/<repo>/blob/<rev>/<file>.safetensors``
  (rewritten to ``/resolve/``) or the ``/resolve/`` URL itself
- ``https://civitai.com/models/<id>[?modelVersionId=<vid>]`` (a model page;
  the version is resolved through Civitai's public API)
- ``https://civitai.com/api/download/models/<vid>`` (a direct download link)
- any other ``https://…/<file>.safetensors``

An optional API key is used once for the request (Civitai gated files,
Hugging Face gated repos) and never persisted anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.parse import parse_qs, unquote, urlparse

SourceKind = Literal["huggingface", "civitai", "direct"]

#: (bytes downloaded, total bytes when the server said) — called per chunk.
ProgressCallback = Callable[[int, "int | None"], None]
CancelledCallback = Callable[[], bool]


class LoraFetchError(Exception):
    """Anything that stops the fetch, with a message fit for the job error."""


class LoraDownloadCancelled(Exception):
    """Raised by a fetcher when ``is_cancelled()`` turned true mid-download."""


@dataclass(frozen=True)
class LoraSource:
    kind: SourceKind
    #: Ready-to-fetch URL ('' for a Civitai model page until resolved).
    download_url: str = ""
    #: Filename when the URL already names one ('' when only headers know).
    filename: str = ""
    civitai_model_id: str = ""
    civitai_version_id: str = ""


@dataclass(frozen=True)
class ResolvedDownload:
    url: str
    filename: str
    size_bytes: int | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])


class LoraFetcher(Protocol):
    """Resolve a parsed source to a concrete file URL, then stream it down."""

    def resolve(self, source: LoraSource, api_key: str) -> ResolvedDownload: ...

    def download(
        self,
        resolved: ResolvedDownload,
        dest: Path,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCallback,
    ) -> None: ...


_HF_HOSTS = ("huggingface.co", "www.huggingface.co", "hf.co")
_CIVITAI_HOSTS = ("civitai.com", "www.civitai.com")


def parse_lora_url(url: str) -> LoraSource:
    """Classify a pasted link. Raises ``ValueError`` with a user-facing
    message when the link is not something a LoRA can be fetched from."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Paste an https:// link from Hugging Face or Civitai, or a direct .safetensors URL")
    host = parsed.netloc.lower()
    path = PurePosixPath(unquote(parsed.path))

    if host in _HF_HOSTS:
        parts = list(path.parts)  # ('/', owner, repo, 'blob'|'resolve', rev, *file)
        if len(parts) >= 6 and parts[3] in ("blob", "resolve"):
            filename = parts[-1]
            if not filename.lower().endswith(".safetensors"):
                raise ValueError("The Hugging Face link must point at a .safetensors file inside the repo (open the file page and copy its URL)")
            file_path = "/".join(parts[4:])  # rev/…/file
            resolve_url = f"https://huggingface.co/{parts[1]}/{parts[2]}/resolve/{file_path}?download=true"
            return LoraSource(kind="huggingface", download_url=resolve_url, filename=filename)
        raise ValueError("That Hugging Face link is a repo page — open the .safetensors file and copy the link to the file itself")

    if host in _CIVITAI_HOSTS:
        parts = list(path.parts)
        if len(parts) >= 5 and parts[1] == "api" and parts[2] == "download" and parts[3] == "models":
            return LoraSource(kind="civitai", download_url=f"https://civitai.com/api/download/models/{parts[4]}", civitai_version_id=parts[4])
        if len(parts) >= 3 and parts[1] == "models" and parts[2].isdigit():
            version = parse_qs(parsed.query).get("modelVersionId", [""])[0]
            return LoraSource(kind="civitai", civitai_model_id=parts[2], civitai_version_id=version)
        raise ValueError("That Civitai link is not a model page or a download link (expected civitai.com/models/<id> or /api/download/models/<id>)")

    if path.name.lower().endswith(".safetensors"):
        return LoraSource(kind="direct", download_url=url.strip(), filename=path.name)

    raise ValueError("Only Hugging Face links, Civitai links, or direct .safetensors URLs are supported")


def safe_lora_filename(name: str) -> str:
    """A bare, safe file name ending in .safetensors, or ''."""
    bare = Path(name.strip().replace("\\", "/")).name
    if not bare.lower().endswith(".safetensors"):
        return ""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_. " else "-" for ch in bare).strip()
    return cleaned[:120] if cleaned.lower().endswith(".safetensors") else ""
