"""Tests for the Windows build scripts that run outside the backend."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIND_INSTALLER = REPO_ROOT / "scripts" / "lib" / "find-built-installer.ps1"


def _powershell() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "PowerShell (pwsh) is needed to test the build scripts"
    return shell


def test_build_summary_names_the_installer_just_built_not_a_stale_one(tmp_path: Path) -> None:
    # Round 5 on the audit box: `pnpm build:win` produced "LTX Desktop-Setup.exe"
    # (270.1 MiB) but the summary printed a 3-day-old "LTX Desktop WanGP-Setup.exe"
    # (189.42 MB) left in release/ by an earlier WanGP-branded build, because it
    # took the first *Setup*.exe by name and a space sorts before a hyphen.
    stale = tmp_path / "LTX Desktop WanGP-Setup.exe"
    fresh = tmp_path / "LTX Desktop-Setup.exe"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    os.utime(stale, (1_700_000_000, 1_700_000_000))
    os.utime(fresh, (1_800_000_000, 1_800_000_000))
    # electron-builder also writes a temporary uninstaller whose name contains "Setup"
    uninstaller = tmp_path / "LTX Desktop-Setup.__uninstaller.exe"
    uninstaller.write_bytes(b"x")
    os.utime(uninstaller, (1_900_000_000, 1_900_000_000))

    script = f". '{FIND_INSTALLER}'; (Find-BuiltInstaller -ReleaseDir '{tmp_path}').Name"
    out = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert out.stdout.strip() == "LTX Desktop-Setup.exe"
