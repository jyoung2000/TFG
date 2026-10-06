"""Installed models, uninstall and storage location (user, 2026-10-04: "I want the
user to have a place in settings where they can easily see the local ai models
installed, see how much allocation ... change where ai models are stored, or
uninstall ai models entirely")."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from _routes._errors import HTTPError
from handlers.model_store_handler import ModelStoreHandler


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    return path


class Store:
    def __init__(self, tmp_path: Path) -> None:
        self.ckpts = tmp_path / "wangp" / "ckpts"
        self.models = tmp_path / "app" / "models"
        self.loras = tmp_path / "app" / "loras"
        self.busy = ""
        self.released = 0
        self.deleted_loras: list[str] = []
        _write(self.ckpts / "qwen_edit_int8.safetensors", 2000)
        _write(self.ckpts / "qwen_vae.safetensors", 300)
        _write(self.ckpts / "flux_klein_int8.safetensors", 1000)
        _write(self.ckpts / "Qwen2.5-VL-7B-Instruct" / "te_int8.safetensors", 900)
        _write(self.ckpts / "Qwen2.5-VL-7B-Instruct" / "config.json", 10)
        _write(self.models / "zero123plus-v1.2" / "unet" / "w.safetensors", 700)
        _write(self.models / "face" / "sface.onnx", 40)
        _write(self.loras / "z_image" / "raven.safetensors", 130)
        _write(self.loras / "qwen_image_edit" / "angles.safetensors", 30)
        self.definitions = [
            {"id": "qwen_edit_2511", "name": "Qwen Image Edit 2511", "urls": ["https://x/qwen_edit_int8.safetensors", "https://x/qwen_edit_bf16.safetensors"], "installed": True},
            {"id": "qwen_edit_other", "name": "Qwen Image Edit (shares the VAE)", "urls": ["https://x/qwen_vae.safetensors"], "installed": True},
            {"id": "qwen_layered", "name": "Qwen layered (shares the VAE too)", "urls": ["https://x/qwen_vae.safetensors", "https://x/layered.safetensors"], "installed": True},
            {"id": "flux2_klein_4b", "name": "FLUX.2 Klein 4B", "urls": ["https://x/flux_klein_int8.safetensors"], "installed": True},
            {"id": "ltx2", "name": "LTX-2 (not downloaded)", "urls": ["https://x/ltx.safetensors"], "installed": False},
        ]
        self.registry = [{"id": "lora-1", "name": "Raven", "file": str(self.loras / "z_image" / "raven.safetensors")}]
        self.handler = ModelStoreHandler(
            checkpoints=self.ckpts, models_dir=self.models, lora_root=self.loras,
            definitions=lambda: self.definitions, lora_registry=lambda: self.registry,
            delete_lora=self.deleted_loras.append, busy=lambda: self.busy, release_models=self._release,
        )

    def _release(self) -> None:
        self.released += 1


def _by_id(store: Store) -> dict[str, dict[str, object]]:
    return {m.id: m.model_dump() for m in store.handler.inventory().models}


def test_every_installed_model_is_listed_with_its_size(tmp_path: Path) -> None:
    store = Store(tmp_path)
    models = _by_id(store)
    assert models["wangp:qwen_edit_2511"]["size_bytes"] == 2000 and models["wangp:qwen_edit_2511"]["name"] == "Qwen Image Edit 2511"
    assert models["wangp:flux2_klein_4b"]["size_bytes"] == 1000
    assert "wangp:ltx2" not in models, "not downloaded: not installed"
    assert models["component:Qwen2.5-VL-7B-Instruct"]["size_bytes"] == 910, "a text encoder no model json names: a shared component"
    assert models["folder:zero123plus-v1.2"]["size_bytes"] == 700 and "Zero123++" in str(models["folder:zero123plus-v1.2"]["name"])
    assert models["lora:lora-1"]["name"] == "Raven" and models["lora:lora-1"]["size_bytes"] == 130
    assert models["lora-file:qwen_image_edit/angles.safetensors"]["size_bytes"] == 30, "a helper LoRA outside the registry"
    inventory = store.handler.inventory()
    assert inventory.total_bytes == 2000 + 300 + 1000 + 910 + 700 + 40 + 130 + 30


def test_a_file_two_installed_models_use_is_counted_once_and_shown_as_shared(tmp_path: Path) -> None:
    store = Store(tmp_path)
    models = _by_id(store)
    assert models["wangp:qwen_edit_other"]["size_bytes"] == 0 and models["wangp:qwen_edit_other"]["shared_bytes"] == 300
    assert models["wangp:qwen_layered"]["shared_bytes"] == 300


def test_uninstall_deletes_a_models_own_files_and_keeps_shared_ones(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.handler.uninstall("wangp:qwen_edit_2511")
    assert not (store.ckpts / "qwen_edit_int8.safetensors").exists()
    assert (store.ckpts / "qwen_vae.safetensors").exists() and (store.ckpts / "flux_klein_int8.safetensors").exists()
    assert store.released == 1, "the WanGP worker lets go of the model first"
    store.handler.uninstall("wangp:qwen_edit_other")
    assert (store.ckpts / "qwen_vae.safetensors").exists(), "the layered model still uses it"


def test_uninstall_removes_folders_components_and_loras(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.handler.uninstall("folder:zero123plus-v1.2")
    assert not (store.models / "zero123plus-v1.2").exists() and (store.models / "face").exists()
    store.handler.uninstall("component:Qwen2.5-VL-7B-Instruct")
    assert not (store.ckpts / "Qwen2.5-VL-7B-Instruct").exists()
    store.handler.uninstall("lora:lora-1")
    assert store.deleted_loras == ["lora-1"], "a registry LoRA goes through the registry"
    store.handler.uninstall("lora-file:qwen_image_edit/angles.safetensors")
    assert not (store.loras / "qwen_image_edit" / "angles.safetensors").exists()


def test_uninstall_is_refused_while_busy_and_for_unknown_or_escaping_ids(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.busy = "A render is running"
    with pytest.raises(HTTPError) as busy:
        store.handler.uninstall("wangp:flux2_klein_4b")
    assert busy.value.status_code == 409 and (store.ckpts / "flux_klein_int8.safetensors").exists()
    store.busy = ""
    for bad in ("wangp:nope", "folder:../../app", "lora-file:../models/face/sface.onnx", "component:..", "what:ever"):
        with pytest.raises(HTTPError):
            store.handler.uninstall(bad)
    assert (store.models / "face" / "sface.onnx").exists()


def test_storage_lists_each_area_with_size_and_free_space(tmp_path: Path) -> None:
    store = Store(tmp_path)
    areas = {a.id: a for a in store.handler.inventory().areas}
    assert set(areas) == {"checkpoints", "models", "loras"}
    assert areas["checkpoints"].size_bytes == 2000 + 300 + 1000 + 910 and areas["checkpoints"].free_bytes > 0
    assert areas["checkpoints"].path == str(store.ckpts) and not areas["checkpoints"].moved_to


@pytest.mark.skipif(sys.platform != "win32", reason="directory junctions are a Windows feature")
def test_moving_an_area_keeps_every_old_path_working(tmp_path: Path) -> None:
    store = Store(tmp_path)
    target = tmp_path / "bigdisk"
    target.mkdir()
    store.handler.move_area("loras", str(target))
    store.handler.wait_for_move()
    moved = target / "loras"
    assert (moved / "z_image" / "raven.safetensors").is_file()
    assert (store.loras / "z_image" / "raven.safetensors").is_file(), "the old path still reaches the files"
    assert os.path.isjunction(store.loras)
    areas = {a.id: a for a in store.handler.inventory().areas}
    assert Path(areas["loras"].moved_to) == moved
    # Moving it again re-points the same junction.
    second = tmp_path / "otherdisk"
    second.mkdir()
    store.handler.move_area("loras", str(second))
    store.handler.wait_for_move()
    assert (second / "loras" / "z_image" / "raven.safetensors").is_file() and not moved.exists()
    assert (store.loras / "z_image" / "raven.safetensors").is_file()


def test_a_move_is_refused_while_busy_or_onto_an_occupied_folder(tmp_path: Path) -> None:
    store = Store(tmp_path)
    target = tmp_path / "bigdisk"
    (target / "loras").mkdir(parents=True)
    (target / "loras" / "something.txt").write_text("x")
    with pytest.raises(HTTPError) as taken:
        store.handler.move_area("loras", str(target))
    assert taken.value.status_code == 409
    store.busy = "A download is running"
    with pytest.raises(HTTPError) as busy:
        store.handler.move_area("models", str(tmp_path / "elsewhere"))
    assert busy.value.status_code == 409
    with pytest.raises(HTTPError):
        store.handler.move_area("nope", str(target))
    with pytest.raises(HTTPError):
        store.handler.move_area("models", str(store.models / "inside"))


def test_the_settings_screen_reaches_the_store(client, test_state) -> None:
    models_dir = test_state.config.models_dir
    _write(models_dir / "zero123plus-v1.2" / "unet" / "w.safetensors", 700)
    listed = client.get("/api/model-manager/installed").json()
    assert any(m["id"] == "folder:zero123plus-v1.2" and m["size_bytes"] == 700 for m in listed["models"])
    assert {a["id"] for a in listed["areas"]} >= {"models", "loras"}
    after = client.delete("/api/model-manager/installed/folder:zero123plus-v1.2")
    assert after.status_code == 200 and not (models_dir / "zero123plus-v1.2").exists()
    assert client.delete("/api/model-manager/installed/folder:../outputs").status_code == 404


def test_hidden_folders_are_not_models_and_known_folders_have_names(tmp_path: Path) -> None:
    """Live QA on r72: Hugging Face's download cache (`.cache`, 17.8 GB, a model
    mid-download) was listed as a removable component, and the trainer's weights
    folder showed as plain "training"."""
    store = Store(tmp_path)
    _write(store.ckpts / ".cache" / "huggingface" / "partial.incomplete", 500)
    _write(store.ckpts / "training" / "z_image_de_turbo.safetensors", 400)
    _write(store.ckpts / "umt5-xxl" / "te.safetensors", 100)
    models = _by_id(store)
    assert not any(".cache" in model_id for model_id in models), "a download in progress is not a model"
    assert models["component:training"]["name"] == "LoRA training weights (Z-Image)"
    assert models["component:umt5-xxl"]["name"] == "UMT5-XXL text encoder (Wan)"
    assert models["component:Qwen2.5-VL-7B-Instruct"]["name"] == "Qwen2.5-VL 7B text encoder (Qwen-Image)"
    import pytest as _pytest
    from _routes._errors import HTTPError as _HTTPError
    with _pytest.raises(_HTTPError):
        store.handler.uninstall("component:.cache")

