import { describe, expect, it } from 'vitest'
import { loraThumb, newestFirst, runThumb, whenLabel } from './loraList'

/* 2026-10-02: every LoRA and run row read "Raven (asset) · z_image" with a date only. */

const runs = [{ id: 'r1', samples: [{ path: 's0.png' }, { path: 's1.png' }], lora_id: 'l1' }, { id: 'r2', samples: [], lora_id: '' }] as never[]

describe('loraThumb', () => {
  it('prefers the LoRA preview, then the run sample, then nothing', () => {
    expect(loraThumb({ preview_paths: ['p1.png'], run_id: 'r1' }, runs)).toEqual({ kind: 'preview', path: 'p1.png' })
    expect(loraThumb({ preview_paths: [], run_id: 'r1' }, runs)).toEqual({ kind: 'sample', runId: 'r1', path: 's1.png' })
    expect(loraThumb({ run_id: 'r2' }, runs)).toEqual({ kind: 'none' })
  })
})

describe('runThumb', () => {
  it('shows the LoRA preview once rendered, else the last sample', () => {
    expect(runThumb(runs[0], [{ id: 'l1', preview_paths: ['p1.png'], run_id: 'r1' }])).toEqual({ kind: 'preview', path: 'p1.png' })
    expect(runThumb(runs[0], [])).toEqual({ kind: 'sample', runId: 'r1', path: 's1.png' })
    expect(runThumb(runs[1], [])).toEqual({ kind: 'none' })
  })
})

describe('whenLabel and newestFirst', () => {
  it('gives date and time, and orders newest first', () => {
    const now = new Date(2026, 9, 2, 23, 0)
    expect(whenLabel(new Date(2026, 9, 2, 22, 25).getTime(), now)).toMatch(/Oct.*10:25/)
    expect(whenLabel(new Date(2025, 0, 5, 9, 5).getTime(), now)).toMatch(/2025/)
    expect(newestFirst([{ created_at: 1 }, { created_at: 3 }, { created_at: 2 }]).map(i => i.created_at)).toEqual([3, 2, 1])
  })
})
