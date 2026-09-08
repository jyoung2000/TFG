import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

// Unit tests for pure frontend modules (solver maths, motion presets, error
// mapping, conversion helpers). Rendering/UI behaviour is covered by the
// Playwright-over-CDP scripts in scripts/verify/.
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./frontend', import.meta.url)),
    },
  },
  test: {
    include: ['frontend/**/*.test.ts'],
    environment: 'node',
  },
})
