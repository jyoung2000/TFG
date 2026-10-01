import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PreviewScheduler } from './previewScheduler'

/* Asked 2026-10-01: a live preview of the image as the 3D model is edited.
 * A drag sends an edit every frame and a render takes seconds. */

describe('PreviewScheduler', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('renders once after a burst of edits settles, not per edit', async () => {
    const render = vi.fn(async () => {})
    const scheduler = new PreviewScheduler(render, 1000)
    for (let i = 0; i < 30; i++) { scheduler.edited(); await vi.advanceTimersByTimeAsync(16) }
    expect(render).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(render).toHaveBeenCalledTimes(1)
  })

  it('never runs two renders at once, and ends on the latest pose', async () => {
    let finish: () => void = () => {}
    let active = 0
    let peak = 0
    const render = vi.fn(() => new Promise<void>(resolve => { active++; peak = Math.max(peak, active); finish = () => { active--; resolve() } }))
    const scheduler = new PreviewScheduler(render, 100)
    scheduler.edited(); await vi.advanceTimersByTimeAsync(100)
    expect(render).toHaveBeenCalledTimes(1)
    // Three more edits while the first render is still running…
    for (let i = 0; i < 3; i++) { scheduler.edited(); await vi.advanceTimersByTimeAsync(150) }
    expect(render).toHaveBeenCalledTimes(1)
    finish(); await vi.advanceTimersByTimeAsync(0)
    // …queue exactly one more render, of the latest pose.
    expect(render).toHaveBeenCalledTimes(2)
    finish(); await vi.advanceTimersByTimeAsync(500)
    expect(render).toHaveBeenCalledTimes(2)
    expect(peak).toBe(1)
  })

  it('stops when the composer closes', async () => {
    const render = vi.fn(async () => {})
    const scheduler = new PreviewScheduler(render, 100)
    scheduler.edited()
    scheduler.dispose()
    await vi.advanceTimersByTimeAsync(500)
    expect(render).not.toHaveBeenCalled()
  })
})
