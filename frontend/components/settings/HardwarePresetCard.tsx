import { useCallback, useEffect, useState } from 'react'
import { Check, Gauge, Loader2 } from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { presetsApi, type HardwarePresetsResponse } from '../../lib/presets-api'
import { Button } from '../ui/button'

/**
 * Settings → General: the hardware preset for this card. Shows the detected
 * GPU, which preset fits it, what the preset sets, and applies it in one
 * click. The RTX 4070 12 GB preset is also applied automatically on first run.
 */
export function HardwarePresetCard() {
  const { refreshSettings, settings } = useAppSettings()
  const [data, setData] = useState<HardwarePresetsResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try { setData(await presetsApi.list()); setError('') } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [])
  useEffect(() => { void load() }, [load, settings.hardwarePreset])

  const apply = async (id: string) => {
    setBusy(id)
    try { await presetsApi.apply(id); await refreshSettings(); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy('') }
  }

  return (
    <div className="space-y-3" data-testid="hardware-preset">
      <div className="flex items-center gap-2">
        <Gauge className="h-4 w-4 text-fuchsia-300" />
        <h3 className="text-sm font-semibold text-white">Hardware preset</h3>
        {data && <span className="text-xs text-zinc-500">{data.gpu_name ?? 'No GPU detected'}{data.gpu_vram_gb != null ? ` · ${data.gpu_vram_gb} GB` : ''}</span>}
      </div>
      {error && <p className="text-xs text-red-300" role="alert">{error}</p>}
      {data?.presets.map(preset => (
        <div key={preset.id} className={`rounded-lg border p-3 space-y-2 ${preset.applied ? 'border-fuchsia-800/70 bg-fuchsia-950/20' : 'border-zinc-800 bg-zinc-800/40'}`}>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-white font-medium">{preset.name}</span>
            {preset.recommended && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300">Recommended for this GPU</span>}
            {preset.applied && <span className="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-900/50 text-fuchsia-200 flex items-center gap-1"><Check className="h-3 w-3" /> Applied</span>}
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void apply(preset.id)} className="ml-auto h-7 px-2 text-xs text-zinc-200 hover:text-white hover:bg-zinc-700" aria-label={`Apply ${preset.name}`}>
              {busy === preset.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : preset.applied ? 'Re-apply' : 'Apply'}
            </Button>
          </div>
          <p className="text-xs text-zinc-400">{preset.description}</p>
          <ul className="text-[11px] text-zinc-500 list-disc pl-4 space-y-0.5">{preset.changes.map(line => <li key={line}>{line}</li>)}</ul>
          <p className="text-[11px] text-zinc-500">Video profiles: {preset.video_profiles.map(p => `${p.label} (${p.resolution} · ${p.duration_seconds} s)`).join(' · ')}. Wan 2.2 5B TI2V as a second video profile is not offered: its WanGP model key could not be verified in this session.</p>
        </div>
      ))}
    </div>
  )
}
