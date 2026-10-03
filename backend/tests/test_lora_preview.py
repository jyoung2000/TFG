"""A preview of a LoRA inside the app (user, 2026-10-02: "provide a preview of
the LoRA where we can see the different LoRA angle images in the software").

POST /api/training/loras/{id}/preview renders the standard views with the LoRA
from its trigger alone, scores each face against the dataset's photo, keeps
the images under the LoRA folder and records them on the registry entry.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_asset_angles import FLUX2, _image_params
from tests.test_training import _dataset


def test_a_lora_can_be_previewed_at_the_standard_views(client, test_state, fake_services, create_fake_model_files, tmp_path: Path) -> None:
    create_fake_model_files(include_zit=True)
    test_state.config.wangp_enabled = True
    fake_services.wangp_bridge.available = True
    fake_services.wangp_bridge.definitions.append(FLUX2)
    dataset = _dataset(client, tmp_path, count=4, trigger="rvnx")
    client.put(f"/api/training/datasets/{dataset['id']}/items/{dataset['items'][0]['id']}", json={"caption": "rvnx, woman"})
    lora = tmp_path / "raven.safetensors"
    lora.write_bytes(b"0" * 64)
    entry = client.post("/api/training/loras/import", json={"path": str(lora), "name": "Raven", "target": "z_image", "trigger": "rvnx"}).json()
    client.put(f"/api/training/loras/{entry['id']}", json={"dataset_id": dataset["id"]})
    fake_services.face_matcher.enabled = True
    before = len(_image_params(fake_services))
    response = client.post(f"/api/training/loras/{entry['id']}/preview")
    assert response.status_code == 200, response.text
    updated = response.json()
    assert len(updated["preview_paths"]) == 4 and all(Path(p).is_file() for p in updated["preview_paths"])
    assert len(updated["preview_scores"]) == 4
    params = _image_params(fake_services)[before:]
    assert len(params) == 4 and all(p["prompt"].startswith("rvnx, woman") for p in params)
    assert all(any("raven.safetensors" in str(v) for v in p.values()) for p in params), "the LoRA is applied"
    served = client.get("/api/film/output", params={"path": updated["preview_paths"][0]})
    assert served.status_code == 200
    assert client.get("/api/training/loras").json()["loras"][0]["preview_paths"] == updated["preview_paths"]
