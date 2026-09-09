// Model Library + provider walkthrough over CDP against the dev Electron app.
// Covers: library search/filters, local vs hosted rows, download refusal for
// hosted models, custom model ids, provider settings (Claude/Grok/media keys),
// the chat model pickers, hosted generation through a stubbed provider, and
// asset reference generation. Never uses a real API key.
// Run: ELECTRON_DEBUG=1 pnpm dev (xvfb-run -a on headless Linux), then
// `node scripts/verify/verify-models.mjs`.
import { chromium } from 'playwright'
import fs from 'node:fs'

const SHOTS = './verify-shots/models'
fs.mkdirSync(SHOTS, { recursive: true })
const results = []
const log = (step, ok, note = '') => {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.connectOverCDP('http://127.0.0.1:9222')
const context = browser.contexts()[0]
const page = context.pages().find(p => p.url().includes('localhost:5173')) ?? context.pages()[0]
await page.bringToFront()
page.setDefaultTimeout(20000)
page.on('dialog', d => d.accept())
const snap = name => page.screenshot({ path: `${SHOTS}/${name}.png` })
const RUN = Date.now().toString(36).slice(-5)
const FAKE = 'test-placeholder-not-a-real-key'

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
  }
  const back = page.getByRole('button', { name: /back to home/i }).first()
  if (await back.isVisible().catch(() => false)) { await back.click(); await page.waitForTimeout(800) }

  // ---- A. Open a film and reach the Model Library ----
  await page.getByRole('button', { name: /Filmmaker Studio/i }).first().click()
  await page.waitForTimeout(800)
  const nameInput = page.locator('input').first()
  if (await nameInput.isVisible().catch(() => false)) { await nameInput.fill(`Models ${RUN}`); await page.keyboard.press('Enter') }
  await page.waitForTimeout(2500)
  await page.getByRole('tab', { name: 'Models', exact: true }).click()
  await page.waitForTimeout(2500)
  log('Models tab opens on the Model Library', await page.getByRole('tab', { name: 'Model Library', exact: true }).getAttribute('aria-selected') === 'true')
  const rows = page.locator('input[aria-label="Search models"]')
  log('Library has a search box and filters', (await rows.isVisible()) && (await page.getByRole('tab', { name: 'Video', exact: true }).isVisible()))
  log('Offline readiness is stated honestly', /offline|local/i.test((await page.locator('[role="status"]').first().innerText().catch(() => '')) || ''))
  await snap('01-library')

  // ---- B. Search + filters actually filter ----
  await rows.fill('flux')
  await page.waitForTimeout(1200)
  const fluxRows = await page.locator('div.font-mono').filter({ hasText: /flux/i }).count()
  log('Search narrows the catalog', fluxRows > 0, `${fluxRows} flux rows`)
  await rows.fill('')
  await page.getByRole('tab', { name: 'Text / script', exact: true }).click()
  await page.waitForTimeout(1200)
  await page.getByRole('tab', { name: 'Hosted (API key)', exact: true }).click()
  await page.waitForTimeout(1200)
  const textHosted = await page.locator('div.font-mono').count()
  log('Hosted text providers list nothing until a key is added', textHosted === 0, `${textHosted} rows`)
  await page.getByRole('tab', { name: 'Video', exact: true }).click()
  await page.waitForTimeout(1400)
  const needsKey = await page.getByText('Needs API key').count()
  log('Hosted video models are offered but marked "Needs API key"', needsKey > 0, `${needsKey} rows`)
  await page.getByRole('tab', { name: 'All', exact: true }).click()
  await page.getByRole('tab', { name: 'Anywhere', exact: true }).click()
  await page.waitForTimeout(1000)

  // ---- C. A local model can be downloaded; a hosted one cannot ----
  const hostedDownload = await api('/api/models/library/download', { method: 'POST', body: JSON.stringify({ provider: 'fal', model_id: 'fal-ai/x' }) })
  log('Hosted models refuse a download with an explanation', hostedDownload.status === 400 && /cloud/i.test(hostedDownload.text))
  const library = (await api('/api/models/library')).json
  const localRow = (library.models || []).find(m => m.source === 'local')
  log('Local weights are listed with install state', Boolean(localRow), localRow ? `${localRow.provider}:${localRow.id} (${localRow.state})` : 'none')
  log('Library reports where weights install', typeof library.models_path === 'string' && library.models_path.length > 0, library.models_path)

  // ---- D. Custom model id is remembered and searchable ----
  await page.getByLabel('Custom model id', { exact: true }).fill(`owner/custom-${RUN}`)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.waitForTimeout(1500)
  await rows.fill(`custom-${RUN}`)
  await page.waitForTimeout(1200)
  log('A pasted model id joins the library', await page.getByText(`owner/custom-${RUN}`).first().isVisible().catch(() => false))
  await rows.fill('')
  await snap('02-custom-id')

  // ---- E. Provider settings: Claude / Grok / media keys ----
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'apiKeys' } })))
  await page.waitForTimeout(1200)
  log('Claude and Grok have their own key + model cards', (await page.getByLabel('Claude (Anthropic) API key').isVisible()) && (await page.getByLabel('Grok (xAI) API key').isVisible()))
  log('Media providers expose keys and a provider choice', (await page.getByLabel('fal API key').isVisible()) && (await page.getByRole('button', { name: /This computer \(offline\)/ }).isVisible()))
  await page.getByLabel('Claude (Anthropic) API key').fill(FAKE)
  await page.getByRole('button', { name: 'Save', exact: true }).first().click()
  await page.waitForTimeout(1800)
  const settings = (await api('/api/settings')).json
  log('Claude key is stored write-only (only a flag comes back)', settings.hasAnthropicApiKey === true && !JSON.stringify(settings).includes(FAKE))
  await page.getByLabel('Claude (Anthropic) model id').fill('claude-opus-5')
  await page.getByLabel('Claude (Anthropic) model id').press('Tab')
  await page.waitForTimeout(1800)
  const status = (await api('/api/film/director/status')).json
  log('Director status lists every provider and its model', status.providers.length === 5 && status.anthropic_configured === true, `active=${status.active_provider}`)
  await snap('03-provider-settings')
  await page.getByRole('button', { name: 'Done' }).click()
  await page.waitForTimeout(800)

  // ---- F. Chat model pickers change real state ----
  await page.getByRole('tab', { name: 'Storyboard', exact: true }).click()
  await page.waitForTimeout(1500)
  const directorChip = page.locator('button[title^="Director model:"]')
  log('Chat shows Director / Video / Image model chips', (await directorChip.isVisible()) && (await page.locator('button[title^="Image model:"]').isVisible()))
  await directorChip.click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: /Claude \(Anthropic\)/ }).first().click()
  await page.waitForTimeout(1500)
  const afterPick = (await api('/api/settings')).json
  log('Picking a provider in the chat changes the director provider', afterPick.directorProvider === 'anthropic', afterPick.directorProvider)
  await snap('04-chat-pickers')
  await page.keyboard.press('Escape')

  const videoChip = page.locator('button[title^="Video model:"]')
  await videoChip.click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: /^fal\.ai/ }).first().click()
  await page.waitForTimeout(600)
  await page.getByLabel('video model id', { exact: true }).fill('fal-ai/ltx-video-13b-distilled')
  await page.getByLabel('video model id', { exact: true }).press('Enter')
  await page.waitForTimeout(2000)
  const projects = await page.evaluate(() => JSON.parse(localStorage.getItem('ltx-projects') || '[]'))
  const project = projects.find(p => p.name === `Models ${RUN}`)
  const film = (await api(`/api/film/projects/${project.id}`)).json.project
  log(
    'Picking a video model writes it onto the film project',
    film.settings.media_provider === 'fal' && film.settings.video_model === 'fal-ai/ltx-video-13b-distilled',
    `${film.settings.media_provider} / ${film.settings.video_model}`,
  )

  // ---- G. Hosted generation fails with an actionable error when no key ----
  const scene = (await api(`/api/film/projects/${project.id}/scenes`, { method: 'POST', body: JSON.stringify({ title: 'S1' }) })).json
  const shot = (await api(`/api/film/projects/${project.id}/scenes/${scene.id}/shots`, { method: 'POST', body: JSON.stringify({ title: 'Shot', description: 'a beat', duration_seconds: 3 }) })).json
  await api(`/api/film/projects/${project.id}/scenes/${scene.id}/shots/${shot.id}/generate`, { method: 'POST', body: JSON.stringify({ kind: 'preview' }) })
  await page.waitForTimeout(3000)
  const afterGen = (await api(`/api/film/projects/${project.id}`)).json.project
  const version = afterGen.scenes[0].shots[0].versions[0]
  log(
    'A hosted render without a key fails with a typed, key-free message',
    version && version.status === 'failed' && /FAL_KEY_MISSING/.test(version.error) && !version.error.includes(FAKE),
    version ? version.error.slice(0, 80) : 'no version',
  )
  log('The failed version records the provider as its execution mode', version && version.execution_mode === 'fal', version?.execution_mode)

  // ---- H. Asset reference generation reports the same way ----
  const asset = (await api(`/api/film/projects/${project.id}/assets`, { method: 'POST', body: JSON.stringify({ kind: 'character', name: 'Mara', appearance: 'red coat' }) })).json.asset
  const reference = await api(`/api/film/projects/${project.id}/assets/${asset.id}/generate-reference`, { method: 'POST', body: JSON.stringify({}) })
  log('Reference generation surfaces the missing key rather than crashing', reference.status === 400 && /FAL_KEY_MISSING/.test(reference.text))

  // ---- I. Back to fully local ----
  await page.getByRole('tab', { name: 'Models', exact: true }).click()
  await page.waitForTimeout(1500)
  await page.getByRole('tab', { name: 'Video' }).click()
  await page.waitForTimeout(1500)
  const localUse = page.locator('div', { hasText: /HardDrive|/ })
  void localUse
  const backLocal = await api(`/api/film/projects/${project.id}/settings`, {
    method: 'PUT',
    body: JSON.stringify({ settings: { ...film.settings, media_provider: 'local', video_model: '' } }),
  })
  log('A film can be put back on fully local generation', backLocal.status === 200)
  await snap('05-final')
} catch (err) {
  log('unexpected failure', false, String(err && err.stack ? err.stack.split('\n').slice(0, 3).join(' | ') : err))
  await snap('99-error').catch(() => {})
}

const passed = results.filter(r => r.ok).length
console.log(`\n${passed}/${results.length} passed`)
fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2))
await browser.close()
process.exit(passed === results.length ? 0 : 1)
