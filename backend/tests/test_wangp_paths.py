"""F-077: WanGP checkout/interpreter resolution for the packaged app.

The packaged app bundles a venv-less Wan2GP under `resources/` (it has
`wgp.py` but no `.venv`), so the resolver finds it, `_resolve_wangp_python`
falls back to `sys.executable`, and `select_wangp_mode` answers `in_process` —
the installed app cannot render. The behaviour under test: an explicit
environment override still wins, otherwise discovery prefers a checkout that
can actually drive the isolated worker (one with its own `.venv`) over a
venv-less one, and a venv-less checkout remains a usable last resort so a
bare install still degrades to in-process instead of to nothing.
"""

from __future__ import annotations

from pathlib import Path

from services.wangp_paths import in_process_diagnostic, resolve_wangp_extra_args, resolve_wangp_python, resolve_wangp_root


def _checkout(root: Path, *, venv: bool, os_name: str = "nt") -> None:
    """A WanGP checkout: `wgp.py`, and optionally its own venv."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "wgp.py").write_text("", encoding="utf-8")
    if venv:
        python = root / ".venv" / ("Scripts/python.exe" if os_name == "nt" else "bin/python")
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("", encoding="utf-8")


# ---- resolve_wangp_root --------------------------------------------------------------------


def test_no_checkout_anywhere_resolves_to_none(tmp_path: Path) -> None:
    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) is None


def test_checkout_beside_the_project_is_found(tmp_path: Path) -> None:
    sibling = tmp_path / "proj" / "Wan2GP"
    _checkout(sibling, venv=False)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) == sibling.resolve()


def test_env_override_beats_every_discovered_candidate(tmp_path: Path) -> None:
    _checkout(tmp_path / "proj" / "Wan2GP", venv=True)
    _checkout(tmp_path / "appdata" / "Wan2GP", venv=True)
    explicit = tmp_path / "explicit"
    _checkout(explicit, venv=False)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={"WANGP_ROOT": str(explicit)},
        os_name="nt",
    ) == explicit.resolve()


def test_venvless_env_override_is_honoured_so_a_container_stays_in_process(tmp_path: Path) -> None:
    # An explicit root means exactly what the operator said. Demoting it to a
    # discovered checkout would break the container, where one shared
    # environment is the point.
    explicit = tmp_path / "explicit"
    _checkout(explicit, venv=False)
    _checkout(tmp_path / "appdata" / "Wan2GP", venv=True)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={"WANGP_ROOT": str(explicit)},
        os_name="nt",
    ) == explicit.resolve()


def test_env_override_naming_wgp_py_uses_its_directory(tmp_path: Path) -> None:
    script = tmp_path / "explicit" / "wgp.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={"WANGP_ROOT": str(script)},
        os_name="nt",
    ) == script.parent.resolve()


def test_app_data_checkout_is_found_when_the_project_tree_has_none(tmp_path: Path) -> None:
    # The packaged app has no source tree to search, so app data is the only
    # place a user can put (or junction) a real checkout.
    real = tmp_path / "appdata" / "Wan2GP"
    _checkout(real, venv=True)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) == real.resolve()


def test_app_data_checkout_is_preferred_over_a_bundled_venvless_one(tmp_path: Path) -> None:
    # The live F-077 layout: resources/Wan2GP ships wgp.py but no .venv, and a
    # real checkout with a venv is reachable in app data.
    _checkout(tmp_path / "proj" / "Wan2GP", venv=False)
    real = tmp_path / "appdata" / "Wan2GP"
    _checkout(real, venv=True)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) == real.resolve()


def test_venvful_checkout_beats_an_earlier_venvless_one(tmp_path: Path) -> None:
    # The regression that made the installed app render in-process: a venv-less
    # checkout appearing first in the scan shadowed a real one behind it, and
    # the resolver returned a root that can never drive the worker.
    _checkout(tmp_path / "appdata" / "Wan2GP", venv=False)
    real = tmp_path / "Wan2GP"  # found by the project tree's parent scan
    _checkout(real, venv=True)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) == real.resolve()


def test_a_venvless_checkout_is_kept_when_it_is_the_only_one(tmp_path: Path) -> None:
    # Degrading to in-process is documented behaviour; resolving to nothing
    # would take the WanGP bridge away entirely.
    bundled = tmp_path / "proj" / "Wan2GP"
    _checkout(bundled, venv=False)

    assert resolve_wangp_root(
        project_root=tmp_path / "proj",
        app_data_dir=tmp_path / "appdata",
        environ={},
        os_name="nt",
    ) == bundled.resolve()


# ---- resolve_wangp_python ------------------------------------------------------------------


def test_wangp_python_env_wins_over_the_checkout_venv(tmp_path: Path) -> None:
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=True)

    assert resolve_wangp_python(
        wangp_root=root,
        environ={"WANGP_PYTHON": "X:/elsewhere/python.exe"},
        os_name="nt",
        current_executable="C:/current/python.exe",
    ) == "X:/elsewhere/python.exe"


def test_the_checkout_own_interpreter_is_used(tmp_path: Path) -> None:
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=True)

    assert resolve_wangp_python(
        wangp_root=root,
        environ={},
        os_name="nt",
        current_executable="C:/current/python.exe",
    ) == str(root / ".venv" / "Scripts" / "python.exe")


def test_posix_checkout_uses_the_bin_layout(tmp_path: Path) -> None:
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=True, os_name="posix")

    assert resolve_wangp_python(
        wangp_root=root,
        environ={},
        os_name="posix",
        current_executable="/app/.venv/bin/python",
    ) == str(root / ".venv" / "bin" / "python")


def test_without_a_venv_the_running_interpreter_is_used(tmp_path: Path) -> None:
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=False)

    assert resolve_wangp_python(
        wangp_root=root,
        environ={},
        os_name="nt",
        current_executable="C:/current/python.exe",
    ) == "C:/current/python.exe"


def test_without_a_root_the_running_interpreter_is_used() -> None:
    assert resolve_wangp_python(
        wangp_root=None,
        environ={},
        os_name="nt",
        current_executable="C:/current/python.exe",
    ) == "C:/current/python.exe"


# ---- in_process_diagnostic -----------------------------------------------------------------


def test_a_venvless_checkout_is_explained(tmp_path: Path) -> None:
    # F-077 failed silently: mode came out `in_process` with nothing saying why.
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=False)
    appdata = tmp_path / "appdata"

    message = in_process_diagnostic(root, app_data_dir=appdata, os_name="nt")

    assert message is not None
    assert str(root) in message and str(appdata) in message
    assert ".venv" in message and "worker mode" in message


def test_a_venvful_checkout_has_nothing_to_explain(tmp_path: Path) -> None:
    root = tmp_path / "Wan2GP"
    _checkout(root, venv=True)

    assert in_process_diagnostic(root, app_data_dir=tmp_path / "appdata", os_name="nt") is None


def test_no_root_has_nothing_to_explain(tmp_path: Path) -> None:
    assert in_process_diagnostic(None, app_data_dir=tmp_path / "appdata", os_name="nt") is None


def test_a_separate_wangp_venv_keeps_the_fastest_attention() -> None:
    """The venv worker has headers and SageAttention: forcing sdpa halved VACE's speed (81 s/step vs ~40)."""
    args = resolve_wangp_extra_args("", wangp_python=r"C:\Wan2GP\.venv\Scripts\python.exe", current_executable=r"C:\app\python\python.exe")
    assert "sdpa" not in args


def test_wangp_on_the_embedded_interpreter_falls_back_to_sdpa() -> None:
    args = resolve_wangp_extra_args("", wangp_python=r"C:\app\python\python.exe", current_executable=r"C:\app\python\python.exe")
    assert args == ("--attention", "sdpa")


def test_an_explicit_attention_choice_is_kept() -> None:
    assert resolve_wangp_extra_args("--attention=sage --profile 4", wangp_python=None, current_executable="py") == ("--attention=sage", "--profile", "4")
