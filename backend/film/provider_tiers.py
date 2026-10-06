"""Per-task provider capabilities and tiered fallback (phase 9).

A *tier list* is the order providers are tried for one task
(`local → fal → wavespeed`). "local" is whatever this backend renders with
(WanGP, the LTX pipeline or the LTX API); hosted providers need a key and a
model id, and the capability catalog (`media_providers.capabilities_for`)
says whether that model can do the task at all. Local-first is the default
and nothing here ever adds a hosted tier a person did not configure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from film.media_providers import capabilities_for
from film.media_runner import MediaRunResult

Task = Literal["t2i", "i2i", "t2v", "i2v", "edit"]
TASKS: tuple[Task, ...] = ("t2i", "i2i", "t2v", "i2v", "edit")
HOSTED: tuple[str, ...] = ("fal", "wavespeed", "replicate")

#: What the local engine can do today. i2i/edit stay off until the WanGP
#: edit parameters are confirmed (image_generation_handler.edit says so).
LOCAL_TASKS: frozenset[str] = frozenset({"t2i", "t2v", "i2v"})


@dataclass(frozen=True)
class Tier:
    provider: str
    model: str
    #: Empty when usable; otherwise why this tier is skipped.
    skip_reason: str = ""

    @property
    def usable(self) -> bool:
        return not self.skip_reason


@dataclass
class TierPlan:
    task: Task
    tiers: list[Tier] = field(default_factory=list[Tier])

    @property
    def usable(self) -> list[Tier]:
        return [t for t in self.tiers if t.usable]


def catalog_supports(model_id: str, task: Task) -> bool | None:
    """True/False from the capability catalog, None when the model is unknown."""
    caps = capabilities_for(model_id)
    if caps is None:
        return None
    flags = {flag.lower() for flag in caps.tasks}
    return task in flags


def plan(
    task: Task,
    *,
    order: list[str],
    local_available: bool,
    keys: Callable[[str], str],
    models: Callable[[str, Task], str],
) -> TierPlan:
    """Resolve an ordered tier list into concrete, checked tiers.

    `keys(provider)` returns the API key ("" when missing); `models(provider,
    task)` returns the model id configured for that provider and task.
    """
    tiers: list[Tier] = []
    seen: set[str] = set()
    for provider in order or ["local"]:
        name = provider.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        if name == "local":
            if task not in LOCAL_TASKS:
                tiers.append(Tier("local", "", f"local engine cannot do {task} yet"))
            elif not local_available:
                tiers.append(Tier("local", "", "local engine unavailable"))
            else:
                tiers.append(Tier("local", "local"))
            continue
        if name not in HOSTED:
            tiers.append(Tier(name, "", f"unknown provider {name}"))
            continue
        if not keys(name):
            tiers.append(Tier(name, "", f"{name.upper()}_KEY_MISSING"))
            continue
        model = models(name, task).strip()
        if not model:
            tiers.append(Tier(name, "", f"no {name} model id for {task}"))
            continue
        supported = catalog_supports(model, task)
        if supported is False:
            tiers.append(Tier(name, model, f"{model} cannot do {task} per the capability catalog"))
            continue
        tiers.append(Tier(name, model))
    return TierPlan(task=task, tiers=tiers)


@dataclass
class FallbackOutcome:
    result: MediaRunResult
    provider: str
    #: (provider, error) for every tier that failed before this one.
    attempts: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    @property
    def fell_back(self) -> bool:
        return bool(self.attempts)

    def note(self) -> str:
        if not self.attempts:
            return ""
        tried = "; ".join(f"{p}: {e}" for p, e in self.attempts)
        return f"fell back to {self.provider} after {tried}"


def run_with_fallback(
    tiers: list[Tier],
    attempt: Callable[[Tier], MediaRunResult],
    *,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> FallbackOutcome:
    """Try each usable tier in order; a failure moves on, a cancel stops."""
    attempts: list[tuple[str, str]] = []
    last: MediaRunResult | None = None
    last_provider = ""
    for tier in tiers:
        if not tier.usable:
            continue
        if is_cancelled():
            return FallbackOutcome(MediaRunResult(status="cancelled", error="Cancelled"), tier.provider, attempts)
        result = attempt(tier)
        last, last_provider = result, tier.provider
        if result.status == "complete" or result.status == "cancelled":
            return FallbackOutcome(result, tier.provider, attempts)
        attempts.append((tier.provider, result.error or "failed"))
    if last is None:
        skipped = "; ".join(f"{t.provider}: {t.skip_reason}" for t in tiers) or "no providers configured"
        return FallbackOutcome(MediaRunResult(status="failed", error=f"No usable provider ({skipped})"), "", attempts)
    return FallbackOutcome(last, last_provider, attempts[:-1])


def default_order(app_provider: str) -> list[str]:
    """Pre-tiering behaviour: the single configured provider."""
    provider = (app_provider or "local").strip().lower()
    return [provider] if provider else ["local"]
