import { expect, test } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/**
 * Phase 6 against the UI mock: an analysed video → Build 3D storyboard →
 * shot cards carry blockout thumbnails → the composer opens pre-seeded with
 * figures, the reference underlay and camera words → Deliver writes passes.
 */

async function analysedVideo(request: import('@playwright/test').APIRequestContext, baseURL: string): Promise<string> {
  await request.post(`${baseURL}/api/__ui_mock/reset`)
  const imported = await request.post(`${baseURL}/api/video-analysis/import`, { data: { path: 'C:\\Users\\demo\\Videos\\reference.mp4', title: 'Reference clip', depth: 'standard' } })
  const { id } = (await imported.json()) as { id: string }
  expect((await request.post(`${baseURL}/api/video-analysis/${id}/detect`)).ok()).toBeTruthy()
  expect((await request.post(`${baseURL}/api/video-analysis/${id}/analyze`, { data: {} })).ok()).toBeTruthy()
  return id
}

test.describe('3D storyboard', () => {
  test('builds cards with blockouts and opens the composer with underlay and figures', async ({ page, request, baseURL }) => {
    await analysedVideo(request, baseURL!)
    const guard = attachConsoleGuard(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Analyse video/i }).first().click()
    await page.getByRole('button', { name: /Reference clip/ }).first().click()
    await page.getByRole('button', { name: 'Build 3D storyboard' }).click()

    // The storyboard opens with one card per shot, each carrying a blockout thumbnail.
    await expect(page.locator('[aria-label^="Shot "]').first()).toBeVisible()
    const blockouts = page.getByTestId('shot-thumb-blockout')
    await expect(blockouts.first()).toBeVisible()
    const cards = await page.locator('[aria-label^="Shot "]').count()
    await expect(blockouts).toHaveCount(cards)
    await settle(page, 1200)
    await expectMediaIntact(page, guard, { minImages: cards })

    // Open the first shot in the composer: pre-seeded figures, underlay on, camera words derived.
    await page.locator('[aria-label^="Shot "]').first().click()
    await page.getByRole('button', { name: /Compose Shot/i }).first().click()
    const composer = page.getByRole('dialog', { name: 'Shot Composer' })
    await expect(composer).toBeVisible()
    await expect(composer.locator('canvas')).toBeVisible()
    await expect(composer.getByTestId('composer-underlay')).toBeChecked()
    await expect(composer.getByText('from video')).toBeVisible()
    await expect(composer.getByText(/Person/).first()).toBeVisible()
    await expect(composer.getByText(/Chair/).first()).toBeVisible()
    await expect(composer.getByTestId('composer-camera-words')).toContainText(/shot/, { timeout: 10_000 })

    // The move library is wired; picking a classic move produces camera keyframes.
    await composer.getByRole('button', { name: /^Motion/ }).click()
    await composer.getByLabel('Move library').selectOption('slow-push-in')
    await expect(composer.getByText(/Camera/).first()).toBeVisible()

    // Deliver: passes render in the browser and land as control signals.
    await composer.getByRole('button', { name: /^Deliver/ }).click()
    await composer.getByLabel('Deliver size').selectOption('640')
    await composer.getByRole('button', { name: 'Deliver passes' }).click()
    await expect(composer.getByTestId('composer-deliver-result')).toContainText('reference.mp4', { timeout: 60_000 })
    await expect(composer.getByTestId('composer-deliver-result')).toContainText('depth.mp4')

    // Apply the 3D layout back to the shot spec.
    await composer.getByRole('button', { name: 'Apply 3D layout to the shot spec' }).click()
    await expect(composer.getByText('3D layout written to the shot spec', { exact: false })).toBeVisible()

    await settle(page, 800)
    await expectMediaIntact(page, guard)
    await page.getByRole('button', { name: 'Close composer' }).click()
    await expect(composer).toHaveCount(0)
  })
})
