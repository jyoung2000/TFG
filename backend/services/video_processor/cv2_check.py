"""cv2 install integrity (round-2 F-040, recurring round-1 F-013).

A broken opencv install (site-packages/cv2 present but missing its
__init__.py) imports as an empty NAMESPACE package: `import cv2` succeeds,
`cv2.__file__` is None, and every attribute — VideoWriter, VideoCapture,
CAP_PROP_* — is missing. The symptom shows up far from the cause: 57
pyright errors in round 2, and runtime AttributeErrors mid-export. This
check names the corruption and the repair at startup instead.
"""

from __future__ import annotations

from typing import Any

_REPAIR = (
    "uv pip install --python <backend venv python> --reinstall-package "
    "opencv-python-headless opencv-python-headless==4.13.0.92"
)


def check_cv2_module(module: Any) -> str:
    """'' when the module is a real opencv install; else the problem, with
    the repair command. Pure, so the corrupt-install shape is testable."""
    if getattr(module, "__file__", None) is None:
        return (
            "cv2 imported as an empty namespace package (its __init__.py is missing) — "
            f"the opencv install is corrupt. Repair: {_REPAIR}"
        )
    missing = [name for name in ("VideoWriter", "VideoCapture", "imread") if not hasattr(module, name)]
    if missing:
        return f"cv2 at {module.__file__} lacks {', '.join(missing)} — the opencv install is corrupt. Repair: {_REPAIR}"
    return ""


def verify_cv2() -> None:
    """Import cv2 and refuse to continue on a corrupt install."""
    try:
        import cv2  # noqa: PLC0415 - deliberate lazy import, heavy DLL
    except Exception as exc:  # noqa: BLE001 - surfaced with the repair path
        raise RuntimeError(f"cv2 failed to import ({exc}). Repair: {_REPAIR}") from exc
    problem = check_cv2_module(cv2)
    if problem:
        raise RuntimeError(problem)
