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


def _script(name: str) -> str:
    return (Path(__file__).resolve().parents[2] / "scripts" / name).read_text(encoding="utf-8")


def test_output_folder_is_movable_so_a_locked_build_does_not_block_shipping() -> None:
    """F-065: rebuilding into `release-wangp` fails with EBUSY on app.asar.

    The handle survives killing the app by exact name and every python process,
    so the folder cannot always be cleared first. The build therefore has to be
    movable: `wangp-release.ps1 -OutputDir` -> `local-build.ps1` -> `create-installer.ps1`
    -> electron-builder, or the workaround is only a comment.

    Each hop is asserted, because a break anywhere in the chain silently sends
    the build back to the locked folder.
    """
    release = _script("wangp-release.ps1")
    assert "[string]$OutputDir" in release, "wangp-release.ps1 takes no -OutputDir"
    assert "-c.directories.output=$ReleaseDir" in release, "the override never reaches electron-builder"
    # A bare `--` is handed to the script as a parameter name and fails with
    # "the parameter name '' is ambiguous", so the arg must be passed directly.
    assert "'--'," not in release and '"--"' not in release, "do not pass a -- separator to a PowerShell script"

    local = _script("local-build.ps1")
    assert "ValueFromRemainingArguments" in local, "local-build.ps1 cannot receive `--` args"
    assert '$pkgParams["BuilderArgs"]' in local, "local-build.ps1 drops the builder args"

    installer = _script("create-installer.ps1")
    assert "[string[]]$BuilderArgs" in installer, "create-installer.ps1 takes no BuilderArgs"
    # both the --dir and the installer invocation must carry them
    assert installer.count("@BuilderArgs") >= 2, "BuilderArgs must reach every electron-builder call"


def test_the_default_output_folder_is_unchanged_when_no_override_is_given() -> None:
    """The override must be opt-in: a plain `pnpm wangp:ship` still builds into
    release-wangp, so the documented workflow does not change."""
    release = _script("wangp-release.ps1")
    assert "Join-Path $ProjectDir 'release-wangp'" in release
    assert "if ($OutputDir)" in release, "the override must be conditional"


def test_backend_runtime_data_files_are_packaged() -> None:
    """The backend resource filter was `**/*.py` + `pyproject.toml`, so every
    data file the backend reads at runtime was left out of the installed app,
    silently: the CLIP term lists (services/vision/clip_data/*.txt - style
    tags came back empty, MEASURED on job ia-da9ab2af6672) and the media
    capability catalog (film/data/model_catalog.json - load_catalog() returns
    an empty catalog when the file is missing)."""
    from fnmatch import fnmatch

    lines = (REPO_ROOT / "electron-builder.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- from: backend")
    patterns: list[str] = []
    for line in lines[start + 1:]:
        text = line.strip()
        if text.startswith("- from:"):
            break
        if text.startswith('- "') or text.startswith("- "):
            patterns.append(text[2:].strip().strip('"'))
    includes = [p for p in patterns if not p.startswith("!") and p not in ("filter:",)]

    tracked = subprocess.run(["git", "ls-files", "backend"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    dev_only = {"pyrightconfig.json", "vision-requirements.txt", "install_sageattention.bat", "py.typed", "uv.lock"}
    runtime_data = [
        f[len("backend/"):] for f in tracked
        if not f.endswith((".py", ".md", ".pyi")) and "/tests/" not in f and not f.startswith("backend/tests/")
        and Path(f).name not in dev_only and not Path(f).name.startswith(".")
    ]
    assert runtime_data, "expected the backend's runtime data files"
    missing = [f for f in runtime_data if not any(fnmatch(f, p) or fnmatch(f, p.replace("**/", "")) for p in includes)]
    assert missing == [], f"not packaged into the installed app: {missing}"


def test_the_installer_never_bundles_a_lora_trainer() -> None:
    """The backend filter takes every `**/*.py`, so the trainer clone and its
    virtual environment beside the backend (scripts/ensure-trainer.ps1) went
    into the installer: MEASURED in r48, 271 MB -> 311 MB, with musubi-tuner's
    site-packages under resources/backend (2026-10-02)."""
    from fnmatch import fnmatch

    lines = (REPO_ROOT / "electron-builder.yml").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- from: backend")
    excludes: list[str] = []
    for line in lines[start + 1:]:
        text = line.strip()
        if text.startswith("- from:"):
            break
        if text.startswith('- "!'):
            excludes.append(text[3:].strip().strip('"')[1:])
    for path in (".venv-trainer-musubi/Lib/site-packages/torch/__init__.py", ".trainer-musubi/src/musubi_tuner/zimage_train_network.py",
                 ".venv-trainer-aitoolkit/Lib/site-packages/x.py", ".trainer-ai-toolkit/run.py"):
        assert any(fnmatch(path, pattern) for pattern in excludes), f"{path} would ship in the installer"
