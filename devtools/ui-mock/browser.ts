/**
 * Runs the UI-only mock backend inside the browser, with no server at all.
 *
 * This is what makes the standalone build a file you can double-click: the
 * same routes and the same state machine the dev server hosts, reached through
 * a patched `fetch` instead of HTTP, with state in `localStorage` and media
 * resolved straight to `data:` and `blob:` URLs — because a `file://` page has
 * no origin that could serve them.
 *
 * Only ever loaded when `VITE_UI_STANDALONE` is set; the app build has no
 * reference to it.
 */

import { placeholderDataUrl } from './media'
import { createMockBackend, type MockBackend } from './server'
import type { Persistence } from './state'

const STATE_KEY = 'ltx-ui-mock-state'

/** Resolvers the renderer uses in place of URLs it would fetch from a backend. */
export interface MediaResolver {
  media(projectId: string, path: string): Promise<string>
  output(path: string): Promise<string>
  file(path: string): string
}

function localStoragePersistence(): Persistence {
  return {
    read: () => {
      try {
        return localStorage.getItem(STATE_KEY)
      } catch {
        return null
      }
    },
    write: data => {
      try {
        localStorage.setItem(STATE_KEY, data)
      } catch {
        // Quota or a privacy mode that blocks storage: the session still works,
        // it just will not survive a reload.
      }
    },
  }
}

const isVideo = (path: string) => /\.(mp4|webm|mov|mkv)$/i.test(path)

/**
 * A few seconds of real video, drawn in a canvas and captured.
 *
 * The alternative — shipping an encoded clip inside the HTML — would add
 * megabytes of base64 to a file meant to be easy to pass around. Recording one
 * costs nothing to ship and gives genuinely playable video, so `<video>`,
 * canvas thumbnail extraction and the timeline all behave normally.
 */
async function recordClip(): Promise<string | null> {
  if (typeof MediaRecorder === 'undefined') return null
  const canvas = document.createElement('canvas')
  canvas.width = 1280
  canvas.height = 720
  const ctx = canvas.getContext('2d')
  if (!ctx || typeof canvas.captureStream !== 'function') return null

  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(
    type => MediaRecorder.isTypeSupported?.(type),
  )
  if (!mimeType) return null

  try {
    const stream = canvas.captureStream(24)
    const recorder = new MediaRecorder(stream, { mimeType })
    const chunks: Blob[] = []
    recorder.ondataavailable = event => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    const stopped = new Promise<void>(resolve => {
      recorder.onstop = () => resolve()
    })
    recorder.start()

    const start = performance.now()
    const DURATION = 2600
    await new Promise<void>(resolve => {
      const draw = () => {
        const elapsed = performance.now() - start
        const t = elapsed / DURATION
        const sweep = ctx.createLinearGradient(0, 0, canvas.width, canvas.height)
        sweep.addColorStop(0, '#0f172a')
        sweep.addColorStop(1, `hsl(${210 + t * 60}, 45%, ${18 + t * 12}%)`)
        ctx.fillStyle = sweep
        ctx.fillRect(0, 0, canvas.width, canvas.height)

        ctx.save()
        ctx.translate(canvas.width / 2, canvas.height / 2)
        ctx.rotate(t * Math.PI * 0.4)
        ctx.strokeStyle = 'rgba(248, 250, 252, 0.35)'
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.arc(0, 0, 160 + Math.sin(t * Math.PI * 2) * 30, 0, Math.PI * 2)
        ctx.stroke()
        ctx.restore()

        ctx.fillStyle = 'rgba(248, 250, 252, 0.85)'
        ctx.font = '600 44px Inter, system-ui, sans-serif'
        ctx.fillText('UI MOCK — NOT A RENDER', 64, 96)
        ctx.font = '400 30px Inter, system-ui, sans-serif'
        ctx.fillText(`${(elapsed / 1000).toFixed(1)}s`, 64, canvas.height - 64)

        if (elapsed < DURATION) requestAnimationFrame(draw)
        else resolve()
      }
      requestAnimationFrame(draw)
    })

    recorder.stop()
    await stopped
    if (chunks.length === 0) return null
    return URL.createObjectURL(new Blob(chunks, { type: mimeType }))
  } catch {
    return null
  }
}

let clipPromise: Promise<string | null> | null = null
let clipUrl: string | null = null

function clip(): Promise<string | null> {
  if (!clipPromise) {
    clipPromise = recordClip().then(url => {
      clipUrl = url
      return url
    })
  }
  return clipPromise
}

/** "captures/shot-1-2.png" → "shot 1 2". */
function label(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? path
  return base.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ')
}

async function resolveAsync(path: string, detail: string): Promise<string> {
  if (isVideo(path)) return (await clip()) ?? placeholderDataUrl(label(path), 'video unavailable here', path)
  return placeholderDataUrl(label(path), detail, path)
}

export interface BrowserMock {
  backend: MockBackend
  media: MediaResolver
}

/**
 * Patch `fetch` so every backend call the renderer makes is answered locally,
 * and hand back the media resolvers. Idempotent.
 */
export function installBrowserMock(): BrowserMock {
  const backend = createMockBackend({ persistence: localStoragePersistence() })
  void clip()

  const original = window.fetch.bind(window)
  const ours = (pathname: string) => pathname.startsWith('/api/') || pathname === '/health'

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : null
    const rawUrl = request ? request.url : String(input)
    let pathname: string
    try {
      pathname = new URL(rawUrl, window.location.href).pathname
    } catch {
      return original(input as RequestInfo, init)
    }
    if (!ours(pathname)) return original(input as RequestInfo, init)

    const method = (init?.method ?? request?.method ?? 'GET').toUpperCase()
    let body = ''
    if (typeof init?.body === 'string') body = init.body
    else if (request) body = await request.clone().text().catch(() => '')

    const search = rawUrl.includes('?') ? rawUrl.slice(rawUrl.indexOf('?')) : ''
    const result = await backend.handle(method, `${pathname}${search}`, body)
    if (!result) return new Response('Not found', { status: 404 })
    return new Response(result.body, { status: result.status, headers: result.headers })
  }

  const media: MediaResolver = {
    media: (projectId, path) => resolveAsync(path, `${projectId} · ${path}`),
    output: path => resolveAsync(path, path),
    // Sync, because the renderer builds these URLs inline. The clip is
    // recorded at startup, so by the time a render "finishes" it is ready.
    file: path =>
      isVideo(path)
        ? (clipUrl ?? placeholderDataUrl(label(path), 'clip still recording', path))
        : placeholderDataUrl(label(path), path, path),
  }

  return { backend, media }
}
