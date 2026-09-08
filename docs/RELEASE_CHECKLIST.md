# Release checklist

Run through this list for every tagged release. Items marked **P0** block
the release; anything that cannot be verified must be recorded in the
release notes as unverified — never assume.

## 1. Code health (CI)

- [ ] `pnpm typecheck` — TypeScript (`tsc --noEmit`) and Python (`pyright`, strict) clean
- [ ] `pnpm test:frontend` — Vitest unit tests (solver, motion, conversion, error mapping) green
- [ ] `pnpm backend:test` — full pytest suite green (mock-free; `test_pyright.py` included)
- [ ] `pnpm build:frontend` — Vite production build succeeds
- [ ] CI `installer-windows` and `installer-linux` jobs green; download the artifacts and keep the recorded SHA-256
- [ ] No API keys, tokens or personal paths in the diff (`git grep -n "sk-or-v1-\|AIza" -- . ':!docs' ':!backend/tests/test_security.py'` returns nothing — the security test carries deliberately fake key-shaped strings to exercise the redactor)

## 2. Installers — **P0**

### Windows (must be run on a Windows machine; cannot be built on Linux/macOS)

- [ ] Fresh clone; `pnpm install`; `pnpm build:win` completes **without** Azure signing credentials (unsigned by default — `electron-builder-signed.yml` is opt-in via `-Signed`/`AZURE_TENANT_ID`) — or take the CI `installer-windows` artifact and verify its SHA-256 matches `INSTALLER-VERIFICATION.txt`
- [ ] `release/LTX Desktop-<version>-Setup.exe` exists; size roughly as documented in `docs/INSTALLER.md`
- [ ] Run the installer on a clean Windows 10/11 VM: install completes, Start-menu and desktop shortcuts exist
- [ ] Launch: the app starts, downloads/stages the Python runtime on first run (`%APPDATA%\LTXDesktop\python`), the packaged backend starts (`/api/health` reachable from the app), ffmpeg export works
- [ ] Generate one quick video (WanGP path if an NVIDIA GPU is present, otherwise LTX API with a key)
- [ ] On an RTX 4070-class GPU: fill in `docs/RTX_4070_TEST_MATRIX.md` from the recorded version telemetry (never from reasoning)
- [ ] Uninstall from *Apps & features*: install directory removed; user data left in place (documented)
- [ ] Record: installer SHA-256, tested OS build, GPU/driver used

### Linux

- [ ] `pnpm build:linux` (or `bash scripts/local-build.sh --platform linux`) from a fresh clone
- [ ] `release/LTX Desktop-<version>-x86_64.AppImage` runs (`--appimage-extract-and-run` on sandboxes without FUSE); `.deb` installs with `dpkg -i` and registers the desktop entry
- [ ] Packaged backend starts from `resources/python` (no system Python needed); `Wan2GP` present under `resources/`
- [ ] Storyboard → Models lists capabilities for the machine

### macOS

- [ ] `pnpm build:mac` produces the DMG; app opens (unsigned builds need right-click → Open); API mode works with an LTX key

## 3. Product smoke (any platform, ~15 min)

- [ ] Home → *Quick video*: prompt → generate → result; *Edit in Film Maker* creates Scene 1 / Shot 1 with prompt, seed, model, resolution, duration and output preserved
- [ ] Home → *Filmmaker Studio*: new film opens on Storyboard; *Build Film with AI* → *Plan offline* → edit → apply creates scenes/shots/assets
- [ ] Shot drawer: continuity level shows **good**; introduce a location mismatch → **significant** → *Fix* returns to good
- [ ] Shot Composer: open, change shot size/angle/OTS (both shoulders), move a figure with the gizmo, lock it, move the camera by hand (mode shows *manual*), add a camera move + a keyframe, **Capture** → card shows the capture, shot is `ready`; close → auto-saved
- [ ] AI Director: *"make this an over-the-shoulder shot of A over B's right shoulder"* changes the shot's framing/composition (visible in the composer), not just the prompt
- [ ] Video Editor: right-click a clip sent from the Film Maker → *Edit / Regenerate Shot in Film Maker* opens that shot; promote another version → *Replace timeline clip* swaps it
- [ ] Storyboard undo/redo (Ctrl+Z / Ctrl+Shift+Z) reverts a delete/rename; disabled while the queue is busy
- [ ] Generate Preview → queue bar shows progress; Pause / Resume / per-job cancel / prioritize behave; version appears with status; failed versions show an actionable error
- [ ] Kill the backend mid-generation and relaunch: the version is `failed` ("Interrupted…"), the shot is not stuck in *generating*
- [ ] Send to Timeline places the clip on the video track; Video Editor exports
- [ ] Export `.ltxfilm` → import into a new project → media and versions intact
- [ ] Settings → API Keys → OpenRouter: save a key (masked), *Test key*, models list loads, role model picked, AI Director bar enabled; *Remove* clears it; `GET /api/settings` never returns the key
- [ ] With **no** AI key: Build Film (offline), storyboard from script (parser), continuity, composer, generation all still work; AI-only buttons explain what to configure

## 4. Documentation

- [ ] `README.md` version/requirements current; `docs/INSTALLER.md` sizes and steps current
- [ ] `docs/FINAL_HARDENING_AUDIT.md` updated with what was verified for this release and what was not
- [ ] Third-party notices regenerated if dependencies changed (`NOTICES.md`); Open Media/BlueFish attribution intact

## 5. Tag and publish

- [ ] Bump `package.json` version; changelog entry
- [ ] Tag `v<version>`; attach installers + SHA-256 sums
- [ ] Release notes list: verified platforms, known limitations, unverified items
