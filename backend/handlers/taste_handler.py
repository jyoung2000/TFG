"""Thumbs up / thumbs down on what the software makes, and what they steer
(film/taste.py says why)."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from _routes._errors import HTTPError
from film.identity_dataset import PERSON_WORDS
from film.knowledge_models import KnowledgeEvent
from film.taste import TASTE_KINDS, TasteStore, TasteSummary, TasteVote, summarize, taste_note
from handlers.base import StateHandlerBase
from state.app_state_types import AppState

if TYPE_CHECKING:
    from handlers.film_handler import FilmHandler
    from handlers.knowledge_handler import KnowledgeHandler
    from handlers.training_handler import TrainingHandler

#: A thumbs up / down as the knowledge store's 1..5 rating (its model averages).
UP_RATING = 5
DOWN_RATING = 1


def _same_file(a: str, b: str) -> bool:
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class TasteHandler(StateHandlerBase):
    def __init__(
        self,
        state: AppState,
        lock: RLock,
        path: Path,
        knowledge: KnowledgeHandler,
        film: FilmHandler,
        training: TrainingHandler | None = None,
    ) -> None:
        super().__init__(state, lock)
        self._store = TasteStore(path)
        self._knowledge = knowledge
        self._film = film
        self._training = training

    def attach_training(self, training: TrainingHandler) -> None:
        self._training = training

    # ---- votes ----------------------------------------------------------

    def vote(self, vote: TasteVote) -> TasteVote:
        if vote.kind not in TASTE_KINDS:  # pragma: no cover - the request type already refuses
            raise HTTPError(400, f"Unknown kind {vote.kind}")
        if not vote.subject.strip():
            raise HTTPError(400, "A vote needs something to grade")
        vote.file = self._file_of(vote)
        if vote.kind == "lora":
            self._describe_lora(vote)
        stored = self._store.put(vote)
        # The model's average rating (Settings -> Learning) learns from it too.
        self._knowledge.record(
            KnowledgeEvent(
                kind="rating", model=vote.model, project_id=vote.project_id, prompt=vote.prompt,
                rating=UP_RATING if vote.vote > 0 else DOWN_RATING, note=f"{vote.kind}: {vote.subject}"[:400],
            )
        )
        return stored

    def clear(self, kind: str, subject: str) -> bool:
        return self._store.clear(kind, subject)

    def votes(self, kind: str = "") -> list[TasteVote]:
        return [v for v in self._store.all() if not kind or v.kind == kind]

    def _file_of(self, vote: TasteVote) -> str:
        if vote.kind not in ("image", "video", "style_guide"):
            return ""
        path = Path(vote.subject)
        if not path.is_absolute() and vote.project_id:
            try:
                path = self._film.store.resolve_media_path(vote.project_id, vote.subject)
            except Exception:  # noqa: BLE001 - a stale path is graded, just not tied to a file
                return ""
        return str(path) if path.is_absolute() else ""

    def _describe_lora(self, vote: TasteVote) -> None:
        """A LoRA vote remembers what made the LoRA, so Train can learn from it."""
        if self._training is None:
            return
        try:
            entry = self._training.get_lora(vote.subject)
        except HTTPError:
            return
        vote.model = vote.model or entry.target
        vote.prompt = vote.prompt or entry.trigger
        if not entry.run_id:
            return
        try:
            config = self._training.get_run(entry.run_id).config
        except HTTPError:
            return
        vote.meta.update({"resolution": config.resolution, "steps": config.steps, "batch_size": config.batch_size, "learning_rate": config.learning_rate})

    # ---- what the votes steer --------------------------------------------

    def learning(self) -> bool:
        return self._knowledge.settings().allows("feedback")

    def summary(self) -> TasteSummary:
        votes = self._store.all()
        if not self.learning():
            return TasteSummary(enabled=False, votes=len(votes), up=sum(1 for v in votes if v.vote > 0), down=sum(1 for v in votes if v.vote < 0))
        triggers: set[str] = set()
        if self._training is not None:
            triggers = {e.trigger.strip().lower() for e in self._training.list_loras() if e.trigger.strip()}
        return summarize(votes, ignore=frozenset(triggers | set(PERSON_WORDS)))

    def note(self) -> str:
        """For an AI that writes prompts: what the user's votes say they like."""
        return taste_note(self.summary())

    def rejected(self, path: str) -> bool:
        """Whether the user graded this file down (and learning is on)."""
        if not self.learning():
            return False
        return any(v.vote < 0 and _same_file(v.file, path) for v in self._store.all())

    def liked_renders(self, lora_file: str) -> list[str]:
        """Images the user graded up that were made with this LoRA."""
        if not self.learning() or not lora_file:
            return []
        name = Path(lora_file).name
        return [
            v.file for v in self._store.all()
            if v.kind == "image" and v.vote > 0 and v.file and Path(v.file).is_file() and any(Path(l).name == name for l in v.loras)
        ]
