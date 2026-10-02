import { describe, expect, it } from 'vitest'
import { syncDraft } from './drawerDraft'

/* QA pass 2026-10-01. The shot drawer reset its whole form whenever the shot
 * changed on the server - including `updated_at`, which the 2 s queue poll
 * bumps throughout a render - so text being typed into Action / Dialogue /
 * Prompt vanished mid-sentence while that shot rendered. */

const server = { title: 'Shot 1', action: 'She walks in', dialogue: '' }

describe('syncDraft', () => {
  it('keeps what the user is typing when the shot refreshes', () => {
    const draft = { ...server, action: 'She walks in, slow' }
    expect(syncDraft(draft, server, { ...server })).toEqual(draft)
  })

  it('takes a new server value for a field the user has not touched', () => {
    const draft = { ...server, action: 'She walks in, slow' }
    const next = { ...server, title: 'Shot 1 (renamed by Director)' }
    expect(syncDraft(draft, server, next)).toEqual({ ...draft, title: 'Shot 1 (renamed by Director)' })
  })

  it("keeps the user's edit even when the server changed the same field", () => {
    const draft = { ...server, dialogue: 'Hello.' }
    expect(syncDraft(draft, server, { ...server, dialogue: 'Hi' }).dialogue).toBe('Hello.')
  })

  it('returns the same object when nothing changes (no re-render)', () => {
    const draft = { ...server }
    expect(syncDraft(draft, server, { ...server })).toBe(draft)
  })
})
