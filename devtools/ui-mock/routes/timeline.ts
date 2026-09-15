/**
 * Timeline editing, simulated.
 *
 * The same shape as the app: snapshot, apply, save, record. The snapshot is a
 * structured clone of the project rather than a file, but undo restores exactly
 * what was there for the same reason — an exact copy cannot drift out of step
 * with the operation the way a hand-written inverse can.
 */

import type { FilmProject, FilmScene, FilmShot } from '../../../frontend/types/film'
import type { DirectorAction, ShotTransition, TimelineEntry, TimelineView } from '../../../frontend/types/timeline'
import { MockHttpError, type Router } from '../http'
import type { MockState, Store, StoredTimelineAction } from '../state'

const MIN_DURATION = 0.5
const MAX_DURATION = 60
const UNDOABLE = 25

class TimelineRefusal extends Error {}

let counter = 0
const newId = (prefix: string) => {
  counter += 1
  return `${prefix}-${counter.toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

const clampDuration = (seconds: number) =>
  Math.round(Math.max(MIN_DURATION, Math.min(MAX_DURATION, seconds)) * 100) / 100

const cut = (): ShotTransition => ({ kind: 'cut', duration_seconds: 0.5 })

function renumber(scene: FilmScene): void {
  scene.shots.sort((a, b) => a.order - b.order)
  scene.shots.forEach((shot, index) => {
    shot.order = index
  })
}

function locate(project: FilmProject, shotId: string): [FilmScene, FilmShot] {
  for (const scene of project.scenes) {
    const shot = scene.shots.find(s => s.id === shotId)
    if (shot) return [scene, shot]
  }
  throw new TimelineRefusal(`Shot not found: ${shotId}`)
}

function requireScene(project: FilmProject, sceneId: string): FilmScene {
  const scene = project.scenes.find(s => s.id === sceneId)
  if (!scene) throw new TimelineRefusal(`Scene not found: ${sceneId}`)
  return scene
}

/** A new shot with the same look and none of the source's render history. */
function copyShot(source: FilmShot, title: string, order: number): FilmShot {
  return {
    ...structuredClone(source),
    id: newId('shot'),
    title,
    order,
    versions: [],
    current_version: null,
    capture_path: '',
    status: 'draft',
    created_at: Date.now(),
    updated_at: Date.now(),
  }
}

type Operation = (project: FilmProject, params: Record<string, unknown>) => [string, string[]]

const str = (params: Record<string, unknown>, key: string, required = true, fallback = ''): string => {
  const value = params[key]
  if (typeof value !== 'string' || !value.trim()) {
    if (required) throw new TimelineRefusal(`${key} is required`)
    return fallback
  }
  return value.trim()
}

const num = (params: Record<string, unknown>, key: string, fallback: number): number =>
  typeof params[key] === 'number' ? (params[key] as number) : fallback

const maybeInt = (params: Record<string, unknown>, key: string): number | null =>
  typeof params[key] === 'number' ? Math.trunc(params[key] as number) : null

const idList = (params: Record<string, unknown>, key: string): string[] => {
  const value = params[key]
  if (!Array.isArray(value)) throw new TimelineRefusal(`${key} must be a list of shot ids`)
  return value.map(String).filter(Boolean)
}

function insertShot(project: FilmProject, sceneId: string, position: number | null, title: string, duration: number): FilmShot {
  const scene = requireScene(project, sceneId)
  const template = scene.shots[0] ?? project.scenes.flatMap(s => s.shots)[0]
  if (!template) throw new TimelineRefusal('Add a shot by hand before inserting one here')
  const index = position === null ? scene.shots.length : Math.max(0, Math.min(scene.shots.length, position))
  for (const other of scene.shots) if (other.order >= index) other.order += 1
  const shot = copyShot(template, title || `Shot ${index + 1}`, index)
  shot.duration_seconds = clampDuration(duration)
  shot.gap_before_seconds = null
  shot.transition_in = cut()
  shot.transition_out = cut()
  scene.shots.push(shot)
  renumber(scene)
  return shot
}

const OPERATIONS: Record<string, Operation> = {
  split_shot(project, params) {
    const [scene, shot] = locate(project, str(params, 'shot_id'))
    const point = typeof params.at_seconds === 'number' ? (params.at_seconds as number) : shot.duration_seconds / 2
    if (point <= 0 || point >= shot.duration_seconds) {
      throw new TimelineRefusal(`Split point must be inside the shot (0 to ${shot.duration_seconds}s), got ${point}s`)
    }
    if (Math.min(point, shot.duration_seconds - point) < MIN_DURATION) {
      throw new TimelineRefusal(`Both halves must be at least ${MIN_DURATION}s`)
    }
    const second = copyShot(shot, `${shot.title} (b)`, shot.order + 1)
    second.duration_seconds = clampDuration(shot.duration_seconds - point)
    second.gap_before_seconds = 0
    second.transition_in = cut()
    second.transition_out = structuredClone(shot.transition_out)
    shot.duration_seconds = clampDuration(point)
    shot.title = `${shot.title} (a)`
    shot.transition_out = cut()
    shot.updated_at = Date.now()
    for (const other of scene.shots) if (other.order > shot.order) other.order += 1
    scene.shots.push(second)
    renumber(scene)
    return [`Split into two shots at ${point}s`, [shot.id, second.id]]
  },

  trim_shot(project, params) {
    const [, shot] = locate(project, str(params, 'shot_id'))
    shot.duration_seconds = clampDuration(num(params, 'duration_seconds', 4))
    shot.updated_at = Date.now()
    return [`Trimmed to ${shot.duration_seconds}s`, [shot.id]]
  },

  ripple_trim(project, params) {
    const [scene, shot] = locate(project, str(params, 'shot_id'))
    const before = shot.duration_seconds
    shot.duration_seconds = clampDuration(num(params, 'duration_seconds', 4))
    shot.updated_at = Date.now()
    let remaining = Math.round((shot.duration_seconds - before) * 100) / 100
    for (const candidate of [...scene.shots].sort((a, b) => a.order - b.order)) {
      if (remaining === 0) break
      if (candidate.order <= shot.order) continue
      const gap = candidate.gap_before_seconds ?? 0
      const adjusted = Math.max(0, gap - remaining)
      candidate.gap_before_seconds = Math.round(adjusted * 100) / 100
      remaining = Math.round((remaining - (gap - adjusted)) * 100) / 100
    }
    const note = remaining === 0 ? '' : `, ${Math.abs(remaining)}s the gaps could not absorb`
    return [`Ripple trimmed to ${shot.duration_seconds}s${note}`, [shot.id]]
  },

  move_shot(project, params) {
    const shotId = str(params, 'shot_id')
    const [source, shot] = locate(project, shotId)
    const target = requireScene(project, str(params, 'scene_id'))
    source.shots = source.shots.filter(s => s.id !== shotId)
    renumber(source)
    const position = maybeInt(params, 'position')
    const index = position === null ? target.shots.length : Math.max(0, Math.min(target.shots.length, position))
    for (const other of target.shots) if (other.order >= index) other.order += 1
    shot.order = index
    shot.updated_at = Date.now()
    target.shots.push(shot)
    renumber(target)
    return [`Moved to position ${index + 1}`, [shotId]]
  },

  reorder_shots(project, params) {
    const scene = requireScene(project, str(params, 'scene_id'))
    const ordered = idList(params, 'ordered_shot_ids')
    const known = new Set(scene.shots.map(s => s.id))
    const unknown = ordered.filter(id => !known.has(id))
    if (unknown.length) throw new TimelineRefusal(`Not in this scene: ${unknown.join(', ')}`)
    let position = 0
    for (const id of ordered) {
      const shot = scene.shots.find(s => s.id === id)
      if (shot) shot.order = position++
    }
    for (const shot of [...scene.shots].sort((a, b) => a.order - b.order)) {
      if (!ordered.includes(shot.id)) shot.order = position++
    }
    renumber(scene)
    return [`Reordered ${scene.shots.length} shots`, scene.shots.map(s => s.id)]
  },

  insert_shot(project, params) {
    const shot = insertShot(
      project,
      str(params, 'scene_id'),
      maybeInt(params, 'position'),
      str(params, 'title', false),
      num(params, 'duration_seconds', 4),
    )
    return ['Inserted a shot', [shot.id]]
  },

  replace_shot(project, params) {
    const shotId = str(params, 'shot_id')
    const sourceId = str(params, 'source_shot_id')
    if (shotId === sourceId) throw new TimelineRefusal('A shot cannot replace itself')
    const [, target] = locate(project, shotId)
    const [, source] = locate(project, sourceId)
    const { order, gap_before_seconds, transition_in, transition_out } = target
    Object.assign(target, structuredClone(source), {
      id: target.id,
      order,
      gap_before_seconds,
      transition_in,
      transition_out,
      versions: [],
      current_version: null,
      capture_path: '',
      status: 'draft',
      updated_at: Date.now(),
    })
    return ["Replaced the shot's content, keeping its place", [shotId, sourceId]]
  },

  replace_with_version(project, params) {
    const [, shot] = locate(project, str(params, 'shot_id'))
    const number = maybeInt(params, 'version_number')
    if (number === null) throw new TimelineRefusal('version_number is required')
    const version = shot.versions.find(v => v.number === number)
    if (!version) throw new TimelineRefusal(`Version not found: ${number}`)
    if (version.status !== 'complete') {
      throw new TimelineRefusal(`Version ${number} has no render to put on the timeline`)
    }
    shot.current_version = number
    if (shot.status !== 'approved' && shot.status !== 'rejected') shot.status = 'review'
    shot.updated_at = Date.now()
    return [`Put take ${number} on the timeline`, [shot.id]]
  },

  duplicate_shot(project, params) {
    const [scene, shot] = locate(project, str(params, 'shot_id'))
    const copy = copyShot(shot, `${shot.title} (copy)`, shot.order + 1)
    for (const other of scene.shots) if (other.order > shot.order) other.order += 1
    scene.shots.push(copy)
    renumber(scene)
    return ['Duplicated the shot', [shot.id, copy.id]]
  },

  delete_shot(project, params) {
    const shotId = str(params, 'shot_id')
    const [scene, shot] = locate(project, shotId)
    scene.shots = scene.shots.filter(s => s.id !== shotId)
    renumber(scene)
    return [`Removed "${shot.title}" from the timeline`, [shotId]]
  },

  set_transition(project, params) {
    const [, shot] = locate(project, str(params, 'shot_id'))
    const where = str(params, 'where', false, 'out')
    const kind = str(params, 'kind', false, 'cut')
    if (!['cut', 'dissolve', 'fade_in', 'fade_out', 'wipe', 'dip_to_black'].includes(kind)) {
      throw new TimelineRefusal(`Unknown transition: ${kind}`)
    }
    if (where !== 'in' && where !== 'out') throw new TimelineRefusal("Transitions go 'in' or 'out'")
    const transition: ShotTransition = {
      kind: kind as ShotTransition['kind'],
      duration_seconds: Math.round(Math.max(0, Math.min(5, num(params, 'duration_seconds', 0.5))) * 100) / 100,
    }
    if (where === 'in') shot.transition_in = transition
    else shot.transition_out = transition
    shot.updated_at = Date.now()
    const length = transition.kind === 'cut' ? '' : ` over ${transition.duration_seconds}s`
    return [`Set the ${where} transition to ${transition.kind}${length}`, [shot.id]]
  },

  set_duration(project, params) {
    return OPERATIONS.trim_shot(project, params)
  },

  set_gap(project, params) {
    const [, shot] = locate(project, str(params, 'shot_id'))
    const raw = params.gap_seconds
    shot.gap_before_seconds =
      raw === null || raw === undefined ? null : Math.round(Math.max(0, Math.min(30, Number(raw))) * 100) / 100
    shot.updated_at = Date.now()
    return [
      shot.gap_before_seconds === null
        ? 'Cleared the gap'
        : `Set the gap before it to ${shot.gap_before_seconds}s`,
      [shot.id],
    ]
  },

  build_montage(project, params) {
    const scene = requireScene(project, str(params, 'scene_id'))
    const ids = idList(params, 'shot_ids')
    const known = new Map(scene.shots.map(s => [s.id, s]))
    const missing = ids.filter(id => !known.has(id))
    if (missing.length) throw new TimelineRefusal(`Not in this scene: ${missing.join(', ')}`)
    if (ids.length < 2) throw new TimelineRefusal('A montage needs at least two shots')
    const length = clampDuration(num(params, 'shot_seconds', 1.2))
    for (const id of ids) {
      const shot = known.get(id)!
      shot.duration_seconds = length
      shot.gap_before_seconds = 0
      shot.transition_in = cut()
      shot.transition_out = cut()
      shot.updated_at = Date.now()
    }
    return [`Cut ${ids.length} shots into a montage at ${length}s each`, ids]
  },

  add_opening(project, params) {
    const first = [...project.scenes].sort((a, b) => a.order - b.order)[0]
    if (!first) throw new TimelineRefusal('Add a scene before adding an opening shot')
    const shot = insertShot(project, first.id, 0, str(params, 'title', false, 'Opening'), num(params, 'duration_seconds', 3))
    shot.transition_in = { kind: 'fade_in', duration_seconds: 1 }
    return ['Added an opening shot that fades in', [shot.id]]
  },

  add_ending(project, params) {
    const scenes = [...project.scenes].sort((a, b) => a.order - b.order)
    const last = scenes[scenes.length - 1]
    if (!last) throw new TimelineRefusal('Add a scene before adding an ending shot')
    const shot = insertShot(project, last.id, null, str(params, 'title', false, 'Ending'), num(params, 'duration_seconds', 3))
    shot.transition_out = { kind: 'fade_out', duration_seconds: 1 }
    return ['Added an ending shot that fades out', [shot.id]]
  },

  insert_broll(project, params) {
    const afterId = str(params, 'after_shot_id')
    const [scene, anchor] = locate(project, afterId)
    const shot = insertShot(
      project,
      scene.id,
      anchor.order + 1,
      str(params, 'title', false) || `B-roll after ${anchor.title}`,
      num(params, 'duration_seconds', 2),
    )
    shot.gap_before_seconds = 0
    const prompt = str(params, 'prompt', false)
    if (prompt) {
      shot.visual_prompt = prompt
      shot.prompt_locked = true
    }
    shot.location_id = anchor.location_id
    shot.updated_at = Date.now()
    return ['Inserted a B-roll cutaway', [afterId, shot.id]]
  },

  align_durations(project, params) {
    const scene = requireScene(project, str(params, 'scene_id'))
    if (!scene.shots.length) throw new TimelineRefusal('That scene has no shots to align')
    const length = clampDuration(num(params, 'duration_seconds', 4))
    for (const shot of scene.shots) {
      shot.duration_seconds = length
      shot.updated_at = Date.now()
    }
    return [`Aligned ${scene.shots.length} shots to ${length}s each`, scene.shots.map(s => s.id)]
  },

  normalize_timeline(project, params) {
    const gap = Math.max(0, num(params, 'gap_seconds', 0))
    const touched: string[] = []
    for (const scene of [...project.scenes].sort((a, b) => a.order - b.order)) {
      renumber(scene)
      scene.shots.forEach((shot, index) => {
        let changed = false
        const clamped = clampDuration(shot.duration_seconds)
        if (clamped !== shot.duration_seconds) {
          shot.duration_seconds = clamped
          changed = true
        }
        const wanted = index === 0 ? null : Math.round(gap * 100) / 100
        if (shot.gap_before_seconds !== wanted) {
          shot.gap_before_seconds = wanted
          changed = true
        }
        if (changed) {
          shot.updated_at = Date.now()
          touched.push(shot.id)
        }
      })
    }
    project.scenes.sort((a, b) => a.order - b.order)
    project.scenes.forEach((scene, index) => {
      scene.order = index
    })
    return [`Normalised the timeline — ${touched.length} shots changed`, touched]
  },
}

function buildView(project: FilmProject): TimelineView {
  const entries: TimelineEntry[] = []
  let clock = 0
  let rendered = 0
  for (const scene of [...project.scenes].sort((a, b) => a.order - b.order)) {
    for (const shot of [...scene.shots].sort((a, b) => a.order - b.order)) {
      let gap = shot.gap_before_seconds
      if (gap === null || gap === undefined) {
        gap = scene.inter_shot_gap_seconds ?? project.settings.inter_shot_gap_seconds
      }
      gap = entries.length === 0 ? 0 : Math.max(0, gap)
      clock += gap
      const hasRender = shot.versions.some(v => v.status === 'complete' && v.number === shot.current_version)
      if (hasRender) rendered += 1
      entries.push({
        scene_id: scene.id,
        scene_title: scene.title,
        shot_id: shot.id,
        shot_title: shot.title,
        order: entries.length,
        start_seconds: Math.round(clock * 100) / 100,
        duration_seconds: shot.duration_seconds,
        gap_before_seconds: Math.round(gap * 100) / 100,
        transition_in: structuredClone(shot.transition_in),
        transition_out: structuredClone(shot.transition_out),
        status: shot.status,
        has_render: hasRender,
      })
      clock += shot.duration_seconds
    }
  }
  return {
    entries,
    total_seconds: Math.round(clock * 100) / 100,
    shot_count: entries.length,
    rendered_count: rendered,
  }
}

function historyFor(state: MockState, projectId: string): StoredTimelineAction[] {
  state.timelineHistory[projectId] ??= []
  return state.timelineHistory[projectId]
}

const withoutSnapshot = (action: StoredTimelineAction): DirectorAction => {
  const { snapshot: _snapshot, ...rest } = action
  return rest
}

export function registerTimelineRoutes(router: Router, store: Store): void {
  const project = (id: string): FilmProject => store.ensureProject(id)

  router.get('/api/film/projects/:projectId/timeline', req => buildView(project(req.params.projectId)))

  router.get('/api/film/projects/:projectId/timeline/history', req => {
    const limit = Number(req.query.get('limit') ?? 50) || 50
    const actions = historyFor(store.data, req.params.projectId)
    return {
      actions: actions.slice(-limit).map(withoutSnapshot),
      undoable: actions.filter(a => !a.undone && a.snapshot !== null).length,
    }
  })

  router.post('/api/film/projects/:projectId/timeline/actions', req =>
    store.mutate(state => {
      const body = req.body as { action?: string; params?: Record<string, unknown>; actor?: string }
      const operation = OPERATIONS[body.action ?? '']
      if (!operation) throw new MockHttpError(400, `Unknown timeline action: ${body.action}`)

      const projectId = req.params.projectId
      const target = store.ensureProject(projectId)
      const snapshot = structuredClone(target)
      let summary: string
      let affected: string[]
      try {
        ;[summary, affected] = operation(target, body.params ?? {})
      } catch (err) {
        // Nothing was written: the snapshot is still the truth, so put it back.
        state.projects[projectId] = snapshot
        if (err instanceof TimelineRefusal) throw new MockHttpError(400, err.message)
        throw err
      }
      target.updated_at = Date.now()

      const record: StoredTimelineAction = {
        id: newId('act'),
        created_at: Date.now(),
        action: body.action ?? '',
        actor: body.actor === 'director' ? 'director' : 'user',
        summary,
        params: body.params ?? {},
        affected_shot_ids: affected,
        before: null,
        undone: false,
        snapshot,
      }
      const history = historyFor(state, projectId)
      history.push(record)
      // Only the most recent edits keep a snapshot, as in the app.
      for (const old of history.slice(0, -UNDOABLE)) old.snapshot = null

      return { action: withoutSnapshot(record), timeline: buildView(target) }
    }),
  )

  router.post('/api/film/projects/:projectId/timeline/undo', req =>
    store.mutate(state => {
      const projectId = req.params.projectId
      const history = historyFor(state, projectId)
      const target = [...history].reverse().find(a => !a.undone && a.snapshot !== null)
      if (!target || !target.snapshot) throw new MockHttpError(400, 'Nothing to undo')
      state.projects[projectId] = structuredClone(target.snapshot)
      state.projects[projectId].updated_at = Date.now()
      target.undone = true
      // Spent: keeping it would let a second undo rewind work done since.
      target.snapshot = null
      return { action: withoutSnapshot(target), timeline: buildView(state.projects[projectId]) }
    }),
  )
}
