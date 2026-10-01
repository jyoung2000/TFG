/**
 * What the composer says while a body part is dragged (asked 2026-10-01:
 * "give the 3d editor draggable arrows to easier edit 3d models and tell
 * where your dragging"): the part, how far it has moved in the figure's own
 * directions (up, forward, to its left), and why it stopped if it did.
 */

import type { Contact } from './anatomy'
import type { JointName } from './figure'

/** The part a joint's handle moves: dragging the elbow swings the forearm. */
export const PART_NAMES: Record<JointName, string> = {
  torso: 'Torso',
  neck: 'Neck',
  head: 'Head',
  l_arm: 'Left upper arm',
  l_elbow: 'Left forearm',
  l_wrist: 'Left hand',
  r_arm: 'Right upper arm',
  r_elbow: 'Right forearm',
  r_wrist: 'Right hand',
  l_leg: 'Left thigh',
  l_knee: 'Left shin',
  l_ankle: 'Left foot',
  r_leg: 'Right thigh',
  r_knee: 'Right shin',
  r_ankle: 'Right foot',
}

const JOINT_WORDS: Partial<Record<JointName, string>> = {
  l_elbow: 'elbow', r_elbow: 'elbow', l_knee: 'knee', r_knee: 'knee',
  l_wrist: 'wrist', r_wrist: 'wrist', l_ankle: 'ankle', r_ankle: 'ankle',
  torso: 'spine', neck: 'neck', head: 'head',
}

export interface DragReadout {
  text: string
  tone: 'moving' | 'blocked' | 'hint'
}

/** Below this a direction is not worth naming (metres). */
const NOTICE = 0.005

const cm = (metres: number) => `${Math.round(Math.abs(metres) * 100)} cm`

/**
 * `moved`: the part's offset from where the drag began, in the figure's own
 * axes (+x its left, +y up, +z forward), metres. `reached`: false when the
 * limb is at full stretch short of the cursor.
 */
export function dragReadout(joint: JointName, moved: { x: number; y: number; z: number } | null, blocked: Contact | null, limited: JointName[], reached: boolean): DragReadout {
  const part = PART_NAMES[joint]
  if (blocked) return { text: `${part} · stopped: the ${blocked.a} would go through the ${blocked.b}`, tone: 'blocked' }
  const bits: string[] = []
  if (!moved) {
    // Turned on its rings: only a limit is worth saying.
    const limit = limited.map(name => JOINT_WORDS[name]).find(Boolean)
    return limit ? { text: `${part} · the ${limit} is at its limit`, tone: 'blocked' } : { text: part, tone: 'moving' }
  }
  if (Math.abs(moved.y) >= NOTICE) bits.push(`${cm(moved.y)} ${moved.y > 0 ? 'up' : 'down'}`)
  if (Math.abs(moved.z) >= NOTICE) bits.push(`${cm(moved.z)} ${moved.z > 0 ? 'forward' : 'back'}`)
  if (Math.abs(moved.x) >= NOTICE) bits.push(`${cm(moved.x)} to the figure's ${moved.x > 0 ? 'left' : 'right'}`)
  if (!bits.length) bits.push('not moved')
  const limit = limited.map(name => JOINT_WORDS[name]).find(Boolean)
  if (limit) return { text: [part, ...bits, `the ${limit} is at its limit`].join(' · '), tone: 'blocked' }
  if (!reached) {
    const limb = joint.endsWith('ankle') || joint.endsWith('knee') || joint.endsWith('leg') ? 'leg' : 'arm'
    return { text: [part, ...bits, `the ${limb} is at full stretch`].join(' · '), tone: 'blocked' }
  }
  return { text: [part, ...bits].join(' · '), tone: 'moving' }
}

const AXIS_WORDS: Record<string, string> = { X: 'left / right', Y: 'up / down', Z: 'forward / back' }
const AXIS_COLOURS: Record<string, string> = { X: 'red', Y: 'green', Z: 'blue' }

/** What hovering a move-gizmo handle (an arrow, a plane square, the centre) will do. */
export function axisHint(joint: JointName, axis: string | null): string | null {
  if (!axis) return null
  const part = PART_NAMES[joint]
  if (axis.length === 1) return `${part} · drag the ${AXIS_COLOURS[axis]} arrow: ${AXIS_WORDS[axis]}`
  if (axis === 'XYZ' || axis === 'XYZE' || axis === 'E') return `${part} · drag the centre: move it freely`
  const words = ['Y', 'Z', 'X'].filter(a => axis.includes(a)).map(a => AXIS_WORDS[a])
  return `${part} · drag the square: ${words.join(' and ')}`
}
