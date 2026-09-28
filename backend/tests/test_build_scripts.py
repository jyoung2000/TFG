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


def _builder_config(name: str) -> dict[str, dict[str, str] | str]:
    """Top-level scalars and one-level blocks of an electron-builder YAML file."""
    config: dict[str, dict[str, str] | str] = {}
    block: dict[str, str] | None = None
    for raw in (REPO_ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, value = line.partition(":")
            if value.strip():
                config[key] = value.strip()
                block = None
            else:
                block = {}
                config[key] = block
        elif block is not None and line.startswith("  ") and not line.startswith("   ") and ":" in line:
            key, _, value = line.strip().partition(":")
            block[key] = value.strip()
    return config


def test_wangp_flavor_is_its_own_app_on_its_own_update_feed() -> None:
    # Round 5 on the audit box: `electron-builder-wangp.yml` extends the base
    # config and inherited its `publish:` block, so the installed LTX Desktop
    # WanGP shipped `app-update.yml` -> owner: Lightricks, repo: ltx-desktop.
    # On first launch it downloaded upstream v1.2.7 and staged its installer,
    # and updater.ts then calls quitAndInstall -- the fork replaced by upstream.
    # It also staged into the same release/ as the normal app.
    base = _builder_config("electron-builder.yml")
    wangp = _builder_config("electron-builder-wangp.yml")
    assert wangp["extends"] == "electron-builder.yml"

    publish = wangp.get("publish", base["publish"])  # `extends` inherits the base block
    assert isinstance(publish, dict)
    assert publish.get("owner") != "Lightricks", "the WanGP build would auto-update to upstream LTX Desktop"
    assert wangp["appId"] != base["appId"]
    assert wangp["productName"] == "LTX Desktop WanGP"

    base_dirs = base["directories"]
    wangp_dirs = wangp.get("directories", base_dirs)
    assert isinstance(base_dirs, dict) and isinstance(wangp_dirs, dict)
    assert wangp_dirs.get("output", base_dirs["output"]) != base_dirs["output"]


def _wan2gp_packaging_filter() -> list[str]:
    lines = (REPO_ROOT / "electron-builder.yml").read_text(encoding="utf-8").splitlines()
    start = lines.index("  - from: Wan2GP")
    patterns: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("  - "):
            break
        item = line.strip()
        if item.startswith("- "):
            patterns.append(item[2:].strip().strip('"'))
    return patterns


def test_installer_never_bundles_downloaded_wangp_weights() -> None:
    # Round 5: a 1.3 GB LoRA that WanGP downloaded into Wan2GP/loras/ltx2 on
    # first use of the reference-image mode turned the 283 MB WanGP installer
    # into a 1.2 GB one. Checkpoints were excluded; downloaded LoRAs were not.
    patterns = _wan2gp_packaging_filter()
    assert "!ckpts/**" in patterns
    assert "!loras/**" in patterns, "downloaded LoRA weights would ship inside the installer"

