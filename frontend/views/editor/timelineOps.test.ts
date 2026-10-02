import { describe, expect, it } from 'vitest'
import { copyTimelineContent, removeTrackAt } from './timelineOps'
import type { SubtitleClip, TimelineClip, Track } from '../../types/project'

/* QA pass 2026-10-01 (video editor).
 * - Deleting a subtitle track (its own trash button) removed the track but
 *   never shifted the clips and subtitles on the tracks after it, so every
 *   clip landed one track off.
 * - Duplicating a timeline gave the clips new ids but kept their old
 *   linkedClipIds, so a linked video/audio pair in the copy pointed at the
 *   original timeline's clips. */

const clip = (id: string, trackIndex: number, linkedClipIds?: string[]) => ({ id, trackIndex, linkedClipIds } as TimelineClip)
const sub = (id: string, trackIndex: number) => ({ id, trackIndex } as SubtitleClip)
const track = (name: string) => ({ id: name, name } as Track)

describe('removeTrackAt', () => {
  it('drops the track and what is on it, and moves everything after it up one', () => {
    const result = removeTrackAt(
      [clip('v1', 1), clip('v2', 2)],
      [sub('s0', 0), sub('s2', 2)],
      [track('Subs'), track('V1'), track('V2')],
      0,
    )
    expect(result.tracks.map(t => t.name)).toEqual(['V1', 'V2'])
    expect(result.clips.map(c => [c.id, c.trackIndex])).toEqual([['v1', 0], ['v2', 1]])
    expect(result.subtitles.map(s => [s.id, s.trackIndex])).toEqual([['s2', 1]])
  })
})

describe('copyTimelineContent', () => {
  it('gives the copies new ids and links them to each other, not to the original', () => {
    let n = 0
    const copy = copyTimelineContent({ clips: [clip('v', 0, ['a']), clip('a', 1, ['v'])], subtitles: [sub('s', 2)] }, () => `new-${++n}`)
    const [v, a] = copy.clips
    expect(v.id).not.toBe('v')
    expect(v.linkedClipIds).toEqual([a.id])
    expect(a.linkedClipIds).toEqual([v.id])
    expect(copy.subtitles?.[0].id).not.toBe('s')
  })

  it('drops a link to a clip that is not in the copy', () => {
    const copy = copyTimelineContent({ clips: [clip('v', 0, ['elsewhere'])] }, () => 'x')
    expect(copy.clips[0].linkedClipIds).toBeUndefined()
  })
})
