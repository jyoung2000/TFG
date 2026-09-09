/**
 * Vite plugin that serves the UI-only mock backend from the dev server.
 *
 * Enabled by `VITE_UI_MOCK=1` (that is what `pnpm dev:ui` sets). Serving the
 * mock over real HTTP on the same origin as the app — rather than patching
 * `fetch` in the renderer — is what keeps UI-only mode a faithful copy: image
 * and video elements, redirects, status codes and error bodies all behave as
 * they do against the Python backend, and not one line of renderer code knows
 * the difference.
 */

import type { Plugin } from 'vite'

import { createMockBackend } from './server'

export const UI_MOCK_ENV = 'VITE_UI_MOCK'

export function isUiMockEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env[UI_MOCK_ENV] === '1'
}

export function uiMockPlugin(stateFile: string): Plugin {
  return {
    name: 'ltx-ui-mock-backend',
    apply: 'serve',
    configureServer(server) {
      const backend = createMockBackend(stateFile)
      server.middlewares.use((req, res, next) => {
        void backend
          .handle(req, res)
          .then(handled => {
            if (!handled) next()
          })
          .catch(next)
      })
      server.config.logger.info(
        '\n  UI-only mode: mock backend serving /api - no Python, no Electron, no models.' +
          `\n  State: ${stateFile}  (POST /api/__ui_mock/reset to start over)\n`,
      )
    },
  }
}
