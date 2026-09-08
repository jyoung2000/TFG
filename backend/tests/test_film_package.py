"""Film project export/import packages: round-trip, validation, safety."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

PROJECT = "package-project"
TARGET = "package-target"


def _png_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _populate(client, test_state, create_fake_model_files) -> tuple[str, str]:
    create_fake_model_files()
    test_state.state.app_settings.use_local_text_encoder = True
    sarah = client.post(
        f"/api/film/projects/{PROJECT}/assets",
        json={"kind": "character", "name": "Sarah", "wardrobe": "red coat"},
    ).json()["asset"]
    client.post(
        f"/api/film/projects/{PROJECT}/assets/{sarah['id']}/references",
        json={"image_base64": _png_base64(), "name_hint": "sarah-front"},
    )
    client.put(f"/api/film/projects/{PROJECT}/script", json={"content": "INT. CAFE - DAY\n\nSARAH waits."})
    scene = client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "Cafe", "character_ids": [sarah["id"]]}).json()
    shot = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots",
        json={"title": "Wide", "description": "Sarah waits", "duration_seconds": 3},
    ).json()
    client.put(
        f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}",
        json={"characters": [{"asset_id": sarah["id"]}]},
    )
    client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/capture",
        json={"image_base64": _png_base64(), "composition": {"objects": [], "camera": None}},
    )
    response = client.post(
        f"/api/film/projects/{PROJECT}/scenes/{scene['id']}/shots/{shot['id']}/generate", json={"kind": "preview"}
    )
    assert response.status_code == 200, response.text
    return scene["id"], shot["id"]


class TestExportImportRoundTrip:
    def test_round_trip_preserves_project_and_media(self, client, test_state, create_fake_model_files, tmp_path: Path):
        scene_id, shot_id = _populate(client, test_state, create_fake_model_files)
        original = client.get(f"/api/film/projects/{PROJECT}").json()["project"]
        destination = tmp_path / "exports" / "cafe.ltxfilm"

        exported = client.post(
            f"/api/film/projects/{PROJECT}/export",
            json={"destination_path": str(destination), "include_outputs": True},
        )
        assert exported.status_code == 200, exported.text
        summary = exported.json()
        assert summary["scenes"] == 1 and summary["shots"] == 1 and summary["assets"] == 1
        assert summary["includes_outputs"] is True
        assert summary["path"] == str(destination)
        assert destination.is_file()

        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            packaged = json.loads(archive.read("project.json"))
        assert manifest["format"] == "ltx-film-package"
        assert manifest["format_version"] == 1
        assert f"captures/{shot_id}.png" in names
        assert any(n.startswith("references/") for n in names)
        assert f"outputs/{shot_id}-v1.mp4" in names
        # Inside the package the output path is relative, never a machine path.
        assert packaged["scenes"][0]["shots"][0]["versions"][0]["output_path"] == f"outputs/{shot_id}-v1.mp4"

        inspected = client.get(f"/api/film/packages/inspect", params={"package_path": str(destination)})
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["project_name"] == original["name"]
        # capture PNG + composition JSON snapshot + reference image + render
        assert inspected.json()["media_files"] == 4

        imported = client.post(
            f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination)}
        )
        assert imported.status_code == 200, imported.text
        project = imported.json()["project"]
        assert project["id"] == TARGET
        assert project["script"]["content"] == original["script"]["content"]
        assert project["assets"][0]["wardrobe"] == "red coat"
        assert project["assets"][0]["reference_images"][0].startswith("references/")
        shot = project["scenes"][0]["shots"][0]
        assert shot["id"] == shot_id
        assert shot["capture_path"] == f"captures/{shot_id}.png"
        version = shot["versions"][0]
        assert version["status"] == "complete"
        target_dir = test_state.film.store.project_dir(TARGET)
        assert Path(version["output_path"]) == (target_dir / "outputs" / f"{shot_id}-v1.mp4").resolve()
        assert Path(version["output_path"]).is_file()
        assert (target_dir / "captures" / f"{shot_id}.png").is_file()
        # The imported output is servable through the outputs route.
        served = client.get("/api/film/output", params={"path": version["output_path"]})
        assert served.status_code == 200
        media = client.get(f"/api/film/projects/{TARGET}/media", params={"path": shot["capture_path"]})
        assert media.status_code == 200

    def test_export_without_outputs(self, client, test_state, create_fake_model_files, tmp_path: Path):
        _populate(client, test_state, create_fake_model_files)
        destination = tmp_path / "no-outputs.ltxfilm"
        summary = client.post(
            f"/api/film/projects/{PROJECT}/export",
            json={"destination_path": str(destination), "include_outputs": False},
        ).json()
        assert summary["includes_outputs"] is False
        assert summary["warnings"]
        with zipfile.ZipFile(destination) as archive:
            assert not any(n.startswith("outputs/") for n in archive.namelist())
        imported = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination)}).json()
        version = imported["project"]["scenes"][0]["shots"][0]["versions"][0]
        assert version["output_path"] == ""

    def test_import_requires_replace_for_non_empty_project(self, client, test_state, create_fake_model_files, tmp_path: Path):
        _populate(client, test_state, create_fake_model_files)
        destination = tmp_path / "p.ltxfilm"
        client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": str(destination)})
        client.post(f"/api/film/projects/{TARGET}/scenes", json={"title": "Existing"})
        refused = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination)})
        assert refused.status_code == 409
        replaced = client.post(
            f"/api/film/projects/{TARGET}/import", json={"package_path": str(destination), "replace": True}
        )
        assert replaced.status_code == 200
        assert [s["title"] for s in replaced.json()["project"]["scenes"]] == ["Cafe"]

    def test_export_destination_extension_and_missing_dir(self, client, tmp_path: Path):
        client.post(f"/api/film/projects/{PROJECT}/scenes", json={"title": "S"})
        destination = tmp_path / "deep" / "nested" / "film"
        summary = client.post(f"/api/film/projects/{PROJECT}/export", json={"destination_path": str(destination)}).json()
        assert summary["path"].endswith(".ltxfilm")
        assert Path(summary["path"]).is_file()


def _write_package(path: Path, *, manifest: dict | None = None, project: dict | None = None, extra: dict[str, bytes] | None = None) -> Path:
    manifest = manifest if manifest is not None else {"format": "ltx-film-package", "format_version": 1, "media": []}
    project = project if project is not None else {"schema_version": 1, "id": "x", "scenes": []}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("project.json", json.dumps(project))
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return path


class TestPackageValidation:
    def test_not_a_zip(self, client, tmp_path: Path):
        bogus = tmp_path / "bogus.ltxfilm"
        bogus.write_bytes(b"not a zip")
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(bogus)})
        assert response.status_code == 400
        assert "zip" in response.text.lower()

    def test_missing_file(self, client, tmp_path: Path):
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(tmp_path / "nope.ltxfilm")})
        assert response.status_code == 400

    def test_wrong_format_and_future_version(self, client, tmp_path: Path):
        wrong = _write_package(tmp_path / "wrong.ltxfilm", manifest={"format": "something-else", "format_version": 1})
        assert "not an LTX film package" in client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(wrong)}).text
        future = _write_package(tmp_path / "future.ltxfilm", manifest={"format": "ltx-film-package", "format_version": 99})
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(future)})
        assert response.status_code == 400
        assert "format version" in response.text

    def test_schema_validation_error_is_actionable(self, client, tmp_path: Path):
        bad = _write_package(
            tmp_path / "bad.ltxfilm",
            project={"schema_version": 1, "id": "x", "scenes": [{"title": "S", "shots": [{"duration_seconds": "long"}]}]},
        )
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(bad)})
        assert response.status_code == 400
        assert "schema validation" in response.text
        assert "duration_seconds" in response.text
        # Nothing was written for the target project.
        assert client.get(f"/api/film/projects/{TARGET}").json()["project"]["scenes"] == []

    def test_path_traversal_and_disallowed_types_rejected(self, client, tmp_path: Path):
        traversal = _write_package(tmp_path / "trav.ltxfilm", extra={"captures/../../evil.png": b"x"})
        assert client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(traversal)}).status_code == 400
        absolute = _write_package(tmp_path / "abs.ltxfilm", extra={"/etc/passwd.png": b"x"})
        assert client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(absolute)}).status_code == 400
        executable = _write_package(tmp_path / "exe.ltxfilm", extra={"outputs/payload.exe": b"x"})
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(executable)})
        assert response.status_code == 400
        assert "not allowed" in response.text
        stray = _write_package(tmp_path / "stray.ltxfilm", extra={"notes.json": b"{}"})
        assert "outside the media folders" in client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(stray)}).text

    def test_v0_project_json_is_migrated_on_import(self, client, tmp_path: Path):
        legacy = _write_package(
            tmp_path / "legacy.ltxfilm",
            project={"id": "old", "shots": [{"title": "Only shot", "duration_seconds": 2}]},
        )
        response = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(legacy)})
        assert response.status_code == 200, response.text
        project = response.json()["project"]
        assert project["schema_version"] == 1
        assert project["scenes"][0]["shots"][0]["title"] == "Only shot"

    def test_dangling_media_references_are_cleared(self, client, tmp_path: Path):
        package = _write_package(
            tmp_path / "dangling.ltxfilm",
            project={
                "schema_version": 1,
                "id": "d",
                "scenes": [
                    {
                        "title": "S",
                        "shots": [
                            {
                                "capture_path": "captures/missing.png",
                                "versions": [{"number": 1, "kind": "final", "status": "complete", "output_path": "outputs/missing.mp4"}],
                                "current_version": 1,
                            }
                        ],
                    }
                ],
            },
        )
        project = client.post(f"/api/film/projects/{TARGET}/import", json={"package_path": str(package)}).json()["project"]
        shot = project["scenes"][0]["shots"][0]
        assert shot["capture_path"] == ""
        assert shot["versions"][0]["output_path"] == ""
        assert "not included" in shot["versions"][0]["error"]
