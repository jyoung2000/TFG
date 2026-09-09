/**
 * Stand-in media for UI-only mode.
 *
 * Captures and reference images are drawn as SVG so they carry a readable
 * label (which shot, which asset) instead of being grey boxes — that makes
 * layout and cropping problems obvious while working on the UI. Rendered
 * clips redirect to a real video already in the repo, so `<video>`, thumbnail
 * extraction from a canvas, duration probing and the timeline all behave as
 * they do against the Python backend.
 */

import { RawResponse, redirect } from './http'

/** A real MP4 that Vite already serves from `public/`. */
const SAMPLE_CLIP = '/splash/splash.mp4'

const PALETTE = [
  ['#0f172a', '#334155', '#f8fafc'],
  ['#1c1917', '#78350f', '#fef3c7'],
  ['#082f49', '#0e7490', '#ecfeff'],
  ['#2e1065', '#7c3aed', '#f5f3ff'],
  ['#1a2e05', '#4d7c0f', '#f7fee7'],
]

function hash(value: string): number {
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) | 0
  return Math.abs(h)
}

function escapeXml(value: string): string {
  return value.replace(/[<>&'"]/g, ch =>
    ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : ch === '&' ? '&amp;' : ch === "'" ? '&apos;' : '&quot;',
  )
}

/**
 * A 16:9 placeholder frame labelled with `title`, with a second line of
 * detail and a mock-mode marker so a screenshot is never mistaken for a real
 * render.
 */
export function placeholderFrame(title: string, detail = '', seed = title): RawResponse {
  const [bg, accent, ink] = PALETTE[hash(seed) % PALETTE.length]
  const angle = (hash(seed + 'a') % 60) - 30
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" role="img" aria-label="${escapeXml(title)}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${bg}"/>
      <stop offset="100%" stop-color="${accent}"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#g)"/>
  <g opacity="0.18" stroke="${ink}" stroke-width="2" transform="rotate(${angle} 640 360)">
    <line x1="-200" y1="240" x2="1480" y2="180"/>
    <line x1="-200" y1="420" x2="1480" y2="500"/>
    <circle cx="640" cy="360" r="210" fill="none"/>
  </g>
  <g opacity="0.35" stroke="${ink}" stroke-width="1.5" fill="none">
    <rect x="426" y="0" width="1" height="720"/>
    <rect x="853" y="0" width="1" height="720"/>
    <rect x="0" y="240" width="1280" height="1"/>
    <rect x="0" y="480" width="1280" height="1"/>
  </g>
  <text x="64" y="600" fill="${ink}" font-family="Inter, system-ui, sans-serif" font-size="54" font-weight="600">${escapeXml(title)}</text>
  <text x="64" y="654" fill="${ink}" opacity="0.75" font-family="Inter, system-ui, sans-serif" font-size="30">${escapeXml(detail)}</text>
  <text x="64" y="96" fill="${ink}" opacity="0.6" font-family="Inter, system-ui, sans-serif" font-size="26" letter-spacing="4">UI MOCK — NOT A RENDER</text>
</svg>`
  return new RawResponse(
    200,
    { 'content-type': 'image/svg+xml; charset=utf-8', 'cache-control': 'no-store' },
    svg,
  )
}

/** Rendered clips point at the sample video so playback is genuinely real. */
export function sampleClip(): RawResponse {
  return redirect(SAMPLE_CLIP)
}

/** Treat anything that looks like a video path as a clip, everything else as a frame. */
export function isVideoPath(path: string): boolean {
  return /\.(mp4|webm|mov|mkv)$/i.test(path)
}

/** "captures/shot-1-2.png" → "shot 1 2" — a label a human can read on the frame. */
export function labelFromPath(path: string): string {
  const base = path.split(/[\\/]/).pop() ?? path
  return base.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ')
}
