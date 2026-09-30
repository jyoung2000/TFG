/** "Analyse with" - which vision model reads the reference.

There was no dropdown: Reproduce image offered only a "change vision AI" link
into Settings -> Vision, so the choice was two screens away and could not be
made per job.

The list comes from GET /api/vision/models and is honest in both directions:
a text-only model is shown and marked, not hidden (the user can see what they
have and why it is not offered), and two names sharing one digest are collapsed
by the backend, so `llava:latest` and `llava:7b` - the same weights - appear
once rather than as a phantom pair.

Measured on the audit machine: 12 models, 7 image-capable, 5 text-only. Of the
image-capable ones only three are proven to work with the reproduce flow:

  qwen2.5vl:7b  works  (81.7 s; filled scene, lighting, style and narrative)
  llava:7b      works  (scene, lighting, narrative)
  llava:13b     works  but reads the white cyclorama as "indoors"
  llama3.2-vision  fails  ollama API error (500)
  llava:latest     fails  request timed out at 180 s
  moondream:1.8b   fails  "no JSON returned"
  gemma4:12b        untested - it reports vision but was not exercised

So the dropdown lists what CAN read an image; whether each one produces a good
spec is a separate question, answered per model by the run itself.
*/

import { useEffect, useState } from 'react'

import { backendFetch } from '../../lib/backend'

export interface VisionModelEntry {
  id: string
  name: string
  provider: string
  size_gb: number | null
  can_analyse_images: boolean
  detail: string
}

export interface VisionModelList {
  models: VisionModelEntry[]
  note: string
}

export interface AnalyseWithChoice {
  id: string
  label: string
}

/** Models that may be chosen: the image-capable ones, vision models first. */
export function partitionVisionModels(models: readonly VisionModelEntry[]): {
  usable: AnalyseWithChoice[]
  textOnly: AnalyseWithChoice[]
} {
  const usable: AnalyseWithChoice[] = []
  const textOnly: AnalyseWithChoice[] = []
  for (const m of models) {
    const label = `${m.name || m.id}${m.size_gb ? ` · ${m.size_gb} GB` : ''}`
    if (m.can_analyse_images) usable.push({ id: m.id, label })
    else textOnly.push({ id: m.id, label: `${label} — text only, cannot read an image` })
  }
  return { usable, textOnly }
}

async function fetchVisionModels(): Promise<VisionModelList> {
  const response = await backendFetch('/api/vision/models')
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return (await response.json()) as VisionModelList
}

interface Props {
  /** The model in use, '' when none is chosen explicitly. */
  value: string
  onChange: (id: string) => void
  disabled?: boolean
}

export function AnalyseWith({ value, onChange, disabled }: Props) {
  const [list, setList] = useState<VisionModelList | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    // The app's own client: backendFetch resolves to the mock server in UI-only
    // mode and to localhost:8000 in the app. A literal URL to :8000 fails with
    // ERR_CONNECTION_REFUSED under `pnpm e2e`, which asserts a clean console.
    fetchVisionModels()
      .then(r => {
        if (live) setList(r)
      })
      .catch((e: unknown) => {
        if (live) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      live = false
    }
  }, [])

  const { usable, textOnly } = partitionVisionModels(list?.models ?? [])

  return (
    <span className="inline-flex items-center gap-1" data-testid="analyse-with">
      <label className="text-xs text-zinc-500" htmlFor="analyse-with-select">
        Analyse with
      </label>
      <select
        id="analyse-with-select"
        aria-label="Analyse with"
        className="select-chip text-xs"
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
      >
        <option value="">{list ? 'Current setting' : 'loading…'}</option>
        {usable.map(m => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        {textOnly.length > 0 && (
          <optgroup label="Cannot read an image" disabled>
            {textOnly.map(m => (
              <option key={m.id} value={`text:${m.id}`} disabled>
                {m.label}
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {list?.note && <span className="text-xs text-amber-300">{list.note}</span>}
      {error && <span className="text-xs text-red-300">Could not list vision models: {error}</span>}
    </span>
  )
}
