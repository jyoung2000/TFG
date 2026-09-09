// Release-candidate walkthrough over CDP against the dev Electron app:
// Shot Composer (gizmo, camera row, lock, keyframes, generate panel),
// storyboard undo/redo + gap controls, Models tab states + model location,
// Settings OpenAI-compatible endpoint, drawer AI visual check, AI Director
// set_ots changing real shot state, Quick Mode reference-image zone, and the
// timeline/Film Maker link through the shared conversion. Never uses a real
// key. Run: ELECTRON_DEBUG=1 pnpm dev (under xvfb-run -a on headless Linux),
// then `node scripts/verify/verify-rc.mjs`.
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const SHOTS = './verify-shots/rc'
fs.mkdirSync(SHOTS, { recursive: true })
const results = []
const log = (step, ok, note = '') => {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.connectOverCDP('http://127.0.0.1:9222')
const context = browser.contexts()[0]
const page = context.pages().find(p => p.url().includes('localhost:5173')) ?? context.pages()[0]
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
  await page.waitForTimeout(1000)
  const back = page.getByRole('button', { name: /back to home/i }).first()
  if (await back.isVisible().catch(() => false)) { await back.click(); await page.waitForTimeout(800) }

  // ---- A. Quick video: reference-image zone present ----
  await page.getByRole('button', { name: /Quick video/i }).first().click()
  await page.waitForTimeout(1200)
  const refZone = page.getByRole('button', { name: /reference image/i }).first()
  log('Quick video offers a reference-image (image-to-video) drop zone', await refZone.isVisible().catch(() => false))
  await snap('01-quick-reference')
  await page.getByRole('button', { name: /back to home/i }).first().click()
  await page.waitForTimeout(800)

  // ---- B. Filmmaker Studio → new film → offline plan (setup) ----
  await page.getByRole('button', { name: /Filmmaker Studio/i }).first().click()
  await page.waitForTimeout(800)
  const nameInput = page.locator('input').first()
  if (await nameInput.isVisible().catch(() => false)) { await nameInput.fill(`RC Film ${RUN}`); await page.keyboard.press('Enter') }
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: 'Build Film with AI' }).first().click()
  const dialog = page.getByRole('dialog', { name: /Build Film with AI/ })
  await dialog.waitFor({ state: 'visible' })
  await dialog.locator('textarea').first().fill('Two friends argue on a rooftop at dusk. One walks away. The other follows.')
  await page.getByRole('button', { name: 'Plan offline' }).click()
  await page.getByText(/scenes ·.*shots ·.*characters/).waitFor({ state: 'visible' })
  const includeBoxes = dialog.getByRole('checkbox', { name: /Include scene/ })
  const sceneCount = await includeBoxes.count()
  log('Build plan has per-scene include checkboxes', sceneCount >= 2, `${sceneCount} scenes`)
  await includeBoxes.last().uncheck()
  const applyLabel = await page.getByRole('button', { name: /Apply selected|Apply all/ }).textContent()
  log('Apply button reflects the selection', /Apply selected \(/.test(applyLabel || ''), applyLabel || '')
  log('Regenerate plan button present', await dialog.getByRole('button', { name: /Regenerate plan/ }).isVisible())
  await page.getByRole('button', { name: /Apply selected/ }).click()
  await page.waitForTimeout(2500)
  const projects = await page.evaluate(() => JSON.parse(localStorage.getItem('ltx-projects') || '[]'))
  const project = projects.find(p => p.name === `RC Film ${RUN}`)
  let film = (await api(`/api/film/projects/${encodeURIComponent(project.id)}`)).json.project
  log('Only the selected scenes were applied', film.scenes.length === sceneCount - 1, `${film.scenes.length} of ${sceneCount}`)
  await snap('02-storyboard')

  // ---- C. Storyboard: undo/redo + scene gap field + card labels ----
  const undo = page.getByRole('button', { name: 'Undo' })
  const redo = page.getByRole('button', { name: 'Redo' })
  log('Undo/redo controls present', (await undo.isVisible()) && (await redo.isVisible()))
  const gapField = page.getByLabel(/Inter-shot gap for/).first()
  log('Scene header exposes an inter-shot gap override', await gapField.isVisible())
  await gapField.fill('1.5')
  await gapField.press('Enter')
  await page.waitForTimeout(1500)
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  log('Scene gap override persisted', film.scenes[0].inter_shot_gap_seconds === 1.5, String(film.scenes[0].inter_shot_gap_seconds))
  const firstShotBefore = [...film.scenes[0].shots].sort((a, b) => a.order - b.order)[0]
  // Delete the first card through the UI (confirm dialog auto-accepted), then undo via the toolbar.
  const firstCard = page.locator('[role="button"][aria-label^="Shot "]').first()
  await firstCard.hover()
  await firstCard.getByRole('button', { name: 'Delete shot' }).click()
  await page.waitForTimeout(3000)
  const cardsAfterDelete = await page.locator('[role="button"][aria-label^="Shot "]').count()
  await undo.click()
  await page.waitForTimeout(2500)
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  const restored = film.scenes[0].shots.some(s => s.id === firstShotBefore.id)
  log('Undo restores a deleted shot', restored, `${cardsAfterDelete} cards after delete → ${film.scenes[0].shots.length} shots after undo`)
  await page.waitForTimeout(2500) // let a poll cycle pass: redo must survive it
  log('Redo stays available after undo', !(await redo.isDisabled()))
  await redo.click()
  await page.waitForTimeout(3500)
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  log('Redo re-applies the deletion', !film.scenes[0].shots.some(s => s.id === firstShotBefore.id))
  await undo.click()
  await page.waitForTimeout(3500)
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  log('Second undo brings the shot back again', film.scenes[0].shots.some(s => s.id === firstShotBefore.id))
  const cardText = await page.locator('[role="button"][aria-label^="Shot "]').first().textContent()
  log('Shot card shows the model label', /fast|pro|ltx|project model|distilled/i.test(cardText || ''), (cardText || '').slice(0, 80))
  await snap('03-undo-redo')

  // ---- D. AI Director tool changes actual state: set_ots over the right shoulder ----
  const scene = film.scenes[0]
  // The storyboard sorts by `order`; the JSON array order can differ after a restore.
  const shot = [...scene.shots].sort((a, b) => a.order - b.order)[0]
  const mara = (await api(`/api/film/projects/${project.id}/assets`, { method: 'POST', body: JSON.stringify({ kind: 'character', name: `Mara ${RUN}` }) })).json.asset
  const theo = (await api(`/api/film/projects/${project.id}/assets`, { method: 'POST', body: JSON.stringify({ kind: 'character', name: `Theo ${RUN}` }) })).json.asset
  const ots = await api(`/api/film/projects/${project.id}/director/command`, {
    method: 'POST',
    body: JSON.stringify({ name: 'set_ots', params: { shot_id: shot.id, foreground: `Mara ${RUN}`, subject: `Theo ${RUN}`, shoulder: 'right' } }),
  })
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  const otsShot = film.scenes[0].shots.find(s => s.id === shot.id)
  log(
    'Director set_ots changed framing, shoulder and cast (not just the prompt)',
    ots.json?.results?.[0]?.ok === true && otsShot.framing.camera_angle === 'ots' && otsShot.framing.ots_shoulder === 'right' && otsShot.characters.length === 2 && otsShot.composition?.objects?.length === 2,
    `angle=${otsShot.framing.camera_angle} shoulder=${otsShot.framing.ots_shoulder} cast=${otsShot.characters.length} objects=${otsShot.composition?.objects?.length}`,
  )
  const moved = await api(`/api/film/projects/${project.id}/director/command`, {
    method: 'POST',
    body: JSON.stringify({ name: 'position_object', params: { shot_id: shot.id, target: `Theo ${RUN}`, hint: 'background right' } }),
  })
  log('Director position_object moved the figure in the composition', moved.json?.results?.[0]?.ok === true && moved.json.results[0].result.position[0] === 1.1)
  void mara
  // The commands above went straight to the API (the in-app Director bar refreshes by itself);
  // leave and re-enter the storyboard so the UI reloads the project.
  await page.getByRole('button', { name: 'Gen Space' }).first().click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(3000)

  // ---- E. Shot Composer: gizmo, camera row, lock, keyframes, generate panel, manual camera ----
  await page.locator('[role="button"][aria-label^="Shot "]').first().click()
  await page.getByRole('button', { name: 'Compose Shot' }).click()
  const composer = page.getByRole('dialog', { name: 'Shot Composer' })
  await composer.waitFor({ state: 'visible' })
  await page.waitForTimeout(2500)
  log('Composer opens with the gizmo mode group', await composer.getByRole('group', { name: 'Gizmo mode' }).isVisible())
  log('Composer scene tree lists the Shot Camera and both cast figures', (await composer.getByText('Shot Camera').first().isVisible()) && (await composer.getByText(`Mara ${RUN}`).first().isVisible()) && (await composer.getByText(`Theo ${RUN}`).first().isVisible()))
  await composer.getByText(`Mara ${RUN}`).first().click()
  await page.waitForTimeout(500)
  log('Selecting a figure shows numeric transform + body type controls', (await composer.getByLabel('Body type').isVisible()) && (await composer.getByLabel('X').first().isVisible()))
  await composer.getByRole('button', { name: `Lock Mara ${RUN}` }).click()
  log('Lock toggles and disables the transform inputs', await composer.getByLabel('X').first().isDisabled())
  await composer.getByRole('button', { name: `Unlock Mara ${RUN}` }).click()
  log('OTS shoulder toggle reflects the director change (right)', await composer.getByRole('button', { name: 'right shoulder' }).getAttribute('aria-pressed') === 'true')
  await composer.locator('aside').first().getByText('Shot Camera', { exact: true }).click()
  await page.waitForTimeout(400)
  log('Selecting the camera row shows the camera overlay', await composer.getByLabel('Aim camera at').isVisible())
  const camX = composer.getByLabel('X').first()
  await camX.fill('0.5')
  await camX.press('Tab')
  await page.waitForTimeout(400)
  log('Numeric camera edit switches to manual mode', await composer.getByText(/manual/).first().isVisible())
  await composer.getByRole('button', { name: 'Motion' }).click()
  await composer.getByRole('button', { name: 'Key camera' }).click()
  await composer.getByRole('button', { name: 'Key camera' }).click().catch(() => {})
  log('Camera keyframe recorded in the timeline editor', await composer.getByLabel('Camera keyframe time').first().isVisible())
  log('Generate panel is available inside the composer', (await composer.getByRole('button', { name: 'Preview' }).isVisible()) && (await composer.getByRole('button', { name: 'Final' }).isVisible()))
  await snap('04-composer')
  await composer.getByRole('button', { name: 'Save' }).click()
  await page.waitForTimeout(2000)
  film = (await api(`/api/film/projects/${project.id}`)).json.project
  const saved = film.scenes[0].shots.find(s => s.id === shot.id)
  log(
    'Saved composition carries manual camera mode, right shoulder and a camera keyframe',
    saved.framing.camera_mode === 'manual' && saved.framing.ots_shoulder === 'right' && (saved.composition?.camera?.keyframes?.length ?? 0) >= 1 && saved.composition.objects.length === 2,
    `mode=${saved.framing.camera_mode} keys=${saved.composition?.camera?.keyframes?.length}`,
  )
  await composer.getByRole('button', { name: 'Close composer' }).click()
  await page.waitForTimeout(1500)

  // ---- F. Drawer: AI visual check button explains what it needs ----
  const visualBtn = page.getByRole('button', { name: /AI visual check/ })
  log('Drawer offers the AI visual check (disabled without provider/render)', (await visualBtn.isVisible()) && (await visualBtn.isDisabled()))
  const gapBefore = page.getByLabel('Gap before (s)')
  log('Drawer exposes the per-shot gap override', await gapBefore.isVisible())
  await snap('05-drawer')
  await page.getByRole('button', { name: 'Close shot details' }).click()

  // ---- G. Settings → AI Models: states + model location ----
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'aiModels' } })))
  await page.waitForTimeout(2500)
  const chips = await page.locator('span').filter({ hasText: /^(Active|Installed|Available|Downloading|Update available|Incompatible|Cloud)$/ }).count()
  log('AI Models shows product state chips', chips >= 1, `${chips} chips`)
  log('AI Models offers "Open model location"', await page.getByRole('button', { name: 'Open model location' }).isVisible())
  const caps = (await api('/api/film/capabilities')).json
  log('Capabilities carry models_path, RAM and per-model state/family', typeof caps.models_path === 'string' && 'system_ram_gb' in caps && caps.models.every(m => 'state' in m && 'family' in m))
  await snap('06-models')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)

  // ---- H. Settings: OpenAI-compatible endpoint + provider option ----
  await page.getByRole('tab', { name: 'Storyboard' }).click()
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'aiModels' } })))
  await page.waitForTimeout(1000)
  const baseUrl = page.getByLabel('OpenAI-compatible base URL')
  log('Settings show the Local / OpenAI-compatible endpoint section', await baseUrl.isVisible())
  log('Provider picker includes the local endpoint option', await page.getByRole('button', { name: /Local \/ OpenAI-compatible/ }).isVisible())
  await baseUrl.fill('http://127.0.0.1:1/v1')
  await page.getByLabel('OpenAI-compatible model id').fill('local-test-model')
  await page.getByLabel('OpenAI-compatible model id').press('Tab')
  await page.waitForTimeout(1500)
  const settings = (await api('/api/settings')).json
  log('Endpoint settings synced to the backend (no secret involved)', settings.openaiCompatibleBaseUrl === 'http://127.0.0.1:1/v1' && settings.openaiCompatibleModel === 'local-test-model')
  await page.getByRole('button', { name: /Local \/ OpenAI-compatible/ }).click()
  await page.waitForTimeout(1200)
  const status = (await api('/api/film/director/status')).json
  log('Director status activates the local endpoint provider', status.active_provider === 'openai_compatible' && status.openai_compatible_configured === true, status.active_provider)
  const chat = await api('/api/film/director/chat', { method: 'POST', body: JSON.stringify({ messages: [{ role: 'user', content: 'ready?' }] }) })
  log('Unreachable local endpoint fails with a typed, key-free error (not a crash)', chat.status === 502 && /unreachable/i.test(chat.text), `${chat.status} ${chat.text.slice(0, 60)}`)
  await snap('07-openai-compatible')
  // Reset provider + endpoint so later runs start clean.
  await page.getByRole('button', { name: /^Auto\b/ }).click()
  await baseUrl.fill('')
  await page.getByLabel('OpenAI-compatible model id').fill('')
  await page.getByLabel('OpenAI-compatible model id').press('Tab')
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: 'Done' }).click()

  // ---- I. Whole-project replace (undo transport) refuses while queued, secrets never in project JSON ----
  const snapshot = (await api(`/api/film/projects/${project.id}`)).json.project
  const replaced = await api(`/api/film/projects/${project.id}`, { method: 'PUT', body: JSON.stringify({ project: snapshot }) })
  log('Replace-project endpoint accepts a validated snapshot', replaced.status === 200)
  const projectText = (await api(`/api/film/projects/${project.id}`)).text
  log('Project JSON contains no key-shaped strings', !/sk-or-v1-|AIza|api_key/i.test(projectText))

  // ---- J. Gen Space / editor conversion path through the shared helper (API) ----
  const clipDir = path.join(process.env.LTX_APP_DATA_DIR || '/root/.local/share/LTXDesktop', 'outputs')
  fs.mkdirSync(clipDir, { recursive: true })
  const clip = path.join(clipDir, `verify-rc-${RUN}.mp4`)
  fs.writeFileSync(clip, Buffer.from('fake-video'))
  const imported = await api(`/api/film/projects/${project.id}/import-generation`, {
    method: 'POST',
    body: JSON.stringify({ prompt: 'A rooftop at dusk', output_path: clip, model: 'fast', resolution: '540p', duration_seconds: 4, seed: 5, mode: 'text-to-video', title: 'From Gen Space' }),
  })
  log('A generated clip becomes a new shot with the file referenced (no re-encode)', imported.status === 200 && imported.json.project.scenes.at(-1).shots[0].versions[0].output_path === clip)
  const bad = await api(`/api/film/projects/${project.id}/import-generation`, { method: 'POST', body: JSON.stringify({ prompt: 'x', output_path: '/etc/passwd' }) })
  log('Path policy rejects a non-video absolute path', bad.status === 400)
} catch (err) {
  log('unexpected failure', false, String(err && err.stack ? err.stack.split('\n').slice(0, 3).join(' | ') : err))
  await snap('99-error').catch(() => {})
}

const passed = results.filter(r => r.ok).length
console.log(`\n${passed}/${results.length} passed`)
fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2))
await browser.close()
process.exit(passed === results.length ? 0 : 1)
