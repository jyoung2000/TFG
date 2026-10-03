import { describe, expect, it } from 'vitest'
import { appendPhrase, byTaste, jobTasteTarget, nextVote, speedForTaste, tasteChips } from './taste'
import type { Job } from '../types/jobs'

const job = (over: Partial<Job>): Job => ({
  id: 'j1', kind: 'image_gen', status: 'complete', progress: 100, phase: '', title: '', created_at: 0, updated_at: 0, started_at: 0, finished_at: 0,
  model: 'z_image', provider: 'wangp', seed: 1, prompt: 'rvnx, woman', negative_prompt: '', spec: {}, params: {}, inputs: {},
  outputs: [{ path: 'C:/out/a.png', kind: 'image', width: 768, height: 1024, duration: 0, thumb: '' }], metrics: {}, parent_job_id: '', project_id: '', shot_id: '', error: '',
  ...over,
} as Job)

describe('nextVote', () => {
  it('sets a thumb, switches it, and takes it back', () => {
    expect(nextVote(0, 1)).toBe(1)
    expect(nextVote(1, -1)).toBe(-1)
    expect(nextVote(-1, -1)).toBe(0)
  })
})

describe('jobTasteTarget', () => {
  it("grades a finished render's image or video with what made it", () => {
    const target = jobTasteTarget(job({ params: { loras: [{ name: 'C:/loras/raven.safetensors', multiplier: 1 }] } }))
    expect(target).toEqual({ kind: 'image', subject: 'C:/out/a.png', prompt: 'rvnx, woman', model: 'z_image', loras: ['C:/loras/raven.safetensors'], projectId: undefined })
    expect(jobTasteTarget(job({ kind: 'video_gen', outputs: [{ path: 'C:/out/b.mp4', kind: 'video', width: 0, height: 0, duration: 5, thumb: '' }] }))?.kind).toBe('video')
  })
  it('has nothing to grade before the job finishes or without a picture', () => {
    expect(jobTasteTarget(job({ status: 'running' }))).toBeNull()
    expect(jobTasteTarget(job({ kind: 'training', outputs: [{ path: 'C:/loras/x.safetensors', kind: 'file', width: 0, height: 0, duration: 0, thumb: '' }] }))).toBeNull()
  })
})

describe('speedForTaste', () => {
  it('maps the liked LoRAs settings to a Train speed', () => {
    expect(speedForTaste({ resolution: 384, steps: 300, batch_size: 2, liked: 2 })).toBe('balanced')
    expect(speedForTaste({ resolution: 512, steps: 150, batch_size: 2, liked: 1 })).toBe('fast')
    expect(speedForTaste({ resolution: 512, steps: 840, batch_size: 1, liked: 1 })).toBe('standard')
    expect(speedForTaste(null)).toBeNull()
  })
})

describe('tasteChips and appendPhrase', () => {
  it('offers liked phrases the prompt does not have yet', () => {
    const liked = [{ text: 'soft studio light', up: 3, down: 0 }, { text: 'red lips', up: 2, down: 0 }]
    expect(tasteChips(liked, 'rvnx, woman, Soft Studio Light')).toEqual(['red lips'])
    expect(appendPhrase('rvnx, woman, ', 'red lips')).toBe('rvnx, woman, red lips')
    expect(appendPhrase('', 'red lips')).toBe('red lips')
  })
})

describe('byTaste', () => {
  it('puts liked first and disliked last, keeping the order otherwise', () => {
    const votes: Record<string, 1 | -1 | 0> = { a: 0, b: -1, c: 1, d: 0 }
    expect(byTaste(['a', 'b', 'c', 'd'], x => votes[x])).toEqual(['c', 'a', 'd', 'b'])
  })
})
