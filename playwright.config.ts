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
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`
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
        command: `pnpm dev:ui -- --port ${PORT} --strictPort --host 127.0.0.1`,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
})
