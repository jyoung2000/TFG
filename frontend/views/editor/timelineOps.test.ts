import { describe, expect, it } from 'vitest'
import { audioPartner, clipTargets, copyTimelineContent, deleteClips, removeTrackAt } from './timelineOps'
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

/* QA pass 2026-10-01 (video editor menus):
 * - Clip > Delete ignored locked tracks and left links to deleted clips (the
 *   Delete key did both right); both now use deleteClips.
 * - Flip / Reverse / Speed / Mute acted on one clip with several selected.
 * - "Link Audio" did nothing on an unlinked clip. */

const placed = (id: string, trackIndex: number, extra: Partial<TimelineClip> = {}) => ({ id, trackIndex, startTime: 0, assetId: 'asset-1', ...extra } as TimelineClip)
const kinds = [{ id: 'v', name: 'V1', kind: 'video' }, { id: 'a', name: 'A1', kind: 'audio' }, { id: 'l', name: 'V2', kind: 'video', locked: true }] as Track[]

describe('deleteClips', () => {
  it('skips clips on locked tracks and drops links to deleted clips', () => {
    const clips = [placed('v', 0, { linkedClipIds: ['a'] }), placed('a', 1, { linkedClipIds: ['v'] }), placed('locked', 2)]
    const next = deleteClips(clips, kinds, new Set(['a', 'locked']))
    expect(next.map(c => c.id)).toEqual(['v', 'locked'])
    expect(next[0].linkedClipIds).toBeUndefined()
  })

  it('deletes the linked partner too when both are selected', () => {
    const clips = [placed('v', 0, { linkedClipIds: ['a'] }), placed('a', 1, { linkedClipIds: ['v'] })]
    expect(deleteClips(clips, kinds, new Set(['v', 'a']))).toEqual([])
  })
})

describe('clipTargets', () => {
  it('acts on every selected clip, else the focused one', () => {
    const clips = [placed('x', 0), placed('y', 0), placed('z', 0)]
    expect(clipTargets(clips[0], new Set(['x', 'z']), clips).map(c => c.id)).toEqual(['x', 'z'])
    expect(clipTargets(clips[1], new Set(), clips).map(c => c.id)).toEqual(['y'])
    expect(clipTargets(null, new Set(), clips)).toEqual([])
  })
})

describe('audioPartner', () => {
  it('finds the same media starting at the same time on a track of the other kind', () => {
    const clips = [placed('v', 0), placed('a', 1), placed('later', 1, { startTime: 5 })]
    expect(audioPartner(clips[0], clips, kinds)?.id).toBe('a')
    expect(audioPartner(clips[1], clips, kinds)?.id).toBe('v')
  })

  it('has none for different media or an already-linked clip', () => {
    const clips = [placed('v', 0), placed('other', 1, { assetId: 'asset-2' })]
    expect(audioPartner(clips[0], clips, kinds)).toBeNull()
    const linked = [placed('v', 0, { linkedClipIds: ['x'] }), placed('a', 1)]
    expect(audioPartner(linked[0], linked, kinds)).toBeNull()
  })
})
