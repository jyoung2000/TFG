import { describe, expect, it } from 'vitest'
import { ASSET_COLORS, pickAssetColor } from './assetColors'

/* Asked 2026-10-01: colour-code the models so separate assets read apart. */
describe('pickAssetColor', () => {
  it('gives ten objects ten different colours', () => {
    const used: string[] = []
    for (let i = 0; i < 10; i++) used.push(pickAssetColor('', used))
    expect(new Set(used).size).toBe(10)
  })

  it('replaces the old shared greys', () => {
    expect(pickAssetColor('#8a93a6', [])).toBe(ASSET_COLORS[0])
    expect(pickAssetColor('#7f9cc4', [ASSET_COLORS[0]])).toBe(ASSET_COLORS[1])
  })

  it('keeps an object its palette colour across reloads, unless another object has it', () => {
    expect(pickAssetColor(ASSET_COLORS[3], [ASSET_COLORS[0]])).toBe(ASSET_COLORS[3])
    expect(pickAssetColor(ASSET_COLORS[0], [ASSET_COLORS[0]])).toBe(ASSET_COLORS[1])
  })
})
