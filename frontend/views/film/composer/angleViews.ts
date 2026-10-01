/**
 * Camera angles around a figure, for multi-angle character shots (asked
 * 2026-10-01: shots of high enough quality and variety to train a LoRA).
 *
 * A view is a yaw around the figure (0 = in front of them, 90 = at their
 * left side, 180 = behind), an elevation (positive = above, looking down)
 * and a framing. `angleCamera` puts the shot camera at the distance where
 * that framing fills the frame, aimed at the matching part of the body.
 */

import type { Vec3 } from '../../../types/film'

export type AngleSize = 'full' | 'medium' | 'closeup'

export interface AngleView {
  name: string
  label: string
  yawDeg: number
  elevationDeg: number
  size: AngleSize
  /** How the view reads in a prompt. */
  words: string
}

/** Frame height (× figure height) and aim point (× figure height) per framing. */
const FRAMING: Record<AngleSize, { frame: number; aim: number; words: string }> = {
  full: { frame: 1.18, aim: 0.5, words: 'full body shot, head to toe' },
  medium: { frame: 0.6, aim: 0.72, words: 'medium shot from the waist up' },
  closeup: { frame: 0.3, aim: 0.88, words: 'close-up portrait of the head and shoulders' },
}

function view(name: string, label: string, yawDeg: number, size: AngleSize, side: string, elevationDeg = 0, height = ''): AngleView {
  return { name, label, yawDeg, elevationDeg, size, words: [side, FRAMING[size].words, height].filter(Boolean).join(', ') }
}

/** A LoRA-ready spread: every side at full length, the main sides closer, and two heights. */
export const LORA_ANGLES: AngleView[] = [
  view('full-front', 'Front', 0, 'full', 'seen from the front, facing the camera'),
  view('full-34-left', '¾ left', 45, 'full', 'seen from a three-quarter angle from their left'),
  view('full-profile-left', 'Profile left', 90, 'full', 'seen in profile from their left side'),
  view('full-back-34-left', 'Back ¾ left', 135, 'full', 'seen from behind at a three-quarter angle from their left'),
  view('full-back', 'Back', 180, 'full', 'seen from behind, their back to the camera'),
  view('full-back-34-right', 'Back ¾ right', -135, 'full', 'seen from behind at a three-quarter angle from their right'),
  view('full-profile-right', 'Profile right', -90, 'full', 'seen in profile from their right side'),
  view('full-34-right', '¾ right', -45, 'full', 'seen from a three-quarter angle from their right'),
  view('medium-front', 'Medium front', 0, 'medium', 'seen from the front, facing the camera'),
  view('medium-34-left', 'Medium ¾ left', 45, 'medium', 'seen from a three-quarter angle from their left'),
  view('medium-34-right', 'Medium ¾ right', -45, 'medium', 'seen from a three-quarter angle from their right'),
  view('closeup-front', 'Close-up front', 0, 'closeup', 'seen from the front, facing the camera'),
  view('closeup-34-left', 'Close-up ¾ left', 45, 'closeup', 'seen from a three-quarter angle from their left'),
  view('closeup-profile-left', 'Close-up profile', 90, 'closeup', 'seen in profile from their left side'),
  view('closeup-34-right', 'Close-up ¾ right', -45, 'closeup', 'seen from a three-quarter angle from their right'),
  view('full-high', 'High angle', 0, 'full', 'seen from the front', 30, 'high angle looking down'),
  view('full-low', 'Low angle', 0, 'full', 'seen from the front', -15, 'low angle looking up'),
]

/**
 * Where the shot camera goes for `view` of a figure standing at `position`,
 * turned `yaw` radians (the figure faces local +Z), `height` metres tall, seen
 * through a camera with a `vfovDeg` vertical field of view.
 */
export function angleCamera(
  figure: { position: Vec3; yaw: number; height: number },
  view: AngleView,
  vfovDeg: number,
): { position: Vec3; target: Vec3 } {
  const framing = FRAMING[view.size]
  const target: Vec3 = [figure.position[0], figure.position[1] + figure.height * framing.aim, figure.position[2]]
  const distance = (figure.height * framing.frame) / 2 / Math.tan((vfovDeg * Math.PI) / 360)
  const around = figure.yaw + (view.yawDeg * Math.PI) / 180
  const up = (view.elevationDeg * Math.PI) / 180
  const flat = distance * Math.cos(up)
  return {
    position: [target[0] + Math.sin(around) * flat, target[1] + Math.sin(up) * distance, target[2] + Math.cos(around) * flat],
    target,
  }
}
