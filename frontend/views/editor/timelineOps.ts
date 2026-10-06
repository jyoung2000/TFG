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

/**
 * Delete the selected clips as the Delete key does (QA 2026-10-01: Clip >
 * Delete ignored locked tracks and left links to deleted clips): clips on
 * locked tracks stay; a linked partner goes too only when it is selected as
 * well; links to deleted clips are dropped.
 */
export function deleteClips(clips: TimelineClip[], tracks: Track[], selected: Set<string>): TimelineClip[] {
  const deleteIds = new Set<string>()
  for (const id of selected) {
    const clip = clips.find(c => c.id === id)
    if (!clip || tracks[clip.trackIndex]?.locked) continue
    deleteIds.add(id)
    if (clip.linkedClipIds?.every(lid => selected.has(lid))) clip.linkedClipIds.forEach(lid => deleteIds.add(lid))
  }
  return clips.filter(c => !deleteIds.has(c.id)).map(c => {
    if (!c.linkedClipIds) return c
    const remaining = c.linkedClipIds.filter(lid => !deleteIds.has(lid))
    return { ...c, linkedClipIds: remaining.length ? remaining : undefined }
  })
}

/** The clips a Clip-menu command acts on: every selected clip, else the focused one. */
export function clipTargets(focused: TimelineClip | null | undefined, selected: Set<string>, clips: TimelineClip[]): TimelineClip[] {
  if (selected.size > 0) return clips.filter(c => selected.has(c.id))
  return focused ? [focused] : []
}

const trackKind = (tracks: Track[], index: number) => (tracks[index]?.kind === 'audio' ? 'audio' : 'video')

/**
 * The clip "Link Audio" pairs `clip` with: the same media, starting at the
 * same time, on a track of the other kind (video <-> audio); null if none or
 * if `clip` is already linked.
 */
export function audioPartner(clip: TimelineClip, clips: TimelineClip[], tracks: Track[]): TimelineClip | null {
  if (clip.linkedClipIds?.length) return null
  const kind = trackKind(tracks, clip.trackIndex)
  return clips.find(c =>
    c.id !== clip.id &&
    !c.linkedClipIds?.length &&
    c.assetId === clip.assetId &&
    Math.abs(c.startTime - clip.startTime) < 0.05 &&
    trackKind(tracks, c.trackIndex) !== kind,
  ) ?? null
}
