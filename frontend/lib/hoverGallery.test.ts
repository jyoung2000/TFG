import { describe, expect, it } from 'vitest'
import { jobGallery, loraGallery, nextFrame, runGallery } from './hoverGallery'
import type { Job } from '../types/jobs'

/* User, 2026-10-04: "let the user click on the preview image to see in a big
 * screen modal, also hovering over an item with a thumbnail should cycle through
 * the pictures on that listing like a gallery or autoplay the video on silent". */

const runs = [
  { id: 'r1', lora_id: 'l1', samples: [{ step: 0, path: 's0.png' }, { step: 150, path: 's1.png' }, { step: 300, path: 's2.png' }] },
  { id: 'r2', lora_id: '', samples: [] },
] as never[]

const job = (over: Partial<Job>): Job => ({
  id: 'j', kind: 'image_gen', status: 'complete', progress: 100, phase: '', title: '', created_at: 0, updated_at: 0, started_at: 0, finished_at: 0,
  model: '', provider: '', seed: null, prompt: '', negative_prompt: '', spec: {}, params: {}, inputs: {}, outputs: [], metrics: {}, parent_job_id: '', project_id: '', shot_id: '', error: '',
  ...over,
} as Job)

describe('nextFrame', () => {
  it('walks the pictures and wraps', () => {
    expect(nextFrame(0, 4)).toBe(1)
    expect(nextFrame(3, 4)).toBe(0)
    expect(nextFrame(0, 1)).toBe(0)
    expect(nextFrame(0, 0)).toBe(0)
  })
})

describe('loraGallery', () => {
  it('shows every preview view, the close-up first', () => {
    expect(loraGallery({ preview_paths: ['p1.jpg', 'p2.jpg', 'p3.jpg'], run_id: 'r1' }, runs, ['Close-up', 'Medium'])).toEqual([
      { kind: 'image', path: 'p1.jpg', label: 'Close-up' },
      { kind: 'image', path: 'p2.jpg', label: 'Medium' },
      { kind: 'image', path: 'p3.jpg' },
    ])
  })
  it("falls back to its run's samples, newest first", () => {
    expect(loraGallery({ preview_paths: [], run_id: 'r1' }, runs).map(m => [m.path, m.runId, m.label])).toEqual([
      ['s2.png', 'r1', 'step 300'], ['s1.png', 'r1', 'step 150'], ['s0.png', 'r1', 'step 0'],
    ])
    expect(loraGallery({ run_id: 'r2' }, runs)).toEqual([])
  })
})

describe('runGallery', () => {
  it("is the run's LoRA preview once rendered, then its samples", () => {
    const loras = [{ id: 'l1', preview_paths: ['p1.jpg'], run_id: 'r1' }]
    expect(runGallery(runs[0], loras).map(m => m.path)).toEqual(['p1.jpg', 's2.png', 's1.png', 's0.png'])
    expect(runGallery(runs[0], []).map(m => m.path)).toEqual(['s2.png', 's1.png', 's0.png'])
    expect(runGallery(runs[1], loras)).toEqual([])
  })
})

describe('jobGallery', () => {
  it('cycles every image a render made', () => {
    const outputs = [
      { path: 'a.png', kind: 'image', width: 0, height: 0, duration: 0, thumb: 'a.thumb.jpg' },
      { path: 'b.png', kind: 'image', width: 0, height: 0, duration: 0, thumb: '' },
    ] as Job['outputs']
    expect(jobGallery(job({ outputs }))).toEqual([{ kind: 'image', path: 'a.thumb.jpg' }, { kind: 'image', path: 'b.png' }])
  })
  it('plays a video, with its thumbnail as the still', () => {
    const outputs = [{ path: 'clip.mp4', kind: 'video', width: 0, height: 0, duration: 5, thumb: 'clip.jpg' }] as Job['outputs']
    expect(jobGallery(job({ kind: 'video_gen', outputs }))).toEqual([{ kind: 'video', path: 'clip.mp4', poster: 'clip.jpg' }])
  })
  it("shows a training run's samples newest first, never its .safetensors", () => {
    const outputs = [{ path: 'lora.safetensors', kind: 'file', width: 0, height: 0, duration: 0, thumb: '' }] as Job['outputs']
    expect(jobGallery(job({ kind: 'training', outputs, metrics: { samples: ['s0.png', 's1.png'] } })).map(m => m.path)).toEqual(['s1.png', 's0.png'])
    expect(jobGallery(job({ kind: 'download', outputs }))).toEqual([])
  })
})
