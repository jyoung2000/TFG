import { describe, expect, it } from 'vitest'
import { estimateVramMb, maxBlocksToSwap } from './vramEstimate'

/* QA pass 2026-10-02 (Train): the estimate ignored Block swap, so a 12 GB card with
 * desktop apps open could not start a Z-Image run and nothing showed how to fit it. */

describe('estimateVramMb', () => {
  it('drops as more blocks are swapped, matching the backend', () => {
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 8, estimated_vram_mb: 10500 })).toBe(10500)
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 20, estimated_vram_mb: 10500 })).toBe(10500 - 12 * 205)
    expect(estimateVramMb({ target: 'z_image', blocks_to_swap: 99, estimated_vram_mb: 10500 })).toBe(10500 - 20 * 205)
  })
  it('keeps other targets at their fixed estimate', () => {
    expect(estimateVramMb({ target: 'wan22', blocks_to_swap: 40, estimated_vram_mb: 24000 })).toBe(24000)
    expect(maxBlocksToSwap('wan22')).toBeNull()
    expect(maxBlocksToSwap('z_image')).toBe(28)
  })
})
