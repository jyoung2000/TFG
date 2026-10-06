// Progress shown while a render reports no step counts of its own.
//
// F-054 (round 4, RTX 4070): the old fallback was a straight line to 95% over
// a hardcoded 45 s. Measured Fast clips took 121–699 s, so the bar hit 95% in
// under a minute and then sat still for the rest of the render. This curve
// keeps moving, never shows less than the backend reported, and never claims
// to be finished.

/** Seconds a local render usually takes, from the round-4 measurements
 *  (Fast 540p · 6 s: 121 s warm / 174 s cold; Balanced 720p · 6 s: 232 s). */
export function expectedInferenceSeconds(model: string): number {
  return model === 'pro' ? 240 : 150
}

const START = 15
const CEILING = 94

/** 15% → 94% along 1 − e^(−t/T): about 65% at the expected time, still rising
 *  after it, and never above what only completion should show. */
export function interpolateInferenceProgress(elapsedSeconds: number, expectedSeconds: number, reported: number): number {
  const t = Math.max(0, elapsedSeconds) / Math.max(1, expectedSeconds)
  const curve = START + (CEILING - START) * (1 - Math.exp(-t))
  return Math.max(Math.min(reported, CEILING), Math.min(CEILING, Math.floor(curve)))
}

/** Say so once the render outlives its estimate, instead of looking stuck. */
export function inferenceStatusMessage(elapsedSeconds: number, expectedSeconds: number, base: string): string {
  return elapsedSeconds > expectedSeconds ? `${base.replace(/\.\.\.$/, '')} — taking longer than usual, still working...` : base
}
