/**
 * Continuity, mirroring the deterministic half of `film_continuity.py`.
 *
 * The kinds, severities, messages and fixes match the real checker so the
 * storyboard dots, the drawer's warning list and the one-click Fix button all
 * behave the way they do in the app. The AI visual review is reported as
 * unavailable, which is also what the backend says with no provider.
 */

import type {
  ContinuityLevel,
  ContinuityReport,
  ContinuitySeverity,
  ContinuityWarning,
  FilmProject,
  FilmScene,
  FilmShot,
} from '../../../frontend/types/film'
import { MockHttpError, type Router } from '../http'
import type { Store } from '../state'

const SEVERITY: Record<string, ContinuitySeverity> = {
  missing_asset: 'broken',
  duration_invalid: 'broken',
  location_mismatch: 'significant',
  missing_previous_output: 'significant',
  wardrobe_change: 'significant',
  character_not_in_scene: 'minor',
  prop_not_in_scene: 'minor',
  missing_capture: 'minor',
  screen_direction: 'significant',
  jump_cut: 'minor',
  framing_jump: 'minor',
}

const LEVEL_RANK: Record<ContinuityLevel, number> = { good: 0, minor: 1, significant: 2, broken: 3 }

function warn(kind: string, message: string, fix: string, subjectId = ''): ContinuityWarning {
  return { kind, message, severity: SEVERITY[kind] ?? 'minor', fix, auto_fixable: true, subject_id: subjectId }
}

function locate(project: FilmProject, shotId: string): { scene: FilmScene; shot: FilmShot } | null {
  for (const scene of project.scenes) {
    const shot = scene.shots.find(s => s.id === shotId)
    if (shot) return { scene, shot }
  }
  return null
}

export function checkShot(project: FilmProject, scene: FilmScene, shot: FilmShot): ContinuityReport {
  const warnings: ContinuityWarning[] = []
  const assetById = new Map(project.assets.map(a => [a.id, a]))

  for (const character of shot.characters) {
    const asset = assetById.get(character.asset_id)
    if (!asset) {
      warnings.push(
        warn(
          'missing_asset',
          `Shot references a character asset that no longer exists (${character.asset_id}).`,
          'Remove the dangling character reference from the shot.',
          character.asset_id,
        ),
      )
    } else if (scene.character_ids.length > 0 && !scene.character_ids.includes(character.asset_id)) {
      warnings.push(
        warn(
          'character_not_in_scene',
          `${asset.name} is in this shot but not listed in the scene's characters.`,
          `Add ${asset.name} to the scene's cast.`,
          asset.id,
        ),
      )
    }
  }

  if (shot.location_id !== null) {
    const location = assetById.get(shot.location_id)
    if (!location) {
      warnings.push(
        warn(
          'missing_asset',
          `Shot references a location asset that no longer exists (${shot.location_id}).`,
          "Clear the shot's location.",
          shot.location_id,
        ),
      )
    } else if (scene.location_id !== null && shot.location_id !== scene.location_id) {
      const sceneLocation = assetById.get(scene.location_id)
      const sceneName = sceneLocation ? sceneLocation.name : scene.location_id
      warnings.push(
        warn(
          'location_mismatch',
          `Shot location (${location.name}) differs from the scene's location (${sceneName}).`,
          `Use the scene's location (${sceneName}) for this shot.`,
          shot.location_id,
        ),
      )
    }
  }

  for (const propId of shot.prop_ids) {
    const prop = assetById.get(propId)
    if (!prop) {
      warnings.push(
        warn(
          'missing_asset',
          `Shot references a prop asset that no longer exists (${propId}).`,
          'Remove the dangling prop reference from the shot.',
          propId,
        ),
      )
    } else if (scene.prop_ids.length > 0 && !scene.prop_ids.includes(propId)) {
      warnings.push(
        warn(
          'prop_not_in_scene',
          `Prop ${prop.name} is in this shot but not listed in the scene's props.`,
          `Add ${prop.name} to the scene's props.`,
          prop.id,
        ),
      )
    }
  }

  if (shot.generation.use_capture_as_reference && shot.composition !== null && !shot.capture_path) {
    warnings.push(
      warn(
        'missing_capture',
        'Generation is set to use the composition capture, but no capture exists yet.',
        'Open the Shot Composer and capture the frame, or generate from text only.',
      ),
    )
  }

  if (shot.duration_seconds <= 0) {
    warnings.push(
      warn('duration_invalid', 'Shot duration must be greater than zero.', 'Set a duration of at least one second.'),
    )
  }

  const level = warnings.reduce<ContinuityLevel>(
    (worst, w) => (LEVEL_RANK[w.severity] > LEVEL_RANK[worst] ? w.severity : worst),
    'good',
  )
  return { level, warnings }
}

/** Apply the same repair the backend's fix endpoint performs. */
function applyFix(scene: FilmScene, shot: FilmShot, kind: string, subjectId: string): string {
  switch (kind) {
    case 'location_mismatch':
      shot.location_id = scene.location_id
      return "Shot now uses the scene's location."
    case 'character_not_in_scene':
      if (subjectId && !scene.character_ids.includes(subjectId)) scene.character_ids.push(subjectId)
      return "Character added to the scene's cast."
    case 'prop_not_in_scene':
      if (subjectId && !scene.prop_ids.includes(subjectId)) scene.prop_ids.push(subjectId)
      return "Prop added to the scene's props."
    case 'missing_capture':
      shot.generation.use_capture_as_reference = false
      return 'Shot will generate from text instead of a capture.'
    case 'duration_invalid':
      shot.duration_seconds = 5
      return 'Duration reset to 5 seconds.'
    case 'missing_asset':
      shot.characters = shot.characters.filter(c => c.asset_id !== subjectId)
      shot.prop_ids = shot.prop_ids.filter(id => id !== subjectId)
      if (shot.location_id === subjectId) shot.location_id = null
      return 'Dangling reference removed.'
    default:
      throw new MockHttpError(400, `Cannot fix automatically: ${kind}`)
  }
}

export function registerContinuityRoutes(router: Router, store: Store): void {
  router.get('/api/film/projects/:projectId/continuity/:shotId', req => {
    const project = store.ensureProject(req.params.projectId)
    const found = locate(project, req.params.shotId)
    if (!found) throw new MockHttpError(404, `Shot not found: ${req.params.shotId}`)
    return checkShot(project, found.scene, found.shot)
  })

  router.get('/api/film/projects/:projectId/continuity', req => {
    const project = store.ensureProject(req.params.projectId)
    const shots: { shot_id: string; scene_id: string; level: ContinuityLevel; warning_count: number }[] = []
    const counts: Record<string, number> = { good: 0, minor: 0, significant: 0, broken: 0 }
    let worst: ContinuityLevel = 'good'

    for (const scene of project.scenes) {
      for (const shot of scene.shots) {
        const report = checkShot(project, scene, shot)
        shots.push({
          shot_id: shot.id,
          scene_id: scene.id,
          level: report.level,
          warning_count: report.warnings.length,
        })
        counts[report.level] += 1
        if (LEVEL_RANK[report.level] > LEVEL_RANK[worst]) worst = report.level
      }
    }
    return { level: worst, shots, counts }
  })

  router.post('/api/film/projects/:projectId/continuity/:shotId/fix', req =>
    store.mutate(() => {
      const project = store.ensureProject(req.params.projectId)
      const found = locate(project, req.params.shotId)
      if (!found) throw new MockHttpError(404, `Shot not found: ${req.params.shotId}`)
      const message = applyFix(
        found.scene,
        found.shot,
        String(req.body.kind ?? ''),
        String(req.body.subject_id ?? ''),
      )
      found.shot.updated_at = Date.now()
      project.updated_at = Date.now()
      return {
        fixed: true,
        message,
        report: checkShot(project, found.scene, found.shot),
        shot: found.shot,
      }
    }),
  )

  router.post('/api/film/projects/:projectId/continuity/:shotId/visual-review', req => {
    const project = store.ensureProject(req.params.projectId)
    const found = locate(project, req.params.shotId)
    if (!found) throw new MockHttpError(404, `Shot not found: ${req.params.shotId}`)
    return {
      available: false,
      reason: 'UI-only mode does not call a vision model. Run the full app with a provider key for a real review.',
      category: 'unavailable' as const,
      summary: '',
      issues: [],
      previous_shot_id: null,
      previous_frame_path: '',
      current_frame_path: found.shot.capture_path,
      context: null,
    }
  })
}
