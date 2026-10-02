/**
 * Which framing the 3D scene already shows (QA pass 2026-10-01). The
 * composer re-applied the shot's framing every time it loaded a scene -
 * opening the composer, undo, redo - and in preset mode that re-solves the
 * camera and empties its keyframes, so saved camera keyframes were wiped on
 * reopen and by any undo. Framing edits also never counted as edits (not
 * saved on close, not undoable).
 *
 * `loaded` records the framing a scene came with; `changed` is true only for
 * a framing the scene does not show yet - a user's pick, to apply and record.
 */

import type { ShotFraming } from '../../../types/film'

function key(framing: ShotFraming): string {
  return JSON.stringify(Object.keys(framing).sort().map(k => [k, (framing as unknown as Record<string, unknown>)[k]]))
}

export class FramingTracker {
  private shown: string | null = null

  /** The scene was loaded (or restored) with this framing already in place. */
  loaded(framing: ShotFraming): void {
    this.shown = key(framing)
  }

  /** True when `framing` is new to the scene (and remembers it). */
  changed(framing: ShotFraming): boolean {
    const next = key(framing)
    if (next === this.shown) return false
    this.shown = next
    return true
  }
}
