# LTX Desktop - Installer Build Guide

This guide explains how to build a distributable installer for **LTX Desktop**
on Windows, Linux and macOS, and — just as important — what has and has not
been verified for each. A green `pnpm build:*` exit code is **not** installer
success; see *Verification status* and `RELEASE_CHECKLIST.md`.

- For running from source and debugging: see [`README.md`](../README.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).
- For end-user requirements and first-run behavior: see [`README.md`](../README.md).

## What Gets Bundled

| Component | Windows (NSIS `.exe`) | Linux (AppImage / `.deb`) | macOS (`.dmg`) |
|---|---|---|---|
| Electron app (React frontend + main process) | ✔ | ✔ | ✔ |
| Backend Python code (`resources/backend`) | ✔ | ✔ | ✔ |
| `Wan2GP` checkout (`resources/Wan2GP`) | ✔ | ✔ | ✔ (bridge disabled — no CUDA) |
| Embedded Python runtime + locked deps | **downloaded on first launch** into `%LOCALAPPDATA%\LTXDesktop\python`, validated against the bundled `python-deps-hash.txt` | bundled in `resources/python` (prepared by `scripts/prepare-python.sh`: CUDA PyTorch from the cu128 index **plus** `Wan2GP/requirements.txt`) | bundled in `resources/python` (MPS PyTorch) |
| ffmpeg for export | ✔ (`ffmpeg-static`) | ✔ | ✔ |

**NOT bundled** (downloaded at runtime): model weights (large, from Hugging
Face; the Models tab shows what fits the GPU and downloads only what is
missing).

The embedded Python is **fully isolated** from the target system's Python —
it lives inside the install/app-data directory and never modifies system
settings. `LTX_BACKEND_PYTHON=/path/to/python` overrides it for debugging.

## Prerequisites

1. **Node.js 18+** and **pnpm 10** (`corepack enable`)
2. **uv** - https://docs.astral.sh/uv/ (exports the locked requirements)
3. **git** - needed for git-based Python packages and the Wan2GP checkout
4. **Internet connection** (Python runtime, packages, Wan2GP)
5. **~15 GB free space** (Python environment + build artifacts)

Platform-specific: Windows needs PowerShell 5.1+; macOS needs the Xcode
Command Line Tools; Linux needs `fakeroot`/`dpkg` for the `.deb` (electron-
builder downloads its own tooling for the AppImage).

## Quick Build

```bash
pnpm build:win      # Windows, on Windows          → release/LTX Desktop-<version>-Setup.exe
pnpm build:mac      # macOS, on macOS              → release/LTX Desktop-<version>-arm64.dmg
bash scripts/local-build.sh --platform linux   # Linux → release/LTX Desktop-<version>-x86_64.AppImage + -amd64.deb
```

Each runs: typecheck → frontend build → Python preparation → electron-builder.

### Code signing is opt-in

`electron-builder.yml` produces **unsigned** builds so a clean checkout
builds without secrets. Release builds with Azure Trusted Signing set
`AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET` (or pass
`-Signed` / `--signed`) and the scripts switch to
`electron-builder-signed.yml`, which `extends` the base config and adds
`win.azureSignOptions`.

## Build Options

```bash
# skip Python preparation when python-embed/ is already there
pnpm build:win:skip-python   |  pnpm build:mac:skip-python  |  bash scripts/local-build.sh --platform linux --skip-python
# unpacked app only (fast iteration)
pnpm build:fast:win          |  pnpm build:fast:mac         |  bash scripts/local-build.sh --platform linux --unpack
# just the Python environment
pnpm prepare:python:win      |  pnpm prepare:python:mac     |  bash scripts/prepare-python.sh
# runtime-only Python bundle for CI/packaging smoke tests (backend cannot run — never ship)
LTX_PYTHON_DEPS=skip bash scripts/prepare-python.sh
```

`local-build.sh` / `local-build.ps1` accept `--platform`, `--skip-python`,
`--clean`, `--unpack`; `create-installer.*` accept `--signed`/`-Signed`
and `--publish`.

## Verification status (be honest here)

| Platform | Built from clean checkout | Installs | Launches + packaged backend starts | Generation | Uninstall |
|---|---|---|---|---|---|
| **Linux** AppImage + `.deb` | ✔ built in CI-like Linux container (runtime-only Python bundle: `LTX_PYTHON_DEPS=skip`, no CUDA) | `.deb` inspected (control, postinst, desktop entry, `/opt/LTX Desktop/resources/{backend,Wan2GP,python}`) | ✔ AppImage launched with `--appimage-extract-and-run --no-sandbox`; Home, Storyboard and Models panel verified over CDP, backend `isPackaged=true` | not possible in the container (no GPU, no API key) | not exercised |
| **Windows** NSIS | pipeline fixed to build unsigned by default; **not buildable on Linux/macOS (no Wine)** | **unverified** | **unverified** | **unverified** | **unverified** |
| **macOS** DMG | unchanged from upstream; not built in this environment | unverified | unverified | unverified | unverified |

**Remaining P0 for Windows** (must be done on a Windows machine, see
`RELEASE_CHECKLIST.md` § 2): fresh clone → `pnpm build:win` → install on a
clean VM → launch → first-run Python download → backend health → one quick
video → ffmpeg export → uninstall. Record installer SHA-256 and the tested
OS/GPU.

## Build Output

```
release/
  LTX Desktop-<version>-Setup.exe          # Windows (NSIS)
  LTX Desktop-<version>-x86_64.AppImage    # Linux
  LTX Desktop-<version>-amd64.deb          # Linux
  LTX Desktop-<version>-arm64.dmg          # macOS
```

## Application Icon

Place icon files in `resources/` before building: `icon.ico` (Windows,
multi-size) and `icon.png` (macOS/Linux, 1024×1024).

## Troubleshooting

- **"Python not found" during build** — the script downloads a
  python-build-standalone runtime; it needs internet and maps
  `backend/.python-version` (`3.12`/`3.13`) to an available PBS build.
- **pip cannot reach `download.pytorch.org`** — corporate proxies sometimes
  block it; the Linux build needs it for CUDA wheels. Configure the proxy or
  build on a machine with access.
- **Build fails with CUDA errors** — the build does not need a GPU; CUDA
  packages are pre-built binaries.
- **macOS: "App is damaged" / Gatekeeper** — unsigned builds: right-click →
  Open, or `xattr -dr com.apple.quarantine "/Applications/LTX Desktop.app"`.
- **Linux AppImage does not start** — on systems without FUSE run it with
  `--appimage-extract-and-run`; in containers add `--no-sandbox`.
- **Installer is too large** — expected: Windows ~10 GB (PyTorch CUDA +
  ML libraries), Linux several GB with CUDA wheels + Wan2GP deps, macOS
  ~2-3 GB.
- **First-run issues** — see `README.md` (data locations, model downloads,
  API keys).

## Advanced: Manual Build Steps

```bash
# 1. Python environment
bash scripts/prepare-python.sh            # macOS / Linux
./scripts/prepare-python.ps1              # Windows
# 2. Dependencies + frontend
pnpm install && pnpm build:frontend
# 3. Package
npx electron-builder --mac                # or --win / --linux; add --dir for unpacked
```
