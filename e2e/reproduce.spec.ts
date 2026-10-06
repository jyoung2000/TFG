import { expect, test, type Page } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/**
 * Image Reproduce v2 against the UI mock: import → analyse → editable spec
 * blocks with evidence → loop with live rounds → every candidate loads →
 * pin / pick / fix canvas → lightbox. Zero console errors throughout.
 */

async function openReproduce(page: Page) {
  const guard = attachConsoleGuard(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /Reproduce image/i }).first().click()
  await expect(page.getByRole('heading', { name: 'Reproduce image' })).toBeVisible()
  return guard
}

async function importAndAnalyse(page: Page) {
  await page.getByRole('button', { name: 'Import reference image' }).click()
  await expect(page.getByTestId('reproduce-item')).toHaveCount(1)
  await expect(page.getByTestId('reproduce-status')).toContainText('idle')
  await page.getByRole('button', { name: 'Analyse' }).click()
  await expect(page.getByTestId('spec-blocks')).toBeVisible()
  await page.getByText('Why · evidence per block').click()
  await expect(page.getByTestId('why-panel')).toBeVisible()
}

test.describe('Reproduce image', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('empty state renders with no console errors', async ({ page }) => {
    const guard = await openReproduce(page)
    await expect(page.getByText('Import a reference to begin.')).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
  })

  test('import, analyse, edit and lock a spec block, prompt follows', async ({ page }) => {
    const guard = await openReproduce(page)
    await importAndAnalyse(page)
    const prompt = page.getByTestId('reproduce-prompt')
    await expect(prompt).not.toHaveValue('')
    const before = await prompt.inputValue()

    // Lock the lighting block: the lock is persisted through the API and reflected in the UI.
    const lighting = page.getByTestId('spec-block-lighting')
    await lighting.getByRole('button', { name: /^Lock/ }).click()
    await expect(lighting.getByRole('button', { name: /^Unlock/ })).toBeVisible()

    // Switch prompt style: the compiled prompt changes and the server result wins.
    await page.getByLabel('Prompt style').selectOption('narrative')
    await expect(prompt).not.toHaveValue(before)
    await settle(page)
    await expectMediaIntact(page, guard, { minImages: 1 })
  })

  test('the loop runs rounds live and every candidate loads', async ({ page }) => {
    const guard = await openReproduce(page)
    await importAndAnalyse(page)
    await page.getByLabel('Max rounds').fill('2')
    await page.getByLabel('Candidates per round').fill('2')
    await page.getByRole('button', { name: 'Start loop' }).click()
    await expect(page.getByTestId('reproduce-status')).toContainText('rendering')
    await expect(page.getByTestId('round-history').getByRole('listitem')).toHaveCount(1, { timeout: 15_000 })
    await expect(page.getByTestId('reproduce-status')).toContainText('complete', { timeout: 20_000 })
    await expect(page.getByTestId('round-history').getByRole('listitem')).toHaveCount(2)
    await expect(page.getByTestId('candidate-card')).toHaveCount(4)
    await settle(page, 1200)
    // Reference + 4 candidates + the best-vs-reference compare.
    await expectMediaIntact(page, guard, { minImages: 5 })

    // Pin the first candidate as reference, pick the last one.
    await page.getByRole('button', { name: 'Pin r1-c1 as reference' }).click()
    await expect(page.getByRole('button', { name: 'Pin r1-c1 as reference' })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: 'Pick r2-c2' }).click()
    await expect(page.getByTestId('candidate-card').nth(3)).toHaveClass(/ring-amber/)

    // Lightbox on a candidate.
    await page.getByRole('img', { name: 'Candidate r2-c1' }).click()
    const lightbox = page.getByTestId('lightbox')
    await expect(lightbox).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(lightbox).toBeHidden()
    await expectMediaIntact(page, guard)
  })

  test('fix canvas commits adjustments as a new candidate', async ({ page }) => {
    const guard = await openReproduce(page)
    await importAndAnalyse(page)
    await page.getByLabel('Max rounds').fill('1')
    await page.getByLabel('Candidates per round').fill('1')
    await page.getByRole('button', { name: 'Start loop' }).click()
    await expect(page.getByTestId('reproduce-status')).toContainText('complete', { timeout: 20_000 })
    await page.getByRole('button', { name: 'Fix r1-c1' }).click()
    const canvas = page.getByTestId('fix-canvas')
    await expect(canvas).toBeVisible()
    await settle(page, 800)
    await canvas.getByLabel('Exposure').fill('0.3')
    await canvas.getByRole('button', { name: 'Save adjustments as candidate' }).click()
    await expect(canvas).toBeHidden()
    await expect(page.getByTestId('candidate-card')).toHaveCount(2)
    await expect(page.getByTestId('candidate-grid')).toContainText('fix')
    await settle(page, 800)
    await expectMediaIntact(page, guard, { minImages: 3 })
  })

  test('cancel stops a running loop', async ({ page }) => {
    const guard = await openReproduce(page)
    await importAndAnalyse(page)
    await page.getByLabel('Max rounds').fill('4')
    await page.getByRole('button', { name: 'Start loop' }).click()
    await expect(page.getByTestId('reproduce-status')).toContainText('rendering')
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('reproduce-status')).toContainText('cancelled')
    await settle(page)
    await expectMediaIntact(page, guard)
  })
})
