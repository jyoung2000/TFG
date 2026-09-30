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
        self.systems: list[str] = []

    def chat(self, messages, tools=None, *, json_mode=False, timeout=90):  # noqa: ANN001, ARG002
        from film.llm_providers import LLMReply

        self.calls.append([m.role for m in messages])
        self.systems.append(messages[0].content if messages else "")
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
        # 4 sections + 2 repairs + 1 follow-up for the spec fields still empty
        # = 7 calls; the repair carries the broken reply back.
        assert len(provider.calls) == 7
        assert "scene.time_of_day" in provider.systems[-1] and "camera.focal_mm" in provider.systems[-1]
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
        response = client.post(f"/api/video-reproduce/{analysis_id}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [first, second]})
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
        response = client.post(f"/api/video-analysis/{analysis_id}/recreate", json={"candidates": 1, "rounds": 1, "shot_ids": [analysed["shots"][0]["id"]]})
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

    def test_encode_frames_with_the_real_ffmpeg(self, tmp_path: Path):
        """`-vsync vfr` together with `-r` is refused by ffmpeg 7.1 ("One of
        -r/-fpsmax was specified together a non-CFR -vsync/-fps_mode"), so
        every frames-to-clip encode failed - found live when Video Reproduce's
        reference_video rung could not build its control clip."""
        if not find_ffmpeg():
            pytest.skip("ffmpeg missing")
        from PIL import Image

        from services.media_probe.media_probe_impl import MediaProbeImpl

        frames = []
        for i in range(12):
            frame = tmp_path / f"f{i:03d}.jpg"
            Image.new("RGB", (64, 48), (i * 20, 40, 200 - i * 10)).save(frame)
            frames.append(frame)
        out = FfmpegStitcher().encode_frames(frames, 24, tmp_path / "out" / "clip.mp4")
        info = MediaProbeImpl().probe(str(out))
        assert info["fps"] == pytest.approx(24, rel=0.05)
        assert info["duration_seconds"] == pytest.approx(0.5, abs=0.1)


class TestTheVideoLoopKeepsGoingUntilTheTarget:
    """The video loop must not stop at a fixed number of passes.

    Before: `rounds` was capped at 1-3 (the UI always sent 1), there was no
    target, and every round rendered the same image-to-video request - so a
    run was one pass, however far from the reference it landed.

    After: each shot renders round after round until its best candidate
    reaches `target_score`, climbing a ladder when it plateaus: start frame ->
    start + end frames -> the reference clip itself as an LTX-2 raw control
    video (`VG`) whose strength rises toward 1.0. That last rung converges on
    the reference, so the loop ends at the target, a cancel, or `rounds`.
    """

    @staticmethod
    def _content_aware_frames(fake_services, source):
        """Frames that reflect what was rendered: a clip rendered against the
        reference clip at control strength s is s of the way to the reference
        colour (the stock fake returns one fixed 1x1 frame for everything)."""
        import io
        import re

        import numpy as np
        from PIL import Image

        probe = fake_services.media_probe
        stock = probe.extract_jpeg
        with Image.open(io.BytesIO(stock("reference", 0.0))) as image:
            reference = np.asarray(image.convert("RGB").resize((16, 16)), dtype=np.float64)
        far = np.zeros_like(reference)
        far[..., 1] = 230.0

        def extract_jpeg(path, timestamp, *, max_width=640, quality=82):
            if Path(path) == Path(source):
                return stock(path, timestamp, max_width=max_width, quality=quality)
            data = Path(path).read_bytes() if Path(path).is_file() else b""
            found = re.search(rb"control=([0-9.]+)", data)
            strength = float(found.group(1)) if found else 0.0
            pixels = (far + (reference - far) * strength).clip(0, 255).astype("uint8")
            buffer = io.BytesIO()
            Image.fromarray(pixels, "RGB").save(buffer, format="PNG")
            return buffer.getvalue()

        probe.extract_jpeg = extract_jpeg

    @staticmethod
    def _enable_wangp(test_state, fake_services):
        test_state.config.wangp_enabled = True
        fake_services.wangp_bridge.available = True

    def test_a_shot_keeps_rendering_until_it_reaches_the_target(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        self._enable_wangp(test_state, fake_services)
        self._content_aware_frames(fake_services, video)
        shot_id = analysed["shots"][0]["id"]

        response = client.post(
            f"/api/video-reproduce/{analysed['id']}/start",
            json={"candidates": 1, "shot_ids": [shot_id], "seed": 3, "target_score": 0.95},
        )
        assert response.status_code == 200, response.text
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()

        assert job["status"] == "complete", job["message"]
        shot = job["shots"][0]
        best = next(c for c in shot["candidates"] if c["id"] == shot["best_candidate_id"])
        assert best["scores"]["composite"] >= 0.95, best["scores"]
        strategies = [c["strategy"] for c in shot["candidates"]]
        assert strategies[0] == "start_frame" and "start_end_frames" in strategies and strategies[-1] == "reference_video", strategies

        controlled = [c for c in shot["candidates"] if c["strategy"] == "reference_video"]
        strengths = [c["control_strength"] for c in controlled]
        assert strengths == sorted(strengths) and strengths[0] < strengths[-1], strengths

        # The reference clip reached WanGP as a raw control video with its strength.
        guided = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "video_guide" in m[0]["params"]]
        assert guided, "no render was conditioned on the reference clip"
        assert all(p["video_prompt_type"].endswith("VG") for p in guided)
        assert [p["denoising_strength"] for p in guided] == strengths
        ends = [m[0]["params"] for m in fake_services.wangp_bridge.manifests if "image_end" in m[0]["params"]]
        assert ends, "the start+end rung never sent an end frame"

    def test_without_wangp_the_loop_ends_and_says_why(self, client, video, fake_services, test_state, create_fake_model_files):
        analysed = _analysed(client, video, test_state, create_fake_model_files)
        self._content_aware_frames(fake_services, video)
        shot_id = analysed["shots"][0]["id"]
        client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "shot_ids": [shot_id], "target_score": 0.95})
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        assert job["status"] == "plateau", job["message"]
        assert "WanGP" in job["message"], job["message"]
        assert job["stitched_path"], "the best takes are still stitched"

    def test_no_round_cap_by_default(self):
        from film.video_analysis_api_types import VideoRecreationRequest

        request = VideoRecreationRequest()
        assert request.rounds is None and request.target_score == 0.95
        assert VideoRecreationRequest(rounds=40).rounds == 40
        assert VideoRecreationRequest(target_score=0).target_score == 0.95


class TestAStalledQueueDoesNotHangTheLoop:
    """MEASURED in the installed app: the film queue's thread died inside
    `_finish_version` (a PermissionError saving project.json), the version
    stayed "generating" forever and `_wait` - which had no way out - kept the
    video reproduce job "running" with nothing rendering. A take the queue no
    longer holds must be recorded as failed so the loop can carry on."""

    def test_a_take_the_queue_dropped_is_failed_not_waited_on_forever(self, client, video, fake_services, test_state, create_fake_model_files):
        import threading

        analysed = _analysed(client, video, test_state, create_fake_model_files)
        queue = test_state.film_generation

        def dies(*args, **kwargs):  # noqa: ANN002, ANN003 - stands in for the crash
            raise RuntimeError("queue thread died while finishing the version")

        queue._finish_version = dies  # type: ignore[method-assign]  # noqa: SLF001
        done = threading.Event()
        result: dict = {}

        def run():
            result["response"] = client.post(f"/api/video-reproduce/{analysed['id']}/start", json={"candidates": 1, "rounds": 1, "shot_ids": [analysed["shots"][0]["id"]]})
            done.set()

        threading.Thread(target=run, daemon=True).start()
        assert done.wait(60), "the reproduce loop hung on a take the queue had dropped"
        job = client.get(f"/api/video-reproduce/{analysed['id']}").json()
        candidate = job["shots"][0]["candidates"][0]
        assert candidate["status"] == "failed" and "queue" in candidate["error"].lower(), candidate
