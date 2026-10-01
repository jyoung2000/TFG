/**
 * When to re-render the live pose preview (asked 2026-10-01: a live preview
 * of how the image will look as the 3D model is edited). Edits come in
 * bursts - every frame of a drag - and a render takes seconds, so:
 *
 *   - a render starts once edits have paused for `quietMs`;
 *   - only one render runs at a time;
 *   - edits during a render queue exactly one more, so the preview always
 *     ends on the latest pose without stacking renders up.
 */

export class PreviewScheduler {
  private timer: ReturnType<typeof setTimeout> | null = null
  private running = false
  private pending = false
  private disposed = false

  constructor(
    private readonly render: () => Promise<void>,
    private readonly quietMs = 1200,
  ) {}

  /** The model changed: render once things settle. */
  edited(): void {
    if (this.disposed) return
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => {
      this.timer = null
      void this.now()
    }, this.quietMs)
  }

  /** Render now (or right after the render in flight). */
  async now(): Promise<void> {
    if (this.disposed) return
    if (this.running) {
      this.pending = true
      return
    }
    this.running = true
    try {
      await this.render()
    } finally {
      this.running = false
    }
    if (this.pending && !this.disposed) {
      this.pending = false
      await this.now()
    }
  }

  get busy(): boolean {
    return this.running
  }

  dispose(): void {
    this.disposed = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
  }
}
