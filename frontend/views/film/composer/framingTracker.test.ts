import { describe, expect, it } from 'vitest'
import { FramingTracker } from './framingTracker'
import type { ShotFraming } from '../../../types/film'

/* QA pass 2026-10-01 ("every feature should be tested and work as intended").
 * The composer re-applied the shot's framing every time it loaded a scene
 * (opening the composer, undo, redo): in preset mode that re-solves the camera
 * and empties its keyframes, so saved "Key camera" / move-library keyframes
 * were wiped on reopen and by any undo. And framing edits (shot size, angle,
 * FOV...) never counted as edits: not saved on close, not undoable. */

const framing = (over: Partial<ShotFraming> = {}): ShotFraming => ({
  shot_size: 'medium', camera_angle: 'front', camera_elevation: 'eye', composition: 'center',
  fov_deg: 40, ots_foreground_id: null, ots_subject_id: null, ots_shoulder: 'left', camera_mode: 'preset', ...over,
} as ShotFraming)

describe('FramingTracker', () => {
  it('a scene loaded with its framing is not re-framed (its camera and keyframes stand)', () => {
    const tracker = new FramingTracker()
    tracker.loaded(framing())
    expect(tracker.changed(framing())).toBe(false)
  })

  it('a framing the user picks is a change - once', () => {
    const tracker = new FramingTracker()
    tracker.loaded(framing())
    expect(tracker.changed(framing({ shot_size: 'closeup' }))).toBe(true)
    expect(tracker.changed(framing({ shot_size: 'closeup' }))).toBe(false)
  })

  it('undo restores a framing without counting it as a new edit', () => {
    const tracker = new FramingTracker()
    tracker.loaded(framing())
    tracker.changed(framing({ fov_deg: 55 }))
    tracker.loaded(framing()) // the undone snapshot's framing
    expect(tracker.changed(framing())).toBe(false)
  })

  it('compares framings by value, not by object or key order', () => {
    const tracker = new FramingTracker()
    tracker.loaded(framing())
    const reordered = Object.fromEntries(Object.entries(framing()).reverse()) as unknown as ShotFraming
    expect(tracker.changed(reordered)).toBe(false)
  })
})
