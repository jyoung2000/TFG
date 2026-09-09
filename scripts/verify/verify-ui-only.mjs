// Walks the browser-only UI (`pnpm dev:ui`) screen by screen and checks that
// each one renders the same content it does in the packaged app, backed by the
// mock backend in devtools/ui-mock. No Python, no Electron, no GPU, no models.
//
// Run: pnpm dev:ui, then `node scripts/verify/verify-ui-only.mjs`
// (from a directory with playwright installed: npm i playwright)
import { chromium } from 'playwright'
import fs from 'node:fs'

const BASE = process.env.UI_ONLY_URL ?? 'http://127.0.0.1:5173'
const CHROME = process.env.CHROME_PATH ?? undefined
const SHOTS = './verify-shots/ui-only'
fs.mkdirSync(SHOTS, { recursive: true })

const results = []
const log = (step, ok, note = '') => {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.launch({ executablePath: CHROME, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
page.setDefaultTimeout(20000)
page.on('dialog', d => d.accept())

// Anything the page could not load is a real defect in UI-only mode: the whole
// point is that no request goes anywhere the browser cannot reach.
// Only same-origin failures matter: the app's web-font links go to Google and
// are expected to fail in a sandbox with no outbound network.
const sameOrigin = url => url.startsWith(BASE) || url.startsWith('http://localhost:5173')
const failedRequests = []
page.on('requestfailed', r => {
  const error = r.failure()?.errorText ?? ''
  // A video element that unmounts, or a page that navigates, aborts its own
  // range requests; that is the browser working normally, not a broken URL.
  if (error === 'net::ERR_ABORTED' && /\.(mp4|webm)$/i.test(new URL(r.url()).pathname)) return
  if (sameOrigin(r.url())) failedRequests.push(`${r.url()} (${error})`)
})
page.on('response', r => {
  if (r.status() >= 400 && sameOrigin(r.url())) failedRequests.push(`${r.status()} ${r.url()}`)
})
const pageErrors = []
page.on('pageerror', e => pageErrors.push(e.message))

const snap = name => page.screenshot({ path: `${SHOTS}/${name}.png` })
const api = (path, init = {}) =>
  page.evaluate(
    async ({ path, init }) => {
      const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
      const text = await res.text()
      let json = null
      try { json = JSON.parse(text) } catch {}
      return { status: res.status, json, text }
    },
    { path, init },
  )

try {
  // Always start from the seed so the run is repeatable.
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' })
  await api('/api/__ui_mock/reset', { method: 'POST' })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)

  // ---- 1. Boot ----
  log('Boots in a plain browser with no backend process', await page.getByText('What do you want to make?').isVisible())
  const health = await api('/health')
  log('Mock backend answers /health like the real one', health.status === 200 && health.json.models_loaded === true)
  await snap('01-home')

  // ---- 2. Quick video ----
  await page.getByRole('button', { name: /Quick video/i }).first().click()
  await page.waitForTimeout(1500)
  log(
    'Quick video renders prompt + settings',
    (await page.getByRole('button', { name: 'Generate' }).first().isVisible()) &&
      (await page.locator('textarea').first().isVisible()),
  )
  await snap('02-quick')

  // ---- 3. The demo film opens from Home like any saved project ----
  await page.getByRole('button', { name: /back to home/i }).first().click().catch(() => {})
  await page.waitForTimeout(800)
  log('The demo film is listed on Home', await page.getByText('The Relay (demo)').first().isVisible())
  await page.getByText('The Relay (demo)').first().click()
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(3500)
  const cards = await page.locator('[aria-label^="Shot "]').count()
  log('Storyboard opens on the seeded demo film', cards >= 6, `${cards} shot cards`)
  log('Scene headings render', await page.getByText('Relay station, night').first().isVisible())
  await snap('03-storyboard')

  // ---- 4. Media actually loads (the reason the mock is served over HTTP) ----
  const media = await page.evaluate(async () => {
    const images = [...document.querySelectorAll('img')].filter(i => i.src.includes('/api/'))
    const videos = [...document.querySelectorAll('video')].filter(v => v.src.includes('/api/'))
    const loaded = images.filter(i => i.naturalWidth > 0).length
    return { images: images.length, loaded, videos: videos.length }
  })
  log('Shot captures render as real images', media.images > 0 && media.loaded === media.images, `${media.loaded}/${media.images} images`)
  log('Rendered clips are served as playable video', media.videos > 0, `${media.videos} video elements`)

  // ---- 5. Continuity ----
  const continuity = await api('/api/film/projects/ui-mock-film/continuity')
  log(
    'Continuity reports a real issue on the seeded film',
    continuity.json.level === 'significant' && continuity.json.shots.some(s => s.level === 'significant'),
    `level=${continuity.json.level}`,
  )

  // ---- 6. Shot drawer ----
  await page.locator('[aria-label^="Shot "]').first().click()
  await page.waitForTimeout(1200)
  log('Shot drawer opens with the shot detail', await page.getByRole('button', { name: 'Close shot details' }).isVisible())
  await snap('04-drawer')
  await page.getByRole('button', { name: 'Close shot details' }).click()

  // ---- 7. Storyboard sub-tabs ----
  for (const [tab, marker] of [['Assets', 'Mara'], ['Script', 'RELAY STATION'], ['Models', 'Model Library']]) {
    await page.getByRole('tab', { name: tab, exact: true }).click()
    await page.waitForTimeout(1500)
    log(`${tab} tab renders`, await page.getByText(marker, { exact: false }).first().isVisible())
    await snap(`05-${tab.toLowerCase()}`)
  }

  // ---- 8. Model Library ----
  const library = await api('/api/models/library')
  log('Model Library lists local and hosted models', library.json.total >= 10, `${library.json.total} models`)
  log('Offline readiness is reported', typeof library.json.offline_ready === 'boolean' && library.json.offline_note.length > 0)

  // ---- 9. Settings ----
  await page.getByRole('tab', { name: 'Storyboard', exact: true }).click()
  await page.waitForTimeout(800)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'apiKeys' } })))
  await page.waitForTimeout(1200)
  log('Settings open with the provider cards', await page.getByLabel('OpenRouter API key').isVisible())
  await snap('06-settings')
  await page.keyboard.press('Escape')

  // ---- 10. Generation through the simulated queue ----
  const queued = await api('/api/film/projects/ui-mock-film/scenes/scene-2/shots/shot-2-2/generate', {
    method: 'POST',
    body: JSON.stringify({ kind: 'preview' }),
  })
  log('A shot can be queued for render', queued.status === 200 && queued.json.status === 'queued')
  await page.waitForTimeout(2500)
  const queue = await api('/api/film/queue')
  log('The queue reports an active job with progress', queue.json.active !== null && queue.json.progress !== null, `${queue.json.progress}% ${queue.json.phase}`)
  await api('/api/film/queue/cancel', { method: 'POST' })

  // ---- 11. Editing round-trips through the mock ----
  const renamed = await api('/api/film/projects/ui-mock-film/scenes/scene-1/shots/shot-1-1', {
    method: 'PUT',
    body: JSON.stringify({ title: 'Renamed by the verifier' }),
  })
  log('Shot edits persist in the mock backend', renamed.json.title === 'Renamed by the verifier')

  // ---- 12. Nothing broke along the way ----
  log('No page errors', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '))
  log('No failed same-origin requests', failedRequests.length === 0, failedRequests.slice(0, 3).join(' | '))
} finally {
  fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2))
  const passed = results.filter(r => r.ok).length
  console.log(`\n${passed}/${results.length} passed`)
  await browser.close()
  if (passed !== results.length) process.exitCode = 1
}
