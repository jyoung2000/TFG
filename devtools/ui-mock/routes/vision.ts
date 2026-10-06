/**
 * The local vision stack, simulated: a status that reflects the settings,
 * a fake analysis, and unload/cache controls. Real analysis needs models the
 * mock does not have; the numbers here only keep the UI honest.
 */

import { MockHttpError, type Router } from '../http'
import type { Store } from '../state'

export function registerVisionRoutes(router: Router, store: Store): void {
  const loaded = new Set<string>(['florence', 'clip'])

  router.get('/api/vision/status', () => {
    const vision = store.data.settings.vision
    const components = [
      { name: 'stats', enabled: true, available: true, loaded: true, model: 'deterministic', vram_class: 'S', estimated_mb: 0, note: '' },
      { name: 'florence', enabled: vision.enabled && vision.florenceEnabled, available: true, loaded: loaded.has('florence'), model: vision.florenceModel, vram_class: vision.florenceModel.includes('base') ? 'S' : 'M', estimated_mb: vision.florenceModel.includes('base') ? 600 : 1700, note: '' },
      { name: 'clip', enabled: vision.enabled && vision.clipEnabled, available: true, loaded: loaded.has('clip'), model: vision.clipModel, vram_class: 'M', estimated_mb: 1000, note: '' },
      { name: 'depth', enabled: vision.enabled && vision.depthEnabled, available: true, loaded: loaded.has('depth'), model: vision.depthModel, vram_class: 'S', estimated_mb: 200, note: '' },
      { name: 'dino', enabled: vision.enabled && vision.dinoEnabled, available: true, loaded: loaded.has('dino'), model: vision.dinoModel, vram_class: 'S', estimated_mb: 150, note: '' },
    ]
    const used = 1024 + [...loaded].reduce((sum, name) => sum + (components.find(c => c.name === name)?.estimated_mb ?? 0), 0)
    return {
      vision: { mode: 'local', device: 'cuda', components },
      vram: { free_mb: 12288 - used, total_mb: 12288, loaded: [...loaded], ollama_model: vision.vlmProvider === 'ollama' ? vision.vlmModel || 'qwen2.5vl:3b' : '' },
      cache: { entries: 3, bytes: 48_112 },
      vlm: vision.vlmProvider === 'off' ? '' : vision.vlmProvider === 'ollama' ? `ollama:${vision.vlmModel || 'qwen2.5vl:3b'}` : vision.vlmProvider,
    }
  })

  router.post('/api/vision/unload', () => {
    const unloaded = [...loaded].sort()
    loaded.clear()
    return { unloaded }
  })

  router.delete('/api/vision/cache', () => ({ removed: 3 }))

  router.post('/api/vision/prepare-render', () => ({ free_mb: 11000, total_mb: 12288, loaded: [], ollama_model: '' }))

  router.post('/api/vision/analyze', req => {
    const path = String(req.body.path ?? '')
    if (!path) throw new MockHttpError(400, 'path is required')
    loaded.add('florence')
    loaded.add('clip')
    loaded.add('depth')
    return {
      image_path: path,
      content_hash: 'mock' + path.length.toString(16),
      measured: { width: 1280, height: 720, aspect: '16:9', palette: [{ hex: '#3a2a20', share: 0.62 }, { hex: '#e6be78', share: 0.21 }, { hex: '#5a3c2d', share: 0.17 }], luminance: 0.31, contrast: 0.22, saturation: 0.41, edge_density: 0.08, sharpness: 0.0021, background_hex: '', vector_likeness: 0.12, exif: {} },
      caption: { text: 'A person crouches at a console in a dim room lit by a warm window.', level: 'more_detailed_caption', model: 'florence-2-large' },
      regions: [{ label: 'person', bbox: [0.28, 0.25, 0.16, 0.7], score: 0.9, depth_median: 0.71 }, { label: 'window', bbox: [0.7, 0.11, 0.22, 0.39], score: 0.85, depth_median: 0.2 }],
      tags: { model: 'openai/clip-vit-large-patch14', tags: [{ term: 'photograph', score: 0.31, category: 'medium' }, { term: 'cinematic', score: 0.28, category: 'flavor' }, { term: 'warm lighting', score: 0.27, category: 'flavor' }], negatives: [{ term: 'blurry', score: 0.2, category: 'negative' }] },
      depth: { model: 'depth-anything-v2-small', depth_png: 'ui-mock/vision/depth.png', width: 1280, height: 720, near: 1, far: 0, mean: 0.45 },
      notes: {},
    }
  })
}
