# UI verification scripts

Playwright scripts that drive the **real** Electron app over the Chrome
DevTools Protocol. They are not part of CI (the host has no frontend test
harness); they document how the UI claims in `docs/FINAL_HARDENING_AUDIT.md`
were checked and let you repeat them.

```bash
# 1. dev app with CDP on :9222 (headless Linux: prefix with xvfb-run -a)
ELECTRON_DEBUG=1 pnpm dev
# 2. from a directory with playwright installed (npm i playwright)
node scripts/verify/verify-hardening.mjs      # home, quick mode, build film, continuity, queue, OpenRouter settings, packages
node scripts/verify/verify-ui.mjs             # original storyboard/composer/generation walkthrough
# packaged AppImage instead of dev:
./release/LTX\ Desktop-*.AppImage --appimage-extract-and-run --no-sandbox --remote-debugging-port=9223 &
node scripts/verify/check-appimage.mjs
```

Screenshots land in `./verify-shots/`. The scripts never use real API keys
(`test-placeholder-not-a-real-key`) and accept the LTX API-key gateway with
a dummy value when it appears.
