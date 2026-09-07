/**
 * Built-in pose library (named joints -> Euler degrees) plus project-pose
 * merging. Categories mirror Open Media's pose-library grouping; the poses
 * themselves are authored for this app's figure rig.
 */

import type { FilmPose, Vec3 } from '../../../types/film'

export interface BuiltInPose {
  name: string
  category: string
  joints: Record<string, Vec3>
}

export const BUILT_IN_POSES: BuiltInPose[] = [
  { name: 'Stand', category: 'basics', joints: {} },
  {
    name: 'Stand Relaxed',
    category: 'basics',
    joints: {
      torso: [2, 0, 1],
      head: [0, 8, 0],
      l_arm: [0, 0, 6],
      r_arm: [0, 0, -6],
      l_elbow: [8, 0, 0],
      r_elbow: [8, 0, 0],
      l_leg: [0, 6, 2],
      r_leg: [0, -4, -1],
    },
  },
  {
    name: 'Walk Mid-Stride',
    category: 'movement',
    joints: {
      torso: [6, 0, 0],
      l_arm: [-28, 0, 4],
      r_arm: [30, 0, -4],
      l_elbow: [24, 0, 0],
      r_elbow: [38, 0, 0],
      l_leg: [28, 0, 0],
      r_leg: [-24, 0, 0],
      l_knee: [12, 0, 0],
      r_knee: [42, 0, 0],
      l_ankle: [-10, 0, 0],
      r_ankle: [16, 0, 0],
    },
  },
  {
    name: 'Run',
    category: 'movement',
    joints: {
      torso: [16, 0, 0],
      l_arm: [-48, 0, 8],
      r_arm: [52, 0, -8],
      l_elbow: [70, 0, 0],
      r_elbow: [82, 0, 0],
      l_leg: [52, 0, 0],
      r_leg: [-38, 0, 0],
      l_knee: [22, 0, 0],
      r_knee: [88, 0, 0],
      l_ankle: [-14, 0, 0],
      r_ankle: [22, 0, 0],
    },
  },
  {
    name: 'Sit',
    category: 'basics',
    joints: {
      l_leg: [88, 0, 4],
      r_leg: [88, 0, -4],
      l_knee: [88, 0, 0],
      r_knee: [88, 0, 0],
      torso: [-4, 0, 0],
      l_arm: [-20, 0, 8],
      r_arm: [-20, 0, -8],
      l_elbow: [30, 0, 0],
      r_elbow: [30, 0, 0],
    },
  },
  {
    name: 'Point Forward',
    category: 'acting',
    joints: {
      r_arm: [-82, 0, -6],
      r_elbow: [4, 0, 0],
      head: [0, -6, 0],
      torso: [0, -8, 0],
      l_arm: [0, 0, 8],
    },
  },
  {
    name: 'Arms Crossed',
    category: 'acting',
    joints: {
      l_arm: [-38, 24, 52],
      r_arm: [-42, -24, -52],
      l_elbow: [96, 0, 0],
      r_elbow: [96, 0, 0],
      torso: [-3, 0, 0],
      head: [4, 0, 0],
    },
  },
  {
    name: 'Hands On Hips',
    category: 'acting',
    joints: {
      l_arm: [0, 0, 42],
      r_arm: [0, 0, -42],
      l_elbow: [58, -40, 0],
      r_elbow: [58, 40, 0],
      torso: [-2, 0, 0],
    },
  },
  {
    name: 'Reach Up',
    category: 'acting',
    joints: {
      r_arm: [-160, 0, -8],
      r_elbow: [10, 0, 0],
      torso: [6, 0, -4],
      head: [-14, 0, 0],
      l_arm: [0, 0, 10],
    },
  },
  {
    name: 'Crouch',
    category: 'movement',
    joints: {
      torso: [28, 0, 0],
      l_leg: [96, 0, 6],
      r_leg: [96, 0, -6],
      l_knee: [118, 0, 0],
      r_knee: [118, 0, 0],
      l_ankle: [-38, 0, 0],
      r_ankle: [-38, 0, 0],
      l_arm: [-38, 0, 10],
      r_arm: [-38, 0, -10],
      l_elbow: [40, 0, 0],
      r_elbow: [40, 0, 0],
    },
  },
  {
    name: 'Fallen',
    category: 'acting',
    joints: {
      torso: [-8, 0, 0],
      head: [-12, 10, 0],
      l_arm: [-30, 0, 70],
      r_arm: [20, 0, -80],
      l_elbow: [30, 0, 0],
      r_elbow: [15, 0, 0],
      l_leg: [15, 12, 0],
      r_leg: [-6, -14, 0],
      l_knee: [30, 0, 0],
      r_knee: [10, 0, 0],
    },
  },
  {
    name: 'Phone Call',
    category: 'acting',
    joints: {
      r_arm: [-30, -18, -68],
      r_elbow: [128, 0, 0],
      head: [0, -10, 6],
      torso: [2, 6, 0],
      l_arm: [0, 0, 8],
    },
  },
]

export interface PoseEntry {
  id: string
  name: string
  category: string
  source: 'builtin' | 'project'
  joints: Record<string, Vec3>
}

/** One flat list: built-ins first, then project poses (a project pose with the
 * same name overrides the built-in, mirroring Open Media's merge rule). */
export function mergePoseLibrary(projectPoses: FilmPose[]): PoseEntry[] {
  const byName = new Map<string, PoseEntry>()
  for (const pose of BUILT_IN_POSES) {
    byName.set(pose.name.toLowerCase(), {
      id: `builtin-${pose.name.toLowerCase().replace(/\s+/g, '-')}`,
      name: pose.name,
      category: pose.category,
      source: 'builtin',
      joints: pose.joints,
    })
  }
  for (const pose of projectPoses) {
    byName.set(pose.name.toLowerCase(), {
      id: pose.id,
      name: pose.name,
      category: pose.category,
      source: 'project',
      joints: pose.joints,
    })
  }
  return [...byName.values()]
}

export function findPose(library: PoseEntry[], name: string): PoseEntry | null {
  const needle = name.trim().toLowerCase()
  return library.find(p => p.name.toLowerCase() === needle) ?? null
}
