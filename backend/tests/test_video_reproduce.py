"""Video Reproduce v2: per-shot film-queue jobs, snapping, I2V conditioning,
scoring, lineage, pick/redo/stitch, cancel — all against fakes, plus the real
ffmpeg stitcher over the synthetic sample clip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from film.video_analysis_models import VideoAnalysis
from handlers.video_generation_handler import get_allowed_durations
from services.motion import MotionSummary
from services.stitcher.video_stitcher import FfmpegStitcher, StitchError, find_ffmpeg

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _import(client, video, **overrides) -> dict:
    response = client.post("/api/video-analysis/import", json={"path": video, "title": "Source", **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def _analysed(client, video, test_state, create_fake_model_files) -> dict:
    from tests.test_generation import _enable_local_text_encoding

    create_fake_model_files()
    _enable_local_text_encoding(test_state)
    analysis = _import(client, video)
    client.post(f"/api/video-analysis/{analysis['id']}/detect")
    analysed = client.post(f"/api/video-analysis/{analysis['id']}/analyze", json={}).json()
    assert analysed["stage"] == "complete"
    return analysed


class TestMotionInAnalysis:
    def test_flow_fills_motion_camera_move_and_spec(self, client, video, fake_services, test_state, create_fake_model_files):
        fake_services.motion.default = MotionSummary(
            analyzed=True, model="fake-flow", pan=0.01, tilt=0.0, zoom=0.0, roll=0.0,
            magnitude=0.012, subject_motion=0.002, jitter=0.1, handheld=False, pacing="slow", frames_sampled=10, confidence=0.9,
        )
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot = analysed["shots"][0]
        # One flow pass per shot, over that shot's span.
        assert len(fake_services.motion.calls) == len(analysed["shots"])
        assert fake_services.motion.calls[0][1:] == (shot["start"], shot["end"])
        assert shot["motion"]["analyzed"] is True
        assert shot["cinematography"]["camera_movement"] == "pan left"
        assert shot["cinematography"]["is_static"] is False
        assert shot["provenance"] == "measured"
        assert shot["spec"]["provenance"]["motion"] == "flow"
        assert shot["spec"]["motion"]["dominant"]["pan"] == pytest.approx(0.01)
        assert shot["spec"]["camera"]["move"]
        assert shot["spec"]["source"]["kind"] == "video_shot"
        assert "pan left" in shot["prompts"]["video"]

    def test_flow_failure_degrades_to_the_stills_pass(self, client, video, fake_services, test_state, create_fake_model_files):
        fake_services.motion.fail_with = RuntimeError("decoder exploded")
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        shot = analysed["shots"][0]
        assert analysed["stage"] == "complete"
        assert shot["motion"]["analyzed"] is False
        assert "Motion analysis unavailable" in shot["evidence_note"]


class _ScriptedProvider:
    """An LLMProvider that answers from a queue; the analysis handler asks one
    section at a time and repairs a broken reply once."""

    name = "scripted"
    model = "scripted-vlm"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[str]] = []

    def chat(self, messages, tools=None, *, json_mode=False, timeout=90):  # noqa: ANN001, ARG002
        from film.llm_providers import LLMReply

        self.calls.append([m.role for m in messages])
        text = self.replies.pop(0) if self.replies else "{}"
        return LLMReply(text=text, tool_calls=[], model=self.model)


class TestPerSectionVlm:
    def test_sections_are_asked_separately_and_repaired_once(self, client, video, test_state, fake_services, create_fake_model_files):
        analysis = _import(client, video)
        client.post(f"/api/video-analysis/{analysis['id']}/detect")
        handler = test_state.video_analysis
        loaded = handler.load(analysis["id"])
        loaded.shots = loaded.shots[:1]
        handler.store.save(loaded)

        visual = json.dumps({"description": "A woman at a console", "subjects": ["woman"], "location": "control room", "shot_size": "medium", "lighting": "warm window light", "confidence": 0.7})
        cine_broken = "Sure! Here is the camera read: pan right, handheld"
        cine_fixed = json.dumps({"camera_position": "eye level", "camera_movement": "pan right", "movement_types": ["pan"], "is_static": False, "confidence": 0.6})
        narrative = json.dumps({"what_happens": "She checks a readout", "narrative_purpose": "setup", "confidence": 0.5})
        lens_bad_twice = "not json"
        provider = _ScriptedProvider([visual, cine_broken, cine_fixed, narrative, lens_bad_twice, lens_bad_twice])

        result = handler.analyze(analysis["id"], provider)
        shot = result.shots[0]
        assert shot.visual.subjects == ["woman"]
        assert shot.visual.location == "control room"
        # Optical flow measured the move: the model's guess does not overwrite it.
        assert shot.cinematography.camera_movement != "pan right"
        assert shot.cinematography.camera_position == "eye level"
        assert shot.narrative.what_happens == "She checks a readout"
        assert shot.narrative.pacing  # timed, kept
        assert shot.provenance == "inferred"
        assert "prompt_lens" in shot.evidence_note  # the one section that never parsed is named
        # 4 sections + 2 repairs = 6 calls; the repair carries the broken reply back.
        assert len(provider.calls) == 6
        assert provider.calls[2] == ["system", "user", "assistant", "user"]
        # The VLM's read landed in the spec where the local stack left gaps.
        assert shot.spec.scene.location == "control room"
        assert shot.spec.provenance.get("scene") == "vlm"


class TestReproduceLoop:
    def test_one_job_per_candidate_with_lineage_snapping_and_i2v(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        analysis_id = analysed["id"]
        fake_services.fast_video_pipeline.generate_calls.clear()

        response = client.post(f"/api/video-analysis/{analysis_id}/recreate", json={"candidates": 2, "rounds": 1, "seed": 40})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "complete"
        assert payload["shots_generated"] == len(analysed["shots"]) == 6
        assert len(payload["video_paths"]) == 12

        job = client.get(f"/api/video-reproduce/{analysis_id}").json()
        assert job["status"] == "complete"
        assert job["project_id"]
        assert len(job["shots"]) == 6
        for shot in job["shots"]:
            # Duration snapped to what the model allows (never the raw 2.0 s shot length).
            assert shot["duration_seconds"] in get_allowed_durations("ltx-2-3-fast", "540p", 24)
            assert shot["start_frame"].startswith("frames/")
            assert shot["prompt"]
            assert len(shot["candidates"]) == 2
            assert shot["best_candidate_id"] and shot["picked_candidate_id"]
            for candidate in shot["candidates"]:
                assert candidate["status"] == "complete"
                assert Path(candidate["path"]).is_file()
                assert candidate["scores"]["composite"] > 0
                assert candidate["motion_match"] is not None
                assert candidate["frames"], "frame thumbnails are extracted for the strip"
        # Seeds are fixed and recorded: seed + (round-1)*100 + n.
        assert [c["seed"] for c in job["shots"][0]["candidates"]] == [40, 41]

        # Every render was image-to-video from the shot's start frame, at the snapped length.
        calls = fake_services.fast_video_pipeline.generate_calls
        assert len(calls) == 12
        assert all(call["images"] for call in calls)
        assert all(call["num_frames"] > 24 * 5 for call in calls)

        # History: one parent, twelve video_gen children, each on its film shot.
        detail = client.get(f"/api/jobs/{job['job_id']}").json()
        parent = detail["job"]
        assert parent["kind"] == "video_reproduce" and parent["status"] == "complete"
        assert parent["inputs"]["analysis_id"] == analysis_id
        mine = [c for c in detail["children"] if c["kind"] == "video_gen"]
        assert len(mine) == 12
        assert all(c["shot_id"] and c["project_id"] == job["project_id"] for c in mine)
        assert all(c["metrics"].get("scores") for c in mine)
        # The stitched result exists and is the parent's first output.
        assert job["stitched_path"]
        stitched = Path(parent["outputs"][0]["path"])
        assert stitched.is_file() and stitched.name == job["stitched_path"]
        assert fake_services.stitcher.calls[-1][0] == [Path(s["candidates"][0]["path"]) if s["picked_candidate_id"] == s["candidates"][0]["id"] else Path(s["candidates"][1]["path"]) for s in job["shots"]]
        # Media is served only for recorded files.
        assert client.get(f"/api/video-reproduce/{analysis_id}/media", params={"path": job["stitched_path"]}).status_code == 200
        assert client.get(f"/api/video-reproduce/{analysis_id}/media", params={"path": job["shots"][0]["candidates"][0]["path"]}).status_code == 200
        assert client.get(f"/api/video-reproduce/{analysis_id}/media", params={"path": "../analysis.json"}).status_code == 400
        # Knowledge saw every scored candidate as a video task.
        events = test_state.knowledge.store.events(kinds=["candidate_scored"], limit=100)
        assert len(events) == 12 and all(e.task == "video" for e in events)

    def test_shot_selection_pick_redo_and_restitch(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        analysis_id = analysed["id"]
        first, second = analysed["shots"][0]["id"], analysed["shots"][1]["id"]
        response = client.post(f"/api/video-reproduce/{analysis_id}/start", json={"candidates": 1, "shot_ids": [first, second]})
        assert response.status_code == 200, response.text
        job = client.get(f"/api/video-reproduce/{analysis_id}").json()
        assert [s["shot_id"] for s in job["shots"]] == [first, second]
        assert len(fake_services.fast_video_pipeline.generate_calls) == 2

        redone = client.post(f"/api/video-reproduce/{analysis_id}/shots/{first}/redo").json()
        shot = next(s for s in redone["shots"] if s["shot_id"] == first)
        assert len(shot["candidates"]) == 2
        assert shot["candidates"][1]["round"] == 2
        other = shot["candidates"][1]["id"] if shot["picked_candidate_id"] != shot["candidates"][1]["id"] else shot["candidates"][0]["id"]
        picked = client.post(f"/api/video-reproduce/{analysis_id}/shots/{first}/pick/{other}").json()
        assert next(s for s in picked["shots"] if s["shot_id"] == first)["picked_candidate_id"] == other
        before = picked["stitched_path"]
        stitched = client.post(f"/api/video-reproduce/{analysis_id}/stitch").json()
        assert stitched["stitched_path"] and stitched["stitched_path"] != before
        assert fake_services.stitcher.calls[-1][0][0] == Path(next(c for c in shot["candidates"] if c["id"] == other)["path"])
        assert client.post(f"/api/video-reproduce/{analysis_id}/shots/{first}/pick/nope").status_code == 404

    def test_a_failed_render_is_recorded_not_hidden(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        analysis_id = analysed["id"]
        fake_services.fast_video_pipeline.raise_on_generate = RuntimeError("CUDA out of memory")
        response = client.post(f"/api/video-analysis/{analysis_id}/recreate", json={"candidates": 1, "shot_ids": [analysed["shots"][0]["id"]]})
        assert response.status_code == 200, response.text
        fake_services.fast_video_pipeline.raise_on_generate = None
        job = client.get(f"/api/video-reproduce/{analysis_id}").json()
        candidate = job["shots"][0]["candidates"][0]
        assert candidate["status"] == "failed"
        assert "out of memory" in candidate["error"]
        assert job["stitched_path"] == ""
        assert "1 failed" in job["message"]
        assert client.post(f"/api/video-reproduce/{analysis_id}/stitch").status_code == 400

    def test_cancel_from_history_stops_the_loop(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        analysis_id = analysed["id"]
        handler = test_state.video_reproduce

        # Cancel as soon as the first render lands: the loop must stop before the second shot.
        original = handler._score  # noqa: SLF001 - hook the first scored candidate

        def score_then_cancel(job, shot, candidate):  # noqa: ANN001
            original(job, shot, candidate)
            handler.cancel(analysis_id)

        handler._score = score_then_cancel  # type: ignore[method-assign]
        response = client.post(f"/api/video-analysis/{analysis_id}/recreate", json={"candidates": 1})
        handler._score = original  # type: ignore[method-assign]
        assert response.status_code == 200
        job = client.get(f"/api/video-reproduce/{analysis_id}").json()
        assert job["status"] == "cancelled"
        rendered = [c for s in job["shots"] for c in s["candidates"]]
        assert len(rendered) == 1
        parent = client.get(f"/api/jobs/{job['job_id']}").json()["job"]
        assert parent["status"] == "cancelled"
        # A second run is allowed afterwards.
        assert client.post(f"/api/video-analysis/{analysis_id}/recreate", json={"candidates": 1, "shot_ids": [analysed["shots"][0]["id"]]}).status_code == 200

    def test_unknown_shot_ids_and_unanalysed_video_are_refused(self, client, video, test_state, create_fake_model_files):
        analysis = _import(client, video)
        assert client.post(f"/api/video-reproduce/{analysis['id']}/start", json={"candidates": 1}).status_code == 400
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        assert client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "shot_ids": ["nope"]}).status_code == 400
        assert client.get("/api/video-reproduce/no-such-analysis").status_code == 404


class TestRealStitcher:
    def test_ffmpeg_concat_doubles_the_sample_clip(self, tmp_path: Path):
        clip = SAMPLES / "clip-01.mp4"
        if not clip.is_file() or not find_ffmpeg():
            pytest.skip("sample clip or ffmpeg missing")
        from services.media_probe.media_probe_impl import MediaProbeImpl

        probe = MediaProbeImpl()
        single = probe.probe(str(clip))["duration_seconds"]
        out = FfmpegStitcher().concat([clip, clip], tmp_path / "out" / "stitched.mp4")
        assert out.is_file() and out.stat().st_size > 0
        assert probe.probe(str(out))["duration_seconds"] == pytest.approx(single * 2, rel=0.1)

    def test_missing_input_is_an_error(self, tmp_path: Path):
        with pytest.raises(StitchError):
            FfmpegStitcher(ffmpeg="ffmpeg").concat([tmp_path / "missing.mp4"], tmp_path / "x.mp4")
