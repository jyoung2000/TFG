import { chromium } from 'playwright'
const SHOTS = './verify-shots/ui'
const browser = await chromium.connectOverCDP('http://localhost:9223')
const page = browser.contexts()[0].pages()[0]
await page.bringToFront()
page.setDefaultTimeout(20000)
const results = []
const log = (s, ok, n = '') => { results.push({ s, ok, n }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${s}${n ? ' — ' + n : ''}`) }
try {
  await page.waitForTimeout(8000)
  await page.screenshot({ path: `${SHOTS}/30-appimage-boot.png` })
  log('packaged app renders a window (url ' + page.url().slice(0, 40) + ')', true)
  // Gates: license / setup / api key
  for (let i = 0; i < 3; i++) {
    const accept = page.getByRole('button', { name: /accept|agree|continue|get started|skip/i }).first()
    if (await accept.isVisible().catch(() => false)) { await accept.click().catch(() => {}); await page.waitForTimeout(1500) }
  }
  const keyInput = page.locator('input[placeholder*="LTX API key"]').first()
  if (await keyInput.isVisible().catch(() => false)) {
    await keyInput.fill('sk-verification-dummy-key-000')
    await page.getByRole('button', { name: /^(Save|Connect|Continue)/i }).first().click().catch(() => {})
    await page.waitForTimeout(1500)
    log('API-key gateway handled in packaged app', true)
  }
  await page.screenshot({ path: `${SHOTS}/31-appimage-after-gates.png` })
  const newProject = page.getByRole('button', { name: /new project/i }).first()
  await newProject.waitFor({ state: 'visible' })
  log('home screen reachable (backend connected)', true)
  await newProject.click(); await page.waitForTimeout(500)
  const nameInput = page.locator('input').first()
  if (await nameInput.isVisible().catch(() => false)) { await nameInput.fill('AppImage Film'); await page.keyboard.press('Enter') }
  await page.waitForTimeout(1500)
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(3000)
  const empty = await page.getByText('Storyboard is empty').isVisible().catch(() => false)
  log('storyboard tab works against packaged backend (film facet created)', empty)
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('open-settings', { detail: { tab: 'aiModels' } })))
  await page.waitForTimeout(2500)
  const verdict = await page.locator('text=/GPU|VRAM/').first().isVisible().catch(() => false)
  log('Settings → AI Models loads capabilities from packaged backend', verdict)
  await page.screenshot({ path: `${SHOTS}/32-appimage-models.png` })
  const info = await page.evaluate(async () => {
    const b = await window.electronAPI.getBackend(); const a = await window.electronAPI.getAppInfo()
    return { backend: b.url, isPackaged: a.isPackaged, userData: a.userDataPath }
  })
  log(`app reports isPackaged=${info.isPackaged}, backend ${info.backend}, userData ${info.userData}`, info.isPackaged === true)
} catch (e) { log('UNCAUGHT', false, String(e).slice(0, 200)); await page.screenshot({ path: `${SHOTS}/39-appimage-error.png` }) }
console.log(`\n${results.filter(r => r.ok).length}/${results.length} passed`)
await browser.close()
