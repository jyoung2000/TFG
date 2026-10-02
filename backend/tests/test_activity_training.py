"""LoRA training shows in Activity and History (user, 2026-10-02: "LoRA
generation should show up in the activity tab / history tab").

The History card of a training job previews its samples - which live under
<app data>/training/runs/<id>/, outside the outputs folder, so the media route
refused them and finished training jobs showed "preview unavailable".
"""

from __future__ import annotations

from pathlib import Path


def test_a_training_sample_can_be_previewed(client, test_state, tmp_path: Path) -> None:
    runs = test_state.training.media_root()
    sample = runs / "run-x" / "sample" / "raven_000140.png"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert client.get("/api/film/output", params={"path": str(sample)}).status_code == 200


def test_files_beside_the_training_runs_are_still_refused(client, test_state, tmp_path: Path) -> None:
    secret = test_state.training.media_root().parent / "datasets" / "secret.png"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_bytes(b"x")
    assert client.get("/api/film/output", params={"path": str(secret)}).status_code == 400
