"""Video intelligence: probe, shot detection, boundary editing, reconstruction.

Detection is exercised against a real signal rather than a stubbed answer: the
fake probe plants cuts at known seconds and the production detector has to find
them. Nothing here needs a video file, a decoder or a model.
"""

from __future__ import annotations

import pytest

from film.shot_detection import (
    DetectionSettings,
    ShotBoundary,
    detect_shots,
    merge_shots,
    set_boundary,
    split_shot,
)
from services.media_probe.fake_media_probe import FakeMediaProbe

#: Only used by the detector tests, which never touch the filesystem.
VIDEO = "/videos/source.mp4"


def _import(client, video, **overrides) -> dict:
    payload = {"path": video, "title": "Source", **overrides}
    response = client.post("/api/video-analysis/import", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class TestShotDetector:
    """The detector alone, over synthetic signal."""

    def _signatures(self, **kwargs):
        return FakeMediaProbe(**kwargs).sample_signatures(VIDEO, sample_fps=8.0)

    def test_finds_the_planted_cuts(self):
        probe = FakeMediaProbe(duration=12.0, shot_seconds=(2.0, 4.0, 6.0, 8.0, 10.0))
        shots = detect_shots(probe.sample_signatures(VIDEO, sample_fps=8.0), 12.0)
        assert len(shots) == 6
        starts = [round(shot.start, 1) for shot in shots]
        assert starts == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        assert all(shot.method == "cut" for shot in shots)

    def test_a_video_with_no_cuts_is_reported_as_uniform_not_invented(self):
        # A continuous take must never come back claiming detected cuts.
        shots = detect_shots(self._signatures(shot_seconds=()), 12.0)
        assert {shot.method for shot in shots} == {"uniform"}
        assert all(shot.confidence == 0.0 for shot in shots)

    def test_minimum_duration_suppresses_cuts_that_are_too_close(self):
        probe = FakeMediaProbe(duration=10.0, shot_seconds=(2.0, 2.2, 2.4, 6.0))
        shots = detect_shots(
            probe.sample_signatures(VIDEO, sample_fps=8.0),
            10.0,
            DetectionSettings(min_shot_seconds=1.5),
        )
        for shot in shots:
            assert shot.duration >= 1.5 - 1e-6

    def test_max_shots_keeps_the_most_confident(self):
        probe = FakeMediaProbe(duration=40.0, shot_seconds=tuple(float(s) for s in range(2, 40, 2)))
        shots = detect_shots(probe.sample_signatures(VIDEO, sample_fps=8.0), 40.0, DetectionSettings(max_shots=5))
        assert len(shots) <= 5

    def test_empty_input_yields_nothing_rather_than_a_fake_shot(self):
        assert detect_shots([], 0.0) == []


class TestBoundaryEditing:
    def _shots(self) -> list[ShotBoundary]:
        return [
            ShotBoundary(0, 0.0, 4.0, 0.9, "cut"),
            ShotBoundary(1, 4.0, 8.0, 0.9, "cut"),
        ]

    def test_split_produces_touching_shots(self):
        shots = split_shot(self._shots(), 0, 2.0)
        assert [(s.start, s.end) for s in shots] == [(0.0, 2.0), (2.0, 4.0), (4.0, 8.0)]
        assert [s.index for s in shots] == [0, 1, 2]

    def test_split_outside_the_shot_is_refused(self):
        with pytest.raises(ValueError):
            split_shot(self._shots(), 0, 6.0)

    def test_merge_joins_neighbours_and_keeps_the_lower_confidence(self):
        shots = merge_shots([ShotBoundary(0, 0.0, 4.0, 0.9, "cut"), ShotBoundary(1, 4.0, 8.0, 0.3, "fade")], 0)
        assert len(shots) == 1
        assert (shots[0].start, shots[0].end) == (0.0, 8.0)
        assert shots[0].confidence == 0.3

    def test_moving_a_boundary_drags_the_neighbour_so_there_is_no_gap(self):
        shots = set_boundary(self._shots(), 1, start=5.0)
        assert shots[0].end == 5.0 and shots[1].start == 5.0

    def test_the_first_shot_cannot_start_later_than_zero(self):
        with pytest.raises(ValueError):
            set_boundary(self._shots(), 0, start=1.0)


class TestAnalysisPipeline:
    def test_import_records_measured_metadata(self, client, video):
        analysis = _import(client, video)
        source = analysis["source"]
        assert source["duration_seconds"] == 12.0
        assert source["fps"] == 24.0
        assert source["aspect_ratio"] == "16:9"
        assert source["codec"] == "h264"
        assert source["has_audio"] is True
        assert analysis["stage"] == "idle"

    def test_a_path_outside_the_allowed_kinds_is_refused(self, client):
        response = client.post("/api/video-analysis/import", json={"path": "/tmp/notes.txt"})
        assert response.status_code == 400

    def test_a_relative_path_is_refused(self, client):
        response = client.post("/api/video-analysis/import", json={"path": "clips/source.mp4"})
        assert response.status_code == 400

    def test_audio_analysis_is_not_promised_on_a_silent_file(self, client, test_state, video):
        test_state.media_probe.has_audio = False
        analysis = _import(client, video, analyze_audio=True)
        assert analysis["analyze_audio"] is False

    def test_detect_then_analyze_without_a_provider_still_describes_shots(self, client, video):
        analysis = _import(client, video)
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        assert len(detected["shots"]) == 6
        assert all(shot["frames"] for shot in detected["shots"])

        analyzed = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
        assert analyzed["stage"] == "complete"
        first = analyzed["shots"][0]
        # No model ran, so measured fields are filled and inference stays empty.
        assert first["editorial"]["cut_type"] == "cut"
        assert first["provenance"] == "measured"
        assert first["visual"]["confidence"] == 0.0
        assert "without a model" in analyzed["message"]

    def test_analyze_before_detect_is_refused(self, client, video):
        analysis = _import(client, video)
        response = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={})
        assert response.status_code == 400

    def test_frames_are_served_only_from_inside_the_analysis(self, client, video):
        analysis = _import(client, video)
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        frame = detected["shots"][0]["frames"][0]["path"]
        assert client.get(f"/api/video-analysis/{analysis['id']}/frame", params={"path": frame}).status_code == 200
        escape = client.get(
            f"/api/video-analysis/{analysis['id']}/frame",
            params={"path": "../../../etc/passwd"},
        )
        assert escape.status_code == 400

    def test_editing_a_boundary_keeps_the_untouched_shots(self, client, video):
        analysis = _import(client, video)
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        last_id = detected["shots"][-1]["id"]
        first_id = detected["shots"][0]["id"]

        split = client.post(
            f"/api/video-analysis/{analysis['id']}/shots/{first_id}/split", json={"at": 1.0}
        ).json()
        assert len(split["shots"]) == 7
        # The shot at the far end was not touched, so it keeps its identity.
        assert split["shots"][-1]["id"] == last_id
        assert split["shots"][0]["boundary_edited"] is True

    def test_detection_does_not_silently_undo_a_manual_edit(self, client, video):
        analysis = _import(client, video)
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        first_id = detected["shots"][0]["id"]
        client.post(f"/api/video-analysis/{analysis['id']}/shots/{first_id}/split", json={"at": 1.0})

        again = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        assert "edited" in again["message"]

    def test_merge_removes_a_boundary(self, client, video):
        analysis = _import(client, video)
        detected = client.post(f"/api/video-analysis/{analysis['id']}/detect").json()
        merged = client.post(
            f"/api/video-analysis/{analysis['id']}/shots/{detected['shots'][0]['id']}/merge"
        ).json()
        assert len(merged["shots"]) == 5
        assert merged["shots"][0]["end"] == 4.0

    def test_prompt_edits_are_pinned_against_regeneration(self, client, video):
        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        analyzed = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
        shot_id = analyzed["shots"][0]["id"]

        edited = client.put(
            f"/api/video-analysis/{analysis['id']}/shots/{shot_id}/prompts",
            json={"video": "my own prompt"},
        ).json()
        assert edited["shots"][0]["prompts"]["video"] == "my own prompt"
        assert edited["shots"][0]["prompts"]["edited"] is True
        assert edited["shots"][0]["provenance"] == "user"

        again = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
        assert again["shots"][0]["prompts"]["video"] == "my own prompt"

    def test_an_unreadable_file_fails_honestly(self, client, test_state, video):
        test_state.media_probe.readable = False
        response = client.post("/api/video-analysis/import", json={"path": video})
        assert response.status_code == 400
        assert "could not read" in response.text.lower()

    def test_interrupted_jobs_are_recovered_as_failed_not_left_running(self, client, test_state, video):
        analysis = _import(client, video)
        stored = test_state.video_analysis.store.load(analysis["id"])
        stored.stage = "analyzing"
        test_state.video_analysis.store.save(stored)

        assert test_state.video_analysis.recover_interrupted() == 1
        recovered = client.get(f"/api/video-analysis/{analysis['id']}").json()
        assert recovered["stage"] == "failed"
        assert "restart" in recovered["error"].lower()

    def test_analyses_are_listed_and_can_be_deleted(self, client, video):
        analysis = _import(client, video)
        assert any(item["id"] == analysis["id"] for item in client.get("/api/video-analysis").json()["analyses"])
        assert client.delete(f"/api/video-analysis/{analysis['id']}").status_code == 200
        assert client.get(f"/api/video-analysis/{analysis['id']}").status_code == 404


class TestReconstruction:
    def test_an_analysis_becomes_a_normal_editable_film_project(self, client, video):
        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={})

        project = client.post(f"/api/video-analysis/{analysis['id']}/reconstruct", json={}).json()
        shots = [shot for scene in project["scenes"] for shot in scene["shots"]]
        assert len(shots) == 6
        # Durations carry over from the source rather than being defaulted.
        assert shots[0]["duration_seconds"] == 2.0
        # Lineage back to the source survives.
        assert shots[0]["source_ref"]["kind"] == "video_analysis"
        assert shots[0]["source_ref"]["analysis_id"] == analysis["id"]
        assert shots[0]["source_ref"]["end"] == 2.0

        # And it is a real project: the film API can load and edit it.
        loaded = client.get(f"/api/film/projects/{project['id']}").json()["project"]
        assert loaded["name"] == analysis["title"]

    def test_reconstruction_is_recorded_on_the_analysis(self, client, video):
        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        project = client.post(f"/api/video-analysis/{analysis['id']}/reconstruct", json={}).json()
        refreshed = client.get(f"/api/video-analysis/{analysis['id']}").json()
        assert refreshed["reconstructed_project_id"] == project["id"]

    def test_reconstructing_before_detection_is_refused(self, client, video):
        analysis = _import(client, video)
        assert client.post(f"/api/video-analysis/{analysis['id']}/reconstruct", json={}).status_code == 400
