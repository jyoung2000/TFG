"""Deleting one take.

The risk here is not that a version fails to disappear. It is that deleting a
take quietly undoes a decision the user already made, or removes a file that
was never this app's to remove. Most of these tests are about what deletion
refuses to do.
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROJECT = "deletion-project"


@pytest.fixture
def shot(client) -> tuple[str, str]:
    scene_id = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Scene"}).json()["id"]
    shot_id = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots", json={"title": "Shot"}
    ).json()["id"]
    return scene_id, shot_id


def _render(client, scene_id: str, shot_id: str) -> int:
    """Run one take through the real queue and return its number."""
    client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}
    )
    shot = _shot(client, scene_id, shot_id)
    return shot["versions"][-1]["number"]


def _shot(client, scene_id: str, shot_id: str) -> dict:
    project = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
    scene = next(s for s in project["scenes"] if s["id"] == scene_id)
    return next(s for s in scene["shots"] if s["id"] == shot_id)


def _complete(client, scene_id: str, shot_id: str, number: int, path: Path) -> None:
    """Give a take a real file on disk, inside this project's outputs."""
    from state import get_state_service

    handler = get_state_service()
    with handler.film.lock:
        project = handler.film.store.load(PROJECT)
        found = project.find_shot(shot_id)
        assert found is not None
        _, shot = found
        version = shot.version(number)
        assert version is not None
        outputs = handler.film.store.outputs_dir(PROJECT)
        outputs.mkdir(parents=True, exist_ok=True)
        target = outputs / f"v{number}.mp4"
        target.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        version.status = "complete"
        version.output_path = str(target)
        shot.current_version = number
        shot.status = "review"
        handler.film.store.save(project)


def _delete(client, scene_id: str, shot_id: str, number: int, force: bool = False):
    query = "?force=true" if force else ""
    return client.delete(
        f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/versions/{number}{query}"
    )


class TestWhatDeletionRefuses:
    def test_the_approved_take_cannot_be_deleted(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        client.put(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}", json={"status": "approved"}
        )
        response = _delete(client, scene_id, shot_id, number, force=True)
        assert response.status_code == 400
        assert "approved" in response.json()["error"].lower()
        # And it is still there, still complete.
        version = next(v for v in _shot(client, scene_id, shot_id)["versions"] if v["number"] == number)
        assert version["status"] == "complete"

    def test_the_current_take_needs_force(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        assert _delete(client, scene_id, shot_id, number).status_code == 409
        assert _delete(client, scene_id, shot_id, number, force=True).status_code == 200

    def test_a_take_that_is_still_rendering_cannot_be_deleted(self, client, shot):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        from state import get_state_service

        handler = get_state_service()
        with handler.film.lock:
            project = handler.film.store.load(PROJECT)
            found = project.find_shot(shot_id)
            assert found is not None
            version = found[1].version(number)
            assert version is not None
            version.status = "generating"
            handler.film.store.save(project)

        response = _delete(client, scene_id, shot_id, number, force=True)
        assert response.status_code == 400
        assert "rendering" in response.json()["error"].lower()

    def test_deleting_twice_is_refused_rather_than_silently_repeated(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        assert _delete(client, scene_id, shot_id, number, force=True).status_code == 200
        assert _delete(client, scene_id, shot_id, number, force=True).status_code == 400

    def test_an_unknown_take_is_a_404(self, client, shot):
        scene_id, shot_id = shot
        assert _delete(client, scene_id, shot_id, 99).status_code == 404


class TestMedia:
    def test_the_file_is_removed_from_disk(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        path = Path(
            next(v for v in _shot(client, scene_id, shot_id)["versions"] if v["number"] == number)["output_path"]
        )
        assert path.is_file()

        body = _delete(client, scene_id, shot_id, number, force=True).json()
        assert body["media"] == "removed"
        assert body["removed_path"] == str(path)
        assert not path.exists()

    def test_media_outside_this_apps_outputs_is_left_alone(self, client, shot, tmp_path):
        """A Quick Mode import points at the user's own file. It is not ours to delete."""
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        theirs = tmp_path / "their-own-clip.mp4"
        theirs.write_bytes(b"\x00\x00\x00\x18ftypmp42")

        from state import get_state_service

        handler = get_state_service()
        with handler.film.lock:
            project = handler.film.store.load(PROJECT)
            found = project.find_shot(shot_id)
            assert found is not None
            version = found[1].version(number)
            assert version is not None
            version.status = "complete"
            version.output_path = str(theirs)
            handler.film.store.save(project)

        body = _delete(client, scene_id, shot_id, number, force=True).json()
        assert body["media"] == "kept"
        assert theirs.is_file(), "a file outside this app's outputs must survive"

    def test_a_take_whose_file_already_went_is_reported_as_missing(self, client, shot):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        body = _delete(client, scene_id, shot_id, number, force=True).json()
        assert body["media"] == "missing"


class TestLineageSurvives:
    def test_the_record_stays_as_a_tombstone(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        before = next(v for v in _shot(client, scene_id, shot_id)["versions"] if v["number"] == number)

        _delete(client, scene_id, shot_id, number, force=True)
        after = next(v for v in _shot(client, scene_id, shot_id)["versions"] if v["number"] == number)

        assert after["status"] == "deleted"
        assert after["deleted_at"] is not None
        assert after["output_path"] == ""
        # What produced it survives, so it can still be explained and re-run.
        assert after["prompt"] == before["prompt"]
        assert after["model"] == before["model"]
        assert after["seed"] == before["seed"]
        assert after["shot_snapshot"] == before["shot_snapshot"]

    def test_a_deleted_number_is_never_reused(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        first = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, first, tmp_path)
        _delete(client, scene_id, shot_id, first, force=True)
        second = _render(client, scene_id, shot_id)
        assert second > first
        numbers = [v["number"] for v in _shot(client, scene_id, shot_id)["versions"]]
        assert len(numbers) == len(set(numbers))


class TestTheShotAfterwards:
    def test_the_shot_falls_back_to_the_newest_surviving_take(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        first = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, first, tmp_path)
        second = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, second, tmp_path)

        body = _delete(client, scene_id, shot_id, second, force=True).json()
        assert body["current_version"] == first
        assert body["remaining_versions"] == 1
        assert _shot(client, scene_id, shot_id)["current_version"] == first

    def test_deleting_the_last_take_leaves_the_shot_without_one(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)

        body = _delete(client, scene_id, shot_id, number, force=True).json()
        assert body["current_version"] is None
        assert body["remaining_versions"] == 0
        # A shot in review with nothing to review is not in review.
        assert _shot(client, scene_id, shot_id)["status"] in ("draft", "ready")


class TestItIsRemembered:
    def test_deleting_a_take_is_recorded_against_its_model(self, client, shot, test_state, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        _delete(client, scene_id, shot_id, number, force=True)
        kinds = [event.kind for event in test_state.knowledge.recent_events(limit=500)]
        assert "version_deleted" in kinds

    def test_the_deletion_still_happens_with_learning_off(self, client, shot, tmp_path):
        scene_id, shot_id = shot
        number = _render(client, scene_id, shot_id)
        _complete(client, scene_id, shot_id, number, tmp_path)
        client.put(
            "/api/knowledge/settings",
            json={"enabled": False, "generation": True, "approval": True, "editing": True, "feedback": True},
        )
        assert _delete(client, scene_id, shot_id, number, force=True).status_code == 200
