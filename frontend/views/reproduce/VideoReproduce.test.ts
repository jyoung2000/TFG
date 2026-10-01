import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { VideoAnalysis } from '../../types/video-analysis'
import type { VideoReproduceJob } from '../../types/video-reproduce'
import { VideoReproducePanel } from './VideoReproduce'

/*
 * Asked 2026-10-01: in video reproduce the model and prompt that made each
 * take should sit next to the output, the UI should make clear which is the
 * original and which the reproduction, and the run's storyboard should be
 * there without building it. The panel showed the original as an unlabelled
 * still, the take with no model or prompt, and only "Build 3D storyboard",
 * which made a second, separate project.
 */

const take = {
  id: 'vc-1', version_number: 1, path: 'C:/out/take.mp4', frames: [], prompt: 'close-up. two people kissing, cinematic light',
  negative_prompt: 'blurry', seed: 42, round: 1, model: 'vace_1.3B', target: 'wan22', duration_seconds: 10, status: 'complete' as const,
  error: '', scores: { composite: 0.954, components: { ssim: 0.94 }, weights_used: {}, missing: [] }, motion_match: 0.93,
  strategy: 'reference_video', control_strength: 1, job_id: '', created_at: 0,
}

const job = {
  analysis_id: 'va-1', project_id: 'film-1', title: 'trim', kind: 'preview', target: 'wan22', model: 'ltx2_22B_distilled', resolution: '540p', fps: 24,
  status: 'complete', progress: 1, message: '', error: '', stitched_path: 'stitched-1.mp4', stitched_at: 1, peak_vram_mb: null,
  shots: [{
    shot_id: 'vs-1', index: 0, film_scene_id: 'sc-1', film_shot_id: 'sh-1', start: 0, end: 10.12, duration_seconds: 10,
    start_frame: 'reproduce/start-vs-1.jpg', end_frame: '', reference_clip: 'reference-vs-1.mp4', prompt: take.prompt, negative_prompt: 'blurry',
    prompt_source: 'spec', candidates: [take], best_candidate_id: 'vc-1', picked_candidate_id: 'vc-1', reached: true, note: '',
  }],
} as unknown as VideoReproduceJob

const analysis = { id: 'va-1', source: { file_name: 'trim.mp4' }, shots: [{ id: 'vs-1', frames: [] }] } as unknown as VideoAnalysis

function render(): string {
  return renderToStaticMarkup(createElement(VideoReproducePanel, { analysis, job, onJob: () => undefined, onClose: () => undefined, onOpenStoryboard: () => undefined }))
}

describe('VideoReproducePanel', () => {
  it('labels the original and the reproduction, per shot and for the whole video', () => {
    const html = render()
    expect(html.match(/data-testid="badge-original"/g)).toHaveLength(2)
    expect(html.match(/data-testid="badge-reproduction"/g)).toHaveLength(2)
  })

  it('shows the model that rendered the take and its prompt next to it', () => {
    const html = render()
    expect(html).toContain('VACE 1.3B (Wan 2.1)')
    expect(html).toContain('close-up. two people kissing, cinematic light')
    expect(html).toContain('guided by the original clip')
  })

  it("opens the run's own storyboard", () => {
    expect(render()).toContain('data-testid="video-reproduce-open-storyboard"')
  })
})
