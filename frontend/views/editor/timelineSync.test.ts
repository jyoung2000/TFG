import { describe, expect, it } from 'vitest'
import { mergeExternalClips } from './timelineSync'
import type { TimelineClip } from '../../types/project'

/* Asked 2026-10-01: ensure the video editor works. Live in r44, a storyboard
 * shot sent to the timeline showed in the timeline list ("1 clip") but not
 * in the editor - the editor loads a timeline's clips only when it switches
 * timelines - and its next auto-save would have written the stale (empty)
 * clips back over it. */

const clip = (id: string, startTime = 0): TimelineClip => ({ id, startTime, duration: 4, trackIndex: 0 } as TimelineClip)

describe('mergeExternalClips', () => {
  it('does nothing when the timeline is what the editor last loaded or saved', () => {
    const synced = [clip('a')]
    expect(mergeExternalClips(synced, synced, synced)).toBeNull()
  })

  it('takes a clip another part of the app added (Send to Timeline)', () => {
    const synced: TimelineClip[] = []
    const external = [clip('shot-1')]
    expect(mergeExternalClips([], external, synced)?.map(c => c.id)).toEqual(['shot-1'])
  })

  it("keeps the editor's own unsaved edits while taking the new clip", () => {
    const a = clip('a')
    const synced = [a]
    const local = [{ ...a, startTime: 3 }, clip('b')] // moved a, added b - not saved yet
    const external = [a, clip('shot-1', 8)] // storyboard appended a clip
    const merged = mergeExternalClips(local, external, synced)!
    expect(merged.map(c => c.id)).toEqual(['a', 'b', 'shot-1'])
    expect(merged[0].startTime).toBe(3)
  })

  it('takes a clip changed outside (Replace timeline clip) and drops one removed outside', () => {
    const a = clip('a')
    const gone = clip('gone')
    const synced = [a, gone]
    const replaced = { ...a, duration: 9 }
    const merged = mergeExternalClips(synced, [replaced], synced)!
    expect(merged.map(c => c.id)).toEqual(['a'])
    expect(merged[0].duration).toBe(9)
  })
})
