import { describe, expect, it } from 'vitest'
import type { SpecLayout3D } from '../../../types/shotspec'
import { cameraKeyframes, compositionFromLayout, figureVariantFor, layoutFromComposition } from './sceneFromAnalysis'
import { putKeyframe, sampleKeyframes, travelAlong, validateKeyframes } from './keyframes'
import { CompositionHistory } from './history'

const layout: SpecLayout3D = {
  camera: { pos: [0, 0.857, 0], rot: [0.0349, 0, 0], fov: 40 },
  objects: [
    { id: 'fig-1', kind: 'figure', pos: [-0.655, 0, -3.924], rot: [0, 0, 0], scale: [1, 1, 1], pose: 'stand', label: 'person' },
    { id: 'fig-2', kind: 'figure', pos: [1.058, 0, -5.872], rot: [0, 0.4, 0], scale: [0.7, 0.7, 0.7], pose: 'stand', label: 'child' },
    { id: 'prop-3', kind: 'prop', pos: [-1.813, 0, -4.14], rot: [0, 0, 0], scale: [0.64, 0.9, 0.64], pose: '', label: 'chair' },
  ],
  depth_map_path: 'depth.png',
}

describe('sceneFromAnalysis', () => {
  it('builds figures, props and a keyed camera, and round-trips within tolerance', () => {
    const scene = compositionFromLayout(layout, { duration: 4, move: 'push_in', words: { shot_size: 'full', angle: 'front', height: 'eye' } })
    expect(scene.objects.map(o => o.type)).toEqual(['figure', 'figure', 'cube'])
    expect(scene.objects[1].figure_variant).toBe('child')
    expect(scene.framing.shot_size).toBe('full')
    expect(scene.framing.camera_mode).toBe('manual')
    expect(scene.camera?.keyframes).toHaveLength(2)
    expect(scene.camera!.keyframes[1].transform.position[2]).toBeLessThan(scene.camera!.keyframes[0].transform.position[2])
    const back = layoutFromComposition(scene, layout)
    expect(back.depth_map_path).toBe('depth.png')
    back.objects.forEach((obj, i) => {
      expect(obj.kind).toBe(layout.objects[i].kind)
      obj.pos.forEach((v, k) => expect(v).toBeCloseTo(layout.objects[i].pos[k], 3))
      expect(obj.scale[1]).toBeCloseTo(layout.objects[i].scale[1], 3)
    })
    back.camera.pos.forEach((v, k) => expect(v).toBeCloseTo(layout.camera.pos[k], 3))
    expect(back.camera.fov).toBe(40)
  })

  it('mirrors the backend keyframe rules per move', () => {
    expect(cameraKeyframes(layout, 'static', 3)).toHaveLength(1)
    const orbit = cameraKeyframes(layout, 'orbit', 3)
    expect(orbit[1].transform.rotation[1]).toBeGreaterThan(orbit[0].transform.rotation[1])
    const pan = cameraKeyframes(layout, 'pan_left', 3, 2)
    expect(pan[1].transform.position).toEqual(pan[0].transform.position)
    expect(pan[1].transform.rotation[1] - pan[0].transform.rotation[1]).toBeCloseTo((24 * Math.PI) / 180, 6)
  })

  it('classifies body type from height', () => {
    expect(figureVariantFor(1.1)).toBe('child')
    expect(figureVariantFor(1.6)).toBe('female')
    expect(figureVariantFor(1.8)).toBe('male')
  })
})

describe('keyframes (Blocking-Room port)', () => {
  const a = { id: 'a', time: 0, transform: { position: [0, 0, 0] as [number, number, number], rotation: [0, 3.0, 0] as [number, number, number], scale: [1, 1, 1] as [number, number, number] }, fov: 40 }
  const b = { id: 'b', time: 2, transform: { position: [2, 0, 0] as [number, number, number], rotation: [0, -3.0, 0] as [number, number, number], scale: [1, 1, 1] as [number, number, number] }, fov: 50 }

  it('samples rotations along the shortest arc and holds outside the track', () => {
    const mid = sampleKeyframes([a, b], 1)!
    // 3.0 → −3.0 rad is a 0.28 rad step through ±π, not a 6 rad swing.
    expect(Math.abs(mid.rotation[1])).toBeGreaterThan(3.0)
    expect(mid.position[0]).toBeCloseTo(1, 6)
    expect(mid.fov).toBeCloseTo(45, 6)
    expect(sampleKeyframes([a, b], -1)!.position).toEqual([0, 0, 0])
    expect(sampleKeyframes([a, b], 9)!.position).toEqual([2, 0, 0])
  })

  it('putKeyframe snaps to 0.1 s and replaces a keyframe at the same time', () => {
    const list = putKeyframe([a, b], { ...b, id: 'c', time: 2.04 })
    expect(list.map(k => k.id)).toEqual(['a', 'c'])
    expect(list[1].time).toBe(2)
  })

  it('validates duration, finite numbers and unique times', () => {
    expect(validateKeyframes([a, b], 4)).toEqual([])
    const bad = validateKeyframes([a, { ...b, time: 9 }, { ...a, id: 'dup' }, { ...a, id: 'nan', transform: { ...a.transform, position: [NaN, 0, 0] } }], 4)
    expect(bad.map(i => i.keyframeId)).toEqual(['b', 'dup', 'nan', 'nan'])
  })

  it('measures travel distance and speed for the walk cycle', () => {
    expect(travelAlong([a, b], 1)).toEqual({ distance: 1, speed: 1 })
    expect(travelAlong([a, b], 5).distance).toBe(2)
    expect(travelAlong([a, b], 5).speed).toBe(0)
  })
})

describe('CompositionHistory (Blocking-Room port)', () => {
  it('undo/redo with a bound and drag grouping', () => {
    const history = new CompositionHistory({ n: 0 }, 3)
    history.commit({ n: 1 })
    history.commit({ n: 1 }) // no-op: identical
    history.begin()
    history.commit({ n: 2 })
    history.commit({ n: 3 })
    history.end({ n: 4 }) // one step for the whole drag
    expect(history.length).toBe(3)
    expect(history.undo()).toEqual({ n: 1 })
    expect(history.undo()).toEqual({ n: 0 })
    expect(history.undo()).toBeNull()
    expect(history.redo()).toEqual({ n: 1 })
    history.commit({ n: 5 }) // truncates the redo branch
    expect(history.canRedo).toBe(false)
    history.commit({ n: 6 })
    history.commit({ n: 7 })
    expect(history.length).toBe(4) // limit + 1
  })
})
