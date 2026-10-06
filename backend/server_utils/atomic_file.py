"""Atomic document replace that survives a concurrent reader on Windows.

`Path.replace` onto a file another handle has open fails on Windows with
`PermissionError` (WinError 5 / 32) until that handle closes - and the JSON
documents here are read constantly (Video Reproduce polls `project.json`
every 0.25 s; the UI polls the reproduce documents). The window is short, so
a brief retry turns a crash into a few milliseconds' wait. Other errors, and
a lock that outlives `timeout_s`, still raise.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


def _default_replace(src: Path, dst: Path) -> None:
    src.replace(dst)


def replace_with_retry(
    tmp: Path,
    target: Path,
    *,
    timeout_s: float = 5.0,
    _replace: Callable[[Path, Path], None] = _default_replace,
) -> None:
    deadline = time.monotonic() + timeout_s
    delay = 0.01
    while True:
        try:
            _replace(tmp, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)
