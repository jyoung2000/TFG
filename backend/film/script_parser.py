"""Deterministic screenplay -> scenes/shots parser (offline storyboard path).

Understands the Fountain-style conventions BlueFish's LLM prompt asks for:
`INT.`/`EXT.` scene headings split scenes; blank-line-separated action blocks
become shots; an ALL-CAPS line followed by text is dialogue. This is the
LLM-free fallback so storyboard generation always works locally; the Gemini
path in the director handler produces richer results when a key is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SCENE_HEADING_RE = re.compile(r"^\s*(INT|EXT|INT/EXT|I/E)[\s.].*", re.IGNORECASE)
_CHARACTER_CUE_RE = re.compile(r"^\s*([A-Z][A-Z0-9 .'\-]{1,30})(\s*\(.*\))?\s*$")
_NON_NAME_CUES = {"CUT TO", "FADE IN", "FADE OUT", "DISSOLVE TO", "SMASH CUT", "THE END"}


@dataclass
class ParsedShot:
    description: str
    dialogue: str = ""
    speaker: str = ""
    characters: list[str] = field(default_factory=list[str])


@dataclass
class ParsedScene:
    title: str
    description: str = ""
    time_of_day: str = ""
    interior: bool | None = None
    shots: list[ParsedShot] = field(default_factory=list[ParsedShot])
    characters: list[str] = field(default_factory=list[str])


def _clean_name(raw: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", raw).strip()


def _time_of_day(heading: str) -> str:
    upper = heading.upper()
    for marker in ("DAWN", "MORNING", "DAY", "AFTERNOON", "DUSK", "EVENING", "NIGHT"):
        if marker in upper:
            return marker.capitalize()
    return ""


def parse_script(content: str) -> list[ParsedScene]:
    """Split a script into scenes and shot-sized beats."""
    lines = content.splitlines()
    scenes: list[ParsedScene] = []
    current: ParsedScene | None = None
    paragraph: list[str] = []
    pending_speaker = ""

    def flush_paragraph() -> None:
        nonlocal paragraph, pending_speaker
        if current is None or not paragraph:
            paragraph = []
            pending_speaker = ""
            return
        text = " ".join(part.strip() for part in paragraph).strip()
        paragraph = []
        if not text:
            pending_speaker = ""
            return
        if pending_speaker:
            current.shots.append(
                ParsedShot(
                    description=f"{pending_speaker} speaks",
                    dialogue=text,
                    speaker=pending_speaker,
                    characters=[pending_speaker],
                )
            )
            if pending_speaker not in current.characters:
                current.characters.append(pending_speaker)
            pending_speaker = ""
        else:
            mentioned = [
                _clean_name(match)
                for match in re.findall(r"\b([A-Z][A-Z'\-]{2,})\b", text)
                if _clean_name(match) not in _NON_NAME_CUES
            ]
            current.shots.append(ParsedShot(description=text, characters=mentioned))
            for name in mentioned:
                if name not in current.characters:
                    current.characters.append(name)

    for line in lines:
        stripped = line.strip()
        if _SCENE_HEADING_RE.match(stripped):
            flush_paragraph()
            title = stripped.rstrip(".")
            current = ParsedScene(
                title=title,
                time_of_day=_time_of_day(title),
                interior=stripped.upper().startswith("INT"),
            )
            scenes.append(current)
            continue
        if current is None:
            # Text before any heading becomes an implicit first scene.
            if stripped:
                current = ParsedScene(title="Scene 1")
                scenes.append(current)
            else:
                continue
        if not stripped:
            flush_paragraph()
            continue
        cue = _CHARACTER_CUE_RE.match(stripped)
        if cue and not paragraph:
            name = _clean_name(cue.group(1))
            if name and name not in _NON_NAME_CUES and len(name.split()) <= 3:
                pending_speaker = name
                continue
        paragraph.append(stripped)

    flush_paragraph()
    return scenes


_SHOT_SIZE_CYCLE: tuple[str, ...] = ("wide", "medium", "closeup", "medium", "mcu")


def suggest_shot_size(index: int, shot: ParsedShot) -> str:
    """First shot of a scene establishes wide; dialogue tightens; else cycle."""
    if index == 0:
        return "wide"
    if shot.dialogue:
        return "mcu" if index % 2 else "closeup"
    return _SHOT_SIZE_CYCLE[index % len(_SHOT_SIZE_CYCLE)]


def suggest_duration(shot: ParsedShot) -> float:
    if shot.dialogue:
        words = len(shot.dialogue.split())
        return float(min(12.0, max(3.0, round(words / 2.5))))
    words = len(shot.description.split())
    return float(min(10.0, max(3.0, round(words / 6) + 3)))
