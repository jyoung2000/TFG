import { useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
import { trainingApi } from '../lib/training-api'
import type { LoraEntry, LoraUse } from '../types/training'

interface LoraPickerProps {
  /** Base model id (`z_image`, `qwen_image_20B`, `ltx2_22B_distilled`…) — only compatible LoRAs are offered. */
  model: string
  value: LoraUse[]
  onChange: (next: LoraUse[]) => void
  disabled?: boolean
  compact?: boolean
}

/**
 * Registry-backed LoRA picker shared by Create, Reproduce and Film: toggle a
 * LoRA on, set its strength, and see the trigger word to put in the prompt.
 */
export function LoraPicker({ model, value, onChange, disabled, compact }: LoraPickerProps) {
  const [entries, setEntries] = useState<LoraEntry[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    trainingApi.listLoras({ model }).then(list => { if (!cancelled) { setEntries(list); setError('') } }).catch(e => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [model])

  if (error) return <p className="text-[11px] text-zinc-600" data-testid="lora-picker">LoRAs unavailable: {error}</p>
  if (entries.length === 0) return <p className="text-[11px] text-zinc-600" data-testid="lora-picker"><Layers className="inline h-3 w-3 mr-1 align-[-2px]" />No LoRAs for this model yet — train one from the Train tab.</p>

  const toggle = (entry: LoraEntry) => {
    const on = value.some(v => v.name === entry.file)
    onChange(on ? value.filter(v => v.name !== entry.file) : [...value, { name: entry.file, multiplier: entry.default_multiplier }])
  }
  const setMultiplier = (entry: LoraEntry, multiplier: number) => onChange(value.map(v => (v.name === entry.file ? { ...v, multiplier } : v)))

  return (
    <div className={`space-y-1 ${compact ? '' : 'rounded border border-zinc-800 p-2'}`} data-testid="lora-picker">
      {!compact && <span className="text-[10px] text-zinc-500 uppercase tracking-wide">LoRAs</span>}
      {entries.map(entry => {
        const use = value.find(v => v.name === entry.file)
        return (
          <label key={entry.id} className="flex items-center gap-2 text-xs text-zinc-300">
            <input type="checkbox" checked={!!use} disabled={disabled} onChange={() => toggle(entry)} aria-label={`Use LoRA ${entry.name}`} />
            <span className="truncate flex-1" title={entry.file}>{entry.name}{entry.trigger ? <span className="text-zinc-500"> · trigger “{entry.trigger}”</span> : null}</span>
            {use && (
              <input type="number" step="0.05" min="0" max="2" value={use.multiplier} disabled={disabled} onChange={e => setMultiplier(entry, Number(e.target.value))} aria-label={`Strength for ${entry.name}`} className="w-16 bg-zinc-900 border border-zinc-700 rounded px-1 py-0.5 text-[11px] text-zinc-200" />
            )}
          </label>
        )
      })}
    </div>
  )
}

/** Trigger words for the selected LoRAs, to prepend to a prompt. */
export function loraTriggers(entries: LoraEntry[], value: LoraUse[]): string[] {
  return entries.filter(e => value.some(v => v.name === e.file) && e.trigger).map(e => e.trigger)
}
