import { defineConfig, devices } from '@playwright/test'
import fs from 'node:fs'

/**
 * End-to-end checks against the UI-only dev server (`pnpm dev:ui`): no
 * Python, Electron, GPU or model weights. Every spec runs the media-integrity
 * helper in `e2e/helpers/media.ts`, so a broken thumbnail or a console error
 * anywhere in a view fails the suite.
 *
 * Chromium: uses Playwright's own download when present, otherwise the
 * binary named by PW_CHROMIUM_PATH (or the preinstalled /opt/pw-browsers
 * symlink) so CI containers with a pinned browser need no download.
 */
const PORT = Number(process.env.E2E_PORT ?? 5173)
// Vite's default dev host is `localhost`, which on Windows resolves to IPv6 `::1`
// only — so the server is up while a poll of `http://127.0.0.1:<port>` (IPv4) still
// refuses, and the whole run dies as "Timed out waiting ... from config.webServer".
// Poll the same name the server binds unless the caller pinned a URL.
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`
const fallbackChromium = process.env.PW_CHROMIUM_PATH ?? '/opt/pw-browsers/chromium'
const executablePath = fs.existsSync(fallbackChromium) && !process.env.PW_USE_BUNDLED_CHROMIUM ? fallbackChromium : undefined

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1600, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: { executablePath, args: ['--no-sandbox'] },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        // No `--` before the flags: `pnpm dev:ui -- --port N` hands vite a literal
        // "--" argument, which vite treats as end-of-options, so --port/--strictPort
        // are silently dropped and the server always comes up on 5173.
        command: `pnpm dev:ui --port ${PORT} --strictPort`,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
})
