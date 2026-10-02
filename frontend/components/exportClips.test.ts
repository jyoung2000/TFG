import { describe, expect, it } from 'vitest'
import { exportClipsFor } from './exportClips'
import type { TimelineClip, Track } from '../types/project'

/* QA pass 2026-10-01 (video editor export). The export used each clip's
 * original media (asset.url) even when the timeline plays another take, and
 * ignored track mute and solo - so the exported film differed from what the
 * editor played. */

const asset = { id: 'a', url: 'file:///take0.mp4', takes: [{ url: 'file:///take0.mp4' }, { url: 'file:///take1.mp4' }] }
const clip = (over: Partial<TimelineClip>): TimelineClip => ({ id: 'c', type: 'video', startTime: 0, duration: 4, trimStart: 0, trackIndex: 0, asset, ...over } as unknown as TimelineClip)
const tracks = (over: Partial<Track>[] = []) => [{ kind: 'video' }, { kind: 'audio' }, { kind: 'audio' }].map((t, i) => ({ id: `t${i}`, name: `T${i}`, ...t, ...(over[i] ?? {}) })) as Track[]

describe('exportClipsFor', () => {
  it("exports the take the timeline plays, not the asset's first", () => {
    expect(exportClipsFor([clip({ takeIndex: 1 })], tracks())[0].url).toBe('file:///take1.mp4')
    expect(exportClipsFor([clip({})], tracks())[0].url).toBe('file:///take0.mp4')
  })

  it('a muted track exports silent', () => {
    const out = exportClipsFor([clip({ id: 'x', type: 'audio', trackIndex: 1 })], tracks([{}, { muted: true }]))
    expect(out[0].muted).toBe(true)
  })

  it('with a track soloed, only soloed audio tracks are heard', () => {
    const out = exportClipsFor(
      [clip({ id: 'x', type: 'audio', trackIndex: 1 }), clip({ id: 'y', type: 'audio', trackIndex: 2 })],
      tracks([{}, { solo: true }, {}]),
    )
    expect(out.map(c => c.muted)).toEqual([false, true])
  })

  it('leaves out clips on disabled tracks and non-media clips', () => {
    const out = exportClipsFor([clip({ id: 'off', trackIndex: 0 }), clip({ id: 'text', type: 'text' as never })], tracks([{ enabled: false }]))
    expect(out).toEqual([])
  })
})
