"""Filesystem path policy and secret redaction.

Every renderer-supplied path goes through ``server_utils.path_policy``; every
log record and error body goes through ``logging_policy.redact_secrets``.
These tests pin both down, unit-level and through the HTTP boundary.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from logging_policy import SecretRedactingFilter, install_secret_redaction, redact_secrets
from server_utils.path_policy import (
    PathPolicyError,
    is_within,
    require_absolute_file,
    require_destination,
    require_within_any,
    resolve_within,
)

PROJECT = "security-project"
# Deliberately shaped like real keys so the redactor has to catch them; none is valid.
FAKE_OPENROUTER = "sk-or-v1-0123456789abcdef0123456789abcdef"
FAKE_OPENAI = "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123"
FAKE_GOOGLE = "AIzaSyA-FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAK"


class TestPathPolicyUnit:
    def test_resolve_within_accepts_nested_and_rejects_escapes(self, tmp_path: Path):
        base = tmp_path / "project"
        (base / "captures").mkdir(parents=True)
        assert resolve_within(base, "captures/shot.png") == (base / "captures" / "shot.png").resolve()
        for bad in ("../outside.txt", "captures/../../x", "/etc/passwd", " padded", "", "a\x00b"):
            with pytest.raises(PathPolicyError):
                resolve_within(base, bad)

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_symlink_pointing_outside_is_rejected(self, tmp_path: Path):
        base = tmp_path / "project"
        base.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("no")
        (base / "link.txt").symlink_to(secret)
        assert not is_within(base, base / "link.txt")
        with pytest.raises(PathPolicyError):
            resolve_within(base, "link.txt")
        with pytest.raises(PathPolicyError):
            require_within_any(base / "link.txt", [base])

    def test_require_within_any(self, tmp_path: Path):
        outputs = tmp_path / "policy_outputs"
        outputs.mkdir()
        inside = outputs / "clip.mp4"
        assert require_within_any(str(inside), [tmp_path / "other", outputs]) == inside.resolve()
        with pytest.raises(PathPolicyError, match="absolute"):
            require_within_any("relative/clip.mp4", [outputs])
        with pytest.raises(PathPolicyError, match="outside"):
            require_within_any(str(tmp_path / "clip.mp4"), [outputs])
        with pytest.raises(PathPolicyError):
            require_within_any(str(outputs / ".." / "clip.mp4"), [outputs])

    def test_require_absolute_file(self, tmp_path: Path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x")
        assert require_absolute_file(str(clip), allowed_suffixes=(".mp4",)) == clip.resolve()
        with pytest.raises(PathPolicyError, match="absolute"):
            require_absolute_file("clip.mp4")
        with pytest.raises(PathPolicyError, match="unsupported"):
            require_absolute_file(str(clip), allowed_suffixes=(".mov",))
        with pytest.raises(PathPolicyError, match="not found"):
            require_absolute_file(str(tmp_path / "missing.mp4"))
        with pytest.raises(PathPolicyError, match="required"):
            require_absolute_file("   ")

    def test_require_destination_enforces_suffix(self, tmp_path: Path):
        assert require_destination(str(tmp_path / "film"), suffix=".ltxfilm").name == "film.ltxfilm"
        assert require_destination(str(tmp_path / "film.TXT"), suffix=".ltxfilm").name == "film.TXT.ltxfilm"
        assert require_destination(str(tmp_path / "film.ltxfilm"), suffix=".ltxfilm").name == "film.ltxfilm"
        with pytest.raises(PathPolicyError, match="absolute"):
            require_destination("film.ltxfilm", suffix=".ltxfilm")
        with pytest.raises(PathPolicyError, match="directory"):
            require_destination(str(tmp_path), suffix=".ltxfilm")


class TestPathPolicyOverHttp:
    def test_media_route_rejects_traversal_and_absolute(self, client):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "s"})
        for bad in ("../../etc/passwd", "/etc/passwd", "captures/../../../x"):
            response = client.get(f"/api/film/projects/{PROJECT}/media", params={"path": bad})
            assert response.status_code == 400, bad

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_media_route_rejects_symlink_escape(self, client, test_state, tmp_path: Path):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "s"})
        project_dir = test_state.film._store.project_dir(PROJECT)
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"\x89PNG\r\n")
        (project_dir / "captures").mkdir(exist_ok=True)
        (project_dir / "captures" / "leak.png").symlink_to(outside)
        response = client.get(f"/api/film/projects/{PROJECT}/media", params={"path": "captures/leak.png"})
        assert response.status_code == 400

    def test_output_route_policy(self, client, test_state, tmp_path: Path):
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"x")
        assert client.get("/api/film/output", params={"path": str(outside)}).status_code == 400
        assert client.get("/api/film/output", params={"path": "relative.mp4"}).status_code == 400
        inside = test_state.config.outputs_dir / "clip.mp4"
        inside.write_bytes(b"x")
        assert client.get("/api/film/output", params={"path": str(inside)}).status_code == 200
        assert client.get("/api/film/output", params={"path": str(test_state.config.outputs_dir / "missing.mp4")}).status_code == 404

    def test_export_destination_policy(self, client, tmp_path: Path):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "s"})
        relative = client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": "film.ltxfilm"})
        assert relative.status_code == 400
        directory = client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": str(tmp_path)})
        assert directory.status_code == 400
        renamed = client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": str(tmp_path / "film.exe")})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["path"].endswith("film.exe.ltxfilm")
        assert not (tmp_path / "film.exe").exists()

    def test_import_generation_path_policy(self, client, tmp_path: Path):
        base = {"prompt": "a clip", "duration_seconds": 3}
        relative = client.post(f"/api/film/projects/{PROJECT}/import-generation", json={**base, "output_path": "clip.mp4"})
        assert relative.status_code == 400
        script = tmp_path / "evil.sh"
        script.write_text("echo")
        wrong_type = client.post(f"/api/film/projects/{PROJECT}/import-generation", json={**base, "output_path": str(script)})
        assert wrong_type.status_code == 400
        assert "unsupported" in wrong_type.text
        missing = client.post(
            f"/api/film/projects/{PROJECT}/import-generation", json={**base, "output_path": str(tmp_path / "nope.mp4")}
        )
        assert missing.status_code == 400


class TestSecretRedaction:
    @pytest.mark.parametrize(
        "text",
        [
            f"key={FAKE_OPENROUTER}",
            f"Authorization: Bearer {FAKE_OPENROUTER}",
            f"failed with {FAKE_OPENAI}",
            f"google {FAKE_GOOGLE} rejected",
            "api_key=abcdefghijklmnopqrstuvwxyz",
            'token: "0123456789abcdefghij"',
        ],
    )
    def test_patterns_are_redacted(self, text: str):
        redacted = redact_secrets(text)
        assert "[REDACTED]" in redacted
        for secret in (FAKE_OPENROUTER, FAKE_OPENAI, FAKE_GOOGLE, "abcdefghijklmnopqrstuvwxyz", "0123456789abcdefghij"):
            assert secret not in redacted

    def test_plain_text_untouched(self):
        for text in ("", "shot-42 failed: CUDA out of memory", "model openai/gpt-4o-mini", "seed=12345"):
            assert redact_secrets(text) == text

    def test_logging_filter_rewrites_records(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "auth failed for %s", (FAKE_OPENROUTER,), None)
        assert SecretRedactingFilter().filter(record) is True
        assert FAKE_OPENROUTER not in record.getMessage()
        assert "[REDACTED]" in record.getMessage()

    def test_install_is_idempotent(self):
        root = logging.getLogger()
        install_secret_redaction()
        install_secret_redaction()
        assert sum(isinstance(f, SecretRedactingFilter) for f in root.filters) == 1

    def test_error_bodies_are_redacted_at_the_boundary(self, client, tmp_path: Path):
        # A path that does not exist is echoed in the 400 detail; if it carries
        # something key-shaped the boundary must scrub it.
        leaky = tmp_path / f"{FAKE_OPENROUTER}.mp4"
        response = client.post(
            f"/api/film/projects/{PROJECT}/import-generation",
            json={"prompt": "x", "output_path": str(leaky)},
        )
        assert response.status_code == 400
        assert FAKE_OPENROUTER not in response.text
        assert "[REDACTED]" in response.text

    def test_keys_never_appear_in_project_json_or_settings_response(self, client, test_state):
        client.post("/api/settings", json={"openrouterApiKey": FAKE_OPENROUTER, "geminiApiKey": FAKE_GOOGLE})
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "s"})
        project_text = client.get(f"/api/film/projects/{PROJECT}").text
        assert FAKE_OPENROUTER not in project_text and FAKE_GOOGLE not in project_text
        on_disk = (test_state.film._store.project_dir(PROJECT) / "project.json").read_text()
        assert FAKE_OPENROUTER not in on_disk and FAKE_GOOGLE not in on_disk
        settings_text = client.get("/api/settings").text
        assert FAKE_OPENROUTER not in settings_text and FAKE_GOOGLE not in settings_text
