/** UI-only reference-image workflow. SVGs are clearly marked as mock media. */
import { RawResponse, MockHttpError, type Router } from '../http'
import { placeholderSvg } from '../media'

type Candidate = { id: string; path: string; prompt: string; score: number; round: number; model: string }
type Analysis = {
  id: string; title: string; source_path: string; width: number; height: number;
  prompt: string; description: string; subjects: string; composition: string; colors: string; lighting: string; style: string;
  vision_model: string; image_model: string; confidence: number;
  candidates: Candidate[]; revisions: { differences: string; prompt: string }[]; best_candidate_id: string;
}
const analyses = new Map<string, Analysis>()
let serial = 0
export function registerImageAnalysisRoutes(router: Router): void {
  router.post('/api/image-analysis/import', req => {
    const path = String(req.body.path || '')
    if (!/\.(png|jpe?g|webp)$/i.test(path)) throw new MockHttpError(400, 'Choose a PNG, JPG or WebP image')
    const id = `ia-mock-${++serial}`
    const analysis: Analysis = { id, title: path.split(/[\\/]/).pop() || 'Reference', source_path: 'reference.png', width: 1280, height: 720,
      prompt: '', description: '', subjects: '', composition: '', colors: '', lighting: '', style: '',
      vision_model: '', image_model: 'Z-Image (mock)', confidence: 0, candidates: [], revisions: [], best_candidate_id: '' }
    analyses.set(id, analysis)
    return analysis
  })
  router.get('/api/image-analysis', () => ({ analyses: [...analyses.values()] }))
  router.get('/api/image-analysis/:id', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    return item
  })
  router.delete('/api/image-analysis/:id', req => { analyses.delete(req.params.id); return { status: 'ok' } })
  router.post('/api/image-analysis/:id/analyze', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    Object.assign(item, { prompt: 'A single subject centered against a muted background, soft even light',
      description: 'UI mock description — not an AI reading.', subjects: 'Single subject', composition: 'Centered',
      colors: 'Muted', lighting: 'Soft even light', style: 'Minimal', vision_model: 'UI mock (not a model)', confidence: 0.5 })
    return item
  })
  router.put('/api/image-analysis/:id/prompt', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    item.prompt = String(req.body.prompt || '').trim()
    return item
  })
  router.post('/api/image-analysis/:id/render', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    if (!item.prompt) throw new MockHttpError(400, 'Analyze the reference first')
    for (let i = 0; i < Math.min(Number(req.body.candidates || 2), 3); i++) {
      const id = `candidate-${item.candidates.length + 1}`
      item.candidates.push({ id, path: `${id}.png`, prompt: item.prompt, score: 0.5 + (i / 10), round: item.revisions.length + 1, model: item.image_model })
      item.best_candidate_id = id
    }
    return item
  })
  router.post('/api/image-analysis/:id/refine', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    if (!item.best_candidate_id) throw new MockHttpError(400, 'Render a candidate first')
    item.revisions.push({ differences: 'UI mock: background needs more detail', prompt: item.prompt + ', detailed background' })
    item.prompt = item.revisions.at(-1)?.prompt || item.prompt
    const id = `candidate-${item.candidates.length + 1}`
    item.candidates.push({ id, path: `${id}.png`, prompt: item.prompt, score: 0.75, round: item.revisions.length + 1, model: item.image_model })
    item.best_candidate_id = id
    return item
  })
  router.get('/api/image-analysis/:id/media', req => {
    const item = analyses.get(req.params.id)
    if (!item) throw new MockHttpError(404, 'Image analysis not found')
    const path = req.query.get('path') || ''
    if (path !== item.source_path && !item.candidates.some(candidate => candidate.path === path)) throw new MockHttpError(400, 'Invalid media')
    const svg = placeholderSvg(path === item.source_path ? 'Reference (UI MOCK)' : 'Generated candidate (UI MOCK)', item.title, path)
    return new RawResponse(200, { 'content-type': 'image/svg+xml' }, svg)
  })
}
