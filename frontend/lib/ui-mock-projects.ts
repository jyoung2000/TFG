/**
 * Puts the demo film on Home in UI-only mode.
 *
 * The project list lives in this renderer's `localStorage`, not in the backend,
 * so a fresh browser profile would show an empty Home and the mock backend's
 * seeded film would be unreachable. Writing one entry — only when the list is
 * empty — makes UI-only mode open on the same thing every time, while "New
 * film" still creates an empty project exactly as it does in the real app.
 *
 * Loaded only when `VITE_UI_MOCK` is set, so it is absent from the app.
 */

import { createDefaultTimeline, type Project } from '../types/project'

const STORAGE_KEY = 'ltx-projects'
/** Must match DEMO_PROJECT_ID in devtools/ui-mock/seed.ts. */
const DEMO_PROJECT_ID = 'ui-mock-film'

export function seedDemoProject(): void {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed: unknown = JSON.parse(stored)
      if (Array.isArray(parsed) && parsed.length > 0) return
    }
    const timeline = createDefaultTimeline('Timeline 1')
    const project: Project = {
      id: DEMO_PROJECT_ID,
      name: 'The Relay (demo)',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      assets: [],
      timelines: [timeline],
      activeTimelineId: timeline.id,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify([project]))
  } catch {
    // A browser with storage disabled still gets a usable (empty) Home.
  }
}
