/**
 * The cross-project shot library, simulated.
 *
 * The same rules restated: saving snapshots the shot's settings, the entry is
 * a copy so it keeps working after the source is gone, archive is reversible
 * and delete is not. The "copied preview" here is the mock's own render path —
 * there is no filesystem to copy into — but everything the UI depends on
 * behaves the same.
 */

import type { FilmShot } from '../../../frontend/types/film'
import type { LibraryShot } from '../../../frontend/types/shot-library'
import { MockHttpError, RawResponse, type Router } from '../http'
import { isVideoPath, labelFromPath, placeholderFrame } from '../media'
import type { MockState, Store } from '../state'

const MAX_TAGS = 24

function normaliseTags(tags: string[]): string[] {
  const seen: string[] = []
  for (const tag of tags) {
    const cleaned = tag.trim().toLowerCase().slice(0, 40)
    if (cleaned && !seen.includes(cleaned)) seen.push(cleaned)
  }
  return seen.slice(0, MAX_TAGS)
}

let counter = 0
function newId(): string {
  counter += 1
  return `lib-${counter.toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

function find(state: MockState, id: string): LibraryShot {
  const item = state.shotLibrary.find(i => i.id === id)
  if (!item) throw new MockHttpError(404, `Library item not found: ${id}`)
  return item
}

/** One seeded entry, so the library is not an empty screen on first open. */
export function seedShotLibrary(shot: FilmShot | null, projectName: string): LibraryShot[] {
  if (!shot) return []
  const version = shot.versions.find(v => v.status === 'complete')
  return [
    {
      id: 'lib-seed-1',
      title: 'Console close-up, torchlight',
      notes: 'The look that worked for the interior — kept for the next film.',
      visual_prompt: shot.visual_prompt,
      negative_prompt: shot.negative_prompt,
      framing: shot.framing,
      camera_move: shot.camera_move,
      duration_seconds: shot.duration_seconds,
      model: version?.model ?? 'fast',
      resolution: version?.resolution ?? '960x540',
      fps: version?.fps ?? 24,
      seed: version?.seed ?? null,
      aspect_ratio: shot.generation.aspect_ratio,
      style: '',
      preview_path: version?.output_path ?? '',
      preview_kind: version?.output_path ? 'video' : 'none',
      lineage: {
        project_id: 'ui-mock-film',
        project_name: projectName,
        scene_id: 'scene-1',
        scene_title: 'Relay station, night',
        shot_id: shot.id,
        shot_title: shot.title,
        version_number: version?.number ?? null,
        captured_at: Date.now() - 86_400_000,
      },
      tags: ['night', 'interior'],
      rating: 4,
      favorite: false,
      archived: false,
      archived_at: null,
      used_count: 0,
      last_used_at: 0,
      created_at: Date.now() - 86_400_000,
      updated_at: Date.now() - 86_400_000,
    },
  ]
}

export function registerShotLibraryRoutes(router: Router, store: Store, clipUrl: string): void {
  router.get('/api/shot-library', req => {
    const q = (req.query.get('q') ?? '').trim().toLowerCase()
    const tags = normaliseTags(req.query.getAll('tags'))
    const favoriteParam = req.query.get('favorite')
    const favorite = favoriteParam === null ? undefined : favoriteParam === 'true'
    const archived = req.query.get('archived') === 'true'
    const model = (req.query.get('model') ?? '').toLowerCase()
    const sort = req.query.get('sort') ?? 'recent'

    let items = store.data.shotLibrary.filter(item => {
      if (item.archived !== archived) return false
      if (favorite !== undefined && item.favorite !== favorite) return false
      if (model && !item.model.toLowerCase().includes(model)) return false
      if (tags.length && !tags.every(tag => item.tags.includes(tag))) return false
      if (q) {
        const haystack = [item.title, item.notes, item.visual_prompt, item.model, item.tags.join(' ')]
          .join(' ')
          .toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })

    if (sort === 'rating') items = [...items].sort((a, b) => b.rating - a.rating || b.updated_at - a.updated_at)
    else if (sort === 'used') items = [...items].sort((a, b) => b.used_count - a.used_count || b.last_used_at - a.last_used_at)
    else if (sort === 'title') items = [...items].sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()))
    else items = [...items].sort((a, b) => b.updated_at - a.updated_at)
    items = [...items].sort((a, b) => Number(b.favorite) - Number(a.favorite))

    const counts: Record<string, number> = {}
    for (const item of store.data.shotLibrary) {
      if (item.archived) continue
      for (const tag of item.tags) counts[tag] = (counts[tag] ?? 0) + 1
    }
    return {
      items,
      tags: Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))),
      total: items.length,
    }
  })

  // Registered before the bare :id route so it is not swallowed by it.
  router.get('/api/shot-library/:id/preview', req => {
    const item = find(store.data, req.params.id)
    if (!item.preview_path) throw new MockHttpError(404, 'That library item has no preview')
    if (isVideoPath(item.preview_path) && clipUrl) {
      return new RawResponse(302, { location: clipUrl }, null)
    }
    return placeholderFrame(labelFromPath(item.preview_path), item.preview_path, item.preview_path)
  })

  router.get('/api/shot-library/:id', req => find(store.data, req.params.id))

  router.post('/api/shot-library', req =>
    store.mutate(state => {
      const body = req.body as {
        project_id?: string
        shot_id?: string
        title?: string
        notes?: string
        tags?: string[]
        rating?: number
      }
      const project = state.projects[body.project_id ?? '']
      const scene = project?.scenes.find(s => s.shots.some(sh => sh.id === body.shot_id))
      const shot = scene?.shots.find(sh => sh.id === body.shot_id)
      if (!project || !scene || !shot) throw new MockHttpError(404, `Shot not found: ${body.shot_id}`)

      const version = shot.versions.find(v => v.number === shot.current_version && v.status === 'complete')
      const item: LibraryShot = {
        id: newId(),
        title: (body.title?.trim() || shot.title || 'Untitled shot').slice(0, 200),
        notes: (body.notes ?? '').trim().slice(0, 2000),
        visual_prompt: shot.visual_prompt,
        negative_prompt: shot.negative_prompt,
        framing: shot.framing,
        camera_move: shot.camera_move,
        duration_seconds: shot.duration_seconds,
        model: version?.model ?? shot.generation.model,
        resolution: version?.resolution ?? shot.generation.resolution,
        fps: version?.fps ?? shot.generation.fps,
        seed: version?.seed ?? shot.generation.seed,
        aspect_ratio: shot.generation.aspect_ratio,
        style: project.settings.style_prompt,
        preview_path: version?.output_path ?? shot.capture_path ?? '',
        preview_kind: version?.output_path ? 'video' : shot.capture_path ? 'image' : 'none',
        lineage: {
          project_id: project.id,
          project_name: project.name,
          scene_id: scene.id,
          scene_title: scene.title,
          shot_id: shot.id,
          shot_title: shot.title,
          version_number: version?.number ?? null,
          captured_at: Date.now(),
        },
        tags: normaliseTags(body.tags ?? []),
        rating: Math.max(0, Math.min(5, body.rating ?? 0)),
        favorite: false,
        archived: false,
        archived_at: null,
        used_count: 0,
        last_used_at: 0,
        created_at: Date.now(),
        updated_at: Date.now(),
      }
      state.shotLibrary.push(item)
      return item
    }),
  )

  router.put('/api/shot-library/:id', req =>
    store.mutate(state => {
      const item = find(state, req.params.id)
      const body = req.body as {
        title?: string
        notes?: string
        tags?: string[]
        rating?: number
        favorite?: boolean
      }
      // Only what was sent: a rating edit must not blank the notes.
      if (body.title !== undefined) {
        const cleaned = body.title.trim().slice(0, 200)
        if (!cleaned) throw new MockHttpError(400, 'A library item needs a title')
        item.title = cleaned
      }
      if (body.notes !== undefined) item.notes = body.notes.trim().slice(0, 2000)
      if (body.tags !== undefined) item.tags = normaliseTags(body.tags)
      if (body.rating !== undefined) item.rating = Math.max(0, Math.min(5, body.rating))
      if (body.favorite !== undefined) item.favorite = body.favorite
      item.updated_at = Date.now()
      return item
    }),
  )

  router.post('/api/shot-library/:id/duplicate', req =>
    store.mutate(state => {
      const source = find(state, req.params.id)
      const copy: LibraryShot = {
        ...source,
        id: newId(),
        title: `${source.title} (copy)`.slice(0, 200),
        used_count: 0,
        last_used_at: 0,
        favorite: false,
        archived: false,
        archived_at: null,
        created_at: Date.now(),
        updated_at: Date.now(),
      }
      state.shotLibrary.push(copy)
      return copy
    }),
  )

  router.post('/api/shot-library/:id/apply', req =>
    store.mutate(state => {
      const item = find(state, req.params.id)
      const body = req.body as {
        project_id?: string
        scene_id?: string
        shot_id?: string
        overwrite_prompt?: boolean
      }
      const project = state.projects[body.project_id ?? '']
      if (!project) throw new MockHttpError(404, `Project not found: ${body.project_id}`)
      const scene = project.scenes.find(s => s.id === body.scene_id)
      if (!scene) throw new MockHttpError(404, `Scene not found: ${body.scene_id}`)

      let shot = body.shot_id ? scene.shots.find(s => s.id === body.shot_id) : undefined
      if (body.shot_id && !shot) throw new MockHttpError(404, `Shot not found: ${body.shot_id}`)
      if (!shot) {
        const template = scene.shots[0]
        if (!template) throw new MockHttpError(400, 'That scene has no shot to model a new one on')
        shot = {
          ...structuredClone(template),
          id: `shot-${Date.now().toString(36)}`,
          order: scene.shots.length,
          title: item.title,
          status: 'draft',
          versions: [],
          current_version: null,
          capture_path: '',
        }
        scene.shots.push(shot)
      }

      shot.framing = structuredClone(item.framing)
      shot.camera_move = item.camera_move as FilmShot['camera_move']
      shot.duration_seconds = item.duration_seconds
      shot.generation.model = item.model
      shot.generation.resolution = item.resolution
      shot.generation.fps = item.fps
      shot.generation.seed = item.seed
      if (body.overwrite_prompt !== false && item.visual_prompt) {
        shot.visual_prompt = item.visual_prompt
        shot.prompt_locked = true
      }
      if (item.negative_prompt) shot.negative_prompt = item.negative_prompt
      shot.updated_at = Date.now()
      project.updated_at = Date.now()

      item.used_count += 1
      item.last_used_at = Date.now()
      return shot
    }),
  )

  router.post('/api/shot-library/:id/archive', req =>
    store.mutate(state => {
      const item = find(state, req.params.id)
      item.archived = true
      item.archived_at = Date.now()
      item.updated_at = Date.now()
      return item
    }),
  )

  router.post('/api/shot-library/:id/restore', req =>
    store.mutate(state => {
      const item = find(state, req.params.id)
      item.archived = false
      item.archived_at = null
      item.updated_at = Date.now()
      return item
    }),
  )

  router.delete('/api/shot-library/:id', req =>
    store.mutate(state => {
      const item = find(state, req.params.id)
      state.shotLibrary = state.shotLibrary.filter(i => i.id !== item.id)
      return { status: `deleted ${item.title}` }
    }),
  )
}
