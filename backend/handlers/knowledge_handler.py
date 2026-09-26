"""What TFG has learned about the models it runs.

Records what happened, derives what it suggests, and keeps the two apart.

The derivation rules below are deliberately conservative. A count is reported
as a fact with full confidence because it is arithmetic. Anything that
generalises from those counts is an observed pattern, a preference, or — when
the sample is too small to mean much — a hypothesis that says so. Confidence
never reaches certainty from observation alone: the curve is n / (n + 5), so
five runs buy 0.5 and twenty buy 0.8.

Nothing here is recorded when the user has switched learning off, and the
switch is honoured at write time rather than at read time, so disabling it
stops collection rather than merely hiding it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import RLock

from _routes._errors import HTTPError
from film.film_models import now_ms
from film.prompt_compiler import PromptHints
from film.knowledge_models import (
    EVENT_CATEGORIES,
    KnowledgeEvent,
    KnowledgeExport,
    LearningSettings,
    ModelProfile,
    Observation,
    OBSERVATION_KIND_RANK,
    PromptPattern,
    Task,
)
from film.knowledge_store import KnowledgeStore
from handlers.base import StateHandlerBase
from state.app_state_types import AppState

logger = logging.getLogger(__name__)

#: Below this many runs, a generalisation is labelled a hypothesis.
_PATTERN_MIN_SAMPLE = 5
#: Below this many judgements, a preference is a hypothesis.
_PREFERENCE_MIN_SAMPLE = 3
#: Evidence ids kept per observation — enough to justify, not a full log.
_MAX_EVIDENCE = 8

#: Uses below which a prompt phrase gets no verdict at all.
_PHRASE_MIN_USES = 3
#: Reproduce hints: winners needed before advice, minimum spec-key overlap, minimum score.
_HINT_MIN_WINS = 3
_HINT_MIN_OVERLAP = 0.3
_HINT_MIN_SCORE = 0.5


def _phrases_of(prompt: str) -> list[str]:
    """Comma/semicolon-separated phrases of a prompt, normalised; short and long noise dropped."""
    out: list[str] = []
    for raw in prompt.replace(";", ",").replace(".", ",").split(","):
        phrase = " ".join(raw.strip().lower().split())
        if 3 <= len(phrase) <= 48 and not phrase.startswith("must match"):
            out.append(phrase)
    return out
#: Events scanned per model when extracting prompt patterns. Bounded so a long
#: render history cannot make opening Settings slow.
_PHRASE_EVENT_LIMIT = 500

#: The vocabulary prompt patterns are measured over. Free n-grams would surface
#: "a", "the" and the subject of whatever was being shot; these are the terms a
#: cinematographer actually varies, which is what makes a pattern actionable.
_PROMPT_PHRASES: tuple[str, ...] = (
    # shot size
    "extreme close-up", "close-up", "medium close-up", "medium shot", "medium wide",
    "wide shot", "extreme wide", "establishing shot", "over-the-shoulder", "two shot", "insert shot",
    # camera movement
    "static", "locked off", "handheld", "dolly in", "dolly out", "tracking shot", "pan",
    "tilt", "crane", "steadicam", "zoom", "push in", "pull out", "orbit", "whip pan",
    # lens
    "wide angle", "telephoto", "anamorphic", "macro", "shallow depth of field", "deep focus", "bokeh",
    # lighting
    "golden hour", "blue hour", "backlit", "rim light", "high key", "low key", "practical light",
    "soft light", "hard light", "silhouette", "neon", "candlelight", "overcast", "harsh sunlight",
    # look
    "cinematic", "photorealistic", "film grain", "lens flare", "desaturated", "high contrast",
    "muted palette", "vibrant", "monochrome", "black and white", "vintage", "documentary",
    # motion
    "slow motion", "time lapse", "fast motion", "freeze frame",
)


def confidence_for(sample: int) -> float:
    """How much a conclusion from `sample` observations is worth.

    Asymptotic to 1 but never reaching it: experience raises confidence, it
    does not create certainty.
    """
    if sample <= 0:
        return 0.0
    return round(sample / (sample + 5.0), 3)


class KnowledgeHandler(StateHandlerBase):
    def __init__(self, state: AppState, lock: RLock, database: Path) -> None:
        super().__init__(state, lock)
        self._store = KnowledgeStore(database)

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    # ---- learning controls ----------------------------------------------

    def settings(self) -> LearningSettings:
        with self.lock:
            return self.state.app_settings.learning.model_copy(deep=True)

    def update_settings(self, patch: LearningSettings) -> LearningSettings:
        with self.lock:
            self.state.app_settings.learning = patch
            return patch.model_copy(deep=True)

    # ---- recording -------------------------------------------------------

    def record(self, event: KnowledgeEvent) -> KnowledgeEvent | None:
        """Store one event, unless the user has that category switched off.

        Returns None when nothing was written, so callers can tell the
        difference between "recorded" and "declined" without guessing.
        """
        category = EVENT_CATEGORIES.get(event.kind, event.category)
        if not self.settings().allows(category):
            return None
        event.category = category
        try:
            stored = self._store.record(event)
        except Exception as exc:  # noqa: BLE001 - learning must never break a render
            logger.warning("Could not record a knowledge event: %s", exc)
            return None
        if stored.model:
            self._rederive(stored.model)
        return stored

    def record_generation(
        self,
        *,
        outcome: str,
        model: str,
        provider: str,
        project_id: str = "",
        scene_id: str = "",
        shot_id: str = "",
        version_number: int | None = None,
        task: str = "video",
        execution_mode: str = "",
        prompt: str = "",
        negative_prompt: str = "",
        duration_seconds: float | None = None,
        error: str = "",
    ) -> KnowledgeEvent | None:
        """Convenience for the generation queue, which is the main source."""
        kind = {
            "success": "generation_completed",
            "failure": "generation_failed",
            "cancelled": "generation_cancelled",
        }.get(outcome, "generation_completed")
        return self.record(
            KnowledgeEvent(
                kind=kind,  # type: ignore[arg-type]
                project_id=project_id,
                scene_id=scene_id,
                shot_id=shot_id,
                version_number=version_number,
                model=model,
                provider=provider,
                task=task,  # type: ignore[arg-type]
                execution_mode=execution_mode,
                prompt=prompt[:2000],
                negative_prompt=negative_prompt[:1000],
                outcome=outcome,
                duration_seconds=duration_seconds,
                error=error[:500],
            )
        )

    # ---- Reproduce evidence ----------------------------------------------

    def record_candidate(
        self,
        *,
        picked: bool,
        model: str,
        provider: str,
        target: str,
        prompt: str,
        negative_prompt: str = "",
        seed: int | None = None,
        spec_keys: list[str] | None = None,
        metrics: dict[str, float] | None = None,
        project_id: str = "",
        shot_id: str = "",
        note: str = "",
        task: Task = "image",
    ) -> KnowledgeEvent | None:
        """One scored candidate (`candidate_scored`) or the user's choice
        (`candidate_picked`). The spec keys are what `hints_for` matches on."""
        return self.record(
            KnowledgeEvent(
                kind="candidate_picked" if picked else "candidate_scored",
                project_id=project_id,
                shot_id=shot_id,
                model=model,
                provider=provider,
                task=task,
                execution_mode=provider,
                prompt=prompt[:2000],
                negative_prompt=negative_prompt[:1000],
                outcome="success",
                seed=seed,
                target=target,
                spec_keys=sorted(set(spec_keys or [])),
                metrics={k: float(v) for k, v in (metrics or {}).items()},
                note=note,
            )
        )

    def hints_for(self, spec_keys: list[str], target: str, *, model: str = "", limit: int = 8) -> PromptHints:
        """Top phrase sets and parameters from candidates that won on shots like
        this one. Empty until at least `_HINT_MIN_WINS` winning events exist,
        so a single lucky render never becomes advice."""
        wanted = set(spec_keys)
        events = self._store.events(model=model, kinds=("candidate_picked", "candidate_scored"), target=target, limit=_PHRASE_EVENT_LIMIT)
        winners: list[tuple[float, KnowledgeEvent]] = []
        for event in events:
            keys = set(event.spec_keys)
            if wanted and keys:
                overlap = len(wanted & keys) / len(wanted | keys)
                if overlap < _HINT_MIN_OVERLAP:
                    continue
            elif wanted and not keys:
                continue
            score = float(event.metrics.get("composite", event.metrics.get("score", 0.0)))
            if event.kind == "candidate_picked":
                score += 1.0
            elif score < _HINT_MIN_SCORE:
                continue
            winners.append((score, event))
        if len(winners) < _HINT_MIN_WINS:
            return PromptHints(sample=len(winners))
        winners.sort(key=lambda item: -item[0])
        top = winners[: max(limit, 3)]
        phrase_counts: dict[str, int] = {}
        for _, event in top:
            for phrase in _phrases_of(event.prompt):
                phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
        ranked = sorted(phrase_counts.items(), key=lambda item: (-item[1], item[0]))
        threshold = 2 if len(top) >= 3 else 1
        phrases = [phrase for phrase, count in ranked if count >= threshold][:limit]
        params: dict[str, float | int] = {}
        steps = [int(e.metrics["steps"]) for _, e in top if "steps" in e.metrics]
        guidance = [float(e.metrics["guidance"]) for _, e in top if "guidance" in e.metrics]
        if steps:
            params["steps"] = sorted(steps)[len(steps) // 2]
        if guidance:
            params["guidance"] = round(sorted(guidance)[len(guidance) // 2], 2)
        return PromptHints(
            phrases=phrases,
            params=params,
            evidence=[f"{e.kind} {e.id} composite={e.metrics.get('composite', 0.0):.2f}" for _, e in top[:5]],
            sample=len(winners),
        )

    # ---- derivation ------------------------------------------------------

    def _rederive(self, model: str) -> list[Observation]:
        """Recompute one model's observations from its events."""
        totals = self._store.model_totals(model)
        events = self._store.events(model=model, limit=200)
        if not events:
            self._store.replace_observations(model, [])
            return []

        provider = next((event.provider for event in events if event.provider), "")
        task = next((event.task for event in events if event.task), "")
        evidence = [event.id for event in events[:_MAX_EVIDENCE]]
        first_seen = min(event.created_at for event in events)
        last_seen = max(event.created_at for event in events)

        def make(kind: str, statement: str, sample: int, *, support: int = 0, against: int = 0) -> Observation:
            return Observation(
                model=model,
                provider=provider,
                task=task,  # type: ignore[arg-type]
                kind=kind,  # type: ignore[arg-type]
                statement=statement,
                # A count is arithmetic: it is as certain as the log itself.
                confidence=1.0 if kind == "fact" else confidence_for(sample),
                support_count=support,
                contradiction_count=against,
                sample_size=sample,
                first_seen=first_seen,
                last_seen=last_seen,
                evidence_event_ids=evidence,
            )

        successes = int(totals["successes"] or 0)
        failures = int(totals["failures"] or 0)
        approvals = int(totals["approvals"] or 0)
        rejections = int(totals["rejections"] or 0)
        attempts = successes + failures
        judged = approvals + rejections

        observations: list[Observation] = []

        # --- facts: counts, stated plainly -------------------------------
        if attempts:
            observations.append(
                make("fact", f"Completed {successes} of {attempts} renders here.", attempts, support=successes, against=failures)
            )
        if judged:
            observations.append(
                make("fact", f"You approved {approvals} of {judged} results.", judged, support=approvals, against=rejections)
            )
        average_seconds = totals["average_seconds"]
        if average_seconds is not None and attempts:
            observations.append(make("fact", f"Averages {average_seconds:.1f}s per job.", attempts))

        # --- generalisations, only where the sample supports one ----------
        if attempts:
            failure_rate = failures / attempts
            kind = "observed_pattern" if attempts >= _PATTERN_MIN_SAMPLE else "hypothesis"
            if failure_rate >= 0.5:
                observations.append(
                    make(kind, "Fails more often than it succeeds on this machine.", attempts, support=failures, against=successes)
                )
            elif failure_rate == 0.0 and attempts >= _PATTERN_MIN_SAMPLE:
                observations.append(make("observed_pattern", "Has not failed here yet.", attempts, support=successes))

        if judged:
            approval_rate = approvals / judged
            kind = "user_preference" if judged >= _PREFERENCE_MIN_SAMPLE else "hypothesis"
            if approval_rate >= 0.7:
                observations.append(
                    make(kind, "You usually keep what this model produces.", judged, support=approvals, against=rejections)
                )
            elif approval_rate <= 0.3:
                observations.append(
                    make(kind, "You usually reject what this model produces.", judged, support=rejections, against=approvals)
                )

        # --- the recommendation, which is a conclusion about the above ----
        if attempts >= _PATTERN_MIN_SAMPLE and successes / attempts >= 0.8 and (not judged or approvals >= rejections):
            observations.append(make("model_recommendation", "A dependable default for this kind of shot.", attempts, support=successes))

        # --- recurring errors are worth surfacing verbatim ----------------
        recurring = self._recurring_error(events)
        if recurring:
            message, count = recurring
            kind = "observed_pattern" if count >= 3 else "hypothesis"
            observations.append(make(kind, f"Recurring failure: {message}", count, support=count))

        observations.sort(key=lambda item: (OBSERVATION_KIND_RANK.get(item.kind, 9), -item.confidence))
        self._store.replace_observations(model, observations)
        return observations

    @staticmethod
    def _recurring_error(events: list[KnowledgeEvent]) -> tuple[str, int] | None:
        """The most common failure message, if one repeats."""
        counts: dict[str, int] = {}
        for event in events:
            if event.kind != "generation_failed" or not event.error:
                continue
            # Collapse to the leading clause; the tail is usually a path or a size.
            key = event.error.split(".")[0].split(":")[0].strip()[:120]
            if key:
                counts[key] = counts.get(key, 0) + 1
        if not counts:
            return None
        message, count = max(counts.items(), key=lambda item: item[1])
        return (message, count) if count >= 2 else None

    # ---- reading ---------------------------------------------------------

    def prompt_patterns(self, model: str) -> list[PromptPattern]:
        """Which prompt vocabulary has worked with this model, and which has not.

        Counted over the events that carry both a prompt and an outcome. A
        phrase used once or twice gets `unclear` — the point is to report what
        the history supports, not to have an opinion about everything.
        """
        events = self._store.events(
            model=model,
            kinds=("generation_completed", "generation_failed", "version_approved", "version_rejected"),
            limit=_PHRASE_EVENT_LIMIT,
        )
        tallies: dict[str, dict[str, int]] = {}
        for event in events:
            prompt = event.prompt.lower()
            if not prompt:
                continue
            for phrase in _PROMPT_PHRASES:
                if phrase not in prompt:
                    continue
                tally = tallies.setdefault(
                    phrase, {"uses": 0, "successes": 0, "failures": 0, "approvals": 0, "rejections": 0}
                )
                tally["uses"] += 1
                if event.kind == "generation_completed":
                    tally["successes"] += 1
                elif event.kind == "generation_failed":
                    tally["failures"] += 1
                elif event.kind == "version_approved":
                    tally["approvals"] += 1
                elif event.kind == "version_rejected":
                    tally["rejections"] += 1

        patterns: list[PromptPattern] = []
        for phrase, tally in tallies.items():
            good = tally["successes"] + tally["approvals"]
            bad = tally["failures"] + tally["rejections"]
            judged = good + bad
            verdict: str = "unclear"
            if judged >= _PHRASE_MIN_USES:
                rate = good / judged
                if rate >= 0.7:
                    verdict = "worked"
                elif rate <= 0.4:
                    verdict = "struggled"
            patterns.append(
                PromptPattern(
                    phrase=phrase,
                    uses=tally["uses"],
                    successes=tally["successes"],
                    failures=tally["failures"],
                    approvals=tally["approvals"],
                    rejections=tally["rejections"],
                    confidence=confidence_for(judged),
                    verdict=verdict,  # type: ignore[arg-type]
                )
            )
        # Most-used first: a pattern you lean on matters more than a rare one.
        patterns.sort(key=lambda item: (-item.uses, item.phrase))
        return patterns

    def profile(self, model: str) -> ModelProfile:
        totals = self._store.model_totals(model)
        events = self._store.events(model=model, limit=1)
        provider = events[0].provider if events else ""
        task = events[0].task if events else ""
        return ModelProfile(
            model=model,
            provider=provider,
            task=task,  # type: ignore[arg-type]
            label=model,
            runs=int(totals["runs"] or 0),
            successes=int(totals["successes"] or 0),
            failures=int(totals["failures"] or 0),
            cancellations=int(totals["cancellations"] or 0),
            approvals=int(totals["approvals"] or 0),
            rejections=int(totals["rejections"] or 0),
            average_seconds=totals["average_seconds"],  # type: ignore[arg-type]
            average_rating=totals["average_rating"],  # type: ignore[arg-type]
            last_used_at=int(totals["last_used_at"] or 0),
            observations=self._store.observations(model=model),
            prompt_patterns=self.prompt_patterns(model),
        )

    def profiles(self) -> list[ModelProfile]:
        seen: set[str] = set()
        profiles: list[ModelProfile] = []
        for model, _provider, _task in self._store.known_models():
            if model in seen:
                continue
            seen.add(model)
            profiles.append(self.profile(model))
        profiles.sort(key=lambda item: item.last_used_at, reverse=True)
        return profiles

    def recent_events(self, *, project_id: str = "", limit: int = 100) -> list[KnowledgeEvent]:
        return self._store.events(project_id=project_id, limit=limit)

    def recommend(self, task: str, candidates: list[str]) -> tuple[str, str]:
        """Pick among models the caller already knows are eligible.

        Only ranks what it was given — routing by capability stays with the
        caller. Returns (model, reason); the reason is shown to the user, so it
        cites the evidence rather than asserting a preference.
        """
        if not candidates:
            return "", "No eligible models."
        scored: list[tuple[float, int, str, str]] = []
        for model in candidates:
            totals = self._store.model_totals(model)
            attempts = int(totals["successes"] or 0) + int(totals["failures"] or 0)
            if attempts == 0:
                scored.append((0.0, 0, model, "no history here yet"))
                continue
            success_rate = int(totals["successes"] or 0) / attempts
            judged = int(totals["approvals"] or 0) + int(totals["rejections"] or 0)
            approval_rate = (int(totals["approvals"] or 0) / judged) if judged else 0.5
            # Weight by confidence so one lucky run does not outrank ten solid ones.
            score = (0.6 * success_rate + 0.4 * approval_rate) * confidence_for(attempts)
            scored.append(
                (score, attempts, model, f"{int(success_rate * 100)}% of {attempts} runs completed here")
            )
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best = scored[0]
        if best[0] <= 0:
            return best[2], "No usage history yet, so this is not a recommendation."
        return best[2], best[3]

    # ---- export / import / reset ----------------------------------------

    def export(self) -> KnowledgeExport:
        return KnowledgeExport(
            events=self._store.events(limit=100_000),
            observations=self._store.observations(),
        )

    def import_knowledge(self, payload: KnowledgeExport, *, replace: bool = False) -> int:
        """Merge another machine's knowledge. Ids collide only if they are the same event."""
        if payload.schema_version != 1:
            raise HTTPError(400, f"Unsupported knowledge export version: {payload.schema_version}")
        if replace:
            self._store.clear()
        for event in payload.events:
            self._store.record(event)
        for model in {event.model for event in payload.events if event.model}:
            self._rederive(model)
        return len(payload.events)

    def reset(self, *, model: str = "", project_id: str = "") -> int:
        removed = self._store.clear(model=model, project_id=project_id)
        if model:
            self._rederive(model)
        elif project_id:
            for profile in self.profiles():
                self._rederive(profile.model)
        return removed

    def summary(self) -> dict[str, object]:
        profiles = self.profiles()
        return {
            "learning": self.settings().model_dump(),
            "event_count": self._store.event_count(),
            "model_count": len(profiles),
            "observation_count": sum(len(profile.observations) for profile in profiles),
            "database": str(self._store.path),
            "updated_at": now_ms(),
        }
