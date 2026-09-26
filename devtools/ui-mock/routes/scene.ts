/** 3D scene routes, simulated with the renderer's own scene twin. */

import type { CameraMove } from '../../../frontend/types/film'
import type { ShotSpec, SpecLayout3D } from '../../../frontend/types/shotspec'
import { compositionFromLayout } from '../../../frontend/views/film/composer/sceneFromAnalysis'
import { MockHttpError, type Router } from '../http'
import { mockCameraWords, mockLayout } from './video-analysis'

function svgFor(layout: SpecLayout3D): string {
  const items = layout.objects.map((o, i) => `<rect x="${40 + i * 60}" y="${90 - o.scale[1] * 30}" width="18" height="${o.scale[1] * 60}" rx="8" fill="${o.kind === 'figure' ? '#c9a97a' : '#8a93a6'}"/>`).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" width="320" height="180" role="img" aria-label="3D blockout (UI MOCK)"><rect width="320" height="180" fill="#16181d"/>${items}<text x="8" y="172" font-size="10" fill="#9ca3af" font-family="sans-serif">UI mock blockout</text></svg>`
}

export function registerSceneRoutes(router: Router): void {
  router.post('/api/scene/build', req => {
    const spec = req.body.spec as ShotSpec | undefined
    if (!spec) throw new MockHttpError(400, 'spec is required')
    const layout = spec.layout3d?.objects?.length ? spec.layout3d : mockLayout(0)
    const words = mockCameraWords(layout)
    const move = (req.body.camera_move as CameraMove | null | undefined) ?? 'static'
    return {
      layout3d: layout,
      composition: compositionFromLayout(layout, { duration: Number(req.body.duration_seconds ?? 4), move, motion: spec.motion, words: words.camera_words }),
      camera_words: words.camera_words,
      camera_sentence: words.camera_sentence,
      reprojection_error: 0.012,
      svg: svgFor(layout),
    }
  })

  router.post('/api/scene/describe', req => {
    const layout = req.body.layout3d as SpecLayout3D | undefined
    if (!layout) throw new MockHttpError(400, 'layout3d is required')
    return mockCameraWords(layout)
  })
}
