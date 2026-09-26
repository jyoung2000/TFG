import { expect, test } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'
import type { Page } from '@playwright/test'

/** Open Settings from a project (global controls live outside Home); waits out the cold-start key modal. */
async function openSettings(page: Page) {
  await page.goto('/')
  await expect(page.getByText('What do you want to make?')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Connect API Keys' })).toHaveCount(0)
  await page.getByText('The Relay (demo)').first().click()
  await page.getByTitle('Settings').click()
}

/** Settings → Vision renders its status and saves a change. */
test.describe('Settings', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('Vision tab shows the stack status and persists toggles', async ({ page, request, baseURL }) => {
    const guard = attachConsoleGuard(page)
    await openSettings(page)
    await page.getByRole('tab', { name: 'Vision' }).click()
    const panel = page.getByTestId('vision-settings')
    await expect(panel).toBeVisible()
    await expect(panel.getByText('Florence-2 — captions, detection, grounding')).toBeVisible()
    await expect(panel.getByText(/VRAM free/)).toBeVisible()
    await settle(page)

    await panel.getByLabel('Florence-2', { exact: true }).uncheck()
    await expect.poll(async () => ((await (await request.get(`${baseURL}/api/settings`)).json()) as { vision: { florenceEnabled: boolean } }).vision.florenceEnabled).toBe(false)
    await panel.getByLabel('VLM provider').selectOption('ollama')
    await expect(panel.getByLabel('VLM model')).toBeVisible()
    await panel.getByRole('button', { name: 'Unload models' }).click()
    await expect(panel.getByRole('status')).toContainText('Unloaded')
    await expectMediaIntact(page, guard)
  })

  test('General tab offers the RTX 4070 preset and applies it', async ({ page, request, baseURL }) => {
    const guard = attachConsoleGuard(page)
    await openSettings(page)
    const card = page.getByTestId('hardware-preset')
    await expect(card).toBeVisible()
    await expect(card).toContainText('NVIDIA GeForce RTX 4070')
    await expect(card).toContainText('Recommended for this GPU')
    await card.getByRole('button', { name: 'Apply RTX 4070 · 12 GB' }).click()
    await expect(card).toContainText('Applied')
    await expect.poll(async () => ((await (await request.get(`${baseURL}/api/settings`)).json()) as { hardwarePreset: string; vision: { vlmProvider: string } }).hardwarePreset).toBe('rtx-4070-12gb')
    const settings = (await (await request.get(`${baseURL}/api/settings`)).json()) as { defaultVideoModel: string; vision: { vlmProvider: string; vlmKeepAlive: string } }
    expect(settings.defaultVideoModel).toBe('ltx2_22B_distilled')
    expect(settings.vision.vlmProvider).toBe('off')
    expect(settings.vision.vlmKeepAlive).toBe('0')
    expect(guard.errors).toEqual([])
  })

  test('Remote backend card probes a URL and the tiers editor explains skipped tiers', async ({ page, request, baseURL }) => {
    const guard = attachConsoleGuard(page)
    await openSettings(page)
    const remote = page.getByTestId('remote-backend')
    await expect(remote).toBeVisible()
    await remote.getByLabel('Remote backend URL').fill(baseURL ?? 'http://127.0.0.1:5173')
    await remote.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByTestId('remote-probe')).toContainText('Reachable')

    await page.getByRole('tab', { name: 'AI Models' }).click()
    const tiers = page.getByTestId('media-tiers')
    await expect(tiers).toBeVisible()
    const row = page.getByTestId('tier-row-t2v')
    await expect(row).toContainText('This computer (offline)')
    await row.getByLabel('Add a tier to Text → video').selectOption('fal')
    await expect(row).toContainText('fal.ai')
    await expect(row).toContainText('FAL_KEY_MISSING')
    await expect.poll(async () => ((await (await request.get(`${baseURL}/api/settings`)).json()) as { mediaTiers: Record<string, string[]> }).mediaTiers.t2v).toEqual(['local', 'fal'])
    await row.getByRole('button', { name: 'Remove fal from Text → video' }).click()
    await expect(row.getByRole('button', { name: 'Remove fal from Text → video' })).toHaveCount(0)
    expect(guard.errors).toEqual([])
  })
})
