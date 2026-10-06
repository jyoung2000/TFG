/** "Render with" — only models that can actually render may be chosen.

The four rows below are the real library response from the audit machine after
installing them, so the test pins the behaviour that matters: an installed model
is offered, and a model that is merely *known to the checkout* is shown disabled
with the reason. Offering SDXL would be a lie - it has no definition in the
Wan2GP checkout at all.
*/

import { describe, expect, it } from 'vitest'

import { blockedReason, partitionModels, type RenderWithModel } from './RenderWith'

function model(over: Partial<RenderWithModel> & { id: string }): RenderWithModel {
  return {
    name: over.id,
    installed: false,
    size_gb: null,
    estimated_min_vram_gb: null,
    fits_gpu: null,
    ...over,
  }
}

const REAL_LIBRARY: RenderWithModel[] = [
  model({ id: 'z_image', name: 'Z-Image', installed: true, size_gb: 6.9 }),
  model({ id: 'z_image_nunchaku_r128_fp4', installed: true, size_gb: 4.2 }),
  model({ id: 'z_image_nunchaku_r256_int4', installed: true, size_gb: 4.5 }),
  model({ id: 'flux2_klein_4b', installed: true, size_gb: 4.1 }),
  model({ id: 'flux_dev_kontext', size_gb: 35.8, fits_gpu: true }),
  model({ id: 'qwen_image_20B', size_gb: 61.3, estimated_min_vram_gb: 24, fits_gpu: false }),
]

describe('partitionModels', () => {
  it('offers every installed model and nothing else', () => {
    const { available, blocked } = partitionModels(REAL_LIBRARY)
    expect(available.map(m => m.id)).toEqual([
      'z_image',
      'z_image_nunchaku_r128_fp4',
      'z_image_nunchaku_r256_int4',
      'flux2_klein_4b',
    ])
    expect(blocked.map(m => m.id)).toEqual(['flux_dev_kontext', 'qwen_image_20B'])
  })

  it('labels an installed model with its size', () => {
    const { available } = partitionModels(REAL_LIBRARY)
    expect(available[0].label).toBe('Z-Image · 6.9 GB')
  })

  it('says why a model is unavailable instead of hiding it', () => {
    const { blocked } = partitionModels(REAL_LIBRARY)
    expect(blocked[0].label).toContain('weights not downloaded')
    // a model the GPU cannot hold gets the VRAM reason
    expect(blocked[1].label).toContain('needs 24 GB VRAM')
  })

  it('never offers a model whose weights are absent, even if the GPU could run it', () => {
    // flux_dev_kontext fits_gpu: true but is not installed - the case that
    // would have produced a dropdown full of models that render nothing.
    const kontext = REAL_LIBRARY.find(m => m.id === 'flux_dev_kontext')!
    expect(kontext.fits_gpu).toBe(true)
    expect(blockedReason(kontext)).toBe('weights not downloaded')
  })

  it('keeps the blocked list short without dropping the order', () => {
    const many = Array.from({ length: 20 }, (_, i) => model({ id: `m${i}` }))
    const { available, blocked } = partitionModels(many, 6)
    expect(available).toHaveLength(0)
    expect(blocked.map(m => m.id)).toEqual(['m0', 'm1', 'm2', 'm3', 'm4', 'm5'])
  })

  it('offers nothing and says so when no model is installed', () => {
    const { available } = partitionModels([model({ id: 'sdxl', size_gb: 7 })])
    expect(available).toEqual([])
  })
})
