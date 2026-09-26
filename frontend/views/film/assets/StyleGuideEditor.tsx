/**
 * Editable style guide: trait chips, palette swatches, mood and the
 * generation prompt. Used in the asset detail (edits persist immediately)
 * and in the wizard's review column (edits are a draft until "Create").
 */

import { useState } from 'react'
import { X } from 'lucide-react'
import type { AssetStyleGuide } from '../../../types/film'
import { inputClass, paletteSwatch } from './shared'

export const EMPTY_GUIDE: AssetStyleGuide = { key_traits: [], color_palette: [], mood: '', recommended_prompt: '' }

export function StyleGuideEditor({ guide, onChange, onCommit }: {
  guide: AssetStyleGuide
  onChange: (guide: AssetStyleGuide) => void
  /** Called when an edit is "done" (chip added/removed, field blurred). */
  onCommit?: (guide: AssetStyleGuide) => void
}) {
  const [newTrait, setNewTrait] = useState('')
  const [newColor, setNewColor] = useState('')
  const apply = (next: AssetStyleGuide) => { onChange(next); onCommit?.(next) }

  return (
    <div className="space-y-2.5">
      <div>
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Key traits</span>
        <div className="flex flex-wrap gap-1 mt-1">
          {guide.key_traits.map((trait, i) => (
            <span key={`${trait}-${i}`} className="group flex items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-800 text-[10px] text-zinc-300">
              {trait}
              <button onClick={() => apply({ ...guide, key_traits: guide.key_traits.filter((_, j) => j !== i) })}
                aria-label={`Remove trait ${trait}`} className="text-zinc-600 hover:text-red-300"><X className="h-2.5 w-2.5" /></button>
            </span>
          ))}
          <span className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-dashed border-zinc-700 text-[10px]">
            <input value={newTrait} onChange={e => setNewTrait(e.target.value)} placeholder="+ trait" aria-label="Add trait"
              onKeyDown={e => { if (e.key === 'Enter' && newTrait.trim()) { apply({ ...guide, key_traits: [...guide.key_traits, newTrait.trim()] }); setNewTrait('') } }}
              className="w-16 bg-transparent text-zinc-300 placeholder:text-zinc-600 focus:outline-none" />
          </span>
        </div>
      </div>
      <div>
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Color palette</span>
        <div className="flex flex-wrap gap-1.5 mt-1">
          {guide.color_palette.map((color, i) => (
            <span key={`${color}-${i}`} className="flex flex-col items-center gap-0.5">
              <span className="relative group w-9 h-6 rounded border border-zinc-700" style={{ background: paletteSwatch(color) }}>
                <button onClick={() => apply({ ...guide, color_palette: guide.color_palette.filter((_, j) => j !== i) })}
                  aria-label={`Remove color ${color}`}
                  className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center w-3.5 h-3.5 rounded-full bg-zinc-900 border border-zinc-700 text-zinc-400 hover:text-red-300"><X className="h-2 w-2" /></button>
              </span>
              <span className="text-[9px] text-zinc-500 max-w-12 truncate" title={color}>{color}</span>
            </span>
          ))}
          <span className="flex items-center">
            <input value={newColor} onChange={e => setNewColor(e.target.value)} placeholder="+ hex or word" aria-label="Add color"
              onKeyDown={e => { if (e.key === 'Enter' && newColor.trim()) { apply({ ...guide, color_palette: [...guide.color_palette, newColor.trim()] }); setNewColor('') } }}
              className="w-20 bg-zinc-900 border border-dashed border-zinc-700 rounded px-1.5 py-1 text-[10px] text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600" />
            {newColor.trim() && <span className="ml-1 w-4 h-4 rounded-sm border border-zinc-700" style={{ background: paletteSwatch(newColor) }} />}
          </span>
        </div>
      </div>
      <label className="block">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Mood</span>
        <input className={inputClass + ' mt-0.5'} value={guide.mood} aria-label="Style guide mood"
          onChange={e => onChange({ ...guide, mood: e.target.value })} onBlur={() => onCommit?.(guide)} />
      </label>
      <label className="block">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Generation prompt</span>
        <textarea className={inputClass + ' mt-0.5 font-mono resize-none h-20'} value={guide.recommended_prompt} aria-label="Style guide generation prompt"
          onChange={e => onChange({ ...guide, recommended_prompt: e.target.value })} onBlur={() => onCommit?.(guide)} />
      </label>
    </div>
  )
}
