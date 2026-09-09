"""Hosted image/video generation providers (fal, WaveSpeed, Replicate).

Same shape as ``llm_providers``: pure request/response adaptation over the
fakeable ``HTTPClient`` service, so every test runs without network or keys.
The handler owns the secret and passes it in; nothing here reads settings or
state, and no provider ever echoes the key back in an error.

All three work the same way — submit a job, poll until it finishes, download
the produced file — so ``MediaProvider`` exposes exactly that and the film
generation queue drives it with one loop regardless of vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

from pydantic import BaseModel, Field, ValidationError

from _routes._errors import HTTPError
from services.interfaces import HTTPClient, HttpTimeoutError, JSONValue

MediaTask = Literal["video", "image"]
JobState = Literal["queued", "running", "complete", "failed"]

FAL_QUEUE_URL = "https://queue.fal.run"
WAVESPEED_BASE_URL = "https://api.wavespeed.ai/api/v3"
REPLICATE_BASE_URL = "https://api.replicate.com/v1"

# Where each provider publishes its model catalog, shown in the Model Library
# so a model id can always be looked up at the source.
PROVIDER_CATALOG_URLS: dict[str, str] = {
    "fal": "https://fal.ai/models",
    "wavespeed": "https://wavespeed.ai/models",
    "replicate": "https://replicate.com/explore",
}


@dataclass(slots=True)
class MediaModel:
    """One generation model offered by a hosted provider."""

    id: str
    name: str
    provider: str
    task: MediaTask
    description: str = ""
    supports_image_input: bool = False
    # True when the entry comes from this file's example list rather than the
    # provider's own API — the UI says so, and the id should be checked against
    # the provider's catalog before relying on it.
    curated: bool = False
    url: str = ""


@dataclass(slots=True)
class MediaSpec:
    """What to generate. Fields the chosen model ignores are simply unused."""

    model: str
    prompt: str
    task: MediaTask = "video"
    negative_prompt: str = ""
    duration_seconds: float = 5.0
    fps: int = 24
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    width: int = 1024
    height: int = 576
    seed: int | None = None
    # data: URL of a conditioning image (image-to-video / image-to-image).
    image_data_url: str = ""


@dataclass(slots=True)
class MediaJob:
    provider: str
    id: str
    poll_url: str
    result_url: str = ""


@dataclass(slots=True)
class MediaJobStatus:
    state: JobState
    output_url: str = ""
    error: str = ""
    queue_position: int | None = None


# Example model ids per provider. These are starting points for the Model
# Library, not a catalog: providers add and retire models continuously, so the
# UI marks them "example" and every field accepts any id pasted from the
# provider's own catalog (linked above).
_CURATED: dict[str, list[MediaModel]] = {
    "fal": [
        MediaModel("fal-ai/ltx-video-13b-distilled", "LTX Video 13B Distilled", "fal", "video", "Fast LTX text-to-video", True, True),
        MediaModel("fal-ai/ltx-video-13b-distilled/image-to-video", "LTX Video 13B (image to video)", "fal", "video", "Animate a still frame", True, True),
        MediaModel("fal-ai/flux/schnell", "FLUX schnell", "fal", "image", "Fast reference stills", False, True),
        MediaModel("fal-ai/flux/dev", "FLUX dev", "fal", "image", "Higher quality stills", True, True),
    ],
    "wavespeed": [
        MediaModel("wavespeed-ai/wan-2.2/t2v-480p", "Wan 2.2 text-to-video 480p", "wavespeed", "video", "", False, True),
        MediaModel("wavespeed-ai/wan-2.2/i2v-480p", "Wan 2.2 image-to-video 480p", "wavespeed", "video", "", True, True),
        MediaModel("wavespeed-ai/flux-schnell", "FLUX schnell", "wavespeed", "image", "", False, True),
    ],
    "replicate": [
        MediaModel("lightricks/ltx-video", "LTX Video", "replicate", "video", "", True, True),
        MediaModel("black-forest-labs/flux-schnell", "FLUX schnell", "replicate", "image", "", False, True),
    ],
}


def curated_models(provider: str) -> list[MediaModel]:
    """Copies, so a caller can never mutate the module-level examples."""
    return [replace(model) for model in _CURATED.get(provider, [])]


def _fail(provider: str, status_code: int, text: str) -> None:
    """Map a provider's HTTP status onto the app's typed errors (no key echo)."""
    if 200 <= status_code < 300:
        return
    label = provider.upper()
    detail = text.strip()[:300]
    if status_code in (401, 403):
        raise HTTPError(401, f"{label}_KEY_INVALID: {provider} rejected the API key")
    if status_code == 402:
        raise HTTPError(402, f"{label}_CREDITS: {provider} reports insufficient credits")
    if status_code == 404:
        raise HTTPError(404, f"{label}_MODEL_NOT_FOUND: {detail or 'model id not found'}")
    if status_code == 422:
        raise HTTPError(422, f"{label}_BAD_INPUT: {detail or 'the model rejected these inputs'}")
    if status_code == 429:
        raise HTTPError(429, f"{label}_RATE_LIMITED: rate limit hit, retry shortly")
    raise HTTPError(502 if status_code >= 500 else status_code, f"{provider} API error ({status_code}): {detail}")


def _payload_dict(raw: object, provider: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise HTTPError(502, f"{provider} returned an unexpected payload")
    return cast(dict[str, object], raw)


def _first_url(value: object) -> str:
    """Pull a media URL out of the many shapes providers return."""
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, list):
        for item in cast(list[object], value):
            found = _first_url(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        entry = cast(dict[str, object], value)
        for key in ("url", "video", "videos", "image", "images", "output", "outputs", "file", "data", "result"):
            if key in entry:
                found = _first_url(entry[key])
                if found:
                    return found
    return ""


class MediaProvider:
    """Submit → poll → download, adapted per vendor."""

    name: str = "base"

    def __init__(self, http: HTTPClient, api_key: str) -> None:
        self._http = http
        self._api_key = api_key

    # -- contract ---------------------------------------------------------

    def submit(self, spec: MediaSpec) -> MediaJob:
        raise NotImplementedError

    def poll(self, job: MediaJob) -> MediaJobStatus:
        raise NotImplementedError

    def discover(self, task: MediaTask | None = None) -> list[MediaModel]:
        """Models from the provider's own API; empty when it publishes none."""
        return []

    # -- shared -----------------------------------------------------------

    def _require_key(self) -> None:
        if not self._api_key:
            raise HTTPError(400, f"{self.name.upper()}_KEY_MISSING: no {self.name} API key configured")

    def _post(self, url: str, payload: dict[str, JSONValue], *, timeout: int = 60) -> dict[str, object]:
        self._require_key()
        try:
            response = self._http.post(url, headers=self._headers(), json_payload=payload, timeout=timeout)
        except HttpTimeoutError as exc:
            raise HTTPError(504, f"{self.name} request timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"{self.name} unreachable: {exc}") from exc
        _fail(self.name, response.status_code, response.text)
        return _payload_dict(response.json(), self.name)

    def _get(self, url: str, *, timeout: int = 30) -> dict[str, object]:
        try:
            response = self._http.get(url, headers=self._headers(), timeout=timeout)
        except HttpTimeoutError as exc:
            raise HTTPError(504, f"{self.name} status request timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"{self.name} unreachable: {exc}") from exc
        _fail(self.name, response.status_code, response.text)
        return _payload_dict(response.json(), self.name)

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def download(self, url: str, *, timeout: int = 600) -> bytes:
        """Fetch the finished file. The output URL is public/pre-signed, so no
        credentials are attached."""
        try:
            response = self._http.get(url, headers=None, timeout=timeout)
        except HttpTimeoutError as exc:
            raise HTTPError(504, f"{self.name} download timed out") from exc
        except Exception as exc:
            raise HTTPError(502, f"Could not download the {self.name} result: {exc}") from exc
        if response.status_code != 200:
            raise HTTPError(502, f"{self.name} download failed ({response.status_code})")
        content = response.content
        if not content:
            raise HTTPError(502, f"{self.name} returned an empty file")
        return content

    def curated(self) -> list[MediaModel]:
        return curated_models(self.name)


# ---------------------------------------------------------------------------
# fal.ai — queue API
# ---------------------------------------------------------------------------


class _FalSubmit(BaseModel):
    request_id: str = ""
    status_url: str = ""
    response_url: str = ""


class _FalStatus(BaseModel):
    status: str = ""
    queue_position: int | None = None
    response_url: str = ""


class FalProvider(MediaProvider):
    name = "fal"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Key {self._api_key}"
        return headers

    @staticmethod
    def _inputs(spec: MediaSpec) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {"prompt": spec.prompt}
        if spec.negative_prompt:
            payload["negative_prompt"] = spec.negative_prompt
        if spec.seed is not None:
            payload["seed"] = spec.seed
        if spec.task == "video":
            payload["aspect_ratio"] = spec.aspect_ratio
            payload["resolution"] = spec.resolution
            payload["num_frames"] = max(1, int(spec.duration_seconds * spec.fps))
        else:
            payload["image_size"] = {"width": spec.width, "height": spec.height}
        if spec.image_data_url:
            payload["image_url"] = spec.image_data_url
        return payload

    def submit(self, spec: MediaSpec) -> MediaJob:
        raw = self._post(f"{FAL_QUEUE_URL}/{spec.model.strip('/')}", self._inputs(spec))
        try:
            parsed = _FalSubmit.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "fal returned an unexpected submit payload") from exc
        if not parsed.status_url:
            raise HTTPError(502, "fal did not return a status URL for the job")
        return MediaJob(provider=self.name, id=parsed.request_id, poll_url=parsed.status_url, result_url=parsed.response_url)

    def poll(self, job: MediaJob) -> MediaJobStatus:
        raw = self._get(job.poll_url)
        try:
            status = _FalStatus.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "fal returned an unexpected status payload") from exc
        state = status.status.upper()
        if state in ("IN_QUEUE", "QUEUED"):
            return MediaJobStatus(state="queued", queue_position=status.queue_position)
        if state in ("IN_PROGRESS", "RUNNING"):
            return MediaJobStatus(state="running")
        if state in ("COMPLETED", "OK", "SUCCESS"):
            result = self._get(job.result_url or status.response_url or job.poll_url)
            url = _first_url(result)
            if not url:
                return MediaJobStatus(state="failed", error="fal finished without returning a file URL")
            return MediaJobStatus(state="complete", output_url=url)
        error = str(raw.get("error", "") or raw.get("detail", "") or state or "unknown status")
        return MediaJobStatus(state="failed", error=f"fal job failed: {error}"[:300])


# ---------------------------------------------------------------------------
# WaveSpeed AI
# ---------------------------------------------------------------------------


class _WaveSpeedUrls(BaseModel):
    get: str = ""


class _WaveSpeedData(BaseModel):
    id: str = ""
    status: str = ""
    outputs: list[str] = Field(default_factory=list[str])
    error: str = ""
    urls: _WaveSpeedUrls = Field(default_factory=_WaveSpeedUrls)


class _WaveSpeedEnvelope(BaseModel):
    code: int = 200
    message: str = ""
    data: _WaveSpeedData = Field(default_factory=_WaveSpeedData)


class WaveSpeedProvider(MediaProvider):
    name = "wavespeed"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _inputs(spec: MediaSpec) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {"prompt": spec.prompt}
        if spec.negative_prompt:
            payload["negative_prompt"] = spec.negative_prompt
        if spec.seed is not None:
            payload["seed"] = spec.seed
        if spec.task == "video":
            payload["duration"] = int(round(spec.duration_seconds))
        else:
            payload["size"] = f"{spec.width}*{spec.height}"
        if spec.image_data_url:
            payload["image"] = spec.image_data_url
        return payload

    def submit(self, spec: MediaSpec) -> MediaJob:
        raw = self._post(f"{WAVESPEED_BASE_URL}/{spec.model.strip('/')}", self._inputs(spec))
        try:
            envelope = _WaveSpeedEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "WaveSpeed returned an unexpected submit payload") from exc
        if envelope.code >= 400:
            raise HTTPError(502, f"WaveSpeed rejected the job: {envelope.message[:200]}")
        job_id = envelope.data.id
        if not job_id:
            raise HTTPError(502, "WaveSpeed did not return a prediction id")
        poll = envelope.data.urls.get or f"{WAVESPEED_BASE_URL}/predictions/{job_id}/result"
        return MediaJob(provider=self.name, id=job_id, poll_url=poll)

    def poll(self, job: MediaJob) -> MediaJobStatus:
        raw = self._get(job.poll_url)
        try:
            envelope = _WaveSpeedEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "WaveSpeed returned an unexpected status payload") from exc
        status = envelope.data.status.lower()
        if status in ("created", "queued", "pending"):
            return MediaJobStatus(state="queued")
        if status in ("processing", "running"):
            return MediaJobStatus(state="running")
        if status in ("completed", "succeeded", "success"):
            url = _first_url(cast(object, envelope.data.outputs))
            if not url:
                return MediaJobStatus(state="failed", error="WaveSpeed finished without returning a file URL")
            return MediaJobStatus(state="complete", output_url=url)
        return MediaJobStatus(state="failed", error=f"WaveSpeed job failed: {envelope.data.error or status}"[:300])


# ---------------------------------------------------------------------------
# Replicate
# ---------------------------------------------------------------------------


class _ReplicateUrls(BaseModel):
    get: str = ""
    cancel: str = ""


class _ReplicatePrediction(BaseModel):
    id: str = ""
    status: str = ""
    error: str | None = None
    output: object = None
    urls: _ReplicateUrls = Field(default_factory=_ReplicateUrls)


class _ReplicateModelEntry(BaseModel):
    owner: str = ""
    name: str = ""
    description: str = ""
    url: str = ""


class _ReplicateCollection(BaseModel):
    models: list[_ReplicateModelEntry] = Field(default_factory=list[_ReplicateModelEntry])


class ReplicateProvider(MediaProvider):
    name = "replicate"

    # Replicate's curated collections double as a searchable catalog.
    _COLLECTIONS: dict[MediaTask, tuple[str, ...]] = {
        "video": ("text-to-video", "image-to-video"),
        "image": ("text-to-image",),
    }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _inputs(spec: MediaSpec) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {"prompt": spec.prompt}
        if spec.negative_prompt:
            payload["negative_prompt"] = spec.negative_prompt
        if spec.seed is not None:
            payload["seed"] = spec.seed
        if spec.task == "video":
            payload["aspect_ratio"] = spec.aspect_ratio
        else:
            payload["width"] = spec.width
            payload["height"] = spec.height
        if spec.image_data_url:
            payload["image"] = spec.image_data_url
        return payload

    def submit(self, spec: MediaSpec) -> MediaJob:
        model = spec.model.strip().strip("/")
        inputs = self._inputs(spec)
        if ":" in model:  # owner/name:version — the pinned-version endpoint
            _, _, version = model.partition(":")
            raw = self._post(f"{REPLICATE_BASE_URL}/predictions", {"version": version, "input": inputs})
        else:
            raw = self._post(f"{REPLICATE_BASE_URL}/models/{model}/predictions", {"input": inputs})
        try:
            parsed = _ReplicatePrediction.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "Replicate returned an unexpected submit payload") from exc
        poll = parsed.urls.get or f"{REPLICATE_BASE_URL}/predictions/{parsed.id}"
        if not parsed.id:
            raise HTTPError(502, "Replicate did not return a prediction id")
        return MediaJob(provider=self.name, id=parsed.id, poll_url=poll)

    def poll(self, job: MediaJob) -> MediaJobStatus:
        raw = self._get(job.poll_url)
        try:
            parsed = _ReplicatePrediction.model_validate(raw)
        except ValidationError as exc:
            raise HTTPError(502, "Replicate returned an unexpected status payload") from exc
        status = parsed.status.lower()
        if status in ("starting", "queued"):
            return MediaJobStatus(state="queued")
        if status == "processing":
            return MediaJobStatus(state="running")
        if status == "succeeded":
            url = _first_url(parsed.output)
            if not url:
                return MediaJobStatus(state="failed", error="Replicate finished without returning a file URL")
            return MediaJobStatus(state="complete", output_url=url)
        return MediaJobStatus(state="failed", error=f"Replicate job {status}: {parsed.error or 'no reason given'}"[:300])

    def discover(self, task: MediaTask | None = None) -> list[MediaModel]:
        if not self._api_key:
            return []
        wanted: tuple[MediaTask, ...] = ("video", "image") if task is None else (task,)
        found: list[MediaModel] = []
        seen: set[str] = set()
        for media_task in wanted:
            for slug in self._COLLECTIONS.get(media_task, ()):  # pyright: ignore[reportUnknownMemberType]
                try:
                    raw = self._get(f"{REPLICATE_BASE_URL}/collections/{slug}")
                    collection = _ReplicateCollection.model_validate(raw)
                except (HTTPError, ValidationError):
                    continue  # a collection that moved must not break the library
                for entry in collection.models:
                    model_id = f"{entry.owner}/{entry.name}" if entry.owner else entry.name
                    if not model_id or model_id in seen:
                        continue
                    seen.add(model_id)
                    found.append(
                        MediaModel(
                            id=model_id,
                            name=entry.name or model_id,
                            provider=self.name,
                            task=media_task,
                            description=entry.description[:200],
                            supports_image_input=slug == "image-to-video",
                            url=entry.url,
                        )
                    )
        return found


_PROVIDERS: dict[str, type[MediaProvider]] = {
    "fal": FalProvider,
    "wavespeed": WaveSpeedProvider,
    "replicate": ReplicateProvider,
}

HOSTED_PROVIDERS: tuple[str, ...] = tuple(_PROVIDERS)


def media_provider(name: str, http: HTTPClient, api_key: str) -> MediaProvider:
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise HTTPError(400, f"Unknown media provider: {name}")
    return factory(http, api_key)
