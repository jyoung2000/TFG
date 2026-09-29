/** "Render with" — which installed local image model renders the candidates.

Before this existed the UI's own caption said "Candidates always render with
{job.image_model}" next to tabs for LTX-2, Wan 2.2, SDXL and FLUX, none of
which changed the renderer: the backend picked the model from an environment
variable at startup. Only models that are on disk and runnable here may be
chosen; the rest stay visible but disabled, with their reason.

Measured on the audit machine (RTX 4070, 12282 MiB) against reference
bytedance_seedream-v5-0-pro_edit at 1536x2730 - all four load and render, and
the spread is 0.6996-0.7325 composite, i.e. close to noise:

  z_image                    Z-Image Turbo int8, 6.89 GB   best 0.7113
  z_image_nunchaku_r128_fp4  3.91 GB                        best 0.7257
  z_image_nunchaku_r256_int4 4.23 GB                        best 0.7325
  flux2_klein_4b             FLUX.2 klein 4B, 4.07 GB       best 0.6996

SDXL has no definition in the Wan2GP checkout at all, so it must never appear
as available.
*/

import { useEffect, useState } from 'react'

export interface RenderWithModel {
  id: string
  name: string
  installed: boolean
  size_gb: number | null
  estimated_min_vram_gb: number | null
  fits_gpu: boolean | null
}

/** Why a model cannot be chosen, or '' when it can. */
export function blockedReason(m: RenderWithModel): string {
  if (m.installed) return ''
  if (m.fits_gpu === false && m.estimated_min_vram_gb) return `needs ${m.estimated_min_vram_gb} GB VRAM`
  return 'weights not downloaded'
}

export interface RenderWithChoice {
  id: string
  label: string
}

/** Split the library into what may be chosen and what may not. */
export function partitionModels(models: readonly RenderWithModel[], limitBlocked = 6): {
  available: RenderWithChoice[]
  blocked: RenderWithChoice[]
} {
  const available: RenderWithChoice[] = []
  const blocked: RenderWithChoice[] = []
  for (const m of models) {
    const label = `${m.name || m.id}${m.size_gb ? ` · ${m.size_gb} GB` : ''}`
    const reason = blockedReason(m)
    if (!reason) available.push({ id: m.id, label })
    else if (blocked.length < limitBlocked) blocked.push({ id: m.id, label: `${label} — ${reason}` })
  }
  return { available, blocked }
}

interface Props {
  value: string
  onChange: (id: string) => void
  disabled?: boolean
}

const DEFAULT_URL = 'http://localhost:8000'

export function RenderWith({ value, onChange, disabled }: Props) {
  const [models, setModels] = useState<RenderWithModel[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`${DEFAULT_URL}/api/models/library?task=image&source=local&limit=200`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { models?: RenderWithModel[] }) => {
        if (cancelled) return
        setModels(d.models ?? [])
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(`Could not read the model library: ${String(e)}`)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const { available, blocked } = partitionModels(models ?? [])

  return (
    <div className="space-y-1" data-testid="render-with">
      <label className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold" htmlFor="render-with-select">
        Render with
      </label>
      <select
        id="render-with-select"
        aria-label="Render with"
        className="select-chip w-full"
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
      >
        <option value="">{models ? 'Backend default' : 'loading…'}</option>
        {available.map(m => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        {blocked.length > 0 && (
          <optgroup label="Not installed" disabled>
            {blocked.map(m => (
              <option key={m.id} value={`blocked:${m.id}`} disabled>
                {m.label}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {error && <p className="text-[11px] text-red-300">{error}</p>}
      {available.length === 0 && !error && models && (
        <p className="text-[11px] text-amber-300">
          No local image model is installed. Download one in Settings → AI Models.
        </p>
      )}
    </div>
  )
}
