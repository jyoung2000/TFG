import { describe, expect, it } from 'vitest'
import { kmeansPalette, measurePixels, snapAspect } from './deterministic'

function solid(width: number, height: number, rgb: [number, number, number]): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = rgb[0]; data[i * 4 + 1] = rgb[1]; data[i * 4 + 2] = rgb[2]; data[i * 4 + 3] = 255
  }
  return data
}

describe('deterministic stats (TS twin of the server measurement)', () => {
  it('snaps aspect ratios like the server', () => {
    expect(snapAspect(1920, 1080)).toBe('16:9')
    expect(snapAspect(1080, 1920)).toBe('9:16')
    expect(snapAspect(997, 1003)).toBe('1:1')
  })

  it('measures a flat red frame the way the server does', () => {
    // Server value for a 640x360 (200,40,40) frame: luminance 0.2903, saturation 0.8, contrast 0, edges 0.
    const stats = measurePixels(solid(640, 360, [200, 40, 40]), 640, 360)
    expect(stats.aspect).toBe('16:9')
    expect(stats.luminance).toBeCloseTo(0.2903, 3)
    expect(stats.saturation).toBeCloseTo(0.8, 3)
    expect(stats.contrast).toBe(0)
    expect(stats.edge_density).toBe(0)
    expect(stats.palette).toEqual([{ hex: '#c82828', share: 1 }])
    expect(stats.background_hex).toBe('#c82828')
  })

  it('finds the boundary in a half-black half-white frame', () => {
    const width = 640, height = 360
    const data = new Uint8ClampedArray(width * height * 4)
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const v = x < 320 ? 250 : 0
      const i = (y * width + x) * 4
      data[i] = v; data[i + 1] = v; data[i + 2] = v; data[i + 3] = 255
    }
    const stats = measurePixels(data, width, height)
    expect(stats.contrast).toBeGreaterThan(0.4)
    expect(stats.edge_density).toBeGreaterThan(0)
    expect(stats.background_hex).toBe('')
    expect(stats.palette.length).toBe(2)
    expect(Math.abs(stats.palette[0].share + stats.palette[1].share - 1)).toBeLessThan(0.01)
  })

  it('orders the palette by share, deterministically', () => {
    const rgb = new Float64Array(100 * 3)
    for (let i = 0; i < 100; i++) {
      if (i < 90) rgb[i * 3] = 1
      else rgb[i * 3 + 2] = 1
    }
    const a = kmeansPalette(rgb, 2)
    const b = kmeansPalette(rgb, 2)
    expect(a).toEqual(b)
    expect(a[0].share).toBeGreaterThan(0.8)
  })
})
