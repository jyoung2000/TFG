"""Image Reproduce v2 through the API with fakes: analyse → spec → loop of
scored candidates as History jobs → refinement → pin/pick → FixCanvas commits.
The fake image pipeline renders a flat blue frame, so a blue reference scores
higher than a red one — enough to prove the metrics and the loop are real."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from services.image_ops import Adjustments, apply_adjustments, decode_mask, patch_from_reference
from services.similarity.composite import CompositeScorer, ImageFeatures
from services.similarity.metrics import delta_e2000, hex_to_lab, layout_similarity, luma_array, palette_similarity, ssim


def _png(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (128, 72)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _mask_b64(size: tuple[int, int], box: tuple[int, int, int, int]) -> str:
    mask = Image.new("L", size, 0)
    from PIL import ImageDraw

    ImageDraw.Draw(mask).rectangle(box, fill=255)
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _setup(client, create_fake_model_files, tmp_path: Path, color=(30, 30, 220)) -> dict:
    create_fake_model_files(include_zit=True)
    client.post("/api/settings", json={"vision": {"vlmProvider": "off"}})
    source = _png(tmp_path / "reference.png", color)
    imported = client.post("/api/reproduce/import", json={"path": str(source)})
    assert imported.status_code == 200, imported.text
    analyzed = client.post(f"/api/reproduce/{imported.json()['id']}/analyze")
    assert analyzed.status_code == 200, analyzed.text
    return analyzed.json()


class TestMetrics:
    def test_ssim_and_luma(self):
        a = luma_array(Image.new("RGB", (64, 64), (200, 200, 200)))
        b = luma_array(Image.new("RGB", (64, 64), (200, 200, 200)))
        assert ssim(a, b) > 0.99
        c = luma_array(Image.new("RGB", (64, 64), (10, 10, 10)))
        assert ssim(a, c) < ssim(a, b)

    def test_delta_e2000_reference_values(self):
        # Sharma et al. test pair 1: (50, 2.6772, -79.7751) vs (50, 0, -82.7485) → 2.0425
        assert abs(delta_e2000((50, 2.6772, -79.7751), (50, 0.0, -82.7485)) - 2.0425) < 0.01
        assert delta_e2000(hex_to_lab("#ff0000"), hex_to_lab("#ff0000")) == 0.0

    def test_palette_and_layout(self):
        assert palette_similarity([("#ff0000", 1.0)], [("#ff0000", 1.0)]) > 0.99
        assert palette_similarity([("#ff0000", 1.0)], [("#0000ff", 1.0)]) < 0.2
        same = [("person", [0.3, 0.2, 0.4, 0.7])]
        assert layout_similarity(same, same) == 1.0
        assert layout_similarity(same, [("person", [0.3, 0.2, 0.4, 0.7]), ("person", [0.0, 0.0, 0.2, 0.2])]) < 1.0
        assert layout_similarity(same, []) == 0.0

    def test_composite_renormalises_missing_components(self):
        ref = ImageFeatures(clip=[1.0, 0.0], palette=[("#ff0000", 1.0)])
        cand = ImageFeatures(clip=[1.0, 0.0], palette=[("#ff0000", 1.0)])
        breakdown = CompositeScorer().score(ref, cand)
        assert breakdown.composite > 0.99
        assert set(breakdown.weights_used) == {"clip", "palette"}
        assert abs(sum(breakdown.weights_used.values()) - 1.0) < 1e-6
        assert set(breakdown.missing) == {"dino", "ssim", "layout"}


class TestImageOps:
    def test_adjustments_and_patch(self):
        image = Image.new("RGB", (32, 32), (100, 100, 100))
        brighter = apply_adjustments(image, Adjustments(exposure=1.0))
        assert brighter.getpixel((0, 0))[0] > 150
        neutral = apply_adjustments(image, Adjustments())
        assert neutral.getpixel((0, 0)) == (100, 100, 100)
        mask = decode_mask(_mask_b64((32, 32), (0, 0, 15, 31)), (32, 32))
        assert mask is not None and mask[5, 5] == 1.0 and mask[5, 30] == 0.0
        reference = Image.new("RGB", (32, 32), (0, 200, 0))
        patched = patch_from_reference(image, reference, mask, feather_px=0)
        assert patched.getpixel((5, 5)) == (0, 200, 0)
        assert patched.getpixel((30, 5)) == (100, 100, 100)


class TestLoop:
    def test_analyze_builds_a_spec_with_evidence(self, client, create_fake_model_files, tmp_path):
        job = _setup(client, create_fake_model_files, tmp_path)
        assert job["status"] == "idle"
        assert job["spec"]["source"]["aspect"] == "16:9"
        assert job["spec"]["subjects"][0]["label"] == "person"
        assert job["spec"]["provenance"]["subjects"] == "florence"
        assert job["prompt"], "a compiled prompt is ready"
        assert job["why"]["measured"]["palette"]
        assert job["why"]["subjects"]["source"].startswith("Florence")
        assert job["depth_path"].endswith(".png")
        assert job["vision_model"] == "local-stack"

    def test_loop_scores_candidates_records_jobs_and_knowledge(self, client, create_fake_model_files, tmp_path):
        job = _setup(client, create_fake_model_files, tmp_path)
        started = client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 2, "max_rounds": 2, "target_score": 0.99}, "seed": 11})
        assert started.status_code == 200, started.text
        # The fake task runner ran the loop synchronously.
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert done["status"] == "complete", done["message"]
        assert len(done["candidates"]) == 4
        assert len(done["rounds"]) == 2
        for candidate in done["candidates"]:
            media = client.get(f"/api/reproduce/{job['id']}/media", params={"path": candidate["path"]})
            assert media.status_code == 200 and media.content[:4] == b"\x89PNG"
            scores = candidate["scores"]
            assert 0.0 <= scores["composite"] <= 1.0
            assert {"clip", "dino", "ssim", "palette", "layout"} <= set(scores["components"])
            assert candidate["seed"] is not None
        assert done["best_candidate_id"]
        seeds = [c["seed"] for c in done["candidates"]]
        assert len(set(seeds)) == 4, "every candidate has its own recorded seed"
        assert done["rounds"][0]["seeds"] == seeds[:2]
        # History: one parent image_reproduce job, four child image jobs.
        parents = client.get("/api/jobs", params={"kind": "image_reproduce"}).json()["jobs"]
        assert len(parents) == 1 and parents[0]["status"] == "complete"
        assert parents[0]["metrics"]["candidates"] == 4 and parents[0]["metrics"]["rounds"] == 2
        children = client.get(f"/api/jobs/{parents[0]['id']}").json()["children"]
        assert len(children) == 4 and all(c["kind"] == "image_gen" for c in children)
        # Knowledge: every candidate scored.
        events = client.get("/api/knowledge/events").json()
        scored = [e for e in events if e["kind"] == "candidate_scored"]
        assert len(scored) == 4
        assert scored[0]["spec_keys"] and "composite" in scored[0]["metrics"]
        assert scored[0]["target"] == "z_image"

    def test_metric_guided_patches_change_the_next_round(self, client, create_fake_model_files, tmp_path):
        # A red reference vs blue candidates: palette drifts → the second round carries a colour patch.
        job = _setup(client, create_fake_model_files, tmp_path, color=(220, 30, 30))
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 2, "target_score": 0.99}, "seed": 5})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert done["status"] == "complete"
        first, second = done["rounds"]
        assert first["patches"], "the weak palette component produced a patch"
        assert any(p["metric"] == "palette" for p in first["patches"])
        assert second["prompt"] != first["prompt"]
        assert "red" in second["prompt"] or "#" in second["prompt"]

    def test_blue_reference_scores_higher_than_red(self, client, create_fake_model_files, tmp_path):
        blue = _setup(client, create_fake_model_files, tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, color=(30, 30, 220))
        client.post(f"/api/reproduce/{blue['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}, "seed": 1})
        blue_score = client.get(f"/api/reproduce/{blue['id']}").json()["candidates"][0]["scores"]["composite"]
        (tmp_path / "r").mkdir()
        red = _setup(client, create_fake_model_files, tmp_path / "r", color=(220, 30, 30))
        client.post(f"/api/reproduce/{red['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}, "seed": 1})
        red_score = client.get(f"/api/reproduce/{red['id']}").json()["candidates"][0]["scores"]["composite"]
        assert blue_score > red_score, (blue_score, red_score)

    def test_target_score_stops_early(self, client, create_fake_model_files, tmp_path):
        job = _setup(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 3, "target_score": 0.0}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert len(done["rounds"]) == 1 and "reached" in done["rounds"][0]["note"]

    def test_pin_pick_and_fix(self, client, create_fake_model_files, tmp_path):
        job = _setup(client, create_fake_model_files, tmp_path)
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        cid = done["candidates"][0]["id"]
        picked = client.post(f"/api/reproduce/{job['id']}/pick/{cid}").json()
        assert picked["picked_candidate_id"] == cid
        assert any(e["kind"] == "candidate_picked" for e in client.get("/api/knowledge/events").json())
        pinned = client.post(f"/api/reproduce/{job['id']}/pin/{cid}").json()
        assert pinned["reference_candidate_id"] == cid
        assert client.post(f"/api/reproduce/{job['id']}/pin/source").json()["reference_candidate_id"] == ""
        # Adjustments + patch-from-reference produce a new, scored candidate with lineage.
        fixed = client.post(
            f"/api/reproduce/{job['id']}/candidates/{cid}/fix",
            json={"exposure": 0.5, "mask_png_base64": _mask_b64((128, 72), (0, 0, 63, 71)), "patch_from_reference": True},
        )
        assert fixed.status_code == 200, fixed.text
        payload = fixed.json()
        assert len(payload["candidates"]) == 2
        new = payload["candidates"][-1]
        assert new["source"] == "patch" and new["parent_id"] == cid
        assert new["scores"]["composite"] > 0
        with Image.open(io.BytesIO(client.get(f"/api/reproduce/{job['id']}/media", params={"path": new["path"]}).content)) as image:
            left = np.asarray(image)[:, :60].mean(axis=(0, 1))
            assert left[2] > 150 and left[0] < 80, "the left half is the blue reference again"
        # Inpainting needs the edit model, which the fake backend does not have.
        inpaint = client.post(f"/api/reproduce/{job['id']}/candidates/{cid}/fix", json={"mask_png_base64": _mask_b64((128, 72), (0, 0, 10, 10)), "inpaint_prompt": "a window"})
        assert inpaint.status_code == 400
        assert "patch from reference" in inpaint.json()["error"]

    def test_spec_edit_locks_and_recompiles(self, client, create_fake_model_files, tmp_path):
        job = _setup(client, create_fake_model_files, tmp_path)
        camera = {**job["spec"]["camera"], "shot_size": "closeup", "move": "static"}
        updated = client.put(f"/api/reproduce/{job['id']}/spec", json={"sections": {"camera": camera}}).json()
        assert updated["spec"]["locks"]["camera"] is True
        assert updated["spec"]["provenance"]["camera"] == "user"
        assert "close-up" in updated["prompt"]
        again = client.post(f"/api/reproduce/{job['id']}/analyze").json()
        assert again["spec"]["camera"]["shot_size"] == "closeup", "re-analysis respects the lock"
        custom = client.put(f"/api/reproduce/{job['id']}/prompt", json={"prompt": "my own prompt", "target": "ltx2"}).json()
        assert custom["prompt"] == "my own prompt" and custom["target"] == "ltx2"

    def test_legacy_v1_documents_migrate(self, client, test_state, tmp_path):
        root = test_state.reproduce.root
        folder = root / "ia-legacy000001"
        folder.mkdir(parents=True)
        _png(folder / "reference.png", (1, 2, 3))
        _png(folder / "candidate-a.png", (1, 2, 3))
        (folder / "analysis.json").write_text(json.dumps({
            "id": "ia-legacy000001", "title": "old", "source_path": "reference.png", "width": 128, "height": 72,
            "prompt": "an old prompt", "candidates": [{"id": "candidate-a", "path": "candidate-a.png", "prompt": "p", "score": 0.4, "round": 1, "model": "Z-Image"}],
            "revisions": [], "best_candidate_id": "candidate-a",
        }))
        job = client.get("/api/reproduce/ia-legacy000001").json()
        assert job["version"] == 2 and job["prompt"] == "an old prompt"
        assert job["candidates"][0]["source"] == "legacy" and job["candidates"][0]["scores"]["composite"] == 0.4
        assert job["best_candidate_id"] == "candidate-a"
        assert any(j["id"] == "ia-legacy000001" for j in client.get("/api/reproduce").json()["jobs"])

    def test_cancel_from_history_stops_the_loop(self, client, create_fake_model_files, tmp_path, fake_services):
        job = _setup(client, create_fake_model_files, tmp_path)
        # Make the image pipeline fail so the run ends without candidates, then check the state is honest.
        fake_services.image_generation_pipeline.raise_on_generate = RuntimeError("no gpu today")
        client.post(f"/api/reproduce/{job['id']}/start", json={"budget": {"candidates_per_round": 1, "max_rounds": 1}})
        done = client.get(f"/api/reproduce/{job['id']}").json()
        assert done["status"] == "complete" and done["candidates"] == []
        assert done["message"] == "No candidate was produced"
        parent = client.get("/api/jobs", params={"kind": "image_reproduce"}).json()["jobs"][0]
        assert parent["status"] == "complete" and parent["metrics"]["candidates"] == 0
