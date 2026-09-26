import { expect, test } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/** Settings → Vision renders its status and saves a change. */
test.describe('Settings', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('Vision tab shows the stack status and persists toggles', async ({ page, request, baseURL }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/')
    // Global controls live outside Home; open a project first.
    await page.getByText('The Relay (demo)').first().click()
    await page.getByTitle('Settings').click()
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
})
