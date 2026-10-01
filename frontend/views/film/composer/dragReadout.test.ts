import { describe, expect, it } from 'vitest'
import { axisHint, dragReadout } from './dragReadout'

/* Asked 2026-10-01: "give the 3d editor draggable arrows to easier edit 3d
 * models and tell where your dragging". While a body part is dragged the
 * composer says which part, how far it has gone in the figure's own
 * directions, and why it stopped if it did. */

describe('dragReadout', () => {
  it("says which part moved and how far, in the figure's own directions", () => {
    const readout = dragReadout('l_wrist', { x: 0.03, y: 0.12, z: 0.041 }, null, [], true)
    expect(readout.text).toBe("Left hand · 12 cm up · 4 cm forward · 3 cm to the figure's left")
    expect(readout.tone).toBe('moving')
  })

  it('leaves out directions it barely moved in, and reads down / back / right', () => {
    expect(dragReadout('r_ankle', { x: -0.2, y: -0.004, z: -0.07 }, null, [], true).text).toBe("Right foot · 7 cm back · 20 cm to the figure's right")
    expect(dragReadout('head', { x: 0.002, y: 0, z: 0 }, null, [], true).text).toBe('Head · not moved')
  })

  it('says what stopped it: the body in the way', () => {
    const readout = dragReadout('l_wrist', { x: 0, y: 0, z: -0.1 }, { a: 'left forearm', b: 'chest', depth: 0.01 }, [], true)
    expect(readout.text).toBe('Left hand · stopped: the left forearm would go through the chest')
    expect(readout.tone).toBe('blocked')
  })

  it('says when a joint is at the end of its range, or the limb cannot reach', () => {
    expect(dragReadout('l_elbow', { x: 0, y: 0.05, z: 0 }, null, ['l_elbow'], true).text).toBe('Left forearm · 5 cm up · the elbow is at its limit')
    expect(dragReadout('r_wrist', { x: 0.3, y: 0, z: 0 }, null, [], false).text).toBe("Right hand · 30 cm to the figure's left · the arm is at full stretch")
    // Turned on its rings (no distance to report).
    expect(dragReadout('l_elbow', null, null, ['l_elbow'], true).text).toBe('Left forearm · the elbow is at its limit')
  })
})

describe('axisHint', () => {
  it('names what each arrow does', () => {
    expect(axisHint('l_wrist', 'Y')).toBe('Left hand · drag the green arrow: up / down')
    expect(axisHint('l_wrist', 'X')).toBe('Left hand · drag the red arrow: left / right')
    expect(axisHint('l_wrist', 'Z')).toBe('Left hand · drag the blue arrow: forward / back')
    expect(axisHint('l_wrist', 'XY')).toBe('Left hand · drag the square: up / down and left / right')
    expect(axisHint('l_wrist', null)).toBeNull()
  })
})
