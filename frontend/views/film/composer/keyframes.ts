/**
 * Keyframe utilities: angle-aware sampling, put-or-replace, validation.
 *
 * Adapted from mangerik/Blocking-Room `src/model.js` (MIT; see
 * docs/INTEGRATED_UPSTREAMS.md): `sample()`'s shortest-arc interpolation of
 * rotations, `putKey()`'s 0.1 s snapping/replacement, and `validateProject()`'s
 * finite/range/unique-time rules — reshaped onto the composer's
 * `CompositionKeyframe` (position/rotation/scale + fov) instead of actor rows.
 */

import type { CompositionKeyframe, Vec3 } from '../../../types/film'

const TAU = Math.PI * 2

/** Shortest-arc angle interpolation (radians). */
export function lerpAngle(a: number, b: number, t: number): number {
  let delta = (b - a) % TAU
  if (delta > Math.PI) delta -= TAU
  if (delta < -Math.PI) delta += TAU
  return a + delta * t
}

function lerpVec(a: Vec3, b: Vec3, t: number): Vec3 {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

/**
 * Sample a keyframe track at `time`: positions/scale lerp, rotations take the
 * shortest arc per axis, fov lerps when both ends have one. Holds the first /
 * last keyframe outside the track.
 */
export function sampleKeyframes(keyframes: CompositionKeyframe[], time: number): { position: Vec3; rotation: Vec3; scale: Vec3; fov: number | null } | null {
  if (keyframes.length === 0) return null
  const sorted = [...keyframes].sort((a, b) => a.time - b.time)
  const first = sorted[0]
  const last = sorted[sorted.length - 1]
  if (time <= first.time) return { ...first.transform, fov: first.fov ?? null }
  if (time >= last.time) return { ...last.transform, fov: last.fov ?? null }
  const index = sorted.findIndex(k => k.time > time)
  const a = sorted[index - 1]
  const b = sorted[index]
  const span = b.time - a.time
  const t = span > 0 ? (time - a.time) / span : 0
  return {
    position: lerpVec(a.transform.position, b.transform.position, t),
    rotation: [
      lerpAngle(a.transform.rotation[0], b.transform.rotation[0], t),
      lerpAngle(a.transform.rotation[1], b.transform.rotation[1], t),
      lerpAngle(a.transform.rotation[2], b.transform.rotation[2], t),
    ],
    scale: lerpVec(a.transform.scale, b.transform.scale, t),
    fov: a.fov != null && b.fov != null ? a.fov + (b.fov - a.fov) * t : (b.fov ?? a.fov ?? null),
  }
}

/** Snap a time to the 0.1 s grid the timeline strip shows. */
export function snapTime(time: number): number {
  return Math.round(Math.max(0, time) * 10) / 10
}

/** Insert a keyframe, replacing one within 0.05 s of the same time; returns a sorted copy. */
export function putKeyframe(keyframes: CompositionKeyframe[], keyframe: CompositionKeyframe): CompositionKeyframe[] {
  const snapped = { ...keyframe, time: snapTime(keyframe.time) }
  const rest = keyframes.filter(k => Math.abs(k.time - snapped.time) >= 0.05)
  return [...rest, snapped].sort((a, b) => a.time - b.time)
}

export interface KeyframeIssue {
  keyframeId: string
  message: string
}

const LIMIT = 1000
const MAX_KEYFRAMES = 2400

function finite(value: number, min: number, max: number): boolean {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}

/**
 * Every keyframe must lie inside the shot, carry finite in-range numbers, and
 * own a unique time — the rules a saved composition is checked against
 * before it reaches the backend or the preview.
 */
export function validateKeyframes(keyframes: CompositionKeyframe[], durationSeconds: number): KeyframeIssue[] {
  const issues: KeyframeIssue[] = []
  if (keyframes.length > MAX_KEYFRAMES) issues.push({ keyframeId: '', message: `More than ${MAX_KEYFRAMES} keyframes` })
  const seen = new Map<number, string>()
  for (const keyframe of keyframes) {
    if (!finite(keyframe.time, 0, Math.max(0, durationSeconds))) {
      issues.push({ keyframeId: keyframe.id, message: `Time ${keyframe.time} is outside the ${durationSeconds.toFixed(1)}s shot` })
    }
    const { position, rotation, scale } = keyframe.transform
    if (!position.every(v => finite(v, -LIMIT, LIMIT)) || !rotation.every(v => finite(v, -LIMIT, LIMIT)) || !scale.every(v => finite(v, 0.001, LIMIT))) {
      issues.push({ keyframeId: keyframe.id, message: 'Transform has a non-finite or out-of-range value' })
    }
    if (keyframe.fov != null && !finite(keyframe.fov, 1, 179)) {
      issues.push({ keyframeId: keyframe.id, message: `Field of view ${keyframe.fov} is not between 1° and 179°` })
    }
    const key = Math.round(keyframe.time * 1000)
    const other = seen.get(key)
    if (other !== undefined) issues.push({ keyframeId: keyframe.id, message: `Same time as keyframe ${other}` })
    else seen.set(key, keyframe.id)
  }
  return issues
}

/** Meters travelled along a keyframed position track up to `time`, plus the current speed (m/s). */
export function travelAlong(keyframes: CompositionKeyframe[], time: number): { distance: number; speed: number } {
  const sorted = [...keyframes].sort((a, b) => a.time - b.time)
  let distance = 0
  let speed = 0
  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1]
    const b = sorted[i]
    const length = Math.hypot(
      b.transform.position[0] - a.transform.position[0],
      b.transform.position[2] - a.transform.position[2],
    )
    const duration = b.time - a.time
    if (duration <= 0) continue
    const fraction = Math.max(0, Math.min(1, (time - a.time) / duration))
    distance += length * fraction
    if (time > a.time && time < b.time) speed = length / duration
  }
  return { distance, speed }
}
