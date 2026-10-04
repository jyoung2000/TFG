// Pure helpers for Settings -> Models.

import type { SearchableOption } from '../components/ui/searchable-select'
import type { LibraryModel } from '../types/models'
import type { AngleChoice, InstalledModel } from './model-manager-api'

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  if (n < 1024) return `${Math.round(n)} B`
  if (n < 1024 ** 2) return `${Math.round(n / 1024)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(1)} GB`
}

export interface InstalledGroup {
  title: string
  models: InstalledModel[]
}

const GROUPS: { title: string; kinds: InstalledModel['kind'][] }[] = [
  { title: 'Image & video models', kinds: ['wangp'] },
  { title: 'Shared components', kinds: ['component'] },
  { title: 'Other models', kinds: ['folder'] },
  { title: 'LoRAs', kinds: ['lora', 'lora-file'] },
]

export function groupInstalled(models: InstalledModel[]): InstalledGroup[] {
  return GROUPS.map((g) => ({
    title: g.title,
    models: models.filter((m) => g.kinds.includes(m.kind)).sort((a, b) => b.size_bytes - a.size_bytes),
  })).filter((g) => g.models.length > 0)
}

function rowDetail(r: LibraryModel): string {
  const size = r.size_gb != null && r.size_gb > 0 ? `${Math.round(r.size_gb * 10) / 10} GB` : ''
  return [r.provider, size].filter(Boolean).join(' · ')
}

export function defaultOptions(rows: LibraryModel[], _task: string, current: string): SearchableOption[] {
  const installed: SearchableOption[] = rows
    .filter((r) => r.installed)
    .map((r) => ({ value: r.id, label: r.name, detail: rowDetail(r), group: 'Installed' }))
  const missing: SearchableOption[] = rows
    .filter((r) => !r.installed)
    .map((r) => ({
      value: r.id,
      label: r.name,
      detail: rowDetail(r),
      group: 'Not installed',
      disabled: true,
      badge: 'download first',
    }))
  const out = [...installed, ...missing]
  if (current && !out.some((o) => o.value === current)) {
    out.unshift({ value: current, label: current, group: 'Installed' })
  }
  return out
}

export function angleOptions(choices: AngleChoice[]): SearchableOption[] {
  return [
    { value: '', label: 'Automatic' },
    ...choices.map((c) =>
      c.installed
        ? { value: c.id, label: c.label }
        : { value: c.id, label: c.label, disabled: true, badge: 'not installed' },
    ),
  ]
}

const WEIGHT_EXT = /\.(safetensors|gguf|ckpt|pt|pth|bin)$/i

export function isValidLink(url: string): boolean {
  let u: URL
  try {
    u = new URL(url.trim())
  } catch {
    return false
  }
  if (u.protocol !== 'https:') return false
  if (WEIGHT_EXT.test(u.pathname)) return true
  return u.hostname === 'huggingface.co' && /^\/[^/]+\/[^/]+\/resolve\/.+/.test(u.pathname)
}
