import { describe, expect, it } from 'vitest'
import { withLiveRenders } from './filmUndo'
import type { FilmProject, FilmShot } from '../types/film'

/* QA pass 2026-10-01. Storyboard undo wrote a whole older snapshot back to
 * the project, versions and status included: edit a title, render the shot,
 * approve it, then undo the title - the new takes vanished from the shot and
 * the approval was lost. Undo restores what the user authored, not renders. */

const shot = (id: string, over: Partial<FilmShot> = {}): FilmShot => ({ id, title: id, versions: [], current_version: null, status: 'draft', updated_at: 1, ...over } as unknown as FilmShot)
const project = (shots: FilmShot[]): FilmProject => ({ id: 'p', scenes: [{ id: 's', shots }] } as unknown as FilmProject)
const take = (number: number) => ({ number, status: 'complete', output_path: `v${number}.mp4` })

describe('withLiveRenders', () => {
  it("restores the snapshot's text but keeps the renders and approval made since", () => {
    const snapshot = project([shot('a', { title: 'Old title' })])
    const current = project([shot('a', { title: 'New title', versions: [take(1), take(2)] as never, current_version: 2, status: 'approved' })])
    const restored = withLiveRenders(snapshot, current).scenes[0].shots[0]
    expect(restored.title).toBe('Old title')
    expect(restored.versions.map(v => v.number)).toEqual([1, 2])
    expect(restored.current_version).toBe(2)
    expect(restored.status).toBe('approved')
  })

  it('a shot the undo brings back (deleted since) keeps its own renders', () => {
    const snapshot = project([shot('a'), shot('gone', { versions: [take(1)] as never, current_version: 1 })])
    const current = project([shot('a')])
    const restored = withLiveRenders(snapshot, current).scenes[0].shots
    expect(restored.map(s => s.id)).toEqual(['a', 'gone'])
    expect(restored[1].versions).toHaveLength(1)
  })

  it('leaves the snapshot itself untouched', () => {
    const snapshot = project([shot('a')])
    withLiveRenders(snapshot, project([shot('a', { status: 'approved' })]))
    expect(snapshot.scenes[0].shots[0].status).toBe('draft')
  })
})
