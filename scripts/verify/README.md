# UI verification scripts

Playwright scripts that drive the **real** Electron app over the Chrome
DevTools Protocol. They are not part of CI (they need a display and the dev
app); they document how the UI claims in `docs/FINAL_HARDENING_AUDIT.md`
were checked and let you repeat them.

```bash
# 1. dev app with CDP on :9222 (headless Linux: prefix with xvfb-run -a)
ELECTRON_DEBUG=1 pnpm dev
# 2. from a directory with playwright installed (npm i playwright)
node scripts/verify/verify-rc.mjs             # release-candidate walkthrough: composer gizmo/lock/manual camera/keyframes, undo/redo, gaps, director set_ots, models states, local endpoint settings, path policy (39 checks)
node scripts/verify/verify-hardening.mjs      # home, quick mode, build film, continuity, queue, OpenRouter settings, packages (33 checks)
node scripts/verify/verify-ui.mjs             # original storyboard/composer/generation walkthrough
# packaged AppImage instead of dev:
./release/LTX\ Desktop-*.AppImage --appimage-extract-and-run --no-sandbox --remote-debugging-port=9223 &
node scripts/verify/check-appimage.mjs
```

Screenshots and `results.json` land in `./verify-shots/<script>/`. The
scripts never use real API keys (`test-placeholder-not-a-real-key`), accept
the LTX API-key gateway with a dummy value when it appears, and connect to
`127.0.0.1` (Node ≥ 17 resolves `localhost` to IPv6 first, which Electron's
CDP server does not bind).

If `connectOverCDP` times out although the app is running, check the dev log
for `Cannot start http server for devtools`: a stale backend from an earlier
session can still hold port 9222 (`pkill -f "[l]tx2_server.py"`).
