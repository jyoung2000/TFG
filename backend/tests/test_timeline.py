"""Timeline editing.

Two things carry the feature: that every edit is undoable to exactly the state
before it, and that a refused edit changes nothing at all. Both are properties
of the apply path rather than of any one operation, so they are tested against
the real routes with real persistence.
"""

from __future__ import annotations

import pytest

PROJECT = "timeline-project"


def _base(project: str = PROJECT) -> str:
    return f"/api/film/projects/{project}/timeline"


@pytest.fixture
def film(client) -> dict[str, object]:
    """A two-scene film with five shots, so ordering and moves are visible."""
    scene_a = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Interior"}).json()["id"]
    scene_b = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Exterior"}).json()["id"]
    shots: list[str] = []
    for scene, titles in ((scene_a, ["One", "Two", "Three"]), (scene_b, ["Four", "Five"])):
        for title in titles:
            shots.append(
                client.post(
                    f"/api/film/projects/{PROJECT}/scenes/{scene}/shots",
                    json={"title": title, "duration_seconds": 4.0},
                ).json()["id"]
            )
    return {"scene_a": scene_a, "scene_b": scene_b, "shots": shots}


def _act(client, action: str, params: dict[str, object] | None = None, actor: str = "user"):
    return client.post(f"{_base()}/actions", json={"action": action, "params": params or {}, "actor": actor})


def _view(client) -> dict:
    return client.get(_base()).json()


def _titles(client) -> list[str]:
    return [entry["shot_title"] for entry in _view(client)["entries"]]


class TestTheView:
    def test_the_timeline_is_the_film_in_running_order(self, client, film):
        view = _view(client)
        assert [e["shot_title"] for e in view["entries"]] == ["One", "Two", "Three", "Four", "Five"]
        assert view["shot_count"] == 5

    def test_start_times_accumulate_and_the_film_does_not_open_on_a_pause(self, client, film):
        view = _view(client)
        assert view["entries"][0]["start_seconds"] == 0.0
        assert view["entries"][0]["gap_before_seconds"] == 0.0
        assert view["entries"][1]["start_seconds"] >= 4.0
        assert view["total_seconds"] >= 20.0

    def test_an_unrendered_shot_is_not_counted_as_rendered(self, client, film):
        assert _view(client)["rendered_count"] == 0


class TestCutting:
    def test_splitting_divides_the_duration_and_keeps_both_halves(self, client, film):
        shot = film["shots"][0]  # type: ignore[index]
        response = _act(client, "split_shot", {"shot_id": shot, "at_seconds": 1.5})
        assert response.status_code == 200
        entries = response.json()["timeline"]["entries"]
        assert [e["shot_title"] for e in entries][:2] == ["One (a)", "One (b)"]
        assert entries[0]["duration_seconds"] == 1.5
        assert entries[1]["duration_seconds"] == 2.5

    def test_a_split_half_carries_no_render(self, client, film):
        """The second half is a different shot; showing it the original's take would lie."""
        shot = film["shots"][0]  # type: ignore[index]
        ids = _act(client, "split_shot", {"shot_id": shot}).json()["action"]["affected_shot_ids"]
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        second = next(s for sc in project["scenes"] for s in sc["shots"] if s["id"] == ids[1])
        assert second["versions"] == []
        assert second["current_version"] is None

    def test_splitting_outside_the_shot_is_refused(self, client, film):
        shot = film["shots"][0]  # type: ignore[index]
        assert _act(client, "split_shot", {"shot_id": shot, "at_seconds": 9}).status_code == 400
        assert _act(client, "split_shot", {"shot_id": shot, "at_seconds": 0}).status_code == 400

    def test_a_split_that_would_make_a_sliver_is_refused(self, client, film):
        shot = film["shots"][0]  # type: ignore[index]
        assert _act(client, "split_shot", {"shot_id": shot, "at_seconds": 0.1}).status_code == 400

    def test_trimming_moves_nothing_else(self, client, film):
        before = _view(client)["total_seconds"]
        _act(client, "trim_shot", {"shot_id": film["shots"][1], "duration_seconds": 2.0})  # type: ignore[index]
        assert _view(client)["total_seconds"] == pytest.approx(before - 2.0)

    def test_ripple_trimming_holds_the_running_time_when_the_gaps_can_absorb_it(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        _act(client, "set_gap", {"shot_id": shots[2], "gap_seconds": 3.0})
        before = _view(client)["total_seconds"]
        _act(client, "ripple_trim", {"shot_id": shots[1], "duration_seconds": 6.0})
        assert _view(client)["total_seconds"] == pytest.approx(before)

    def test_ripple_trimming_says_what_the_gaps_could_not_absorb(self, client, film):
        body = _act(client, "ripple_trim", {"shot_id": film["shots"][1], "duration_seconds": 10.0}).json()  # type: ignore[index]
        assert "could not absorb" in body["action"]["summary"]


class TestArranging:
    def test_a_shot_moves_between_scenes(self, client, film):
        _act(client, "move_shot", {"shot_id": film["shots"][0], "scene_id": film["scene_b"], "position": 0})  # type: ignore[index]
        assert _titles(client) == ["Two", "Three", "One", "Four", "Five"]

    def test_reordering_a_scene(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        _act(client, "reorder_shots", {"scene_id": film["scene_a"], "ordered_shot_ids": [shots[2], shots[0], shots[1]]})
        assert _titles(client)[:3] == ["Three", "One", "Two"]

    def test_a_partial_reorder_keeps_what_it_does_not_name(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        _act(client, "reorder_shots", {"scene_id": film["scene_a"], "ordered_shot_ids": [shots[2]]})
        assert _titles(client)[:3] == ["Three", "One", "Two"]

    def test_reordering_with_a_shot_from_another_scene_is_refused(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        response = _act(
            client, "reorder_shots", {"scene_id": film["scene_a"], "ordered_shot_ids": [shots[0], shots[3]]}
        )
        assert response.status_code == 400
        assert _titles(client) == ["One", "Two", "Three", "Four", "Five"]

    def test_inserting_at_a_position(self, client, film):
        _act(client, "insert_shot", {"scene_id": film["scene_a"], "position": 1, "title": "New"})
        assert _titles(client)[:4] == ["One", "New", "Two", "Three"]

    def test_duplicating_puts_the_copy_next_to_the_original(self, client, film):
        _act(client, "duplicate_shot", {"shot_id": film["shots"][0]})  # type: ignore[index]
        assert _titles(client)[:2] == ["One", "One (copy)"]

    def test_deleting_removes_it_from_the_running_order(self, client, film):
        _act(client, "delete_shot", {"shot_id": film["shots"][1]})  # type: ignore[index]
        assert _titles(client) == ["One", "Three", "Four", "Five"]


class TestReplacing:
    def test_replacing_keeps_the_place_and_takes_the_content(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{film['scene_a']}/shots/{shots[2]}",
            json={"visual_prompt": "a distinctive prompt"},
        )
        _act(client, "replace_shot", {"shot_id": shots[0], "source_shot_id": shots[2]})

        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        target = next(s for sc in project["scenes"] for s in sc["shots"] if s["id"] == shots[0])
        assert target["visual_prompt"] == "a distinctive prompt"
        # It kept its place, and lost its renders because it is different now.
        assert _titles(client)[0] == "One"
        assert target["versions"] == []

    def test_a_shot_cannot_replace_itself(self, client, film):
        shot = film["shots"][0]  # type: ignore[index]
        assert _act(client, "replace_shot", {"shot_id": shot, "source_shot_id": shot}).status_code == 400

    def test_putting_a_different_take_on_the_timeline(self, client, film):
        scene, shot = film["scene_a"], film["shots"][0]  # type: ignore[index]
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene}/shots/{shot}/generate", json={"kind": "preview"})

        from state import get_state_service

        handler = get_state_service()
        with handler.film.lock:
            project = handler.film.store.load(PROJECT)
            found = project.find_shot(shot)
            assert found is not None
            version = found[1].versions[-1]
            version.status = "complete"
            version.output_path = "/tmp/take.mp4"
            found[1].current_version = None
            handler.film.store.save(project)

        assert _act(client, "replace_with_version", {"shot_id": shot, "version_number": version.number}).status_code == 200
        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        updated = next(s for sc in project["scenes"] for s in sc["shots"] if s["id"] == shot)
        assert updated["current_version"] == version.number

    def test_a_take_with_no_render_cannot_go_on_the_timeline(self, client, film):
        scene, shot = film["scene_a"], film["shots"][0]  # type: ignore[index]
        client.post(f"/api/film/projects/{PROJECT}/scenes/{scene}/shots/{shot}/generate", json={"kind": "preview"})
        response = _act(client, "replace_with_version", {"shot_id": shot, "version_number": 1})
        assert response.status_code == 400


class TestTransitions:
    def test_setting_a_dissolve(self, client, film):
        body = _act(
            client,
            "set_transition",
            {"shot_id": film["shots"][0], "where": "out", "kind": "dissolve", "duration_seconds": 1.0},  # type: ignore[index]
        ).json()
        assert body["timeline"]["entries"][0]["transition_out"]["kind"] == "dissolve"
        assert body["timeline"]["entries"][0]["transition_out"]["duration_seconds"] == 1.0

    def test_an_unknown_transition_is_refused(self, client, film):
        response = _act(client, "set_transition", {"shot_id": film["shots"][0], "where": "out", "kind": "starwipe"})  # type: ignore[index]
        assert response.status_code == 400


class TestShapingTheWholeThing:
    def test_a_montage_changes_the_rhythm_and_nothing_else(self, client, film):
        shots = film["shots"]  # type: ignore[index]
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{film['scene_a']}/shots/{shots[0]}",
            json={"visual_prompt": "untouched by the montage"},
        )
        _act(client, "build_montage", {"scene_id": film["scene_a"], "shot_ids": shots[:3], "shot_seconds": 1.0})

        entries = _view(client)["entries"][:3]
        assert all(entry["duration_seconds"] == 1.0 for entry in entries)
        assert all(entry["gap_before_seconds"] == 0.0 for entry in entries)

        project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        first = next(s for sc in project["scenes"] for s in sc["shots"] if s["id"] == shots[0])
        assert first["visual_prompt"] == "untouched by the montage"

    def test_a_montage_of_one_shot_is_refused(self, client, film):
        response = _act(client, "build_montage", {"scene_id": film["scene_a"], "shot_ids": [film["shots"][0]]})  # type: ignore[index]
        assert response.status_code == 400

    def test_an_opening_goes_first_and_fades_in(self, client, film):
        _act(client, "add_opening", {"title": "Titles"})
        entry = _view(client)["entries"][0]
        assert entry["shot_title"] == "Titles"
        assert entry["transition_in"]["kind"] == "fade_in"

    def test_an_ending_goes_last_and_fades_out(self, client, film):
        _act(client, "add_ending", {"title": "Credits"})
        entry = _view(client)["entries"][-1]
        assert entry["shot_title"] == "Credits"
        assert entry["transition_out"]["kind"] == "fade_out"

    def test_broll_lands_right_after_the_shot_it_cuts_away_from(self, client, film):
        _act(client, "insert_broll", {"after_shot_id": film["shots"][0], "title": "Hands on the dial"})  # type: ignore[index]
        assert _titles(client)[:2] == ["One", "Hands on the dial"]

    def test_aligning_gives_a_scene_one_length(self, client, film):
        _act(client, "align_durations", {"scene_id": film["scene_a"], "duration_seconds": 2.5})
        assert [e["duration_seconds"] for e in _view(client)["entries"][:3]] == [2.5, 2.5, 2.5]

    def test_normalising_is_conservative_about_durations(self, client, film):
        """It fixes what is inconsistent. How long a shot runs is a decision."""
        _act(client, "trim_shot", {"shot_id": film["shots"][0], "duration_seconds": 7.0})  # type: ignore[index]
        _act(client, "normalize_timeline", {"gap_seconds": 0.25})
        entries = _view(client)["entries"]
        assert entries[0]["duration_seconds"] == 7.0
        assert entries[1]["gap_before_seconds"] == 0.25


class TestUndo:
    def test_undo_restores_exactly_what_was_there(self, client, film):
        before = _view(client)
        _act(client, "delete_shot", {"shot_id": film["shots"][1]})  # type: ignore[index]
        assert len(_view(client)["entries"]) == 4

        undone = client.post(f"{_base()}/undo")
        assert undone.status_code == 200
        assert undone.json()["timeline"]["entries"] == before["entries"]

    def test_undo_walks_back_one_edit_at_a_time(self, client, film):
        _act(client, "insert_shot", {"scene_id": film["scene_a"], "title": "A"})
        _act(client, "insert_shot", {"scene_id": film["scene_a"], "title": "B"})
        assert "B" in _titles(client)

        client.post(f"{_base()}/undo")
        assert "B" not in _titles(client)
        assert "A" in _titles(client)

        client.post(f"{_base()}/undo")
        assert "A" not in _titles(client)

    def test_undoing_the_same_edit_twice_is_not_possible(self, client, film):
        _act(client, "delete_shot", {"shot_id": film["shots"][1]})  # type: ignore[index]
        assert client.post(f"{_base()}/undo").status_code == 200
        # The next undo must be the *previous* edit, not this one again.
        assert client.post(f"{_base()}/undo").status_code == 400

    def test_with_nothing_to_undo_it_says_so(self, client, film):
        assert client.post(f"{_base()}/undo").status_code == 400

    def test_a_refused_edit_leaves_nothing_behind(self, client, film):
        before = _view(client)
        assert _act(client, "split_shot", {"shot_id": film["shots"][0], "at_seconds": 99}).status_code == 400  # type: ignore[index]
        assert _view(client) == before
        # And it is not in the history, because it never happened.
        assert client.get(f"{_base()}/history").json()["actions"] == []


class TestTheRecord:
    def test_every_edit_is_recorded_with_a_readable_summary(self, client, film):
        _act(client, "trim_shot", {"shot_id": film["shots"][0], "duration_seconds": 2.0})  # type: ignore[index]
        actions = client.get(f"{_base()}/history").json()["actions"]
        assert len(actions) == 1
        assert actions[0]["action"] == "trim_shot"
        assert actions[0]["summary"] == "Trimmed to 2s"
        assert actions[0]["affected_shot_ids"] == [film["shots"][0]]  # type: ignore[index]

    def test_a_models_edit_is_marked_as_the_directors(self, client, film):
        _act(client, "trim_shot", {"shot_id": film["shots"][0], "duration_seconds": 3.0}, actor="director")  # type: ignore[index]
        _act(client, "trim_shot", {"shot_id": film["shots"][1], "duration_seconds": 3.0}, actor="user")  # type: ignore[index]
        actors = [a["actor"] for a in client.get(f"{_base()}/history").json()["actions"]]
        assert actors == ["director", "user"]

    def test_the_snapshot_never_travels_over_the_api(self, client, film):
        """It is a copy of the whole project, and the caller already has one."""
        body = _act(client, "trim_shot", {"shot_id": film["shots"][0], "duration_seconds": 2.0}).json()  # type: ignore[index]
        assert body["action"]["before"] is None
        assert all(a["before"] is None for a in client.get(f"{_base()}/history").json()["actions"])

    def test_the_history_survives_a_restart(self, client, test_state, film):
        _act(client, "trim_shot", {"shot_id": film["shots"][0], "duration_seconds": 2.0})  # type: ignore[index]

        from handlers.timeline_handler import TimelineHandler

        reopened = TimelineHandler(
            state=test_state.state, lock=test_state.film.lock, film_handler=test_state.film
        )
        actions = reopened.history(PROJECT).actions
        assert [a.action for a in actions] == ["trim_shot"]
        # And it is still undoable after the restart.
        assert actions[0].before is not None

    def test_an_unknown_action_is_refused(self, client, film):
        assert _act(client, "rewrite_everything", {}).status_code == 400


class TestTheDirectorCanDriveIt:
    def test_every_timeline_action_is_a_director_command(self, client, test_state, film):
        names = set(test_state.film_director.command_names())
        assert {"split_shot", "ripple_trim", "build_montage", "undo_timeline_edit"} <= names

    def test_running_one_through_the_director_records_it_as_the_directors(self, client, film):
        response = client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "trim_shot", "params": {"shot_id": film["shots"][0], "duration_seconds": 2.5}},  # type: ignore[index]
        )
        assert response.status_code == 200, response.text
        actions = client.get(f"{_base()}/history").json()["actions"]
        assert actions[-1]["actor"] == "director"
        assert actions[-1]["action"] == "trim_shot"

    def test_the_director_can_undo_its_own_edit(self, client, film):
        before = _view(client)["total_seconds"]
        client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "trim_shot", "params": {"shot_id": film["shots"][0], "duration_seconds": 1.0}},  # type: ignore[index]
        )
        assert _view(client)["total_seconds"] != before
        client.post(
            f"/api/film/projects/{PROJECT}/director/command",
            json={"name": "undo_timeline_edit", "params": {}},
        )
        assert _view(client)["total_seconds"] == before
