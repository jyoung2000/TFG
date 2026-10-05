"""`@Name` mentions of project assets in a shot's text (user, 2026-10-04: "have an
easy way to reference assets from styleguides in the prompts so the software can
generate accurate images / videos").

A mention is `@` (at the start or after a non-alphanumeric character) followed by
an asset's name, case-insensitively, the longest name first ("Raven QA" before
"Raven"); `_` stands for a space. A mentioned character, prop or location joins
the shot's cast, so its style-guide images are the references; in the prompt the
mention reads as the plain name (a style asset reads as its style prompt).
"""

from __future__ import annotations

from collections.abc import Sequence

from film.film_models import FilmAsset, FilmProject, FilmShot, ShotCharacter


def _norm(text: str) -> str:
    return text.replace("_", " ").lower()


def _scan(text: str, assets: Sequence[FilmAsset]) -> list[tuple[int, int, FilmAsset]]:
    """(start, end, asset) of each mention: `start` is the `@`, `end` after the name."""
    names = sorted((a for a in assets if a.name.strip()), key=lambda a: len(a.name.strip()), reverse=True)
    lowered = _norm(text)
    found: list[tuple[int, int, FilmAsset]] = []
    i = 0
    while i < len(text):
        if text[i] == "@" and (i == 0 or not text[i - 1].isalnum()):
            matched = False
            for asset in names:
                name = _norm(asset.name.strip())
                end = i + 1 + len(name)
                if lowered.startswith(name, i + 1) and (end == len(text) or not text[end].isalnum()):
                    found.append((i, end, asset))
                    i = end
                    matched = True
                    break
            if matched:
                continue
        i += 1
    return found


def mentioned_assets(text: str, assets: Sequence[FilmAsset]) -> list[FilmAsset]:
    """The assets `text` mentions, in order, each once."""
    out: list[FilmAsset] = []
    for _, _, asset in _scan(text, assets):
        if all(a.id != asset.id for a in out):
            out.append(asset)
    return out


def strip_mentions(text: str, assets: Sequence[FilmAsset]) -> str:
    """`text` with each mention read as the asset's name (a style asset: its style prompt)."""
    parts: list[str] = []
    last = 0
    for start, end, asset in _scan(text, assets):
        parts.append(text[last:start])
        parts.append(asset.style_prompt.strip() if asset.kind == "style" and asset.style_prompt.strip() else asset.name.strip())
        last = end
    parts.append(text[last:])
    return "".join(parts)


def with_mentions(project: FilmProject, shot: FilmShot) -> FilmShot:
    """A copy of `shot` with every asset its text mentions in its cast (characters,
    props; the location when it has none) and its text read without the `@`."""
    assets = project.assets
    fields = ("description", "action", "visual_prompt", "dialogue")
    mentioned: list[FilmAsset] = []
    for field in fields:
        for asset in mentioned_assets(getattr(shot, field), assets):
            if all(a.id != asset.id for a in mentioned):
                mentioned.append(asset)
    if not mentioned:
        return shot
    resolved = shot.model_copy(deep=True)
    for field in fields:
        setattr(resolved, field, strip_mentions(getattr(shot, field), assets))
    for asset in mentioned:
        if asset.kind == "character" and all(c.asset_id != asset.id for c in resolved.characters):
            resolved.characters.append(ShotCharacter(asset_id=asset.id))
        elif asset.kind == "prop" and asset.id not in resolved.prop_ids:
            resolved.prop_ids.append(asset.id)
        elif asset.kind == "location" and not resolved.location_id:
            resolved.location_id = asset.id
    return resolved
