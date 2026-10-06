import { expect, test, type Page } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/**
 * Train tab against the UI mock: the seeded dataset and finished run render
 * with intact media; a new dataset imports from a folder, auto-captions with
 * the trigger word, trains (live progress, loss curve, samples), lands in the
 * registry and in History; the pickers and the Consistency Kit read it back.
 */

async function openTrain(page: Page) {
  const guard = attachConsoleGuard(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('What do you want to make?')).toBeVisible()
  // Until the runtime policy answers, the app assumes API-only mode and may flash the key modal.
  await expect(page.getByRole('heading', { name: 'Connect API Keys' })).toHaveCount(0)
  await page.getByRole('button', { name: /^Train$/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Train', exact: true })).toBeVisible()
  await expect(page.getByTestId('trainer-status')).toContainText('musubi-tuner')
  return guard
}

test.describe('Train', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('seeded dataset, run and registry render with intact media', async ({ page }) => {
    const guard = await openTrain(page)
    await expect(page.getByTestId('dataset-item')).toHaveCount(1)
    await page.getByTestId('dataset-item').first().click()
    await expect(page.getByTestId('dataset-grid')).toBeVisible()
    await expect(page.getByTestId('dataset-item-card')).toHaveCount(8)
    await settle(page, 1200)
    await expectMediaIntact(page, guard, { minImages: 8 })
    await expect(page.getByLabel('Trigger word')).toHaveValue('mara_v1')
    // The 12 GB guard is visible before anything starts: a video target is refused.
    await page.getByLabel('Training target').selectOption('wan22')
    await expect(page.getByTestId('train-blocker')).toContainText('does not fit')
    await expect(page.getByTestId('start-training')).toBeDisabled()

    await page.getByTestId('run-item').first().click()
    await expect(page.getByTestId('run-status')).toContainText('complete')
    await expect(page.getByTestId('loss-sparkline')).toBeVisible()
    await expect(page.getByTestId('sample-grid').locator('img')).toHaveCount(6)
    await settle(page, 1200)
    await expectMediaIntact(page, guard, { minImages: 6 })

    await page.getByRole('button', { name: /LoRA registry/ }).click()
    await expect(page.getByTestId('lora-row')).toHaveCount(1)
    await expect(page.getByTestId('lora-row').first()).toContainText('z_image')

    // Download a LoRA from a pasted Civitai link; it lands in the registry.
    await page.getByTestId('lora-url-input').fill('https://civitai.com/models/12345?modelVersionId=67890')
    await page.getByLabel('Trigger for the downloaded LoRA').fill('neon_v1')
    await page.getByTestId('lora-url-download').click()
    await expect(page.getByTestId('lora-url-status')).toContainText('Added to the registry', { timeout: 15_000 })
    await expect(page.getByTestId('lora-row')).toHaveCount(2)
    await expect(page.getByLabel('Name of civitai-12345')).toHaveValue('civitai-12345')
    expect(guard.errors).toEqual([])
  })

  test('build a dataset, caption it, train, cancel, resume and finish', async ({ page }) => {
    const guard = await openTrain(page)
    await page.getByRole('button', { name: 'New dataset' }).click()
    await expect(page.getByTestId('dataset-builder')).toBeVisible()
    await page.getByLabel('Trigger word').fill('lamp_v1')
    await page.getByLabel('Trigger word').press('Tab')
    await expect(page.getByTestId('dataset-item').first()).toContainText('lamp_v1')
    await page.getByLabel('Dataset preset').selectOption('object')
    await expect(page.getByTestId('dataset-item').first()).toContainText('Object')
    await page.getByRole('button', { name: 'Add folder' }).click()
    await expect(page.getByTestId('dataset-item-card')).toHaveCount(6)
    await page.getByRole('button', { name: 'From History' }).click()
    await expect(page.getByTestId('history-picker')).toBeVisible()
    await page.getByTestId('history-picker').getByRole('button').filter({ hasText: /./ }).nth(1).click()
    await expect(page.getByTestId('dataset-item-card')).toHaveCount(8)
    await page.getByRole('button', { name: 'Auto-caption' }).click()
    await expect(page.getByTestId('dataset-item-card').first().locator('textarea')).toHaveValue(/lamp_v1/)
    await settle(page, 1000)
    await expectMediaIntact(page, guard, { minImages: 8 })

    // Object preset lowers the rank; the estimate fits the card.
    await expect(page.getByLabel('Rank')).toHaveValue('12')
    await expect(page.getByTestId('train-panel')).toContainText('of 12 GB')
    await page.getByLabel('Run name').fill('Lamp LoRA')
    await page.getByTestId('start-training').click()
    await expect(page.getByTestId('run-detail')).toBeVisible()
    await expect(page.getByTestId('run-status')).toContainText('running')
    await expect(page.getByTestId('run-step')).not.toContainText('step 0/')
    // Wait for the first checkpoint so the cancelled run has something to resume from.
    await expect(page.getByText(/checkpoint.* kept for resume/)).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('run-status')).toContainText('cancelled')
    await page.getByRole('button', { name: /Resume from step/ }).click()
    await expect(page.getByTestId('run-status')).toContainText(/running|complete/)
    await expect(page.getByTestId('run-status')).toContainText('complete', { timeout: 30_000 })
    await expect(page.getByTestId('loss-sparkline').locator('svg')).toBeVisible()
    await expect(page.getByTestId('sample-grid').locator('img').first()).toBeVisible()
    await expect(page.getByText('LoRA saved to the registry')).toBeVisible()
    await settle(page, 800)
    await expectMediaIntact(page, guard)

    await page.getByRole('button', { name: /LoRA registry/ }).click()
    await expect(page.getByTestId('lora-row')).toHaveCount(2)
    await expect(page.getByLabel('Name of Lamp LoRA (resumed)')).toHaveValue('Lamp LoRA (resumed)')

    // History shows the training job with its loss curve.
    await page.getByRole('button', { name: /back to home/i }).first().click()
    await page.getByRole('button', { name: /^History$/ }).first().click()
    await page.getByLabel('Filter by kind').selectOption('training')
    await page.getByTestId('job-card').first().click()
    await expect(page.getByTestId('loss-sparkline')).toBeVisible()
    expect(guard.errors).toEqual([])
  })

  test('LoRA pickers offer compatible LoRAs in Reproduce and Quick video', async ({ page }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Reproduce image/i }).first().click()
    await page.getByRole('button', { name: 'Import reference image' }).click()
    await expect(page.getByTestId('reproduce-item')).toHaveCount(1)
    await expect(page.getByTestId('lora-picker')).toContainText('Mara v1')
    await page.getByLabel('Use LoRA Mara v1').check()
    await expect(page.getByLabel('Strength for Mara v1')).toHaveValue('0.9')
    await page.getByRole('button', { name: /back to home/i }).first().click()
    await page.getByRole('button', { name: /Quick video/i }).first().click()
    // No LTX-2 LoRA exists yet: the picker says so instead of offering the Z-Image one.
    await expect(page.getByTestId('lora-picker')).toContainText('No LoRAs for this model yet')
    expect(guard.errors).toEqual([])
  })

  test('Consistency Kit binds a LoRA, locks a seed and renders a reference sheet', async ({ page }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByText('The Relay (demo)').first().click()
    await page.getByRole('button', { name: 'Storyboard' }).first().click()
    await page.getByRole('tab', { name: 'Assets', exact: true }).click()
    await page.getByText('Mara', { exact: true }).first().click()
    const kit = page.getByTestId('consistency-kit')
    await expect(kit).toBeVisible()
    await kit.getByLabel('Bound LoRA').selectOption({ label: 'Mara v1 · z_image' })
    await expect(kit.getByLabel('LoRA trigger word')).toHaveValue('mara_v1')
    await expect(kit).toContainText('inherit the LoRA and put “mara_v1” in the prompt')
    await kit.getByLabel('Seed lock').fill('777')
    await kit.getByLabel('Seed lock').press('Enter')
    await expect(kit).toContainText('render with seed 777')
    const before = await page.getByRole('button', { name: /Open reference image/i }).count()
    await page.getByTestId('reference-sheet').click()
    await expect(page.getByText(/Reference sheet: 4 views at seed 777/)).toBeVisible()
    await expect(page.getByRole('button', { name: /Open reference image/i })).toHaveCount(before + 4)
    await settle(page, 1200)
    await expectMediaIntact(page, guard, { minImages: before + 4 })
    expect(guard.errors).toEqual([])
  })
})
