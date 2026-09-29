"""Where the backend looks for a WanGP checkout and for its interpreter.

Split out of `ltx2_server.py` so the packaged-app resolution order (F-077 in
`docs/DEBUG_REPORT_hermes.md`) is testable without importing torch or the
server module. Every input the old module-level code read from the process is a
parameter here: `ltx2_server` passes its globals, tests pass `tmp_path`.

The resolution order is documented on `resolve_wangp_root`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

#: Directory names a WanGP checkout may use, next to the project or app data.
WANGP_DIR_NAMES: tuple[str, ...] = ("Wan2GP", "WanGP", "wan2gp", "wangp")

#: Environment variables naming a checkout explicitly. Both still win over
#: anything discovered on disk, so an existing override is never weakened.
WANGP_ROOT_ENV_KEYS: tuple[str, ...] = ("WANGP_ROOT", "WANGP_WGP_PATH")


def venv_python(root: Path, *, os_name: str) -> Path | None:
    """The WanGP venv interpreter under `root`, or None when it has no venv.

    This is the discriminator between a checkout that can drive the isolated
    worker (`wangp_worker_bridge`) and one that can only be imported in-process.
    """
    if os_name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def is_wangp_checkout(root: Path) -> bool:
    """True when `root` holds a WanGP entry point."""
    return (root / "wgp.py").exists()


def _resolve_quietly(candidate: Path) -> Path | None:
    """`candidate.resolve()`, or None when the path cannot be resolved.

    Broad on purpose, matching the original module-level code: a symlink loop
    raises `RuntimeError`, which is not an `OSError`.
    """
    try:
        return candidate.resolve()
    except Exception:
        # A symlink loop raises RuntimeError, not OSError; the original
        # module-level code swallowed everything here.
        return None


def _tree_roots(project_root: Path) -> list[Path]:
    """`project_root` and its parents, never including the filesystem root.

    The packaged app's `PROJECT_ROOT` is `resources/`, so an unbounded walk
    climbs `Programs/`, `AppData/`, the home directory and finally the drive
    root. A checkout left at `C:\\Wan2GP` would then be picked in preference to
    the bundled one — with no interpreter, so the app degrades to in-process
    for a directory nobody meant as a WanGP root.
    """
    roots: list[Path] = []
    for candidate in (project_root, *project_root.parents):
        if candidate.parent == candidate:
            # The drive or filesystem root: `C:\\`, `/`.
            continue
        roots.append(candidate)
    return roots


def _first_checkout(candidates: list[Path], *, os_name: str, need_interpreter: bool) -> Path | None:
    """The first distinct checkout matching the capability filter."""
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = _resolve_quietly(candidate)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if not is_wangp_checkout(resolved):
            continue
        if need_interpreter and venv_python(resolved, os_name=os_name) is None:
            continue
        return resolved
    return None


def has_wangp_interpreter(root: Path, *, os_name: str) -> bool:
    """True when `root` is a checkout this process can reach a venv in."""
    return is_wangp_checkout(root) and venv_python(root, os_name=os_name) is not None


def in_process_diagnostic(
    wangp_root: Path | None,
    *,
    app_data_dir: Path,
    os_name: str | None = None,
) -> str | None:
    """Why this checkout cannot drive the isolated worker, or None if it can.

    F-077 failed silently: a venv-less checkout resolved without complaint,
    the mode came out `in_process`, and nothing said why renders would not
    work. The packaged copy under `resources/` always has `wgp.py` and never a
    `.venv`, so this message is what tells a user what to put where.

    Kept here rather than in `ltx2_server` so it is testable: the server
    module imports torch and the GPU stack, this does not.
    """
    name = os.name if os_name is None else os_name
    if wangp_root is None or has_wangp_interpreter(wangp_root, os_name=name):
        return None
    return (
        f"WanGP checkout {wangp_root} has no .venv, so renders share this Python and the "
        f"isolated worker is unused. Place a checkout with its own .venv at {app_data_dir} "
        "(e.g. a directory junction), or set WANGP_ROOT/WANGP_PYTHON, for worker mode."
    )


def resolve_wangp_root(
    *,
    project_root: Path,
    app_data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    os_name: str | None = None,
) -> Path | None:
    """The WanGP checkout to use, or None when there is none.

    Candidates are tried in this order, first match wins:

    1. `WANGP_ROOT` / `WANGP_WGP_PATH` — an explicit override, unconditional.
       It wins whenever it holds `wgp.py`, venv or not: a container or a
       deliberate single-environment install means exactly that, and the
       interpreter preference below must not demote the operator's choice.
    2. A discovered checkout that has its own interpreter, i.e. one that can
       drive the isolated worker. `app_data_dir` is scanned first — the
       packaged app has no source tree, so this is where a user places or
       junctions a real checkout — then the project tree.
    3. The first discovered checkout without an interpreter, so a bare or
       bundled venv-less copy still yields the documented in-process
       degradation rather than no bridge at all.

    The project walk stops before the filesystem root (`C:\\`, `/`): a
    checkout parked at a drive root is not a project sibling, and scanning
    there would let a stray venv-less copy win over the bundled one.
    """
    env = os.environ if environ is None else environ
    name = os.name if os_name is None else os_name

    for env_key in WANGP_ROOT_ENV_KEYS:
        raw_value = env.get(env_key, "").strip()
        if not raw_value:
            continue
        candidate = Path(raw_value)
        if candidate.is_file():
            candidate = candidate.parent
        resolved = _resolve_quietly(candidate)
        if resolved is not None and is_wangp_checkout(resolved):
            return resolved

    discovery_roots: list[Path] = []
    if app_data_dir is not None:
        discovery_roots.append(app_data_dir)
    discovery_roots.extend(_tree_roots(project_root))

    discovered: list[Path] = []
    for base in discovery_roots:
        discovered.append(base)
        discovered.extend(base / sibling_name for sibling_name in WANGP_DIR_NAMES)

    with_interpreter = _first_checkout(discovered, os_name=name, need_interpreter=True)
    if with_interpreter is not None:
        return with_interpreter
    return _first_checkout(discovered, os_name=name, need_interpreter=False)


def resolve_wangp_python(
    *,
    wangp_root: Path | None,
    environ: Mapping[str, str] | None = None,
    os_name: str | None = None,
    current_executable: str | None = None,
) -> str | None:
    """The interpreter to run WanGP under.

    `WANGP_PYTHON` wins. Otherwise the checkout's own venv — the only path that
    can reach `wangp_worker_bridge`'s isolated worker. With neither, the
    running interpreter, which is what makes `select_wangp_mode` answer
    `in_process` for a container or a runtime-only install.
    """
    env = os.environ if environ is None else environ
    name = os.name if os_name is None else os_name
    current = sys.executable if current_executable is None else current_executable

    env_python = env.get("WANGP_PYTHON", "").strip()
    if env_python:
        return env_python

    if wangp_root is not None:
        candidate = venv_python(wangp_root, os_name=name)
        if candidate is not None:
            return str(candidate)

    return current
