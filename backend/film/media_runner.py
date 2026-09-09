"""Drive one hosted generation from submit to finished bytes.

The film queue owns *when* a job runs; this owns *how* a hosted job runs:
submit, poll until the provider says it is done, download the file. It is the
only place that waits, so the queue's cancel button works by handing in an
``is_cancelled`` callback that is checked between polls.

Nothing here touches settings, state or disk — the caller passes the key in
and decides where the bytes land.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from _routes._errors import HTTPError
from film.media_providers import MediaSpec, media_provider
from services.interfaces import HTTPClient

logger = logging.getLogger(__name__)

RunStatus = Literal["complete", "failed", "cancelled"]


@dataclass(slots=True)
class MediaRunResult:
    status: RunStatus
    content: bytes = b""
    media_url: str = ""
    error: str = ""
    # Provider-side wait, useful next to the app's own telemetry.
    seconds: float = 0.0


class MediaRunner:
    """Submit → poll → download for any hosted media provider."""

    def __init__(
        self,
        http: HTTPClient,
        *,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 1800.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds
        self._sleep = sleep

    def run(
        self,
        *,
        provider: str,
        api_key: str,
        spec: MediaSpec,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_progress: Callable[[int, str], None] = lambda percent, phase: None,
    ) -> MediaRunResult:
        started = time.perf_counter()
        if not spec.model.strip():
            return MediaRunResult(
                status="failed",
                error=f"No {provider} model id selected — pick one in the Model Library or the chat's model picker.",
            )
        try:
            client = media_provider(provider, self._http, api_key)
            on_progress(2, f"Submitting to {provider}")
            job = client.submit(spec)
        except HTTPError as exc:
            return MediaRunResult(status="failed", error=str(exc.detail), seconds=time.perf_counter() - started)

        polls = 0
        while True:
            if is_cancelled():
                return MediaRunResult(status="cancelled", error="Cancelled", seconds=time.perf_counter() - started)
            if time.perf_counter() - started > self._timeout:
                return MediaRunResult(
                    status="failed",
                    error=f"{provider} did not finish within {int(self._timeout / 60)} minutes",
                    seconds=time.perf_counter() - started,
                )
            try:
                status = client.poll(job)
            except HTTPError as exc:
                return MediaRunResult(status="failed", error=str(exc.detail), seconds=time.perf_counter() - started)
            if status.state == "complete":
                break
            if status.state == "failed":
                return MediaRunResult(status="failed", error=status.error, seconds=time.perf_counter() - started)
            polls += 1
            # No real progress signal from these APIs: report a slow ramp that
            # never claims to be finished, plus the provider's own queue phase.
            percent = min(90, 5 + polls * 3)
            phase = "Queued at the provider" if status.state == "queued" else f"Rendering on {provider}"
            if status.queue_position is not None:
                phase = f"{phase} (position {status.queue_position})"
            on_progress(percent, phase)
            self._sleep(self._poll_interval)

        on_progress(95, "Downloading the result")
        try:
            content = client.download(status.output_url)
        except HTTPError as exc:
            return MediaRunResult(status="failed", error=str(exc.detail), seconds=time.perf_counter() - started)
        if is_cancelled():
            return MediaRunResult(status="cancelled", error="Cancelled", seconds=time.perf_counter() - started)
        return MediaRunResult(
            status="complete",
            content=content,
            media_url=status.output_url,
            seconds=round(time.perf_counter() - started, 2),
        )


def suffix_for(url: str, task: str) -> str:
    """File extension for a downloaded result, from the URL when it says."""
    tail = url.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." in tail:
        candidate = "." + tail.rsplit(".", 1)[-1].lower()
        if candidate in (".mp4", ".webm", ".mov", ".m4v", ".mkv", ".gif", ".png", ".jpg", ".jpeg", ".webp"):
            return candidate
    return ".png" if task == "image" else ".mp4"
