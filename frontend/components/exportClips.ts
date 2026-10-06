/**
 * The clips a video export renders (QA pass 2026-10-01): the export used each
 * clip's original media even when the timeline plays another take, and
 * ignored track mute and solo, so the exported film differed from what the
 * editor played. This mirrors the preview: the active take's media, and
 * audio silenced on muted tracks - or on every non-soloed audio track while
 * any track is soloed.
 */

import type { TimelineClip, Track } from '../types/project'

export interface ExportClip {
  url: string
  type: string
  startTime: number
  duration: number
  trimStart: number
  speed: number
  reversed: boolean
  flipH: boolean
  flipV: boolean
  opacity: number
  trackIndex: number
  muted: boolean
  volume: number
}

function clipUrl(clip: TimelineClip): string {
  const takes = clip.asset?.takes
  if (takes?.length && clip.takeIndex !== undefined) return takes[Math.max(0, Math.min(clip.takeIndex, takes.length - 1))].url
  return clip.asset?.url || clip.importedUrl || ''
}

export function exportClipsFor(clips: TimelineClip[], tracks: Track[]): ExportClip[] {
  const anySolo = tracks.some(t => t.kind === 'audio' && t.solo)
  return clips
    .filter(c => c.type === 'video' || c.type === 'image' || c.type === 'audio')
    .filter(c => tracks[c.trackIndex]?.enabled !== false)
    .map(c => {
      const track = tracks[c.trackIndex]
      const silencedBySolo = anySolo && track?.kind === 'audio' && !track.solo
      return {
        url: clipUrl(c),
        type: c.type as string,
        startTime: c.startTime,
        duration: c.duration,
        trimStart: c.trimStart,
        speed: c.speed || 1,
        reversed: c.reversed || false,
        flipH: c.flipH || false,
        flipV: c.flipV || false,
        opacity: c.opacity ?? 100,
        trackIndex: c.trackIndex,
        muted: !!(c.muted || track?.muted || silencedBySolo),
        volume: c.volume ?? 1,
      }
    })
}
