"""Where the LoRA trainers live.

Found 2026-10-02 (installing musubi-tuner for a character LoRA): the app
looked for trainers beside its own backend - inside the installed app's
resources, which a reinstall replaces - while scripts/ensure-trainer.ps1
installed them into the repository. The installed app said "not installed"
whatever the user did. Trainers now live in the app data folder, which
survives reinstalls; a development checkout's backend/ still works, and
TFG_TRAINER_ROOT overrides both.
"""

from __future__ import annotations

from pathlib import Path

from services.trainer.subprocess_trainer import MusubiTrainer, resolve_trainer_root


def _installed(root: Path, env_name: str = ".venv-trainer-musubi") -> Path:
    (root / env_name / "Scripts").mkdir(parents=True)
    return root


def test_the_app_data_folder_is_where_trainers_live(tmp_path: Path) -> None:
    backend, app_data = tmp_path / "backend", tmp_path / "appdata"
    backend.mkdir()
    assert resolve_trainer_root(backend_root=backend, app_data_dir=app_data, environ={}) == app_data / "trainers"
    _installed(app_data / "trainers")
    _installed(backend)
    assert resolve_trainer_root(backend_root=backend, app_data_dir=app_data, environ={}) == app_data / "trainers"


def test_a_development_checkout_keeps_its_trainers_beside_the_backend(tmp_path: Path) -> None:
    backend = _installed(tmp_path / "backend")
    assert resolve_trainer_root(backend_root=backend, app_data_dir=tmp_path / "appdata", environ={}) == backend


def test_an_explicit_root_wins(tmp_path: Path) -> None:
    backend = _installed(tmp_path / "backend")
    chosen = tmp_path / "D-drive" / "trainers"
    assert resolve_trainer_root(backend_root=backend, app_data_dir=tmp_path / "appdata", environ={"TFG_TRAINER_ROOT": str(chosen)}) == chosen


def test_not_installed_says_the_exact_command_for_this_folder(tmp_path: Path) -> None:
    root = tmp_path / "appdata" / "trainers"
    ok, reason = MusubiTrainer(root).available()
    assert not ok
    assert "ensure-trainer" in reason and str(root) in reason, reason
