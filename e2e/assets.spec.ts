import { expect, test, type Page } from '@playwright/test'
import { attachConsoleGuard, settle, type ConsoleGuard } from './helpers/media'

/**
 * The Assets tab redesign: library grid with consistency badges, the asset
 * detail with the checklist Consistency Kit, and the "New asset" wizard
 * that turns one seed image into a full kit against the ui-mock.
 */

// A 1×1 red PNG, enough for the wizard's seed-image upload.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

async function openAssets(page: Page): Promise<ConsoleGuard> {
  const guard = attachConsoleGuard(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.getByText('The Relay (demo)').first().click()
  await page.getByRole('button', { name: 'Storyboard' }).first().click()
  await page.getByRole('tab', { name: 'Assets', exact: true }).click()
  await settle(page)
  return guard
}

test.describe('assets', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('library grid shows consistency state and filters', async ({ page }) => {
    const guard = await openAssets(page)
    await expect(page.getByTestId('asset-grid')).toBeVisible()
    await expect(page.getByTestId('asset-card').first()).toBeVisible()
    // Every card carries the four consistency pips.
    await expect(page.getByTestId('asset-card').first().getByText('REF', { exact: true })).toBeVisible()
    // The rail filters the grid; an empty filter shows the ghost card, not a bare panel.
    const cards = await page.getByTestId('asset-card').count()
    await page.getByRole('button', { name: /Production-locked/ }).click()
    await expect(page.getByTestId('asset-card')).toHaveCount(0)
    await expect(page.getByTestId('new-asset-ghost')).toBeVisible()
    await expect(page.getByText('Nothing matches this filter.')).toBeVisible()
    await page.getByRole('button', { name: /Production-locked/ }).click()
    await expect(page.getByTestId('asset-card')).toHaveCount(cards)
    expect(guard.errors).toEqual([])
  })

  test('wizard: one seed image → AI kit → edit a trait → create lands in detail', async ({ page }) => {
    const guard = await openAssets(page)
    await page.getByTestId('new-asset-ghost').click()
    await expect(page.getByTestId('new-asset-wizard')).toBeVisible()

    await page.getByLabel('New asset name').fill('Wizard Mara')
    await page.getByTestId('wizard-seed-file').setInputFiles({ name: 'seed.png', mimeType: 'image/png', buffer: PNG })
    await expect(page.getByText('Source ✓')).toBeVisible()
    // The engine indicator reflects the app's real model state (mock = local).
    await expect(page.getByText('Local · GPU')).toBeVisible()

    await page.getByTestId('wizard-build').click()
    // All three pipeline steps complete against the delayed mock endpoints.
    for (const n of [1, 2, 3]) {
      await expect(page.getByTestId(`pipeline-step-${n}`).locator('span').first()).toHaveClass(/emerald/, { timeout: 15_000 })
    }
    // The turnaround tiles render with their view labels.
    await expect(page.getByTestId('kit-tile-front').locator('img')).toBeVisible()
    await expect(page.getByTestId('kit-tile-back').locator('img')).toBeVisible()

    // The AI draft is editable before create.
    await page.getByLabel('Add trait').fill('green field jacket')
    await page.getByLabel('Add trait').press('Enter')
    await expect(page.getByText('green field jacket')).toBeVisible()

    await page.getByTestId('wizard-create').click()
    await expect(page.getByTestId('asset-detail')).toBeVisible()
    await expect(page.getByLabel('Asset name')).toHaveValue('Wizard Mara')
    // Pips reflect the built kit: REF/GUIDE/SEED on, LORA still open.
    const kit = page.getByTestId('consistency-kit')
    await expect(kit).toContainText('3 / 4')
    // The edited trait persisted through Create.
    await expect(page.getByTestId('style-guide-card')).toContainText('green field jacket')
    expect(guard.errors).toEqual([])
  })

  test('wizard cancel offers to keep or delete the partial asset', async ({ page }) => {
    const guard = await openAssets(page)
    const cards = await page.getByTestId('asset-card').count()
    await page.getByTestId('new-asset-ghost').click()
    await page.getByTestId('wizard-seed-file').setInputFiles({ name: 'seed.png', mimeType: 'image/png', buffer: PNG })
    await page.getByTestId('wizard-build').click()
    await expect(page.getByTestId('pipeline-step-3').locator('span').first()).toHaveClass(/emerald/, { timeout: 15_000 })
    page.once('dialog', dialog => void dialog.accept()) // OK = delete it
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(page.getByTestId('asset-grid')).toBeVisible()
    await expect(page.getByTestId('asset-card')).toHaveCount(cards)
    expect(guard.errors).toEqual([])
  })
})
