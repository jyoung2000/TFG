import { expect, test, type Page } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle, type ConsoleGuard } from './helpers/media'

/**
 * Every existing view renders with intact media and zero console errors,
 * against the UI-only mock backend. New views get a test here as they land.
 */

async function openHome(page: Page): Promise<ConsoleGuard> {
  const guard = attachConsoleGuard(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('What do you want to make?')).toBeVisible()
  await settle(page)
  return guard
}

async function backHome(page: Page) {
  await page.getByRole('button', { name: /back to home/i }).first().click()
  await expect(page.getByText('What do you want to make?')).toBeVisible()
}

test.describe('views', () => {
  // Start every test from the seeded demo state, whatever a previous dev session left behind.
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('Home renders the hero and project list', async ({ page }) => {
    const guard = await openHome(page)
    await expect(page.getByText('The Relay (demo)').first()).toBeVisible()
    await expectMediaIntact(page, guard, { minVideos: 1 })
  })

  test('Quick video', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByRole('button', { name: /Quick video/i }).first().click()
    await expect(page.getByRole('button', { name: 'Generate' }).first()).toBeVisible()
    await expect(page.locator('textarea').first()).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
    await backHome(page)
  })

  test('Analyse video', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByRole('button', { name: /Analyse video/i }).first().click()
    await expect(page.getByRole('heading', { name: 'Analyse video' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Import a video/i })).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
    await backHome(page)
  })

  test('Reproduce image', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByRole('button', { name: /Reproduce image/i }).first().click()
    await expect(page.getByRole('heading', { name: 'Reproduce image' })).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
    await backHome(page)
  })

  test('Playground', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByRole('button', { name: /^Playground$/i }).first().click()
    await expect(page.getByRole('button', { name: /Generate video/i })).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
  })

  test('Project: Gen Space, Storyboard tabs, Video Editor', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByText('The Relay (demo)').first().click()
    await expect(page.getByRole('button', { name: 'Gen Space' })).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)

    await page.getByRole('button', { name: 'Storyboard' }).first().click()
    await expect(page.locator('[aria-label^="Shot "]').first()).toBeVisible()
    await settle(page, 1500)
    const storyboard = await expectMediaIntact(page, guard, { minImages: 1 })
    expect(storyboard.images.length).toBeGreaterThan(0)

    for (const tab of ['Timeline', 'Script', 'Assets'] as const) {
      await page.getByRole('tab', { name: tab, exact: true }).click()
      await settle(page)
      await expectMediaIntact(page, guard)
    }

    await page.getByRole('button', { name: 'Video Editor' }).first().click()
    await settle(page)
    await expectMediaIntact(page, guard)
  })

  test('Film Studio Assets: reference thumbnails load and open in the lightbox', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByText('The Relay (demo)').first().click()
    await page.getByRole('button', { name: 'Storyboard' }).first().click()
    await page.getByRole('tab', { name: 'Assets', exact: true }).click()
    await settle(page)
    // Card thumbnails come from the seeded reference images.
    await expectMediaIntact(page, guard, { minImages: 1 })
    await page.getByText('Mara', { exact: true }).first().click()
    await settle(page)
    const open = page.getByRole('button', { name: /Open reference image/i }).first()
    await expect(open).toBeVisible()
    await expectMediaIntact(page, guard, { minImages: 2 })
    await open.click()
    const lightbox = page.getByTestId('lightbox')
    await expect(lightbox).toBeVisible()
    await settle(page)
    await expectMediaIntact(page, guard)
    await page.keyboard.press('ArrowRight')
    await expect(lightbox).toContainText('2 / 2')
    await page.keyboard.press('Escape')
    await expect(lightbox).toHaveCount(0)
    expect(guard.errors).toEqual([])
  })

  test('Shot Composer opens from a shot', async ({ page }) => {
    const guard = await openHome(page)
    await page.getByText('The Relay (demo)').first().click()
    await page.getByRole('button', { name: 'Storyboard' }).first().click()
    await page.locator('[aria-label^="Shot "]').first().click()
    await expect(page.getByRole('button', { name: 'Close shot details' })).toBeVisible()
    await page.getByRole('button', { name: /Compose Shot/i }).first().click()
    const composer = page.getByRole('dialog', { name: 'Shot Composer' })
    await expect(composer).toBeVisible()
    await expect(composer.locator('canvas')).toBeVisible()
    await settle(page, 1500)
    await expectMediaIntact(page, guard)
    await page.getByRole('button', { name: 'Close composer' }).click()
    await expect(composer).toHaveCount(0)
  })
})
