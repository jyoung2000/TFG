import { describe, expect, it } from 'vitest'
import type { FilmAsset } from '../../../types/film'
import { studioShot } from './studio'
import type { FilmProject } from '../../../types/film'
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

describe('studioShot without a saved studio scene', () => {
  it("starts from the character's pose in the storyboard", () => {
    const bare = { ...asset, composition: null } as unknown as FilmAsset
    const posed = { id: 'fig-5', name: 'Woman', type: 'figure', asset_id: 'asset-1', pose: { l_elbow: [0, 0, -80] }, figure_variant: 'female', color: '#e4572e',
      transform: { position: [0.3, 0, -1.2], rotation: [0, 0.4, 0], scale: [1, 1, 1] }, keyframes: [], visible: true, locked: false }
    const project = { scenes: [{ shots: [{ composition: { objects: [posed, { id: 'prop-1', type: 'cube' }], camera: { id: 'shot-camera' } } }] }] } as unknown as FilmProject
    const objects = studioShot(bare, project).composition?.objects ?? []
    expect(objects).toHaveLength(1)
    expect(objects[0].pose).toEqual({ l_elbow: [0, 0, -80] })
    expect(objects[0].transform.position).toEqual([0, 0, 0]) // centre stage, facing the camera
    expect(objects[0].transform.rotation).toEqual([0, 0, 0])
  })
})
