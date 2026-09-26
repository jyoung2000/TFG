"""The unified job store: every path that does work records itself, and the
History API is the single read side.

These tests drive the real handlers through the FastAPI app with fake
services, then read back `/api/jobs`. A job that is missing, stuck in
`running`, or lacks a decodable thumbnail is a failure.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from services.job_store.job_models import Job
from services.job_store.sqlite_job_store import SqliteJobStore
from tests.test_generation import _enable_local_text_encoding


def _jobs(client, **query) -> list[dict]:
    response = client.get("/api/jobs", params=query)
    assert response.status_code == 200, response.text
    return response.json()["jobs"]


def _assert_thumb(output: dict) -> None:
    assert output["thumb"], output
    thumb = Path(output["thumb"])
    assert thumb.is_file()
    with Image.open(thumb) as image:
        assert image.width > 0 and image.height > 0


class TestStore:
    def test_migrations_and_wal(self, tmp_path: Path):
        store = SqliteJobStore(tmp_path / "jobs.sqlite")
        assert store.schema_version() == 1
        job = store.insert(Job(kind="image_gen", title="one"))
        assert store.get(job.id) is not None
        # Re-opening applies nothing twice and keeps the row.
        again = SqliteJobStore(tmp_path / "jobs.sqlite")
        assert again.schema_version() == 1
        assert again.get(job.id) is not None

    def test_list_pages_newest_first_with_cursor(self, tmp_path: Path):
        store = SqliteJobStore(tmp_path / "jobs.sqlite")
        for index in range(5):
            store.insert(Job(kind="video_gen", title=f"job {index}", created_at=1000 + index, updated_at=1000 + index))
        page, cursor = store.list(limit=2)
        assert [j.title for j in page] == ["job 4", "job 3"]
        assert cursor
        rest, cursor2 = store.list(limit=2, cursor=cursor)
        assert [j.title for j in rest] == ["job 2", "job 1"]
        last, cursor3 = store.list(limit=2, cursor=cursor2)
        assert [j.title for j in last] == ["job 0"]
        assert cursor3 == ""

    def test_filters(self, tmp_path: Path):
        store = SqliteJobStore(tmp_path / "jobs.sqlite")
        store.insert(Job(kind="video_gen", status="running", project_id="p1", prompt="a red fox"))
        store.insert(Job(kind="image_gen", status="complete", project_id="p2", prompt="a blue whale"))
        assert len(store.list(kind="image_gen")[0]) == 1
        assert len(store.list(statuses=("queued", "running"))[0]) == 1
        assert len(store.list(project_id="p2")[0]) == 1
        assert len(store.list(search="fox")[0]) == 1

    def test_interrupted_jobs_fail_on_restart(self, tmp_path: Path):
        store = SqliteJobStore(tmp_path / "jobs.sqlite")
        store.insert(Job(kind="video_gen", status="running"))
        store.insert(Job(kind="download", status="queued"))
        store.insert(Job(kind="image_gen", status="complete"))
        assert store.mark_interrupted("restart") == 2
        assert store.count(status="failed") == 2
        assert store.count(status="complete") == 1


class TestVideoGeneration:
    def test_local_t2v_records_a_complete_job_with_thumbnail(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        r = client.post(
            "/api/generate",
            json={"prompt": "A beautiful sunset", "resolution": "540p", "model": "fast", "duration": "2", "fps": "24"},
        )
        assert r.status_code == 200
        jobs = _jobs(client, kind="video_gen")
        assert len(jobs) == 1
        job = jobs[0]
        assert job["status"] == "complete"
        assert job["progress"] == 100
        assert job["prompt"] == "A beautiful sunset"
        assert job["provider"] == "local"
        assert job["seed"] == r.json()["seed"]
        assert job["params"]["resolution"] == "540p"
        assert [o["path"] for o in job["outputs"]] == [r.json()["video_path"]]
        assert job["outputs"][0]["kind"] == "video"
        _assert_thumb(job["outputs"][0])
        assert job["started_at"] and job["finished_at"] and "seconds" in job["metrics"]

    def test_failed_generation_records_the_error(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        r = client.post("/api/generate", json={"prompt": "x", "imagePath": "/nonexistent/image.png", "duration": "2"})
        assert r.status_code in (400, 404, 500)
        jobs = _jobs(client, kind="video_gen")
        assert len(jobs) == 1
        assert jobs[0]["status"] == "failed"
        assert jobs[0]["error"]

    def test_detail_returns_lineage(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        client.post("/api/generate", json={"prompt": "first", "duration": "2"})
        job = _jobs(client)[0]
        detail = client.get(f"/api/jobs/{job['id']}").json()
        assert detail["job"]["id"] == job["id"]
        assert [j["id"] for j in detail["lineage"]] == [job["id"]]
        assert detail["children"] == []

    def test_rerun_uses_the_same_seed_and_links_the_parent(self, client, test_state, create_fake_model_files):
        create_fake_model_files()
        _enable_local_text_encoding(test_state)
        client.post("/api/generate", json={"prompt": "again", "duration": "2"})
        original = _jobs(client)[0]
        rerun = client.post(f"/api/jobs/{original['id']}/rerun")
        assert rerun.status_code == 200, rerun.text
        # The fake task runner runs synchronously, so the re-run has finished.
        new = client.get(f"/api/jobs/{rerun.json()['id']}").json()["job"]
        assert new["status"] == "complete"
        assert new["seed"] == original["seed"]
        assert new["parent_job_id"] == original["id"]
        assert new["prompt"] == "again"
        lineage = client.get(f"/api/jobs/{new['id']}").json()["lineage"]
        assert [j["id"] for j in lineage] == [original["id"], new["id"]]


class TestImageGeneration:
    def test_image_job_has_one_output_per_image(self, client, create_fake_model_files):
        create_fake_model_files(include_zit=True)
        r = client.post("/api/generate-image", json={"prompt": "A cat", "width": 512, "height": 512, "numImages": 2})
        assert r.status_code == 200
        jobs = _jobs(client, kind="image_gen")
        assert len(jobs) == 1
        assert jobs[0]["status"] == "complete"
        assert len(jobs[0]["outputs"]) == 2
        for output in jobs[0]["outputs"]:
            assert output["kind"] == "image"
            assert output["width"] > 0 and output["height"] > 0
            _assert_thumb(output)


class TestFilmQueue:
    def test_queued_shot_becomes_a_job_with_project_lineage(self, client, test_state, create_fake_model_files):
        from tests.test_film_generation import PROJECT, _enable_local, _setup_shot

        _enable_local(test_state, create_fake_model_files)
        scene_id, shot_id = _setup_shot(client, capture=True, duration=4.0)
        response = client.post(
            f"/api/film/projects/{PROJECT}/scenes/{scene_id}/shots/{shot_id}/generate", json={"kind": "preview"}
        )
        assert response.status_code == 200
        jobs = _jobs(client, project=PROJECT)
        assert len(jobs) == 1
        job = jobs[0]
        assert job["kind"] == "video_gen"
        assert job["status"] == "complete"
        assert job["shot_id"] == shot_id
        assert job["project_id"] == PROJECT
        assert job["title"].startswith("Shot")
        assert job["params"]["kind"] == "preview"
        assert job["outputs"] and job["outputs"][0]["path"].endswith(".mp4")
        assert "seconds" in job["metrics"]


class TestAnalysis:
    def test_detect_and_analyze_record_analysis_jobs(self, client, video):
        from tests.test_video_analysis import _import

        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={})
        jobs = _jobs(client, kind="analysis")
        assert [j["title"].split(":")[0] for j in jobs] == ["Analyze", "Detect"]
        for job in jobs:
            assert job["status"] == "complete", job
            assert job["inputs"]["analysis_id"] == analysis["id"]
        detect = jobs[1]
        assert detect["outputs"], "detect exposes the extracted key frames"
        for output in detect["outputs"]:
            assert output["kind"] == "image"


class TestImageReproduce:
    def test_render_records_a_reproduce_job_with_child_image_jobs(self, client, create_fake_model_files, tmp_path):
        create_fake_model_files(include_zit=True)
        source = tmp_path / "reference.png"
        Image.new("RGB", (80, 48), (230, 45, 45)).save(source)
        imported = client.post("/api/image-analysis/import", json={"path": str(source)}).json()
        client.put(f"/api/image-analysis/{imported["id"]}/prompt", json={"prompt": "a red field"})
        r = client.post(f"/api/image-analysis/{imported['id']}/render", json={"candidates": 2, "rounds": 1})
        assert r.status_code == 200, r.text
        parents = _jobs(client, kind="image_reproduce")
        assert len(parents) == 1
        parent = parents[0]
        assert parent["status"] == "complete"
        assert parent["metrics"]["candidates"] == 2
        assert parent["outputs"] and parent["outputs"][0]["kind"] == "image"
        children = client.get(f"/api/jobs/{parent['id']}").json()["children"]
        assert len(children) == 1
        assert children[0]["kind"] == "image_gen"
        assert children[0]["parent_job_id"] == parent["id"]


class TestDownloads:
    def test_model_download_records_download_jobs(self, client, test_state):
        r = client.post("/api/models/download", json={})
        assert r.status_code == 200
        jobs = _jobs(client, kind="download")
        assert jobs, "each model file is a download job"
        for job in jobs:
            assert job["status"] == "complete", job
            assert job["provider"] == "huggingface"


class TestControl:
    def test_cancel_queued_job(self, client, test_state):
        job = test_state.jobs.queue("video_gen", title="waiting")
        r = client.post(f"/api/jobs/{job.id}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_delete_with_files_only_touches_outputs_dir(self, client, test_state, tmp_path):
        outputs = test_state.config.outputs_dir
        inside = outputs / "made.png"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(inside)
        outside = tmp_path / "elsewhere.png"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(outside)
        job = test_state.jobs.start("image_gen", title="x")
        test_state.jobs.complete(job.id, [str(inside), str(outside)])
        thumbs = [o["thumb"] for o in client.get(f"/api/jobs/{job.id}").json()["job"]["outputs"]]
        assert all(Path(t).is_file() for t in thumbs)
        r = client.delete(f"/api/jobs/{job.id}", params={"files": "true"})
        assert r.status_code == 200
        assert not inside.exists()
        assert outside.exists(), "files outside the outputs directory are never deleted"
        assert not any(Path(t).exists() for t in thumbs)
        assert client.get(f"/api/jobs/{job.id}").status_code == 404

    def test_running_job_cannot_be_deleted(self, client, test_state):
        job = test_state.jobs.start("video_gen", title="busy")
        assert client.delete(f"/api/jobs/{job.id}").status_code == 409

    def test_change_feed_reports_changed_ids(self, test_state):
        jobs = test_state.jobs
        seq = jobs.seq
        job = jobs.start("image_gen", title="feed")
        new_seq, changed = jobs.wait_for_changes(seq, timeout=0.1)
        assert new_seq > seq
        assert changed == [job.id]
        assert jobs.wait_for_changes(new_seq, timeout=0.05) == (new_seq, [])

    def test_progress_writes_are_rate_limited_but_never_lose_the_final_value(self, test_state):
        jobs = test_state.jobs
        job = jobs.start("video_gen", title="steps")
        for step in range(0, 101, 5):
            jobs.progress(job.id, step, "inference")
        assert jobs.get(job.id).progress == 100

    def test_recover_interrupted_on_startup(self, test_state):
        jobs = test_state.jobs
        job = jobs.start("video_gen", title="was running")
        assert jobs.recover_interrupted() == 1
        assert jobs.get(job.id).status == "failed"
        assert "restart" in jobs.get(job.id).error.lower()

    def test_import_legacy_quick_history_is_idempotent(self, client, test_state):
        clip = test_state.config.outputs_dir / "quick.mp4"
        clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        payload = {"entries": [{"prompt": "old clip", "video_path": str(clip), "seed": 7, "created_at": 1700000000000}]}
        first = client.post("/api/jobs/import", json=payload).json()
        assert first == {"imported": 1, "skipped": 0}
        second = client.post("/api/jobs/import", json=payload).json()
        assert second == {"imported": 0, "skipped": 1}
        job = _jobs(client, kind="video_gen")[0]
        assert job["created_at"] == 1700000000000 and job["seed"] == 7
        assert job["outputs"][0]["kind"] == "video"


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_png_helper_is_valid() -> None:
    assert base64.b64encode(_png_bytes())
