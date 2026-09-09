// Drives the real Electron app over CDP and exercises the hardening features:
// Home entry points, Quick video, Filmmaker Studio, Build Film (offline),
// continuity levels + fixes, quality profiles, queue failure path, OpenRouter
// settings (placeholder key, never a real one), simple/advanced, Quick→Film
// conversion through the backend API.
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const SHOTS = './verify-shots/hardening'
fs.mkdirSync(SHOTS, { recursive: true })

const results = []
function log(step, ok, note = '') {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.connectOverCDP('http://127.0.0.1:9222')
const context = browser.contexts()[0]
let page = context.pages().find(p => p.url().includes('localhost:5173')) ?? context.pages()[0]
if (!page) throw new Error('No page found over CDP')
await page.bringToFront()
page.setDefaultTimeout(20000)
page.on('dialog', d => d.accept())

const snap = name => page.screenshot({ path: `${SHOTS}/${name}.png` })
const RUN = Date.now().toString(36).slice(-5)

async function api(pathname, init = {}) {
  return page.evaluate(
    async ({ pathname, init }) => {
      const { url, token } = await window.electronAPI.getBackend()
      const res = await fetch(`${url}${pathname}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init.headers || {}) },
      })
      const text = await res.text()
      let json = null
      try { json = JSON.parse(text) } catch {}
      return { status: res.status, json, text }
    },
    { pathname, init },
  )
}

try {
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  // Dismiss the API-key gateway if it appears.
  const keyInput = page.locator('input[placeholder*="LTX API key"]').first()
  if (await keyInput.isVisible().catch(() => false)) {
    await keyInput.fill('sk-verification-dummy-key-000')
    await page.getByRole('button', { name: /^(Save|Connect|Continue)/i }).first().click().catch(() => {})
    await page.waitForTimeout(1500)
    const close = page.getByRole('button', { name: /close|done|continue/i }).first()
    if (await close.isVisible().catch(() => false)) await close.click().catch(() => {})
  }

  // Providers are app-wide and persist between runs; start from a clean slate
  // so "no provider configured" assertions mean what they say.
  for (const provider of ['anthropic', 'xai', 'openrouter', 'gemini', 'openai-compatible', 'fal', 'wavespeed', 'replicate']) {
    await api(`/api/settings/api-keys/${provider}`, { method: 'DELETE' }).catch(() => {})
  }
  await api('/api/settings', {
    method: 'POST',
    body: JSON.stringify({ directorProvider: 'auto', mediaProvider: 'local', defaultVideoModel: '', defaultImageModel: '' }),
  }).catch(() => {})
  // Make sure we are on Home (dev server keeps view state in memory only).
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  await snap('00-start')

  // ---- 1. Home: what do you want to make + getting started ----
  await page.getByText('What do you want to make?').waitFor({ state: 'visible' })
  log('Home shows "What do you want to make?"', true)
  const gs = page.getByRole('region', { name: 'Getting started' })
  const gsVisible = await gs.isVisible().catch(() => false)
  log('Getting started strip present (or previously dismissed)', true, gsVisible ? 'visible' : 'dismissed earlier')
  await snap('01-home')

  // ---- 2. Quick video view ----
  await page.getByRole('button', { name: /Start a quick video|Quick video/ }).first().click()
  await page.getByLabel('Video prompt').waitFor({ state: 'visible' })
  const hasModel = await page.getByLabel('Model').isVisible()
  const hasDuration = await page.getByLabel('Duration').isVisible()
  log('Quick video view renders prompt + settings', hasModel && hasDuration)
  const assistantHint = await page.getByText(/connect an AI provider .* to enable/i).first().isVisible().catch(() => false)
  log('Quick video explains how to enable the assistant when no key is set', assistantHint)
  await snap('02-quick')
  await page.getByRole('button', { name: 'Back to home' }).click()
  await page.getByText('What do you want to make?').waitFor({ state: 'visible' })

  // ---- 3. Filmmaker Studio → new film opens on Storyboard ----
  await page.getByRole('button', { name: /Create a film project|Filmmaker Studio/ }).first().click()
  await page.getByText('Create New Film').waitFor({ state: 'visible' })
  await page.locator('input[placeholder="Project name"]').fill(`Hardening Film ${RUN}`)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(2500)
  const storyboardTabActive = await page.getByRole('button', { name: 'Storyboard' }).first().evaluate(el => el.className.includes('bg-zinc-800'))
  log('New film opens on the Storyboard tab', storyboardTabActive)
  await page.getByRole('button', { name: 'Build Film with AI' }).first().waitFor({ state: 'visible' })
  log('Empty storyboard offers Build Film with AI', true)
  await snap('03-empty-storyboard')

  // ---- 4. Build Film with AI (offline planner) → editable plan → apply ----
  await page.getByRole('button', { name: 'Build Film with AI' }).first().click()
  await page.getByRole('dialog', { name: /Build Film with AI/ }).waitFor({ state: 'visible' })
  await page.getByRole('dialog', { name: /Build Film with AI/ }).locator('textarea').first().fill(
    'A courier races across a flooded city to deliver a package before dawn. She finally opens it and it is empty. She laughs.',
  )
  await page.getByRole('button', { name: 'Plan offline' }).click()
  await page.getByText(/scenes ·.*shots ·.*characters/).waitFor({ state: 'visible' })
  const sceneTitle = page.getByLabel('Scene title').first()
  await sceneTitle.fill('Flooded streets')
  log('Offline plan produced and is editable', true)
  await snap('04-build-plan')
  await page.getByRole('button', { name: /Apply (all|selected)/ }).click()
  await page.waitForTimeout(2500)
  const cards = page.locator('[role="button"][aria-label^="Shot "]')
  const cardCount = await cards.count()
  log('Plan applied: shot cards created', cardCount >= 3, `${cardCount} cards`)
  const hasSceneTitle = await page.getByText('Flooded streets').first().isVisible().catch(() => false)
  log('Edited scene title survived apply', hasSceneTitle)
  await snap('05-storyboard-after-build')

  // ---- 5. Shot drawer: continuity good, quality profile, refine disabled ----
  await cards.first().focus()
  await page.keyboard.press('Enter')
  await page.getByText('Continuity good').waitFor({ state: 'visible' })
  log('Shot drawer opens via keyboard and shows continuity GOOD', true)
  const qualityPicker = page.getByLabel('Quality profile')
  log('Quality profile picker present (advanced mode)', await qualityPicker.isVisible())
  const refine = page.getByRole('button', { name: /Refine with AI/ })
  log('Refine with AI disabled without a provider', await refine.isDisabled())
  await snap('06-drawer')

  // ---- 6. Continuity level + fix through the API against the same shot ----
  const projects = await page.evaluate(() => JSON.parse(localStorage.getItem('ltx-projects') || '[]'))
  const project = projects.find(p => p.name === `Hardening Film ${RUN}`)
  const film = (await api(`/api/film/projects/${encodeURIComponent(project.id)}`)).json.project
  const scene = film.scenes[0]
  const shot = scene.shots[0]
  const cafe = (await api(`/api/film/projects/${project.id}/assets`, { method: 'POST', body: JSON.stringify({ kind: 'location', name: 'Cafe' }) })).json.asset
  const alley = (await api(`/api/film/projects/${project.id}/assets`, { method: 'POST', body: JSON.stringify({ kind: 'location', name: 'Alley' }) })).json.asset
  await api(`/api/film/projects/${project.id}/scenes/${scene.id}`, { method: 'PUT', body: JSON.stringify({ location_id: cafe.id }) })
  await api(`/api/film/projects/${project.id}/scenes/${scene.id}/shots/${shot.id}`, { method: 'PUT', body: JSON.stringify({ location_id: alley.id }) })
  // Close + reopen the drawer so it refetches.
  await page.getByRole('button', { name: 'Close shot details' }).click()
  await page.waitForTimeout(2500)
  await cards.first().click()
  await page.getByText('Significant continuity issues').waitFor({ state: 'visible' })
  log('Location mismatch shows as SIGNIFICANT in the drawer', true)
  const dot = page.locator('[aria-label="Significant continuity issues"]').first()
  log('Storyboard card carries the continuity dot', await dot.isVisible().catch(() => false))
  await snap('07-continuity-significant')
  await page.getByRole('button', { name: 'Fix' }).first().click()
  await page.getByText('Continuity good').waitFor({ state: 'visible' })
  log('One-click Fix returns the shot to GOOD', true)
  await snap('08-continuity-fixed')

  // ---- 7. Generation failure path is persisted with a clear error (API mode, dummy key) ----
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  let afterGen = null
  let v = null
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(2500)
    afterGen = (await api(`/api/film/projects/${project.id}`)).json.project
    v = afterGen.scenes[0].shots[0].versions.at(-1)
    if (v && (v.status === 'failed' || v.status === 'complete' || v.status === 'cancelled')) break
  }
  log('Preview attempt recorded as a version', !!v, v ? `${v.status}: ${(v.error || '').slice(0, 80)}` : 'no version')
  const terminal = v && v.status !== 'generating' && v.status !== 'queued'
  log('Generation reached a terminal state within 30s', !!terminal, terminal ? afterGen.scenes[0].shots[0].status : `still ${v?.status} (WanGP bridge without a GPU in this container)`)
  if (!terminal) {
    await api('/api/film/queue/cancel', { method: 'POST' })
    await page.waitForTimeout(3000)
    afterGen = (await api(`/api/film/projects/${project.id}`)).json.project
    v = afterGen.scenes[0].shots[0].versions.at(-1)
    log('Cancel resolves the stuck job', v.status === 'cancelled' || v.status === 'failed', `${v.status} / shot ${afterGen.scenes[0].shots[0].status}`)
  }
  const queue = (await api('/api/film/queue')).json
  log('Queue payload has pause/progress fields', 'paused' in queue && 'progress' in queue)
  await snap('09-after-generate')
  await page.getByRole('button', { name: 'Close shot details' }).click()

  // ---- 8. Queue pause/resume controls ----
  await api('/api/film/queue/pause', { method: 'POST' })
  await page.waitForTimeout(2500)
  const resumeBtn = page.getByRole('button', { name: /Resume/ })
  log('Paused queue shows Resume in the header', await resumeBtn.isVisible().catch(() => false))
  await snap('10-queue-paused')
  if (await resumeBtn.isVisible().catch(() => false)) await resumeBtn.click()
  await page.waitForTimeout(1500)

  // ---- 9. Simple / Advanced toggle ----
  await page.getByRole('button', { name: /^Advanced$/ }).click()
  await page.waitForTimeout(500)
  const scriptTabHidden = !(await page.getByRole('tab', { name: 'Script' }).isVisible().catch(() => false))
  log('Simple mode hides the Script tab', scriptTabHidden)
  await snap('11-simple-mode')
  await page.getByRole('button', { name: /^Simple$/ }).click()
  await page.waitForTimeout(500)
  log('Advanced mode restores tabs', await page.getByRole('tab', { name: 'Script' }).isVisible())

  // ---- 10. Models tab: profiles + render defaults ----
  await page.getByRole('tab', { name: 'Models' }).click()
  await page.waitForTimeout(500)
  // The Models tab opens on the Model Library; profiles live in the second view.
  await page.getByRole('tab', { name: 'Installed & GPU', exact: true }).click()
  await page.getByText('Quality profiles').waitFor({ state: 'visible' })
  log('Models tab lists quality profiles', true)
  log('Project render defaults card present', await page.getByText('Project render defaults').isVisible())
  await snap('12-models')

  // ---- 11. Settings → API Keys → OpenRouter (placeholder key, never real) ----
  await page.getByRole('tab', { name: 'Storyboard' }).click()
  window_open_settings: {
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'apiKeys' } })))
    await page.waitForTimeout(800)
  }
  const orInput = page.getByLabel('OpenRouter API key')
  await orInput.waitFor({ state: 'visible' })
  log('OpenRouter section present in Settings → API Keys', true)
  const inputType = await orInput.getAttribute('type')
  log('OpenRouter key input is masked', inputType === 'password')
  await orInput.fill('test-placeholder-not-a-real-key')
  await page.getByRole('button', { name: 'Save Key' }).nth(2).click()
  await page.waitForTimeout(4000)
  const settingsAfter = (await api('/api/settings')).json
  log('Backend reports hasOpenrouterApiKey without exposing the key', settingsAfter.hasOpenrouterApiKey === true && !JSON.stringify(settingsAfter).includes('test-placeholder'))
  const validationShown = await page.getByText(/OpenRouter rejected|unreachable|Key accepted|✗|✓/).first().isVisible().catch(() => false)
  log('Key validation feedback displayed', validationShown)
  await snap('13-openrouter-settings')
  const status = (await api('/api/film/director/status')).json
  log('Director status: OpenRouter active with placeholder key', status.active_provider === 'openrouter')
  // Remove key cleanly.
  await page.getByRole('button', { name: /^Remove$/ }).first().click()
  await page.waitForTimeout(1500)
  const settingsCleared = (await api('/api/settings')).json
  log('Remove clears the stored key', settingsCleared.hasOpenrouterApiKey === false)
  await page.getByRole('button', { name: 'Done' }).click()
  await page.waitForTimeout(500)

  // ---- 12. Director bar explains missing provider with a settings link ----
  const directorLink = page.getByRole('button', { name: /to enable the AI Director/ })
  log('Director bar links to settings when no provider', await directorLink.isVisible().catch(() => false))

  // ---- 13. Quick → Film conversion via backend (real clip file) ----
  const clipDir = path.join(process.env.LTX_APP_DATA_DIR || '/root/.local/share/LTXDesktop', 'outputs')
  fs.mkdirSync(clipDir, { recursive: true })
  const clip = path.join(clipDir, `verify-quick-${RUN}.mp4`)
  fs.writeFileSync(clip, Buffer.from('fake-video'))
  const imported = await api(`/api/film/projects/quick-${RUN}/import-generation`, {
    method: 'POST',
    body: JSON.stringify({ prompt: 'A lone fisherman rows through fog', output_path: clip, model: 'fast', resolution: '540p', duration_seconds: 5, seed: 77, project_name: 'Quick conversion' }),
  })
  const imp = imported.json
  log('import-generation creates Scene 1 / Shot 1 / v1 with seed preserved', imported.status === 200 && imp.project.scenes[0].shots[0].generation.seed === 77 && imp.project.scenes[0].shots[0].versions[0].output_path === clip, `status ${imported.status}`)

  // ---- 14. Export / import package through the API (dialogs are native) ----
  const dest = path.join(clipDir, `verify-${RUN}.ltxfilm`)
  const exp = await api(`/api/film/projects/${project.id}/export`, { method: 'POST', body: JSON.stringify({ destination_path: dest, include_outputs: true }) })
  log('Export writes an .ltxfilm package', exp.status === 200 && fs.existsSync(dest), exp.json ? `${exp.json.media_files} media files` : exp.text.slice(0, 80))
  const insp = await api(`/api/film/packages/inspect?package_path=${encodeURIComponent(dest)}`)
  const imp2 = await api(`/api/film/projects/imported-${RUN}/import`, { method: 'POST', body: JSON.stringify({ package_path: dest }) })
  log('Inspect + import round-trip', insp.status === 200 && imp2.status === 200 && imp2.json.project.scenes.length === film.scenes.length)
} catch (err) {
  log('unexpected failure', false, String(err && err.stack ? err.stack.split('\n').slice(0, 3).join(' | ') : err))
  await snap('99-error').catch(() => {})
}

const passed = results.filter(r => r.ok).length
console.log(`\n${passed}/${results.length} passed`)
fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2))
await browser.close()
process.exit(passed === results.length ? 0 : 1)
