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

/**
 * A trainer's header chip (QA pass 2026-10-01): it said "ready" for an
 * installed trainer whose model files were never set, while Start stayed off.
 * Ready means installed and at least one target has every file it needs.
 */
export function trainerChip(
  trainer: { installed: boolean; fits_12gb: boolean; reason: string; notes: string; targets: string[]; ready_targets?: string[] },
  weights: Record<string, Record<string, string>> | undefined,
): { text: string; tone: 'ready' | 'idle' | 'warn'; title: string } {
  if (!trainer.installed) {
    return trainer.fits_12gb
      ? { text: 'not installed', tone: 'idle', title: trainer.reason || trainer.notes }
      : { text: 'needs more than 12 GB', tone: 'warn', title: trainer.reason || trainer.notes }
  }
  const statuses = trainer.targets.map(target => weightStatus(weights, target))
  // The backend's answer when it gives one: the same checks Start makes. A
  // name-only row (FLUX) looked ready here though musubi needs files for it.
  const ready = trainer.ready_targets ? trainer.ready_targets.length > 0 : statuses.length === 0 || statuses.some(status => status.ready)
  if (ready) return { text: 'ready', tone: 'ready', title: trainer.ready_targets ? `Ready for ${trainer.ready_targets.join(', ')}. ${trainer.notes}` : trainer.notes }
  const blocker = statuses.find(status => !status.ready)?.blocker
  return { text: 'needs model files', tone: 'warn', title: blocker || 'Set the model files for a target in Trainer settings.' }
}
