"""`@Name` in a shot's text references a project asset (user, 2026-10-04: "have an
easy way to reference assets from styleguides in the prompts so the software can
generate accurate images / videos")."""

from __future__ import annotations

from film.asset_mentions import mentioned_assets, strip_mentions, with_mentions
from film.film_models import FilmAsset, FilmProject, FilmScene, FilmShot, ShotCharacter

RAVEN = FilmAsset(id="a-raven", kind="character", name="Raven")
RAVEN_QA = FilmAsset(id="a-raven-qa", kind="character", name="Raven QA")
LANTERN = FilmAsset(id="a-lantern", kind="prop", name="Ship Lantern")
DOCKS = FilmAsset(id="a-docks", kind="location", name="Docks")
NOIR = FilmAsset(id="a-noir", kind="style", name="Noir", style_prompt="high-contrast black and white film noir")
ASSETS = [RAVEN, RAVEN_QA, LANTERN, DOCKS, NOIR]


def test_a_mention_names_an_asset_case_insensitively_longest_name_first() -> None:
    found = mentioned_assets("@raven qa lifts the @Ship_Lantern at the @Docks.", ASSETS)
    assert [a.id for a in found] == ["a-raven-qa", "a-lantern", "a-docks"]
    assert [a.id for a in mentioned_assets("@Raven walks", ASSETS)] == ["a-raven"]


def test_an_email_or_a_longer_word_is_not_a_mention() -> None:
    assert mentioned_assets("mail me@raven.com, @Ravenous crowds", ASSETS) == []


def test_each_asset_is_mentioned_once() -> None:
    assert [a.id for a in mentioned_assets("@Raven and @RAVEN again", ASSETS)] == ["a-raven"]


def test_the_prompt_reads_naturally_without_the_at_signs() -> None:
    assert strip_mentions("@raven qa lifts the @Ship_Lantern in @Noir style", ASSETS) == (
        "Raven QA lifts the Ship Lantern in high-contrast black and white film noir style"
    )
    assert strip_mentions("@Nobody waves", ASSETS) == "@Nobody waves", "an unknown name is left alone"


def test_a_shot_gains_the_mentioned_cast_and_loses_the_at_signs() -> None:
    shot = FilmShot(id="s1", action="@Raven raises the @Ship Lantern", description="night at the @Docks",
                    characters=[ShotCharacter(asset_id="a-raven-qa")])
    project = FilmProject(id="p1", name="P", assets=ASSETS, scenes=[FilmScene(id="sc1", shots=[shot])])
    resolved = with_mentions(project, shot)
    assert [c.asset_id for c in resolved.characters] == ["a-raven-qa", "a-raven"]
    assert resolved.prop_ids == ["a-lantern"] and resolved.location_id == "a-docks"
    assert resolved.action == "Raven raises the Ship Lantern" and resolved.description == "night at the Docks"
    assert shot.action == "@Raven raises the @Ship Lantern", "the stored shot is untouched"


def test_a_shots_own_location_wins_over_a_mention() -> None:
    shot = FilmShot(id="s1", action="at the @Docks", location_id="a-other")
    project = FilmProject(id="p1", name="P", assets=ASSETS, scenes=[FilmScene(id="sc1", shots=[shot])])
    assert with_mentions(project, shot).location_id == "a-other"
