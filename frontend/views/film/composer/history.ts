/**
 * Bounded snapshot undo for the composer.
 *
 * Adapted from mangerik/Blocking-Room `src/history.js` (MIT; see
 * docs/INTEGRATED_UPSTREAMS.md): serialized snapshots, a limit, and
 * begin/end grouping so a gizmo drag is one undo step. Selection, playhead
 * and orbit-camera navigation are not edits and never enter the history.
 */

export class CompositionHistory<T> {
  private entries: string[]
  private index = 0
  private grouping = false

  constructor(initial: T, private readonly limit = 100) {
    this.entries = [JSON.stringify(initial)]
  }

  get canUndo(): boolean {
    return this.index > 0
  }

  get canRedo(): boolean {
    return this.index < this.entries.length - 1
  }

  get length(): number {
    return this.entries.length
  }

  /** Start a group: commits are ignored until `end()` so a drag is one step. */
  begin(): void {
    this.grouping = true
  }

  commit(state: T): void {
    if (this.grouping) return
    const snapshot = JSON.stringify(state)
    if (snapshot === this.entries[this.index]) return
    this.entries.splice(this.index + 1)
    this.entries.push(snapshot)
    if (this.entries.length > this.limit + 1) this.entries.shift()
    this.index = this.entries.length - 1
  }

  end(state: T): void {
    this.grouping = false
    this.commit(state)
  }

  undo(): T | null {
    return this.canUndo ? (JSON.parse(this.entries[--this.index]) as T) : null
  }

  redo(): T | null {
    return this.canRedo ? (JSON.parse(this.entries[++this.index]) as T) : null
  }
}
