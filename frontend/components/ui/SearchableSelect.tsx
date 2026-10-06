import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'
import { filterOptions, nextActiveIndex, type SearchableOption } from './searchable-select'

interface SearchableSelectProps {
  value: string
  options: SearchableOption[]
  onChange: (value: string) => void
  placeholder?: string
  label?: string
  disabled?: boolean
  emptyText?: string
  testId?: string
  className?: string
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder = 'Select…',
  label,
  disabled,
  emptyText = 'No matches',
  testId,
  className = '',
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const selected = options.find((o) => o.value === value)
  const filtered = useMemo(() => filterOptions(options, query), [options, query])

  const close = (refocus: boolean) => {
    setOpen(false)
    setQuery('')
    if (refocus) buttonRef.current?.focus()
  }

  const select = (o: SearchableOption) => {
    if (o.disabled) return
    onChange(o.value)
    close(true)
  }

  const openPanel = () => {
    if (disabled) return
    setQuery('')
    const idx = options.findIndex((o) => o.value === value && !o.disabled)
    setActive(idx >= 0 ? idx : nextActiveIndex(options, -1, 1))
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  useEffect(() => {
    if (!open || active < 0) return
    rootRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [active, open])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(nextActiveIndex(filtered, active, e.key === 'ArrowDown' ? 1 : -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const o = filtered[active]
      if (o) select(o)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      close(true)
    }
  }

  return (
    <div ref={rootRef} data-testid={testId} className={`relative ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        onClick={() => (open ? close(false) : openPanel())}
        className="flex w-full items-center gap-2 rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-left text-sm text-zinc-200 hover:border-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <span className={`flex-1 truncate ${selected ? '' : 'text-zinc-500'}`}>{selected ? selected.label : placeholder}</span>
        {selected?.badge && (
          <span className="shrink-0 rounded-full bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{selected.badge}</span>
        )}
        <ChevronDown className="h-4 w-4 shrink-0 text-zinc-500" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-full min-w-[14rem] rounded-md border border-zinc-700 bg-zinc-900 shadow-xl">
          <div className="flex items-center gap-2 border-b border-zinc-800 px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(nextActiveIndex(filterOptions(options, e.target.value), -1, 1))
              }}
              onKeyDown={onKeyDown}
              placeholder="Search…"
              aria-label={label ? `Search ${label}` : 'Search'}
              className="w-full bg-transparent text-sm text-zinc-200 placeholder:text-zinc-600 outline-none"
            />
          </div>
          <div role="listbox" aria-label={label} className="max-h-[18rem] overflow-y-auto py-1">
            {filtered.length === 0 && <div className="px-3 py-2 text-xs text-zinc-500">{emptyText}</div>}
            {filtered.map((o, i) => (
              <div key={o.value}>
                {o.group && o.group !== filtered[i - 1]?.group && (
                  <div className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">{o.group}</div>
                )}
                <div
                  role="option"
                  data-testid="searchable-select-option"
                  data-index={i}
                  aria-selected={o.value === value}
                  aria-disabled={o.disabled || undefined}
                  onMouseEnter={() => !o.disabled && setActive(i)}
                  onClick={() => select(o)}
                  className={`flex items-center gap-2 px-3 py-1.5 text-sm ${
                    o.disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
                  } ${i === active ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-300'}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{o.label}</div>
                    {o.detail && <div className="truncate text-xs text-zinc-500">{o.detail}</div>}
                  </div>
                  {o.badge && (
                    <span className="shrink-0 rounded-full bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{o.badge}</span>
                  )}
                  {o.value === value && <Check className="h-3.5 w-3.5 shrink-0 text-violet-400" />}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
