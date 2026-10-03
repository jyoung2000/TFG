"""Taste: the user's thumbs up / thumbs down on what the software makes.

User, 2026-10-03: "Let the user grade prompts, styleguides, videos, and images
the software creates with a simple thumbs up and thumbs down so the user can let
the software know when its doing a good or bad job and the software can generate
to the users taste and preference", and grade LoRAs "so the software and ai can
know if the user likes or doesnt like a LoRA and can use that data to train and
generate LoRA's the user likes".

A vote is one row per thing graded (kind + subject), with what made it: the
prompt, the model, the LoRAs, and for a LoRA its training settings. What the
votes are used for lives with their users (handlers/taste_handler.py):
- a character's LoRA dataset leaves out graded-down images and takes in
  graded-up renders made with that character's LoRA;
- the AI director is told which prompt phrases the user likes and dislikes;
- Train shows (and pre-selects) the training settings of the LoRAs liked.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from film.film_models import now_ms

TasteKind = Literal["lora", "prompt", "style_guide", "image", "video"]
TASTE_KINDS: tuple[str, ...] = ("lora", "prompt", "style_guide", "image", "video")

#: A phrase needs this many more ups than downs (or the reverse) to count.
MIN_NET = 2
#: Phrases longer than this are sentences, not taste.
MAX_PHRASE = 60
MAX_PHRASES = 12


class TasteVote(BaseModel):
    kind: TasteKind
    #: What was graded: a LoRA id, a prompt, or a file path (absolute, or
    #: project-relative with `project_id`).
    subject: str
    vote: Literal[1, -1]
    #: The file the vote is about, when it is one (resolved, absolute).
    file: str = ""
    project_id: str = ""
    prompt: str = ""
    model: str = ""
    #: LoRA files the graded render used.
    loras: list[str] = Field(default_factory=list[str])
    #: Context worth learning from (a LoRA's resolution / steps / batch_size ...).
    meta: dict[str, str | int | float | bool] = Field(default_factory=dict[str, str | int | float | bool])
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TastePhrase(BaseModel):
    text: str
    up: int
    down: int


class TrainingTaste(BaseModel):
    """The training settings of the LoRAs the user liked most."""

    resolution: int
    steps: int
    batch_size: int
    liked: int


class TasteSummary(BaseModel):
    #: False when learning from feedback is switched off in Settings: votes are
    #: kept, nothing is learned from them.
    enabled: bool = True
    votes: int = 0
    up: int = 0
    down: int = 0
    liked_phrases: list[TastePhrase] = Field(default_factory=list[TastePhrase])
    disliked_phrases: list[TastePhrase] = Field(default_factory=list[TastePhrase])
    liked_loras: list[str] = Field(default_factory=list[str])
    disliked_loras: list[str] = Field(default_factory=list[str])
    training: TrainingTaste | None = None


def prompt_phrases(prompt: str) -> list[str]:
    """A prompt's comma-separated phrases, lower-cased, deduplicated."""
    seen: list[str] = []
    for raw in re.split(r"[,;\n]+", prompt.lower()):
        phrase = " ".join(raw.split()).strip(" .:")
        if 3 <= len(phrase) <= MAX_PHRASE and phrase not in seen:
            seen.append(phrase)
    return seen


def summarize(votes: list[TasteVote]) -> TasteSummary:
    tally: dict[str, list[int]] = {}
    for vote in votes:
        for phrase in prompt_phrases(vote.prompt):
            counts = tally.setdefault(phrase, [0, 0])
            counts[0 if vote.vote > 0 else 1] += 1
    phrases = [TastePhrase(text=text, up=up, down=down) for text, (up, down) in tally.items()]
    liked = sorted((p for p in phrases if p.up - p.down >= MIN_NET), key=lambda p: (p.down - p.up, p.text))
    disliked = sorted((p for p in phrases if p.down - p.up >= MIN_NET), key=lambda p: (p.up - p.down, p.text))
    loras = [v for v in votes if v.kind == "lora"]
    configs: dict[tuple[int, int, int], int] = {}
    for vote in loras:
        try:
            key = (int(vote.meta["resolution"]), int(vote.meta["steps"]), int(vote.meta["batch_size"]))
        except (KeyError, TypeError, ValueError):
            continue
        configs[key] = configs.get(key, 0) + vote.vote
    best = max(configs.items(), key=lambda item: item[1], default=None)
    return TasteSummary(
        votes=len(votes),
        up=sum(1 for v in votes if v.vote > 0),
        down=sum(1 for v in votes if v.vote < 0),
        liked_phrases=liked[:MAX_PHRASES],
        disliked_phrases=disliked[:MAX_PHRASES],
        liked_loras=[v.subject for v in loras if v.vote > 0],
        disliked_loras=[v.subject for v in loras if v.vote < 0],
        training=TrainingTaste(resolution=best[0][0], steps=best[0][1], batch_size=best[0][2], liked=best[1]) if best and best[1] > 0 else None,
    )


def taste_note(summary: TasteSummary) -> str:
    """A paragraph for an AI that writes prompts; '' when there is nothing to say."""
    if not summary.enabled or not (summary.liked_phrases or summary.disliked_phrases):
        return ""
    parts = ["The user grades what this app makes with thumbs up and down."]
    if summary.liked_phrases:
        parts.append("They liked results described as: " + "; ".join(p.text for p in summary.liked_phrases) + ".")
    if summary.disliked_phrases:
        parts.append("They disliked results described as: " + "; ".join(p.text for p in summary.disliked_phrases) + ".")
    parts.append("Lean toward what they liked and away from what they disliked, unless the instruction asks otherwise.")
    return " ".join(parts)


class TasteStore:
    """Votes in one JSON file, one per (kind, subject)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _read(self) -> list[TasteVote]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [TasteVote.model_validate(item) for item in raw if isinstance(item, dict)]

    def _write(self, votes: list[TasteVote]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps([v.model_dump() for v in votes], indent=1), encoding="utf-8")
        temp.replace(self._path)

    def all(self) -> list[TasteVote]:
        with self._lock:
            return self._read()

    def put(self, vote: TasteVote) -> TasteVote:
        with self._lock:
            votes = self._read()
            existing = next((v for v in votes if v.kind == vote.kind and v.subject == vote.subject), None)
            if existing is not None:
                vote.created_at = existing.created_at
                votes.remove(existing)
            vote.updated_at = now_ms()
            votes.append(vote)
            self._write(votes)
            return vote

    def clear(self, kind: str, subject: str) -> bool:
        with self._lock:
            votes = self._read()
            kept = [v for v in votes if not (v.kind == kind and v.subject == subject)]
            if len(kept) == len(votes):
                return False
            self._write(kept)
            return True
