import { describe, expect, it } from 'vitest'
import { describeBatch } from './batchNote'

/* QA pass 2026-10-01 (storyboard): a batch never said what it queued or why it skipped shots. */

describe('describeBatch', () => {
  it('counts what was queued', () => {
    expect(describeBatch({ queued: [1] })).toBe('Queued 1 shot')
    expect(describeBatch({ queued: [1, 2], skipped: [] })).toBe('Queued 2 shots')
  })
  it('says how many were skipped and each distinct reason once', () => {
    expect(describeBatch({ queued: [], skipped: [{ reason: 'already rendering' }, { reason: 'already rendering' }, { reason: 'no prompt' }] }))
      .toBe('Queued 0 shots · 3 skipped: already rendering; no prompt')
  })
})
