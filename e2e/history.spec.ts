import { expect, test } from '@playwright/test'
import { attachConsoleGuard, expectMediaIntact, settle } from './helpers/media'

/**
 * History: every job kind renders with a valid thumbnail, an in-progress job
 * updates live, and the drawer exposes outputs, lineage and actions.
 */
const KINDS = ['image_gen', 'video_gen', 'image_reproduce', 'video_reproduce', 'analysis', 'scene_build', 'training', 'download']

test.describe('History', () => {
  test.beforeEach(async ({ request, baseURL }) => {
    await request.post(`${baseURL}/api/__ui_mock/reset`)
  })

  test('renders three jobs of every kind with intact media', async ({ page }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/')
    await page.getByRole('button', { name: /^History$/ }).first().click()
    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
    await expect(page.getByTestId('job-card').first()).toBeVisible()
    await settle(page, 1200)
    const total = await page.getByTestId('job-card').count()
    expect(total).toBeGreaterThanOrEqual(KINDS.length * 3)
    // Download jobs have no preview by design; every other kind must show one.
    await expectMediaIntact(page, guard, { minImages: (KINDS.length - 1) * 3 - 1 })

    for (const kind of KINDS) {
      await page.getByLabel('Filter by kind').selectOption(kind)
      await settle(page, 500)
      const count = await page.getByTestId('job-card').count()
      expect(count, `${kind} cards`).toBeGreaterThanOrEqual(3)
      await expectMediaIntact(page, guard)
    }
    await page.getByLabel('Filter by kind').selectOption('')
  })

  test('an in-progress job updates live and can be cancelled', async ({ page }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/')
    await page.getByRole('button', { name: /^History$/ }).first().click()
    await page.getByRole('tab', { name: 'In progress' }).click()
    const running = page.locator('[data-testid="job-card"][data-status="running"]').first()
    await expect(running).toBeVisible()
    const bar = running.getByRole('progressbar')
    await expect(bar).toBeVisible()
    const first = Number(await bar.getAttribute('aria-valuenow'))
    await expect.poll(async () => Number(await bar.getAttribute('aria-valuenow')), { timeout: 10_000 }).toBeGreaterThan(first)
    await expect(page.getByText(/polling|live/)).toBeVisible()

    const jobId = await running.getAttribute('data-job-id')
    await running.getByRole('button', { name: /^Cancel / }).click()
    // A cancelled job leaves the "In progress" bucket; find it under "All".
    await page.getByRole('tab', { name: 'All' }).click()
    await expect.poll(async () => page.locator(`[data-testid="job-card"][data-job-id="${jobId}"][data-status="cancelled"]`).count(), { timeout: 8_000 }).toBe(1)
    await expectMediaIntact(page, guard)
  })

  test('the drawer shows outputs, lineage and the lightbox', async ({ page }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/')
    await page.getByRole('button', { name: /^History$/ }).first().click()
    await page.getByLabel('Filter by kind').selectOption('image_reproduce')
    await page.getByTestId('job-card').first().click()
    const drawer = page.getByTestId('job-drawer')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByText('Outputs', { exact: false })).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Copy prompt' })).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Open in Reproduce' })).toBeVisible()
    await settle(page, 800)
    await expectMediaIntact(page, guard, { minImages: 1 })

    // Lineage: the reproduce parent lists its candidate child; opening it links back.
    await expect(drawer.getByRole('list', { name: 'Lineage chain' })).toBeVisible()
    await drawer.getByRole('button', { name: /candidate 1 of 6/ }).click()
    await expect(drawer.getByText('(this job)')).toBeVisible()
    await settle(page, 500)

    await drawer.getByRole('button', { name: 'Open output 1' }).click()
    const lightbox = page.getByTestId('lightbox')
    await expect(lightbox).toBeVisible()
    await settle(page, 500)
    await expectMediaIntact(page, guard)
    await page.keyboard.press('Escape')
    await expect(lightbox).toHaveCount(0)
  })

  test('search and re-run', async ({ page, request, baseURL }) => {
    const guard = attachConsoleGuard(page)
    await page.goto('/')
    await page.getByRole('button', { name: /^History$/ }).first().click()
    await page.getByLabel('Search prompts').fill('antenna')
    await settle(page, 700)
    const cards = page.getByTestId('job-card')
    expect(await cards.count()).toBeGreaterThan(0)
    const expected = ((await (await request.get(`${baseURL}/api/jobs?q=antenna`)).json()) as { jobs: { id: string }[] }).jobs.map(j => j.id).sort()
    const shown = (await cards.evaluateAll(nodes => nodes.map(n => n.getAttribute('data-job-id')))).sort()
    expect(shown).toEqual(expected)

    await page.getByLabel('Search prompts').fill('')
    await page.getByLabel('Filter by kind').selectOption('video_gen')
    await page.locator('[data-testid="job-card"][data-status="complete"]').first().click()
    const drawer = page.getByTestId('job-drawer')
    await drawer.getByRole('button', { name: /Re-run/ }).click()
    await page.getByLabel('Filter by kind').selectOption('')
    await page.getByRole('tab', { name: 'In progress' }).click()
    await expect.poll(async () => page.locator('[data-testid="job-card"][data-status="running"]').count(), { timeout: 8_000 }).toBeGreaterThan(0)
    await expectMediaIntact(page, guard)
  })
})
