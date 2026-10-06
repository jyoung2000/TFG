export interface SearchableOption {
  value: string
  label: string
  detail?: string
  group?: string
  disabled?: boolean
  badge?: string
}

export function filterOptions(options: SearchableOption[], query: string): SearchableOption[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (words.length === 0) return options
  return options.filter((o) => {
    const hay = [o.label, o.detail, o.value, o.group].filter(Boolean).join('\n').toLowerCase()
    return words.every((w) => hay.includes(w))
  })
}

export function nextActiveIndex(options: SearchableOption[], current: number, direction: 1 | -1): number {
  const n = options.length
  if (n === 0) return -1
  const start = current < 0 ? (direction === 1 ? -1 : 0) : current
  for (let step = 1; step <= n; step++) {
    const i = (((start + direction * step) % n) + n) % n
    if (!options[i].disabled) return i
  }
  return -1
}
