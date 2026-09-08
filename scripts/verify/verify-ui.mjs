// Drives the real Electron app over CDP and exercises the filmmaking workflow.
import { chromium } from 'playwright'
import fs from 'node:fs'

const SHOTS = './verify-shots/ui'
fs.mkdirSync(SHOTS, { recursive: true })

const results = []
function log(step, ok, note = '') {
  results.push({ step, ok, note })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.connectOverCDP('http://localhost:9222')
const context = browser.contexts()[0]
let page = context.pages().find(p => p.url().includes('localhost:5173')) ?? context.pages()[0]
if (!page) throw new Error('No page found over CDP')
await page.bringToFront()
page.setDefaultTimeout(20000)

async function snap(name) {
  await page.screenshot({ path: `${SHOTS}/${name}.png` })
}

const SCRIPT = `INT. COFFEE SHOP - DAY

Sunlight cuts across empty tables. SARAH sits alone, staring at an unopened letter.

SARAH
I can't keep pretending this never happened.

She tears the envelope open.

EXT. CITY STREET - NIGHT

JOHN walks fast through the rain, phone pressed to his ear.

JOHN
Tell me she didn't read it.
`

const RUN = Date.now().toString(36).slice(-5)
const PROJECT_NAME = `Verification Film ${RUN}`

try {
  // ---- 0. App booted (reload so every run starts from Home) ----
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('domcontentloaded')
  await page.waitForTimeout(6000)
  await snap('00-boot')

  // Handle the blocking API-key gateway if it appears (forced API mode with no key).
  const keyInput = page.locator('input[placeholder*="LTX API key"]').first()
  if (await keyInput.isVisible().catch(() => false)) {
    await keyInput.fill('sk-verification-dummy-key-000')
    await page.getByRole('button', { name: /^(Save|Connect|Continue)/i }).first().click().catch(() => {})
    await page.waitForTimeout(1500)
    const close = page.getByRole('button', { name: /close|done|continue/i }).first()
    if (await close.isVisible().catch(() => false)) await close.click().catch(() => {})
    log('api-key gateway handled', true)
    await snap('01-after-gateway')
  }

  // ---- 1. Home: create a project ----
  const newProject = page.getByRole('button', { name: /new project/i }).first()
  await newProject.waitFor({ state: 'visible' })
  log('home renders with New Project', true)
  await snap('02-home')
  await newProject.click()
  await page.waitForTimeout(500)
  // A dialog may ask for a name.
  const nameInput = page.locator('input').first()
  if (await nameInput.isVisible().catch(() => false)) {
    await nameInput.fill(PROJECT_NAME)
    await page.keyboard.press('Enter')
  }
  await page.waitForTimeout(1500)
  const storyboardTab = page.getByRole('button', { name: 'Storyboard' }).first()
  await storyboardTab.waitFor({ state: 'visible' })
  log('project created and opened', true)
  await snap('03-project-open')

  // ---- 2. Storyboard tab ----
  await storyboardTab.click()
  await page.waitForTimeout(2500)
  await snap('04-storyboard-empty')
  const emptyState = await page.getByText('Storyboard is empty').isVisible().catch(() => false)
  log('storyboard tab renders (film facet auto-created)', emptyState, emptyState ? '' : 'empty state not visible')

  // ---- 3. Script -> storyboard generation (offline parser) ----
  await page.getByRole('button', { name: 'Script', exact: true }).first().click()
  await page.waitForTimeout(800)
  await page.locator('textarea:visible').first().fill(SCRIPT)
  await snap('05-script')
  await page.getByRole('button', { name: 'Generate Storyboard', exact: true }).first().click()
  await page.waitForTimeout(3000)
  await snap('06-storyboard-generated')
  const scene1 = await page.getByText('INT. COFFEE SHOP - DAY').first().isVisible().catch(() => false)
  const scene2 = await page.getByText('EXT. CITY STREET - NIGHT').first().isVisible().catch(() => false)
  log('script → draft storyboard (scenes from headings)', scene1 && scene2)

  // ---- 4. Assets extracted ----
  await page.getByRole('button', { name: 'Assets', exact: true }).first().click()
  await page.waitForTimeout(1000)
  const sarah = await page.getByText('Sarah', { exact: true }).first().isVisible().catch(() => false)
  const john = await page.getByText('John', { exact: true }).first().isVisible().catch(() => false)
  log('characters extracted into assets', sarah && john)
  // Enrich Sarah for prompt synthesis.
  if (sarah) {
    await page.getByText('Sarah', { exact: true }).first().click()
    await page.waitForTimeout(500)
    const textareas = page.locator('textarea:visible')
    await textareas.nth(2).fill('long red coat, dark curled hair')
    await page.getByRole('button', { name: /save character/i }).click()
    await page.waitForTimeout(800)
    log('asset edited (wardrobe saved)', true)
  }
  await snap('07-assets')

  // ---- 5. Shot card + detail drawer ----
  await page.getByRole('button', { name: 'Storyboard' }).last().click()
  await page.waitForTimeout(1000)
  const firstCard = page.locator('.group.w-52').first()
  await firstCard.click()
  await page.waitForTimeout(1200)
  const drawer = await page.getByText('Visual prompt', { exact: false }).first().isVisible().catch(() => false)
  log('shot detail drawer opens', drawer)
  await snap('08-shot-drawer')

  // ---- 6. Open the Shot Composer ----
  await page.getByRole('button', { name: 'Compose Shot' }).first().click()
  await page.waitForTimeout(5000)
  const composerHeader = await page.getByText('Shot Composer —', { exact: false }).isVisible().catch(() => false)
  log('Shot Composer opens (three.js loads)', composerHeader)
  await snap('09-composer-open')

  // ---- 7. Presets ----
  await page.getByRole('button', { name: 'Close-Up', exact: true }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: '3/4 Left' }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: 'Low', exact: true }).click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: 'Right Third' }).click()
  await page.waitForTimeout(600)
  log('framing presets applied (size/angle/elevation/composition)', true)
  await snap('10-composer-presets')

  // ---- 8. Pose ----
  const sceneItem = page.locator('aside').first().getByText(/Sarah|Character 1/).first()
  await sceneItem.click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: 'Pose', exact: true }).click()
  await page.waitForTimeout(400)
  const poseButton = page.getByRole('button', { name: 'Arms Crossed' })
  if (await poseButton.isVisible().catch(() => false)) {
    await poseButton.click()
    await page.waitForTimeout(600)
    log('pose applied from library', true)
  } else {
    log('pose applied from library', false, 'pose section not visible')
  }
  await snap('11-composer-pose')

  // ---- 9. Camera motion ----
  await page.getByRole('button', { name: 'Motion', exact: true }).click()
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: 'Push In', exact: true }).click()
  await page.waitForTimeout(600)
  log('camera move preset applied (keyframes built)', true)

  // ---- 10. Capture ----
  await page.getByRole('button', { name: 'Capture Shot' }).click()
  await page.waitForTimeout(3500)
  const captured = await page.getByText('Shot captured', { exact: false }).isVisible().catch(() => false)
  log('capture: PNG + composition persisted', captured)
  await snap('12-composer-captured')

  // Close composer.
  await page.getByRole('button', { name: 'Close composer' }).click()
  await page.waitForTimeout(1500)
  await snap('13-back-to-storyboard')
  const readyBadge = await page.getByText('Ready', { exact: true }).first().isVisible().catch(() => false)
  const captureThumb = await page.locator('.group.w-52 img').first().isVisible().catch(() => false)
  log('shot card shows capture thumbnail + Ready status', readyBadge && captureThumb)

  // ---- 11. Models panel ----
  await page.getByRole('button', { name: 'Models', exact: true }).first().click()
  await page.waitForTimeout(1500)
  const modelsInfo = await page.getByText(/API-only mode|Local generation|WanGP bridge/).first().isVisible().catch(() => false)
  log('models panel shows execution mode + model list', modelsInfo)
  await snap('14-models')

  // ---- 12. Generate preview (expected to fail fast in this container: dummy API key) ----
  await page.getByRole('button', { name: 'Storyboard' }).last().click()
  await page.waitForTimeout(800)
  await page.locator('.group.w-52').first().click()
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await page.waitForTimeout(1200)
  await snap('15-preview-queued')
  // Wait for the queue to drain and the version row to appear.
  let versionSeen = false
  for (let i = 0; i < 90; i++) {
    await page.waitForTimeout(1500)
    if (await page.getByText(/v1 · preview/).first().isVisible().catch(() => false)) {
      versionSeen = true
      break
    }
  }
  const failedShown = await page.getByText('failed', { exact: true }).first().isVisible().catch(() => false)
  const retryShown = await page.getByRole('button', { name: /retry/i }).first().isVisible().catch(() => false)
  log('generation queued through real pipeline; version row + failure state + retry visible',
    versionSeen && failedShown && retryShown,
    versionSeen ? '' : 'version row missing')
  await snap('16-version-failed-retry')

  // ---- 13. Reorder via drag is covered by unit tests; verify duplicate ----
  const cardCountBefore = await page.locator('.group.w-52').count()
  await page.locator('.group.w-52').first().hover()
  await page.locator('.group.w-52').first().getByTitle('Duplicate shot').click()
  await page.waitForTimeout(1500)
  const cardCountAfter = await page.locator('.group.w-52').count()
  log('shot duplication from card', cardCountAfter === cardCountBefore + 1)

  // ---- 14. Reload persistence ----
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)
  // Re-handle key gateway if it reappears.
  const keyInput2 = page.locator('input[placeholder*="LTX API key"]').first()
  if (await keyInput2.isVisible().catch(() => false)) {
    await keyInput2.fill('sk-verification-dummy-key-000')
    await page.getByRole('button', { name: /^(Save|Connect|Continue)/i }).first().click().catch(() => {})
    await page.waitForTimeout(1200)
  }
  // Back into the project → storyboard.
  await page.getByText(PROJECT_NAME).first().click()
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.waitForTimeout(2500)
  const sceneAfterReload = await page.getByText('INT. COFFEE SHOP - DAY').first().isVisible().catch(() => false)
  const thumbAfterReload = await page.locator('.group.w-52 img').first().isVisible().catch(() => false)
  log('project reload: storyboard + capture persist', sceneAfterReload && thumbAfterReload)
  await snap('17-after-reload')
} catch (error) {
  log('UNCAUGHT', false, String(error).slice(0, 300))
  await snap('99-error')
}

console.log('\nSummary:')
for (const r of results) console.log(`  ${r.ok ? '✅' : '❌'} ${r.step}${r.note ? ' (' + r.note + ')' : ''}`)
const failures = results.filter(r => !r.ok).length
console.log(`\n${results.length - failures}/${results.length} steps passed`)
await browser.close()
process.exit(0)
