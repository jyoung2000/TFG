/**
 * Assembles the UI-only mock backend.
 *
 * Platform-neutral: it takes a method, a URL and a body string and returns a
 * status, headers and a body string. The Vite dev server hands it real HTTP
 * requests (`node-adapter.ts`); the standalone HTML build hands it requests
 * from a patched `fetch` (`browser.ts`). Same handlers, same state machine,
 * same responses either way.
 */

import {
  MockHttpError,
  RawResponse,
  Router,
  parseJsonBody,
  type MockRequest,
  type MockResult,
} from './http'
import { isVideoPath, labelFromPath, placeholderFrame } from './media'
import { registerContinuityRoutes } from './routes/continuity'
import { registerDirectorRoutes } from './routes/director'
import { registerFilmRoutes } from './routes/film'
import { registerGenerationRoutes, tickGeneration } from './routes/generation'
import { registerModelRoutes } from './routes/models'
import { registerProjectOpsRoutes } from './routes/project-ops'
import { registerQueueRoutes, tickQueue } from './routes/queue'
import { registerSettingsRoutes } from './routes/settings'
import { NO_PERSISTENCE, Store, type Persistence } from './state'

export interface MockBackendOptions {
  persistence?: Persistence
  /**
   * Where a request for a rendered clip should be sent. The dev server
   * redirects to a real file it already serves; the standalone build never
   * asks, because it resolves media URLs directly.
   */
  clipUrl?: string
}

export interface MockBackend {
  /** Returns null when the path is not one of ours, so a host can fall through. */
  handle(method: string, url: string, body: string): Promise<MockResult | null>
  reset(): void
}

export function createMockBackend(options: MockBackendOptions = {}): MockBackend {
  const store = new Store(options.persistence ?? NO_PERSISTENCE)
  const router = new Router()

  registerSettingsRoutes(router, store)
  registerModelRoutes(router, store)
  registerFilmRoutes(router, store, options.clipUrl ?? '')
  registerQueueRoutes(router, store)
  registerContinuityRoutes(router, store)
  registerDirectorRoutes(router, store)
  registerProjectOpsRoutes(router, store)
  registerGenerationRoutes(router, store)

  // Local files the renderer would open with a `file://` URL under Electron.
  router.get('/api/__ui_mock/file', req => {
    const path = req.query.get('path') ?? ''
    if (isVideoPath(path) && options.clipUrl) {
      return new RawResponse(302, { location: options.clipUrl }, null)
    }
    return placeholderFrame(labelFromPath(path), path, path)
  })

  router.post('/api/__ui_mock/reset', () => {
    store.reset()
    return { status: 'ok', message: 'UI mock state reset to the seed project' }
  })

  async function handle(method: string, url: string, body: string): Promise<MockResult | null> {
    // A base is needed only to parse; relative and absolute URLs both work.
    const parsed = new URL(url, 'http://ui-mock.invalid')
    const match = router.match(method, parsed.pathname)
    if (!match) return null

    // Both simulations advance on wall-clock time, so bring them to the
    // present before any handler reads state.
    store.mutate(state => {
      tickQueue(state)
      tickGeneration(state)
    })

    const request: MockRequest = {
      method,
      path: parsed.pathname,
      query: parsed.searchParams,
      params: match.params,
      body: parseJsonBody(body),
    }

    try {
      const result = await match.handler(request)
      if (result instanceof RawResponse) {
        return { status: result.status, headers: result.headers, body: result.body ?? '' }
      }
      return {
        status: 200,
        headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
        body: JSON.stringify(result ?? null),
      }
    } catch (error) {
      const status = error instanceof MockHttpError ? error.status : 500
      const message = error instanceof Error ? error.message : String(error)
      if (status >= 500) console.error(`[ui-mock] ${method} ${request.path} failed:`, error)
      // The renderer reads `message` first and falls back to the whole body,
      // and the real backend sends both keys.
      return {
        status,
        headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
        body: JSON.stringify({ detail: message, message, error: message }),
      }
    }
  }

  return { handle, reset: () => store.reset() }
}
