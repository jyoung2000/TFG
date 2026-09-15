"""The cross-project shot library.

The claim the library makes is that a shot saved from one film keeps working
in another — after the source take is deleted, after the source project is
gone. That only holds if the entry is a copy rather than a reference, so most
of these tests attack exactly that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BASE = "/api/shot-library"


def _shot_with_render(client, project: str, title: str = "Shot") -> tuple[str, str, int]:
    """A shot with a completed take whose file exists inside the app's outputs."""
    scene_id = client.post(f"/api/film/projects/{project}/scenes", json={"title": "Scene"}).json()["id"]
    shot_id = client.post(
        f"/api/film/projects/{project}/scenes/{scene_id}/shots",
        json={"title": title, "action": "She turns toward the door"},
    ).json()["id"]
    client.post(
        f"/api/film/projects/{project}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}
    )

    from state import get_state_service

    handler = get_state_service()
    with handler.film.lock:
        film = handler.film.store.load(project)
        found = film.find_shot(shot_id)
        assert found is not None
        _, shot = found
        version = shot.versions[-1]
        outputs = handler.film.store.outputs_dir(project)
        outputs.mkdir(parents=True, exist_ok=True)
        media = outputs / f"{shot_id}-v{version.number}.mp4"
        media.write_bytes(b"\x00\x00\x00\x18ftypmp42 rendered")
        version.status = "complete"
        version.output_path = str(media)
        version.model = "ltxv-13b"
        shot.current_version = version.number
        shot.visual_prompt = "golden hour, slow push in"
        handler.film.store.save(film)
    return scene_id, shot_id, version.number


def _save(client, project: str, shot_id: str, **fields) -> dict:
    payload = {"project_id": project, "shot_id": shot_id, **fields}
    response = client.post(BASE, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class TestSaving:
    def test_a_shot_becomes_a_library_item_with_its_settings(self, client):
        _, shot_id, _ = _shot_with_render(client, "lib-a")
        item = _save(client, "lib-a", shot_id, title="Golden hour push", tags=["Night", " night ", "hero"], rating=4)

        assert item["title"] == "Golden hour push"
        assert item["visual_prompt"] == "golden hour, slow push in"
        assert item["model"] == "ltxv-13b"
        assert item["rating"] == 4
        # Tags are normalised, so "Night" and "night " are one tag.
        assert item["tags"] == ["night", "hero"]
        assert item["lineage"]["shot_id"] == shot_id
        assert item["lineage"]["project_id"] == "lib-a"

    def test_the_preview_is_copied_not_referenced(self, client):
        _, shot_id, _ = _shot_with_render(client, "lib-b")
        item = _save(client, "lib-b", shot_id)
        assert item["preview_kind"] == "video"

        from state import get_state_service

        stored = get_state_service().shot_library.store.preview_path(item["preview_path"])
        assert stored.is_file()
        # And it is in the library's own directory, not the project's.
        assert "shot_library" in str(stored)

    def test_the_entry_survives_the_take_it_came_from_being_deleted(self, client):
        """The point of the library: a copy, so the source can go."""
        scene_id, shot_id, number = _shot_with_render(client, "lib-c")
        item = _save(client, "lib-c", shot_id)

        deleted = client.delete(
            f"/api/film/projects/lib-c/scenes/{scene_id}/shots/{shot_id}/versions/{number}?force=true"
        )
        assert deleted.status_code == 200

        after = client.get(f"{BASE}/{item['id']}").json()
        assert after["visual_prompt"] == "golden hour, slow push in"
        assert client.get(f"{BASE}/{item['id']}/preview").status_code == 200

    def test_the_entry_survives_the_whole_project_being_deleted(self, client):
        """The user deleted the film, or moved machines. The entry keeps working."""
        import shutil

        from state import get_state_service

        _, shot_id, _ = _shot_with_render(client, "lib-d")
        item = _save(client, "lib-d", shot_id)
        shutil.rmtree(get_state_service().film.store.project_dir("lib-d"))

        after = client.get(f"{BASE}/{item['id']}").json()
        assert after["lineage"]["project_id"] == "lib-d", "the lineage is a record, not a link"
        assert client.get(f"{BASE}/{item['id']}/preview").status_code == 200

    def test_a_shot_with_no_render_can_still_be_saved(self, client):
        """The settings are the reusable part; the preview is a bonus."""
        scene_id = client.post("/api/film/projects/lib-e/scenes", json={"title": "S"}).json()["id"]
        shot_id = client.post(
            f"/api/film/projects/lib-e/scenes/{scene_id}/shots", json={"title": "Unrendered"}
        ).json()["id"]
        item = _save(client, "lib-e", shot_id)
        assert item["preview_kind"] == "none"
        assert client.get(f"{BASE}/{item['id']}/preview").status_code == 404

    def test_an_unknown_shot_is_a_404(self, client):
        client.post("/api/film/projects/lib-f/scenes", json={"title": "S"})
        assert client.post(BASE, json={"project_id": "lib-f", "shot_id": "nope"}).status_code == 404


class TestUsingItElsewhere:
    def test_applying_writes_the_settings_onto_another_project_s_shot(self, client):
        _, source_shot, _ = _shot_with_render(client, "lib-src")
        item = _save(client, "lib-src", source_shot, title="Reusable")

        target_scene = client.post("/api/film/projects/lib-dst/scenes", json={"title": "Other"}).json()["id"]
        target_shot = client.post(
            f"/api/film/projects/lib-dst/scenes/{target_scene}/shots", json={"title": "Blank"}
        ).json()["id"]

        applied = client.post(
            f"{BASE}/{item['id']}/apply",
            json={"project_id": "lib-dst", "scene_id": target_scene, "shot_id": target_shot},
        )
        assert applied.status_code == 200
        body = applied.json()
        assert body["visual_prompt"] == "golden hour, slow push in"
        assert body["generation"]["model"] == "ltxv-13b"
        # An applied prompt is an explicit choice; synthesis must not undo it.
        assert body["prompt_locked"] is True

    def test_applying_without_a_shot_adds_one_to_the_scene(self, client):
        _, source_shot, _ = _shot_with_render(client, "lib-src2")
        item = _save(client, "lib-src2", source_shot, title="Adds a shot")
        scene_id = client.post("/api/film/projects/lib-dst2/scenes", json={"title": "Empty"}).json()["id"]

        body = client.post(
            f"{BASE}/{item['id']}/apply", json={"project_id": "lib-dst2", "scene_id": scene_id}
        ).json()
        assert body["title"] == "Adds a shot"

        project = client.get("/api/film/projects/lib-dst2").json()["project"]
        scene = next(s for s in project["scenes"] if s["id"] == scene_id)
        assert len(scene["shots"]) == 1

    def test_editing_the_applied_shot_does_not_change_the_library_item(self, client):
        """Apply copies. Nothing afterwards ties the two together."""
        _, source_shot, _ = _shot_with_render(client, "lib-src3")
        item = _save(client, "lib-src3", source_shot)
        scene_id = client.post("/api/film/projects/lib-dst3/scenes", json={"title": "S"}).json()["id"]
        applied = client.post(
            f"{BASE}/{item['id']}/apply", json={"project_id": "lib-dst3", "scene_id": scene_id}
        ).json()

        client.put(
            f"/api/film/projects/lib-dst3/scenes/{scene_id}/shots/{applied['id']}",
            json={"visual_prompt": "something completely different"},
        )
        assert client.get(f"{BASE}/{item['id']}").json()["visual_prompt"] == "golden hour, slow push in"

    def test_applying_counts_the_use(self, client):
        _, source_shot, _ = _shot_with_render(client, "lib-src4")
        item = _save(client, "lib-src4", source_shot)
        scene_id = client.post("/api/film/projects/lib-dst4/scenes", json={"title": "S"}).json()["id"]
        client.post(f"{BASE}/{item['id']}/apply", json={"project_id": "lib-dst4", "scene_id": scene_id})
        client.post(f"{BASE}/{item['id']}/apply", json={"project_id": "lib-dst4", "scene_id": scene_id})
        assert client.get(f"{BASE}/{item['id']}").json()["used_count"] == 2

    def test_applying_to_an_unknown_scene_is_a_404(self, client):
        _, source_shot, _ = _shot_with_render(client, "lib-src5")
        item = _save(client, "lib-src5", source_shot)
        response = client.post(
            f"{BASE}/{item['id']}/apply", json={"project_id": "lib-src5", "scene_id": "no-such-scene"}
        )
        assert response.status_code == 404


class TestSearchAndFilter:
    @pytest.fixture
    def stocked(self, client) -> list[dict]:
        _, shot_id, _ = _shot_with_render(client, "lib-stock")
        return [
            _save(client, "lib-stock", shot_id, title="Night exterior", tags=["night", "exterior"], rating=5),
            _save(client, "lib-stock", shot_id, title="Day interior", tags=["day", "interior"], rating=2),
            _save(client, "lib-stock", shot_id, title="Night interior", tags=["night", "interior"], rating=4),
        ]

    def _list(self, client, **params) -> list[dict]:
        return client.get(BASE, params=params).json()["items"]

    def test_free_text_searches_titles_prompts_and_tags(self, client, stocked):
        assert {i["title"] for i in self._list(client, q="night")} == {"Night exterior", "Night interior"}
        assert {i["title"] for i in self._list(client, q="exterior")} == {"Night exterior"}

    def test_tags_filter_by_all_of_them_not_any(self, client, stocked):
        both = self._list(client, tags=["night", "interior"])
        assert {i["title"] for i in both} == {"Night interior"}

    def test_favourites_come_first_and_can_be_filtered(self, client, stocked):
        target = stocked[1]["id"]
        client.put(f"{BASE}/{target}", json={"favorite": True})
        listing = self._list(client)
        assert listing[0]["id"] == target
        assert {i["id"] for i in self._list(client, favorite=True)} == {target}

    def test_sorting_by_rating(self, client, stocked):
        ratings = [i["rating"] for i in self._list(client, sort="rating")]
        assert ratings == sorted(ratings, reverse=True)

    def test_tag_counts_come_back_with_the_listing(self, client, stocked):
        body = client.get(BASE).json()
        assert body["tags"]["night"] == 2
        assert body["tags"]["interior"] == 2
        assert body["total"] == 3


class TestCurating:
    @pytest.fixture
    def item(self, client) -> dict:
        _, shot_id, _ = _shot_with_render(client, "lib-curate")
        return _save(client, "lib-curate", shot_id, title="Original", tags=["a"], rating=3)

    def test_editing_only_changes_what_was_sent(self, client, item):
        """A rating edit must not blank the notes."""
        client.put(f"{BASE}/{item['id']}", json={"notes": "Worked well on the wide"})
        updated = client.put(f"{BASE}/{item['id']}", json={"rating": 5}).json()
        assert updated["rating"] == 5
        assert updated["notes"] == "Worked well on the wide"
        assert updated["title"] == "Original"
        assert updated["tags"] == ["a"]

    def test_a_blank_title_is_refused(self, client, item):
        assert client.put(f"{BASE}/{item['id']}", json={"title": "   "}).status_code == 400

    def test_duplicating_copies_the_preview_too(self, client, item):
        copy = client.post(f"{BASE}/{item['id']}/duplicate").json()
        assert copy["id"] != item["id"]
        assert copy["title"] == "Original (copy)"
        assert copy["preview_path"] != item["preview_path"]
        assert client.get(f"{BASE}/{copy['id']}/preview").status_code == 200
        # And the original's preview is untouched.
        assert client.get(f"{BASE}/{item['id']}/preview").status_code == 200

    def test_a_duplicate_starts_its_own_history(self, client, item):
        copy = client.post(f"{BASE}/{item['id']}/duplicate").json()
        assert copy["used_count"] == 0
        assert copy["favorite"] is False


class TestArchiveAndDelete:
    @pytest.fixture
    def item(self, client) -> dict:
        _, shot_id, _ = _shot_with_render(client, "lib-remove")
        return _save(client, "lib-remove", shot_id, title="Removable")

    def test_archiving_hides_it_from_the_default_listing(self, client, item):
        client.post(f"{BASE}/{item['id']}/archive")
        assert client.get(BASE).json()["items"] == []
        archived = client.get(BASE, params={"archived": True}).json()["items"]
        assert [i["id"] for i in archived] == [item["id"]]

    def test_restoring_brings_it_back(self, client, item):
        client.post(f"{BASE}/{item['id']}/archive")
        restored = client.post(f"{BASE}/{item['id']}/restore").json()
        assert restored["archived"] is False
        assert restored["archived_at"] is None
        assert [i["id"] for i in client.get(BASE).json()["items"]] == [item["id"]]

    def test_deleting_is_permanent_and_takes_the_preview(self, client, item):
        from state import get_state_service

        stored = get_state_service().shot_library.store.preview_path(item["preview_path"])
        assert stored.is_file()

        assert client.delete(f"{BASE}/{item['id']}").status_code == 200
        assert client.get(f"{BASE}/{item['id']}").status_code == 404
        assert not stored.exists()

    def test_deleting_an_unknown_item_is_a_404(self, client):
        assert client.delete(f"{BASE}/lib-nope").status_code == 404


class TestItSurvivesRestart:
    def test_the_library_is_read_back_from_disk(self, client, test_state):
        """Not a cache: a fresh handler over the same directory sees the same items."""
        _, shot_id, _ = _shot_with_render(client, "lib-restart")
        item = _save(client, "lib-restart", shot_id, title="Persisted", tags=["keeps"], rating=5)

        from handlers.shot_library_handler import ShotLibraryHandler

        reopened = ShotLibraryHandler(
            state=test_state.state,
            lock=test_state.film.lock,
            root=test_state.shot_library.store.root,
            film_handler=test_state.film,
        )
        again = reopened.get(item["id"])
        assert again.title == "Persisted"
        assert again.tags == ["keeps"]
        assert again.rating == 5
        assert Path(reopened.store.preview_path(again.preview_path)).is_file()
