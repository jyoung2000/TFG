/**
 * Keeping the video editor's working copy of a timeline in step with changes
 * made elsewhere (asked 2026-10-01: ensure the video editor works). The
 * editor edits its own copy of the clips and auto-saves it; the storyboard's
 * Send to Timeline / Replace timeline clip write the same timeline. Live in
 * r44 a sent clip showed in the timeline list but never in the editor, and
 * the editor's next save would have written its stale copy back over it.
 */

import type { TimelineClip } from '../../types/project'

/**
 * The editor's clips with the outside changes applied, or null when there
 * are none. `lastSynced` is the clips array the editor last loaded or saved:
 * the timeline still holding that exact array means nothing changed outside.
 * Outside changes win for clips the outside touched (added, replaced,
 * removed); the editor's own unsaved edits win for everything else.
 */
export function mergeExternalClips(local: TimelineClip[], external: TimelineClip[], lastSynced: TimelineClip[]): TimelineClip[] | null {
  if (external === lastSynced) return null
  const before = new Map(lastSynced.map(c => [c.id, c]))
  const after = new Map(external.map(c => [c.id, c]))
  const merged: TimelineClip[] = []
  const seen = new Set<string>()
  for (const clip of local) {
    seen.add(clip.id)
    const was = before.get(clip.id)
    const now = after.get(clip.id)
    if (was && !now) continue // removed outside
    merged.push(now && was && now !== was ? now : clip) // replaced outside, else the editor's
  }
  for (const clip of external) {
    if (!seen.has(clip.id) && !before.has(clip.id)) merged.push(clip) // added outside
  }
  return merged
}
