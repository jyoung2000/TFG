/**
 * What storyboard undo/redo restores (QA pass 2026-10-01). A snapshot is the
 * project as the user authored it; renders and reviews made since belong to
 * the present. Writing the whole snapshot back erased new takes from their
 * shot and lost approvals, so the restored project keeps each surviving shot's
 * live versions, current version and status.
 */

import type { FilmProject } from '../types/film'

export function withLiveRenders(snapshot: FilmProject, current: FilmProject): FilmProject {
  const live = new Map(current.scenes.flatMap(scene => scene.shots).map(shot => [shot.id, shot]))
  return {
    ...snapshot,
    scenes: snapshot.scenes.map(scene => ({
      ...scene,
      shots: scene.shots.map(shot => {
        const now = live.get(shot.id)
        return now ? { ...shot, versions: now.versions, current_version: now.current_version, status: now.status } : shot
      }),
    })),
  }
}
