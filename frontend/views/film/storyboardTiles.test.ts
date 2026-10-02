import { describe, expect, it } from 'vitest'
import { aiTileLabel, referenceSource } from './storyboardTiles'
import type { FilmShot } from '../../types/film'

/* Asked 2026-10-01: the storyboard shows the AI remake of each scene under
 * the reference image it remakes, so the two can be compared. */

const shot = (over: Partial<FilmShot>): FilmShot => ({ capture_path: '', blockout_path: '', reference_path: '', source_ref: null, ...over } as FilmShot)

describe('referenceSource', () => {
  it("an image shot's reference is the photo the job copied in", () => {
    expect(referenceSource(shot({ reference_path: 'captures/s1-reference.png' }))).toEqual({ kind: 'project', path: 'captures/s1-reference.png' })
  })

  it("a video shot's reference is its frame of the source clip", () => {
    const ref = { kind: 'video_analysis' as const, analysis_id: 'va-1', analysis_shot_id: 'shot-2', source_path: '', start: 0, end: 2 }
    expect(referenceSource(shot({ source_ref: ref }))).toEqual({ kind: 'analysis', analysisId: 'va-1', shotId: 'shot-2' })
  })

  it('a shot made from scratch has none (one picture, as before)', () => {
    expect(referenceSource(shot({ capture_path: 'captures/c.png' }))).toBeNull()
  })
})

describe('aiTileLabel', () => {
  it('names what the lower picture is', () => {
    expect(aiTileLabel('version', shot({}))).toBe('AI scene')
    expect(aiTileLabel('capture', shot({ reference_path: 'captures/r.png' }))).toBe('AI image')
    expect(aiTileLabel('frame', shot({}))).toBe('AI frame')
    expect(aiTileLabel('capture', shot({ source_ref: { kind: 'video_analysis', analysis_id: 'a', analysis_shot_id: 'b', source_path: '', start: 0, end: 1 } }))).toBe('3D capture')
    expect(aiTileLabel('blockout', shot({}))).toBe('3D blockout')
    expect(aiTileLabel(null, shot({}))).toBe('Not made yet')
  })
})
