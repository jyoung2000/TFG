# Hermes — make the installed LTX Desktop WanGP work like `pnpm dev`

You are working on this Windows 11 machine (RTX 4070 12 GB, 32 GB RAM) with
shell access, in the repo at `C:\Users\jalon\TFG`, branch `latest`. Nobody
watches each step: follow the order below and stop where it says to.

```powershell
git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch origin
git checkout -B latest origin/latest      # the single working branch — no PRs
powershell -ExecutionPolicy Bypass -File scripts\verify-hermes-ready.ps1   # every line ok
```

Read first: `AGENTS.md` (the **Shipping to the installed app** section),
then rows **F-065, F-066, F-070 … F-078** in `docs/DEBUG_REPORT_hermes.md`.

## Where things stand (2026-09-29, measured)

- **Release `v1.0.2` is published** on `jyoung2000/TFG` (installer, blockmap,
  `latest.yml`, `python-deps-hash.txt`, `SHA256SUMS.txt`). The installed app
  at `%LOCALAPPDATA%\Programs\LTX Desktop WanGP` auto-updated itself from
  1.0.1 to **1.0.2.0**; its exe matches the release build byte for byte.
- The installed app's update feed is `jyoung2000/TFG`; its Python-runtime
  download source is this repo's releases (`electron/runtime-source.ts`).
- Image and video Reproduce fill every ShotSpec block from the vision AI
  (`qwen2.5vl:7b` via Ollama, Settings → Vision), verified live.
- The **upstream** Lightricks **LTX Desktop 1.2.7** is also installed
  (`%LOCALAPPDATA%\Programs\LTX Desktop`, appId `com.lightricks.ltx-desktop`).
  It is the user's app. It must never change.

## What is still broken in the installed app (your job)

1. **It cannot render: `WanGP mode: in_process`** (F-077). In the package,
   `backend/ltx2_server.py` `_resolve_wangp_root()` finds the bundled
   `resources\Wan2GP`, which has no `.venv` and no `ckpts`, so
   `_resolve_wangp_python()` falls back to the runtime's own interpreter and
   `select_wangp_mode()` (`backend/services/wangp_worker_bridge.py`) picks
   `in_process`. The source checkout renders because
   `C:\Users\jalon\TFG\Wan2GP` has its own `.venv` (torch 2.10.0+cu128) and
   ~50 GB of checkpoints. `WANGP_ROOT` / `WANGP_PYTHON` already override both
   resolutions.
2. **Its Python runtime is not this repo's** (F-076). `%LOCALAPPDATA%\LTXDesktop\python`
   has `transformers 4.54.0` and no `florence2` module, while `backend/uv.lock`
   pins 4.57.6 — yet its `deps-hash.txt` reads the current lock's hash
   (`34857b9d…`), so the app accepts it. Result: no Florence-2 captions or
   detection in the installed app (`cannot import name
   'Florence2ForConditionalGeneration' from 'transformers'`).
3. **A fresh install on another PC cannot finish first-run setup**: no
   runtime (`python-embed-win32.manifest.json` + `.tar.gz.part-*`) is attached
   to any release of this repo (F-066).
4. **After an auto-update the app did not relaunch** (observed once, 1.0.1 →
   1.0.2: installed, then 0 processes), although `electron/updater.ts` calls
   `quitAndInstall(false, true)`.

## Hard rules

- **Report only what tool output showed you.** Every number traces to a
  command you ran. Before quoting on-screen text, find it with `git grep`.
- **Tests.** Every fix gets a test that fails before it and passes after.
  `ServiceBundle` fakes, never `unittest.mock`. Never skip, weaken or delete a test.
- **Architecture.** Keep ADR 0005: `backend\.venv` and `Wan2GP\.venv` stay
  separate. Don't downgrade the backend's transformers. Keep
  `tests/test_licenses.py` intact.
- **Never rebuild** `Wan2GP\.venv` or re-download the installed checkpoints.
- **Only ever install the WanGP flavour** (`electron-builder-wangp.yml`,
  `pnpm wangp:ship`). Never install `release\LTX Desktop-Setup.exe` — it is
  upstream's identity and replaces the user's LTX Desktop 1.2.7. After every
  install, confirm the upstream exe's SHA-256 is unchanged.
- **Kill processes by exact name or path only.** Never by a substring such as
  `win-unpacked` — that pattern killed the user's Hermes app in round 5.
- **Don't touch user data** in `%LOCALAPPDATA%\LTXDesktop` (settings, History,
  outputs) except the runtime folder in task 2, and then rename, never delete.
  A backup from round 5 is in `C:\Users\jalon\TFG-r5-evidence\userdata-backup`.
- **Never reboot.** Commit and push first, then ask the user.
- **Builds:** electron-builder fails with `EBUSY … app.asar` when it rebuilds
  into an existing output folder (a handle on this machine keeps new asar
  files open). Build into a new folder each time
  (`-c.directories.output=release-wangp-<something-new>`).
- **Line endings:** keep each file's committed line endings; check
  `git diff --stat` for whole-file rewrites.
- **Anything public** (a GitHub release, an upload) needs the user's explicit
  go-ahead in chat for that specific release. Ask; don't assume.

## Tasks, in order

### 1. Worker mode in the installed app (F-077)

Make the installed app use a real WanGP environment instead of the empty
bundled one, without breaking the source checkout or the container path.

- Add a **"WanGP folder"** setting (Settings → AI Models or General) holding a
  WanGP root; when set, Electron passes `WANGP_ROOT` (and `WANGP_PYTHON` =
  `<root>\.venv\Scripts\python.exe` when it exists) to the backend it spawns.
  Validate the folder (`wgp.py` present; say which file is missing if not).
- Show the resolved mode in the UI (the backend already logs `WanGP mode: …`)
  so `in_process` is never silent: if the app cannot reach a WanGP
  environment, say so on the Create screen with a link to the setting.
- Tests: backend (settings → env → `select_wangp_mode` returns `worker`),
  plus a frontend/e2e check of the setting against the mock backend.
- **Acceptance on this machine:** set the folder to `C:\Users\jalon\TFG\Wan2GP`,
  restart the installed app, and the session log in
  `%LOCALAPPDATA%\LTXDesktop\logs` shows `WanGP mode: worker` and
  `orphan guard armed — serving`. Then render one **Fast 540p · 6 s** clip
  from the installed app's Create view and report: History job id, History
  `seconds`, History peak, your `nvidia-smi` peak, the idle baseline taken
  just before, `max − baseline`, and the output's `ffprobe` dimensions,
  frame count and duration. (Stop Ollama's model first: `ollama stop
  qwen2.5vl:7b` — it holds ~6 GB and the VRAM guard will refuse the render.)

### 2. A runtime built from this repo (F-076, F-066)

- Write `scripts\build-runtime.ps1`: run `scripts\prepare-python.ps1` (it
  exports `uv.lock` and installs into `python-embed`), write `deps-hash.txt`
  the same way `scripts/prepare-python.sh` does (sha256 of the `uv export …`
  output, computed in bash so the bytes match), pack `python-embed-win32.tar.gz`,
  split it into parts under 2 GB (`python-embed-win32.tar.gz.part-aa`, `-ab`, …),
  and write `python-embed-win32.manifest.json` in the format
  `electron/python-setup.ts` reads (`{"parts":[{"name","size"}],"totalSize"}`).
  The result must carry `transformers==4.57.6` with its `florence2` module.
- Make the runtime check honest: `isPythonReady` must not trust
  `deps-hash.txt` alone. Verify the installed packages (e.g. compare
  `importlib.metadata` versions against the exported requirements) and
  re-stage when they differ. Red-then-green test for the exact case found:
  a runtime whose hash file matches but whose `transformers` is 4.54.0.
- **Ask the user** before uploading the runtime to a release (it is several
  GB on a public repo). With their go-ahead, attach it to the release that
  matches the app version.
- **Acceptance:** rename `%LOCALAPPDATA%\LTXDesktop\python` aside (do not
  delete), start the installed app, and show from its log that it staged the
  runtime from `github.com/jyoung2000/TFG/releases/download/v<version>`; then
  analyse an image in Reproduce and show a Florence-2 caption (not
  `CLIP tags only`). Restore the old folder only if staging failed.

### 3. Relaunch after an auto-update

Find why the app did not restart after `quitAndInstall(false, true)`
(NSIS silent install + `isForceRunAfter`), fix it with a test, and prove it
with a real update. Publish nothing yourself: ask the user for a test
release, or serve `latest.yml` + the installer locally if the updater has a
dev-only override (check the code before assuming one exists).

### 4. Clean-ups to raise with the user (don't change without asking)

- `electron/analytics.ts:6` still sends analytics to
  `https://ltx-desktop.lightricks.com/v2/ingest`. Ask whether to disable it
  or point it elsewhere.
- Both flavours share `updaterCacheDirName: ltx-desktop-updater`, and an
  upstream 1.2.7 installer is still staged in
  `%LOCALAPPDATA%\ltx-desktop-updater\pending\` (round 5 was refused
  permission to move it). Propose giving the WanGP flavour its own cache
  directory, and ask the user to remove that `pending` folder.

## Deliver

- One commit per fix, each with its test; `git push origin latest` (pull
  first if rejected; never force-push). CI runs on every push to `latest`;
  report its result and fix anything your change broke.
- Ship to the installed app with `pnpm wangp:ship` (or the fresh-folder build
  above if `release-wangp` is locked) and verify: installed exe hash = build,
  upstream exe hash unchanged.
- Append rows to `docs/DEBUG_REPORT_hermes.md` from the next free F-number;
  change earlier rows only in new rows, by reference.
- Append a section to `docs/HERMES_REVIEW.md` with each acceptance above,
  its numbers, and screenshots (downscaled to ≤1600 px, JPEG q85) of the
  installed app rendering and of the Florence caption.
- **Could not test → say why.** A partial round with honest gaps beats a
  complete-looking one with guesses.
