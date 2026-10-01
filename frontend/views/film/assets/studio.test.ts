import { describe, expect, it } from 'vitest'
import type { FilmAsset } from '../../../types/film'
import { studioShot } from './studio'
import { underlaySource } from '../composer/sceneFromAnalysis'

/* Asked 2026-10-01: use the 3D composer in the Assets tab. The asset's studio
 * shot casts the asset, reopens its saved scene and shows its image behind
 * the viewfinder. */

const asset = {
  id: 'asset-1', kind: 'character', name: 'Mara', description: '', reference_images: ['assets/mara-front.png'],
  composition: { objects: [{ id: 'fig-1', name: 'Mara', type: 'figure' }], camera: null, framing: {}, camera_move: 'static', duration_seconds: 3 },
} as unknown as FilmAsset

describe('studioShot', () => {
  it('casts the asset so the composer seeds its figure', () => {
    expect(studioShot(asset).characters.map(c => c.asset_id)).toEqual(['asset-1'])
  })

  it('reopens the scene saved on the asset', () => {
    expect(studioShot(asset).composition).toBe(asset.composition)
  })

  it("shows the asset's image behind the viewfinder", () => {
    expect(underlaySource(studioShot(asset))).toEqual({ kind: 'capture', path: 'assets/mara-front.png' })
  })
})
