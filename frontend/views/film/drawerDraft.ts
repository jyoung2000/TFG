/**
 * The shot drawer's form across server refreshes (QA pass 2026-10-01). The
 * drawer reset its whole form whenever the shot changed on the server - and
 * the queue poll changes `updated_at` every 2 s during a render - so text
 * being typed vanished mid-sentence. A refresh now updates only the fields the
 * user has not edited (still equal to the previous server value).
 */

export function syncDraft<T extends Record<string, unknown>>(draft: T, before: T, after: T): T {
  let next: T | null = null
  for (const key of Object.keys(after) as (keyof T)[]) {
    if (Object.is(after[key], before[key])) continue // unchanged on the server
    if (!Object.is(draft[key], before[key])) continue // the user edited it: keep theirs
    next ??= { ...draft }
    next[key] = after[key]
  }
  return next ?? draft
}
