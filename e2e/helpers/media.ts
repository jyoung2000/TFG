import { expect, type ConsoleMessage, type Page } from '@playwright/test'

/**
 * Media-integrity helper.
 *
 * `attachConsoleGuard()` records every `console.error` and uncaught page
 * error from the moment it is attached. `expectMediaIntact()` then checks
 * that every rendered `<img>` decoded to a real bitmap (`naturalWidth > 0`)
 * and every `<video>` reached `HAVE_METADATA` (`readyState >= 1`), and that
 * no console errors were recorded. Call it once per view, after the view has
 * settled.
 */
export interface ConsoleGuard {
  errors: string[]
  /** Ignore noise that is not the app's fault (e.g. the dev server's HMR socket). */
  ignore: RegExp[]
}

const DEFAULT_IGNORE: RegExp[] = [
  /\[vite\] (connecting|connected)/i,
  /WebSocket connection to 'ws:\/\/.*' failed/i, // HMR socket races on shutdown
]

/**
 * Hosts whose failures are the sandbox's, not the app's: Google Fonts is
 * blocked or re-signed by some CI egress proxies. The app must render without
 * it (system font fallback), so a failed font fetch is not an app error.
 */
const ENVIRONMENT_HOSTS = [/^https:\/\/fonts\.googleapis\.com\//, /^https:\/\/fonts\.gstatic\.com\//]

export function attachConsoleGuard(page: Page, ignore: RegExp[] = []): ConsoleGuard {
  const guard: ConsoleGuard = { errors: [], ignore: [...DEFAULT_IGNORE, ...ignore] }
  const record = (text: string) => {
    if (guard.ignore.some(re => re.test(text))) return
    guard.errors.push(text)
  }
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return
    const url = msg.location().url
    if (url && ENVIRONMENT_HOSTS.some(re => re.test(url))) return
    // "Failed to load resource" carries no URL in its text; requestfailed/response below name it.
    if (/Failed to load resource/.test(msg.text())) return
    record(`console.error: ${msg.text()}`)
  })
  page.on('pageerror', err => record(`pageerror: ${err.message}`))
  page.on('requestfailed', req => {
    const url = req.url()
    if (ENVIRONMENT_HOSTS.some(re => re.test(url))) return
    const reason = req.failure()?.errorText ?? 'unknown'
    // A media element abandons its request when the codec is unsupported; the
    // media check below decides whether that is acceptable for this browser.
    if (reason === 'net::ERR_ABORTED' && (req.resourceType() === 'media' || /\.(mp4|webm|mov|m4v|ogv)(\?|$)/i.test(url))) return
    record(`request failed: ${url} (${reason})`)
  })
  page.on('response', res => {
    if (res.status() >= 400 && !ENVIRONMENT_HOSTS.some(re => re.test(res.url()))) {
      record(`HTTP ${res.status()}: ${res.url()}`)
    }
  })
  return guard
}

interface MediaReport {
  images: { src: string; ok: boolean; complete: boolean; naturalWidth: number }[]
  videos: { src: string; ok: boolean; readyState: number; error: string | null; codecLimited: boolean }[]
  /** False in open-source Chromium builds, which ship no H.264 decoder. */
  h264: boolean
}

async function collectMedia(page: Page): Promise<MediaReport> {
  return page.evaluate(async () => {
    const imgs = Array.from(document.querySelectorAll('img'))
    const vids = Array.from(document.querySelectorAll('video'))
    const settle = (el: HTMLImageElement | HTMLVideoElement) =>
      new Promise<void>(resolve => {
        const isImg = el instanceof HTMLImageElement
        if (isImg ? (el as HTMLImageElement).complete : (el as HTMLVideoElement).readyState >= 1) return resolve()
        const done = () => resolve()
        el.addEventListener(isImg ? 'load' : 'loadedmetadata', done, { once: true })
        el.addEventListener('error', done, { once: true })
        setTimeout(done, 10_000)
      })
    await Promise.all([...imgs, ...vids].map(settle))
    const probe = document.createElement('video')
    const h264 = probe.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"') !== ''
    const videos = await Promise.all(vids.map(async v => {
      const src = v.currentSrc || v.src
      const decoded = v.readyState >= 1 && !v.error
      // MEDIA_ERR_SRC_NOT_SUPPORTED (4) on an H.264 file in a browser without
      // the decoder: prove the bytes are there and are video, and mark the row
      // so the report shows the check was codec-limited rather than green.
      let codecLimited = false
      let ok = decoded
      if (!decoded && !h264 && v.error?.code === 4 && src) {
        try {
          // GET rather than HEAD: mock servers and redirects often serve only GET.
          // Abort as soon as the headers are in; the body is not needed.
          const controller = new AbortController()
          const response = await fetch(src, { method: 'GET', signal: controller.signal })
          const type = response.headers.get('content-type') ?? ''
          ok = response.ok && type.startsWith('video/')
          codecLimited = ok
          controller.abort()
        } catch {
          ok = false
        }
      }
      return { src, ok, readyState: v.readyState, error: v.error ? `${v.error.code}: ${v.error.message}` : null, codecLimited }
    }))
    return {
      images: imgs.map(img => ({
        src: img.currentSrc || img.src,
        ok: img.complete && img.naturalWidth > 0,
        complete: img.complete,
        naturalWidth: img.naturalWidth,
      })),
      videos,
      h264,
    }
  })
}

export interface MediaExpectations {
  /** Fail unless at least this many images rendered (guards against an empty view "passing"). */
  minImages?: number
  minVideos?: number
}

export async function expectMediaIntact(page: Page, guard: ConsoleGuard, expectations: MediaExpectations = {}): Promise<MediaReport> {
  const report = await collectMedia(page)
  const brokenImages = report.images.filter(i => !i.ok)
  const brokenVideos = report.videos.filter(v => !v.ok)
  expect(brokenImages, `broken <img>: ${JSON.stringify(brokenImages, null, 1)}`).toEqual([])
  expect(brokenVideos, `broken <video>: ${JSON.stringify(brokenVideos, null, 1)}`).toEqual([])
  if (expectations.minImages !== undefined) {
    expect(report.images.length, 'rendered <img> count').toBeGreaterThanOrEqual(expectations.minImages)
  }
  if (expectations.minVideos !== undefined) {
    expect(report.videos.length, 'rendered <video> count').toBeGreaterThanOrEqual(expectations.minVideos)
  }
  expect(guard.errors, 'console errors').toEqual([])
  const limited = report.videos.filter(v => v.codecLimited)
  if (limited.length) {
    // eslint-disable-next-line no-console
    console.warn(`[media] ${limited.length} H.264 video(s) verified by HTTP only: this Chromium has no H.264 decoder.`)
  }
  return report
}

/**
 * Let React settle and pending fetches resolve before checking media. The
 * mock backend polls and the hero video streams, so `networkidle` never
 * arrives (and the runner's navigation timeout is off by default), so a short
 * fixed wait is the honest option here.
 */
export async function settle(page: Page, ms = 800): Promise<void> {
  await page.waitForTimeout(ms)
}
