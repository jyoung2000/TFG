/**
 * Pick a saved style (lib/styles-api.ts) for the image and video generators: the
 * render is drawn in it (FLUX.1 USO from its pictures, else FLUX.2 Klein).
 */
import { useEffect, useRef, useState } from 'react'
import { Check, Palette, Plus } from 'lucide-react'
import { useProjects } from '../contexts/ProjectContext'
import { stylesApi, type SavedStyle } from '../lib/styles-api'

/** One of a style's pictures. */
export function StyleThumb({ style, index = 0, className = '' }: { style: SavedStyle; index?: number; className?: string }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let gone = false
    let made: string | null = null
    if (style.images.length <= index) return
    stylesApi.imageUrl(style.id, index)
      .then(u => { made = u; if (gone) URL.revokeObjectURL(u); else setUrl(u) })
      .catch(() => { /* the tile stays blank */ })
    return () => { gone = true; if (made) URL.revokeObjectURL(made) }
  }, [style.id, style.images.length, index])
  return url ? <img src={url} alt="" className={`${className} object-cover`} /> : <div className={`${className} bg-zinc-800`} />
}

/** The saved styles as tiles; `value` '' = no style. */
export function StylePicker({ value, onChange, disabled }: {
  value: string
  onChange: (styleId: string) => void
  disabled?: boolean
}) {
  const { setCurrentView } = useProjects()
  const [styles, setStyles] = useState<SavedStyle[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    stylesApi.list().then(setStyles).catch((e: unknown) => { setStyles([]); setError(e instanceof Error ? e.message : String(e)) })
  }, [])
  const chosen = styles?.find(s => s.id === value)
  const tile = (selected: boolean) =>
    `relative flex flex-col items-stretch gap-1 rounded-lg border p-1 text-left text-[11px] transition-colors disabled:opacity-40 ${selected ? 'border-fuchsia-400 bg-fuchsia-950/40 text-white' : 'border-zinc-800 bg-zinc-900 text-zinc-300 hover:border-zinc-600'}`
  return (
    <div className="space-y-2" data-testid="style-picker">
      <div className="grid grid-cols-3 gap-2">
        <button type="button" disabled={disabled} onClick={() => onChange('')} className={tile(!value)} aria-pressed={!value} data-testid="style-none">
          <div className="flex h-16 items-center justify-center rounded bg-zinc-800 text-zinc-500">None</div>
          <span className="truncate px-0.5">No style</span>
        </button>
        {styles?.map(style => (
          <button key={style.id} type="button" disabled={disabled} onClick={() => onChange(style.id)} className={tile(style.id === value)}
            aria-pressed={style.id === value} title={style.style_prompt || style.name} data-testid={`style-${style.id}`}>
            <StyleThumb style={style} className="h-16 w-full rounded" />
            <span className="truncate px-0.5">{style.name}</span>
            {style.id === value && <Check className="absolute right-1.5 top-1.5 h-3.5 w-3.5 rounded-full bg-fuchsia-500 p-0.5 text-white" />}
          </button>
        ))}
        <button type="button" onClick={() => setCurrentView('styles')} className={tile(false)} data-testid="style-save-new">
          <div className="flex h-16 items-center justify-center rounded border border-dashed border-zinc-700 text-zinc-400"><Plus className="h-4 w-4" /></div>
          <span className="truncate px-0.5">Save a style</span>
        </button>
      </div>
      {chosen && (
        <p className="text-[11px] leading-snug text-zinc-400" data-testid="style-chosen">
          <span className="text-fuchsia-300">{chosen.name}:</span> {chosen.style_prompt || 'drawn from its pictures'}
        </p>
      )}
      {styles?.length === 0 && !error && <p className="text-[11px] text-zinc-500">No saved styles yet. Save one from an image (home menu, Save style).</p>}
      {error && <p className="text-[11px] text-red-400">Styles unavailable: {error}</p>}
    </div>
  )
}

/** A toolbar button with the picker in a popover (Gen Space). */
export function StyleButton({ value, onChange, disabled }: { value: string; onChange: (styleId: string) => void; disabled?: boolean }) {
  const [isOpen, setIsOpen] = useState(false)
  const [name, setName] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setIsOpen(false) }
    if (isOpen) document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [isOpen])
  useEffect(() => {
    if (!value) { setName(''); return }
    stylesApi.list().then(all => setName(all.find(s => s.id === value)?.name ?? '')).catch(() => setName(''))
  }, [value])
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setIsOpen(!isOpen)} aria-expanded={isOpen} data-testid="style-button"
        className={`flex shrink-0 items-center gap-1 whitespace-nowrap px-2 py-1.5 rounded-md transition-colors ${isOpen ? 'bg-zinc-700 hover:bg-zinc-700' : 'hover:bg-zinc-800'}`}>
        <Palette className="h-3.5 w-3.5" />
        <span className={value ? 'text-fuchsia-200' : ''}>{name || 'Style'}</span>
      </button>
      {isOpen && (
        <div className="absolute bottom-full right-0 mb-2 w-80 rounded-md border border-zinc-700 bg-zinc-800 p-2 shadow-xl z-[9999] space-y-2" data-testid="style-panel">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">Style</div>
          <StylePicker value={value} onChange={id => { onChange(id); setIsOpen(false) }} disabled={disabled} />
        </div>
      )}
    </div>
  )
}
