import { expect, test } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/**
 * Video Reproduce v2 against the UI mock: an analysed video (set up through
 * the API, because the browser file-dialog shim cannot pick a real clip) →
 * Recreate → the strip fills shot by shot with playable candidates and
 * scores → pick / redo / stitch. Zero console errors throughout.
 */

async function analysedVideo(request: import('@playwright/test').APIRequestContext, baseURL: string): Promise<string> {
  await request.post(`${baseURL}/api/__ui_mock/reset`)
  const imported = await request.post(`${baseURL}/api/video-analysis/import`, { data: { path: 'C:\\Users\\demo\\Videos\\reference.mp4', title: 'Reference clip', depth: 'standard' } })
  expect(imported.ok()).toBeTruthy()
  const { id } = (await imported.json()) as { id: string }
  expect((await request.post(`${baseURL}/api/video-analysis/${id}/detect`)).ok()).toBeTruthy()
  expect((await request.post(`${baseURL}/api/video-analysis/${id}/analyze`, { data: {} })).ok()).toBeTruthy()
  return id
}

test.describe('Video reproduce', () => {
  test('renders shots live, plays every candidate, pick, redo and stitch', async ({ page, request, baseURL }) => {
    await analysedVideo(request, baseURL!)
    const guard = attachConsoleGuard(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Analyse video/i }).first().click()
    await page.getByRole('button', { name: /Reference clip/ }).first().click()
    await expect(page.getByText('Measured motion')).toBeVisible()

    await page.getByLabel('Candidates per shot').fill('1')
    await page.getByRole('button', { name: 'Recreate video' }).click()
    const panel = page.getByTestId('video-reproduce')
    await expect(panel).toBeVisible()
    await expect(page.getByTestId('video-reproduce-status')).toContainText('running')
    const shots = page.getByTestId('video-reproduce-shot')
    const shotCount = await shots.count()
    expect(shotCount).toBeGreaterThanOrEqual(2)
    // Candidates land one by one; the strip updates without a reload.
    await expect(page.getByTestId('video-reproduce-status')).toContainText('complete', { timeout: 30_000 })
    await expect(page.getByTestId('video-reproduce-candidate')).toHaveCount(shotCount)
    await expect(page.getByTestId('video-reproduce-stitched')).toBeVisible()
    await settle(page, 1500)
    // One reference frame + one candidate clip per shot, plus the stitched result.
    await expectMediaIntact(page, guard, { minImages: shotCount * 2, minVideos: shotCount + 1 })

    // Redo the first shot: a second candidate arrives and can be picked.
    await page.getByRole('button', { name: 'Redo shot 1' }).click()
    await expect(page.getByTestId('video-reproduce-status')).toContainText('complete', { timeout: 20_000 })
    const first = shots.first()
    await expect(first.getByTestId('video-reproduce-candidate')).toHaveCount(2)
    const pickButtons = first.getByRole('button', { name: /^Pick / })
    await expect(pickButtons).toHaveCount(2)
    const pressed = await pickButtons.first().getAttribute('aria-pressed')
    const other = pressed === 'true' ? pickButtons.nth(1) : pickButtons.first()
    await other.click()
    await expect(other).toHaveAttribute('aria-pressed', 'true')

    const before = await page.getByTestId('video-reproduce-stitched').locator('video').getAttribute('src')
    await page.getByRole('button', { name: 'Stitch picks' }).click()
    await expect.poll(async () => page.getByTestId('video-reproduce-stitched').locator('video').getAttribute('src')).not.toBe(before)
    await settle(page, 1200)
    await expectMediaIntact(page, guard, { minVideos: shotCount + 1 })
  })

  test('cancel stops the render and the panel closes cleanly', async ({ page, request, baseURL }) => {
    await analysedVideo(request, baseURL!)
    const guard = attachConsoleGuard(page)
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Analyse video/i }).first().click()
    await page.getByRole('button', { name: /Reference clip/ }).first().click()
    await page.getByLabel('Candidates per shot').fill('3')
    await page.getByRole('button', { name: 'Recreate video' }).click()
    await expect(page.getByTestId('video-reproduce-status')).toContainText('running')
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByTestId('video-reproduce-status')).toContainText('cancelled')
    await page.getByRole('button', { name: 'Close video reproduce' }).click()
    await expect(page.getByTestId('video-reproduce')).toHaveCount(0)
    await settle(page)
    await expectMediaIntact(page, guard)
  })
})
