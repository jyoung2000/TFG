/**
 * Assembles the UI-only mock backend and exposes it as connect middleware.
 */

import type { IncomingMessage, ServerResponse } from 'node:http'

import {
  MockHttpError,
  RawResponse,
  Router,
  readJsonBody,
  sendJson,
  sendRaw,
  type MockRequest,
} from './http'
import { isVideoPath, labelFromPath, placeholderFrame, sampleClip } from './media'
import { registerContinuityRoutes } from './routes/continuity'
import { registerDirectorRoutes } from './routes/director'
import { registerFilmRoutes } from './routes/film'
import { registerGenerationRoutes, tickGeneration } from './routes/generation'
import { registerModelRoutes } from './routes/models'
import { registerProjectOpsRoutes } from './routes/project-ops'
import { registerQueueRoutes, tickQueue } from './routes/queue'
import { registerSettingsRoutes } from './routes/settings'
import { Store } from './state'

export function createMockBackend(stateFile: string) {
  const store = new Store(stateFile)
  const router = new Router()

  registerSettingsRoutes(router, store)
  registerModelRoutes(router, store)
  registerFilmRoutes(router, store)
  registerQueueRoutes(router, store)
  registerContinuityRoutes(router, store)
  registerDirectorRoutes(router, store)
  registerProjectOpsRoutes(router, store)
  registerGenerationRoutes(router, store)

  // Local files the renderer would open with a `file://` URL under Electron.
  router.get('/api/__ui_mock/file', req => {
    const path = req.query.get('path') ?? ''
    if (isVideoPath(path)) return sampleClip()
    return placeholderFrame(labelFromPath(path), path, path)
  })

  router.post('/api/__ui_mock/reset', () => {
    store.reset()
    return { status: 'ok', message: 'UI mock state reset to the seed project' }
  })

  async function handle(req: IncomingMessage, res: ServerResponse): Promise<boolean> {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    const match = router.match(req.method ?? 'GET', url.pathname)
    if (!match) return false

    // Both simulations advance on wall-clock time, so bring them to the
    // present before any handler reads state.
    store.mutate(state => {
      tickQueue(state)
      tickGeneration(state)
    })

    const request: MockRequest = {
      method: req.method ?? 'GET',
      path: url.pathname,
      query: url.searchParams,
      params: match.params,
      body: await readJsonBody(req),
    }

    try {
      const result = await match.handler(request)
      if (result instanceof RawResponse) sendRaw(res, result)
      else sendJson(res, 200, result)
    } catch (error) {
      const status = error instanceof MockHttpError ? error.status : 500
      const message = error instanceof Error ? error.message : String(error)
      if (status >= 500) console.error(`[ui-mock] ${request.method} ${request.path} failed:`, error)
      // The renderer reads `message` first and falls back to the whole body,
      // and the real backend sends both keys.
      sendJson(res, status, { detail: message, message, error: message })
    }
    return true
  }

  return {
    /** True when this request was one of ours. */
    handle,
    reset: () => store.reset(),
  }
}
