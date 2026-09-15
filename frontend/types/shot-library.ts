// Mirrors backend/film/shot_library_models.py and shot_library_api_types.py.

import type { ShotFraming } from './film'

export type PreviewKind = 'video' | 'image' | 'none'

/** Where an item came from. A record, never a dependency. */
export interface LibraryLineage {
  project_id: string
  project_name: string
  scene_id: string
  scene_title: string
  shot_id: string
  shot_title: string
  version_number: number | null
  captured_at: number
}

export interface LibraryShot {
  id: string
  title: string
  notes: string

  // What gets applied to a shot that uses this.
  visual_prompt: string
  negative_prompt: string
  framing: ShotFraming
  camera_move: string
  duration_seconds: number
  model: string
  resolution: string
  fps: number
  seed: number | null
  aspect_ratio: string
  style: string

  /** A copy in the library's own directory, so the entry outlives its source. */
  preview_path: string
  preview_kind: PreviewKind

  lineage: LibraryLineage

  tags: string[]
  /** 0 means unrated, which is not the same as rated zero. */
  rating: number
  favorite: boolean
  /** Archived items are hidden by default and restorable; deletion is not. */
  archived: boolean
  archived_at: number | null

  used_count: number
  last_used_at: number
  created_at: number
  updated_at: number
}

export interface LibraryListing {
  items: LibraryShot[]
  /** Every tag in use with its count, so the filter needs no second call. */
  tags: Record<string, number>
  total: number
}

export type LibrarySort = 'recent' | 'rating' | 'used' | 'title'

export const SORT_LABELS: Record<LibrarySort, string> = {
  recent: 'Recently updated',
  rating: 'Highest rated',
  used: 'Most used',
  title: 'Title',
}
