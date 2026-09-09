/**
 * Vite plugin that serves the UI-only mock backend from the dev server.
 *
 * Enabled by `VITE_UI_MOCK=1` (that is what `pnpm dev:ui` sets). Serving the
 * mock over real HTTP on the same origin as the app — rather than patching
 * `fetch` in the renderer — is what keeps `pnpm dev:ui` a faithful copy: image
 * and video elements, redirects, status codes and error bodies all behave as
 * they do against the Python backend, and not one line of renderer code knows
 * the difference.
 *
 * The standalone HTML build cannot have a server, so it runs the same backend
 * in the browser instead — see `browser.ts`.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import type { IncomingMessage } from 'node:http'
import { dirname } from 'node:path'

import type { Plugin } from 'vite'

import { createMockBackend } from './server'
import type { Persistence } from './state'

export const UI_MOCK_ENV = 'VITE_UI_MOCK'
export const UI_STANDALONE_ENV = 'VITE_UI_STANDALONE'

/** A real MP4 Vite already serves from `public/`, used for rendered clips. */
const SAMPLE_CLIP = '/splash/splash.mp4'

export function isUiMockEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env[UI_MOCK_ENV] === '1'
}

/** The standalone build: the mock runs in the browser, so no server is needed. */
export function isUiStandalone(env: NodeJS.ProcessEnv = process.env): boolean {
  return env[UI_STANDALONE_ENV] === '1'
}

function filePersistence(file: string): Persistence {
  return {
    read: () => {
      try {
        return readFileSync(file, 'utf8')
      } catch {
        return null
      }
    },
    write: data => {
      mkdirSync(dirname(file), { recursive: true })
      writeFileSync(file, data)
    },
  }
}

async function readBody(req: IncomingMessage): Promise<string> {
  if (req.method === 'GET' || req.method === 'HEAD') return ''
  const chunks: Buffer[] = []
  for await (const chunk of req) chunks.push(chunk as Buffer)
  return chunks.length ? Buffer.concat(chunks).toString('utf8') : ''
}

export function uiMockPlugin(stateFile: string): Plugin {
  return {
    name: 'ltx-ui-mock-backend',
    apply: 'serve',
    configureServer(server) {
      const backend = createMockBackend({
        persistence: filePersistence(stateFile),
        clipUrl: SAMPLE_CLIP,
      })
      server.middlewares.use((req, res, next) => {
        void readBody(req)
          .then(body => backend.handle(req.method ?? 'GET', req.url ?? '/', body))
          .then(result => {
            if (!result) {
              next()
              return
            }
            res.statusCode = result.status
            for (const [key, value] of Object.entries(result.headers)) res.setHeader(key, value)
            res.end(result.body || undefined)
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
