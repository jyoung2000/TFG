"""Film store persistence, migration, and prompt-synthesis tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from film.film_models import (
    FilmAsset,
    FilmProject,
    FilmScene,
    FilmShot,
    ShotCharacter,
)
from film.film_prompt import synthesize_prompt
from film.film_store import FilmStore, FilmStoreError, migrate
from film.script_parser import parse_script


@pytest.fixture
def store(tmp_path: Path) -> FilmStore:
    return FilmStore(tmp_path / "film_projects")


class TestFilmStore:
    def test_load_creates_empty_project(self, store: FilmStore):
        project = store.load("proj-1")
        assert project.id == "proj-1"
        assert project.schema_version == 1
        assert store.exists("proj-1")

    def test_round_trip(self, store: FilmStore):
        project = store.load("proj-1")
        scene = FilmScene(title="Opening", order=0)
        shot = FilmShot(title="Establishing", duration_seconds=4.5)
        scene.shots.append(shot)
        project.scenes.append(scene)
        project.assets.append(FilmAsset(kind="character", name="Sarah", wardrobe="red coat"))
        store.save(project)

        reloaded = store.load("proj-1")
        assert reloaded.scenes[0].title == "Opening"
        assert reloaded.scenes[0].shots[0].duration_seconds == 4.5
        assert reloaded.assets[0].wardrobe == "red coat"

    def test_invalid_project_id_rejected(self, store: FilmStore):
        with pytest.raises(FilmStoreError):
            store.load("../escape")

    def test_migration_wraps_v0_shots_into_scene(self):
        payload = {
            "id": "old",
            "shots": [{"title": "legacy shot", "duration_seconds": 3.0}],
        }
        migrated = migrate(payload)
        assert migrated["schema_version"] == 1
        project = FilmProject.model_validate(migrated)
        assert len(project.scenes) == 1
        assert project.scenes[0].shots[0].title == "legacy shot"

    def test_migration_applied_on_load(self, store: FilmStore, tmp_path: Path):
        directory = store.project_dir("legacy")
        directory.mkdir(parents=True)
        (directory / "project.json").write_text(
            json.dumps({"id": "legacy", "shots": [{"title": "s1"}]}), encoding="utf-8"
        )
        project = store.load("legacy")
        assert project.schema_version == 1
        assert project.scenes[0].shots[0].title == "s1"

    def test_corrupt_file_preserved_not_destroyed(self, store: FilmStore):
        directory = store.project_dir("bad")
        directory.mkdir(parents=True)
        (directory / "project.json").write_text("{not json", encoding="utf-8")
        project = store.load("bad")
        assert project.scenes == []
        backups = list(directory.glob("project.corrupt-*.json"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "{not json"

    def test_media_path_traversal_refused(self, store: FilmStore):
        store.load("proj-1")
        with pytest.raises(FilmStoreError):
            store.resolve_media_path("proj-1", "../other/secret.png")

    def test_previous_shot_ordering(self):
        project = FilmProject(id="p")
        scene_one = FilmScene(order=0)
        scene_two = FilmScene(order=1)
        first = FilmShot(order=0, title="one")
        second = FilmShot(order=1, title="two")
        third = FilmShot(order=0, title="three")
        scene_one.shots = [second, first]  # store order deliberately scrambled
        scene_two.shots = [third]
        project.scenes = [scene_two, scene_one]

        assert project.previous_shot(first.id) is None
        previous_of_second = project.previous_shot(second.id)
        assert previous_of_second is not None and previous_of_second.id == first.id
        previous_of_third = project.previous_shot(third.id)
        assert previous_of_third is not None and previous_of_third.id == second.id


class TestPromptSynthesis:
    def test_prompt_contains_structured_fields(self):
        project = FilmProject(id="p")
        sarah = FilmAsset(kind="character", name="Sarah", appearance="tall", wardrobe="red coat")
        cafe = FilmAsset(kind="location", name="Cafe", environment="cozy interior")
        project.assets = [sarah, cafe]
        project.settings.style_prompt = "film noir"
        scene = FilmScene(location_id=cafe.id, mood="tense", lighting="low key")
        shot = FilmShot(action="Sarah reaches for the letter")
        shot.characters = [ShotCharacter(asset_id=sarah.id, emotion="anxious")]
        shot.framing.shot_size = "closeup"
        shot.framing.camera_elevation = "low"
        shot.camera_move = "push_in"
        project.scenes = [scene]
        scene.shots = [shot]

        prompt = synthesize_prompt(project, scene, shot)
        assert "close-up" in prompt
        assert "low-angle" in prompt
        assert "Sarah" in prompt and "red coat" in prompt
        assert "anxious" in prompt
        assert "Cafe" in prompt and "cozy interior" in prompt
        assert "tense mood" in prompt
        assert "push in" in prompt
        assert "film noir" in prompt

    def test_prompt_uses_scene_lighting_over_location(self):
        project = FilmProject(id="p")
        cafe = FilmAsset(kind="location", name="Cafe", lighting="fluorescent")
        project.assets = [cafe]
        scene = FilmScene(location_id=cafe.id, lighting="candlelit")
        shot = FilmShot(description="a quiet moment")
        scene.shots = [shot]
        project.scenes = [scene]
        prompt = synthesize_prompt(project, scene, shot)
        assert "candlelit lighting" in prompt
        assert "fluorescent" not in prompt


class TestScriptParser:
    SCRIPT = """INT. COFFEE SHOP - DAY

Sunlight cuts across empty tables. SARAH sits alone, staring at an unopened letter.

SARAH
I can't keep pretending this never happened.

She tears the envelope open.

EXT. CITY STREET - NIGHT

JOHN walks fast through the rain, phone pressed to his ear.
"""

    def test_scene_split_and_metadata(self):
        scenes = parse_script(self.SCRIPT)
        assert len(scenes) == 2
        assert scenes[0].title.startswith("INT. COFFEE SHOP")
        assert scenes[0].time_of_day == "Day"
        assert scenes[0].interior is True
        assert scenes[1].interior is False

    def test_dialogue_attribution(self):
        scenes = parse_script(self.SCRIPT)
        dialogue_shots = [s for s in scenes[0].shots if s.dialogue]
        assert len(dialogue_shots) == 1
        assert dialogue_shots[0].speaker == "SARAH"
        assert "pretending" in dialogue_shots[0].dialogue

    def test_characters_detected(self):
        scenes = parse_script(self.SCRIPT)
        assert "SARAH" in scenes[0].characters
        assert "JOHN" in scenes[1].characters

    def test_action_beats_become_shots(self):
        scenes = parse_script(self.SCRIPT)
        assert len(scenes[0].shots) == 3  # action, dialogue, action
        assert len(scenes[1].shots) == 1
