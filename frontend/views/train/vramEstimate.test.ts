import { describe, expect, it } from 'vitest'
import { estimateMinutes, estimateVramMb, maxBlocksToSwap } from './vramEstimate'

/* QA pass 2026-10-02 (Train): the estimate ignored Block swap, so a 12 GB card with
 * desktop apps open could not start a Z-Image run and nothing showed how to fit it. */

describe('estimateVramMb', () => {
  it('drops as more blocks are swapped, matching the backend', () => {
    // Recalibrated 2026-10-02 from measured peaks (was 10500 MB and 205 MB a block).
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 8, estimated_vram_mb: 8600 })).toBe(8600)
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 20, estimated_vram_mb: 8600 })).toBe(8600 - 12 * 170)
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 99, estimated_vram_mb: 8600 })).toBe(8600 - 20 * 170)
  })
  it('says about how long a Z-Image run takes', () => {
    expect(estimateMinutes({ target: 'z_image', steps: 840, resolution: 512 })).toBe(36)
    expect(estimateMinutes({ target: 'z_image', steps: 1100, resolution: 768 })).toBe(99)
    expect(estimateMinutes({ target: 'flux', steps: 800, resolution: 768 })).toBeNull()
  })
  it('adds the batch to the VRAM estimate (measured: 7.7 GB at batch 1, 9.3 GB at batch 2)', () => {
    const one = estimateVramMb({ target: 'z_image', blocks_to_swap: 8, estimated_vram_mb: 8600 })
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 8, estimated_vram_mb: 8600, batch_size: 2 }) - one).toBe(1650)
  })
  it('keeps other targets at their fixed estimate', () => {
    expect(estimateVramMb({ target: 'wan22', blocks_to_swap: 40, estimated_vram_mb: 24000 })).toBe(24000)
    expect(maxBlocksToSwap('wan22')).toBeNull()
    expect(maxBlocksToSwap('z_image')).toBe(28)
  })
})
