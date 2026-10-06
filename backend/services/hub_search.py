"""Hugging Face Hub search: the protocol the handler depends on and the real implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from _routes._errors import HTTPError


@dataclass
class HubModel:
    repo_id: str
    downloads: int = 0
    likes: int = 0
    pipeline_tag: str = ""
    license: str = ""
    last_modified: str = ""


@dataclass
class HubFile:
    path: str
    size_bytes: int = 0


class HubApi(Protocol):
    def list_models(self, search: str, limit: int) -> list[HubModel]: ...

    def list_files(self, repo_id: str) -> list[HubFile]: ...


def _license_of(info: Any) -> str:
    card: Any = getattr(info, "card_data", None) or getattr(info, "cardData", None)
    value: Any = None
    if isinstance(card, dict):
        value = cast(dict[str, Any], card).get("license")
    elif card is not None:
        value = getattr(card, "license", None)
    if isinstance(value, list) and value:
        value = value[0]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str) and value:
        return value
    tags: Any = getattr(info, "tags", None) or []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return ""


def _stamp(value: Any) -> str:
    if value is None:
        return ""
    iso = getattr(value, "isoformat", None)
    return str(iso()) if callable(iso) else str(value)


class HuggingFaceHubApi:
    """Real `HubApi` over `huggingface_hub.HfApi`; every network failure is a 502."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def _api(self) -> Any:
        from huggingface_hub import HfApi

        return HfApi(token=self._token)

    def list_models(self, search: str, limit: int) -> list[HubModel]:
        try:
            found: Any = self._api().list_models(search=search, sort="downloads", limit=limit)
            models: list[HubModel] = []
            for info in found:
                models.append(
                    HubModel(
                        repo_id=str(getattr(info, "id", "") or getattr(info, "modelId", "")),
                        downloads=int(getattr(info, "downloads", 0) or 0),
                        likes=int(getattr(info, "likes", 0) or 0),
                        pipeline_tag=str(getattr(info, "pipeline_tag", "") or ""),
                        license=_license_of(info),
                        last_modified=_stamp(getattr(info, "last_modified", None)),
                    )
                )
            return models
        except HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001 - any network or API failure is a gateway error
            raise HTTPError(502, f"Hugging Face search failed: {exc}") from exc

    def list_files(self, repo_id: str) -> list[HubFile]:
        try:
            info: Any = self._api().model_info(repo_id, files_metadata=True)
            siblings: Any = getattr(info, "siblings", None) or []
            return [
                HubFile(path=str(getattr(s, "rfilename", "")), size_bytes=int(getattr(s, "size", 0) or 0))
                for s in siblings
                if getattr(s, "rfilename", "")
            ]
        except HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPError(502, f"Hugging Face file listing failed: {exc}") from exc
