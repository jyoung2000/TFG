/**
 * Timeline structure edits shared by the editor and the project store (QA
 * pass 2026-10-01):
 *   - `removeTrackAt`: deleting a track shifts what is on later tracks (the
 *     subtitle track's own delete button skipped this, so every clip landed
 *     one track off);
 *   - `copyTimelineContent`: a duplicated timeline's clips get new ids and
 *     their links (video <-> audio pairs) point at each other, not at the
 *     original timeline's clips.
 */

import type { SubtitleClip, TimelineClip, Track } from '../../types/project'

export function removeTrackAt(clips: TimelineClip[], subtitles: SubtitleClip[], tracks: Track[], index: number) {
  const shift = <T extends { trackIndex: number }>(items: T[]) =>
    items.filter(item => item.trackIndex !== index).map(item => (item.trackIndex > index ? { ...item, trackIndex: item.trackIndex - 1 } : item))
  return { clips: shift(clips), subtitles: shift(subtitles), tracks: tracks.filter((_, i) => i !== index) }
}

export function copyTimelineContent(source: { clips: TimelineClip[]; subtitles?: SubtitleClip[] }, newId: (kind: 'clip' | 'sub') => string) {
  const ids = new Map(source.clips.map(c => [c.id, newId('clip')]))
  const clips = source.clips.map(c => {
    const links = (c.linkedClipIds ?? []).map(id => ids.get(id)).filter((id): id is string => !!id)
    const { linkedClipIds: _old, ...rest } = c
    return { ...rest, id: ids.get(c.id)!, ...(links.length ? { linkedClipIds: links } : {}) } as TimelineClip
  })
  const subtitles = source.subtitles?.map(s => ({ ...s, id: newId('sub') }))
  return { clips, subtitles }
}
