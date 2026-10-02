/**
 * The trainer's model files for a target, as the Train screen shows them (QA
 * pass 2026-10-01): nothing in the app set them, so Start was enabled and a
 * musubi run failed minutes in. The backend reports each file as its path,
 * "missing: <path>" (gone from disk) or "" (not set); a target that loads by
 * model name (`name_or_path`) needs no file.
 */

export type WeightState = 'ok' | 'missing' | 'unset'

export const WEIGHT_LABELS: Record<string, string> = {
  dit: 'DiT model',
  vae: 'VAE',
  text_encoder: 'Text encoder',
  name_or_path: 'Base model (name or path)',
}

export interface WeightRow { key: string; label: string; state: WeightState; path: string }

export function weightStatus(weights: Record<string, Record<string, string>> | undefined, target: string): { rows: WeightRow[]; ready: boolean; blocker: string } {
  const row = weights?.[target] ?? {}
  const rows: WeightRow[] = Object.entries(row).map(([key, value]) => {
    const missing = value.startsWith('missing: ')
    return { key, label: WEIGHT_LABELS[key] ?? key, state: missing ? 'missing' : value ? 'ok' : 'unset', path: missing ? value.slice('missing: '.length) : value }
  })
  const needed = rows.filter(r => r.key !== 'name_or_path' && r.state !== 'ok')
  return {
    rows,
    ready: needed.length === 0,
    blocker: needed.length ? `Set the model files for this target (Trainer settings): ${needed.map(r => r.label).join(', ')}.` : '',
  }
}
