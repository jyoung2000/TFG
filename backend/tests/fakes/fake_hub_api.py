"""Test double for the Hugging Face Hub search API."""

from __future__ import annotations

from services.hub_search import HubFile, HubModel


class FakeHubApi:
    def __init__(self) -> None:
        self.models: list[HubModel] = []
        self.files: dict[str, list[HubFile]] = {}
        self.search_calls: list[tuple[str, int]] = []
        self.file_calls: list[str] = []
        self.fail_next: Exception | None = None

    def _raise_if_needed(self) -> None:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error

    def list_models(self, search: str, limit: int) -> list[HubModel]:
        self._raise_if_needed()
        self.search_calls.append((search, limit))
        needle = search.lower()
        return [m for m in self.models if needle in m.repo_id.lower()][:limit]

    def list_files(self, repo_id: str) -> list[HubFile]:
        self._raise_if_needed()
        self.file_calls.append(repo_id)
        return list(self.files.get(repo_id, []))
