import * as THREE from 'three'
import { describe, expect, it } from 'vitest'
import { applyPose, buildFigure, readPose } from './figure'
import { dragJoint } from './limbPose'
import { poseWords } from './poseWords'

/* Asked 2026-10-01: a live preview of the photo as the 3D model is edited.
 * Shown only the posed mannequin, the image model copied the photo's pose
 * unchanged; told the edit in words ("left arm raised straight up above the
 * head") it followed it. These check the words for real rig poses. The
 * figure faces +Z; its left is +X. */

function figure() {
  const rig = buildFigure('female', '#e4572e')
  new THREE.Scene().add(rig.root)
  rig.root.position.set(0.3, 0, -1)
  rig.root.rotation.y = 0.3
  rig.root.updateMatrixWorld(true)
  return rig
}

type Rig = ReturnType<typeof figure>
const local = (rig: Rig, x: number, y: number, z: number) => rig.root.localToWorld(new THREE.Vector3(x, y, z))
const raiseLeftHand = (rig: Rig) => dragJoint(rig, 'l_wrist', local(rig, 0.1 * rig.height, 1.05 * rig.height, 0.02))
const rightArmOut = (rig: Rig) => dragJoint(rig, 'r_wrist', local(rig, -0.45 * rig.height, 0.82 * rig.height, 0))

describe('poseWords', () => {
  it('says nothing about a figure standing at rest', () => {
    expect(poseWords(figure(), null, 'camera')).toBe('')
  })

  it('names a raised arm, and which side of the picture it is on', () => {
    const rig = figure()
    raiseLeftHand(rig)
    const words = poseWords(rig, null, 'camera')
    expect(words).toContain('left arm (on the right side of the picture) raised straight up above the head')
    expect(words).not.toContain('right arm')
    // Seen from behind, the figure's left is on the left of the picture.
    expect(poseWords(rig, null, 'away')).toContain('left arm (on the left side of the picture)')
  })

  it('names an arm stretched out to the side', () => {
    const rig = figure()
    rightArmOut(rig)
    expect(poseWords(rig, null, 'side')).toContain('right arm stretched out to the side at shoulder height')
  })

  // Live 2026-10-01 (screenshot): a hand brought up to the shoulder, elbow
  // bent down, was described as "stretched out to the side at shoulder height".
  it('names a hand brought up to the shoulder with the elbow bent', () => {
    const rig = figure()
    const shoulder = rig.root.worldToLocal(rig.joints.l_arm.getWorldPosition(new THREE.Vector3()))
    dragJoint(rig, 'l_wrist', rig.root.localToWorld(shoulder.clone().add(new THREE.Vector3(-0.02, 0.01, 0.07))))
    const words = poseWords(rig, null, 'camera')
    expect(words).toContain('left arm (on the right side of the picture) bent up, the hand at the shoulder')
    expect(words).not.toContain('stretched out')
  })

  it('names a raised knee', () => {
    const rig = figure()
    const H = rig.height
    dragJoint(rig, 'l_ankle', local(rig, 0.05 * H, 0.3 * H, 0.2 * H))
    expect(poseWords(rig, null, 'camera')).toContain('left leg (on the right side of the picture) lifted with the knee raised')
  })

  it('leaves out what the photo already shows: only the edited limbs are named', () => {
    const rig = figure()
    rightArmOut(rig)
    const photoPose = readPose(rig)
    expect(poseWords(rig, photoPose, 'camera')).toBe('')
    raiseLeftHand(rig)
    const words = poseWords(rig, photoPose, 'camera')
    expect(words).toContain('left arm')
    expect(words).not.toContain('right arm')
  })

  it('says a limb went back to rest when the photo had it posed', () => {
    const rig = figure()
    rightArmOut(rig)
    const photoPose = readPose(rig)
    applyPose(rig, {})
    expect(poseWords(rig, photoPose, 'camera')).toContain('right arm (on the left side of the picture) hanging relaxed at the side')
  })
})
