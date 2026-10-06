import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Download, FolderInput, HardDrive, Loader2, Search, Trash2, X } from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { SearchableSelect } from '../ui/SearchableSelect'
import { jobsApi } from '../../lib/jobs-api'
import { modelLibraryApi } from '../../lib/model-library-api'
import {
  modelManagerApi,
  type AngleStatus,
  type HubFile,
  type HubModel,
  type InstalledInventory,
  type InstalledModel,
  type StorageArea,
  type StorageAreaId,
} from '../../lib/model-manager-api'
import { angleOptions, defaultOptions, formatBytes, groupInstalled, isValidLink } from '../../lib/modelManager'
import type { LibraryModel } from '../../types/models'

const DESTINATIONS: { id: StorageAreaId; label: string }[] = [
  { id: 'checkpoints', label: 'WanGP checkpoints' },
  { id: 'loras', label: 'LoRAs' },
  { id: 'models', label: 'App models' },
]

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {hint && <p className="text-xs text-zinc-500">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function ErrorLine({ text }: { text: string }) {
  if (!text) return null
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
      <p className="text-xs text-red-300">{text}</p>
    </div>
  )
}

function DestinationSelect({ value, onChange }: { value: StorageAreaId; onChange: (v: StorageAreaId) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as StorageAreaId)}
      aria-label="Download destination"
      className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-200"
    >
      {DESTINATIONS.map((d) => (
        <option key={d.id} value={d.id}>
          {d.label}
        </option>
      ))}
    </select>
  )
}

// ---------------------------------------------------------------- defaults

function DefaultModels() {
  const { settings, updateSettings } = useAppSettings()
  const [video, setVideo] = useState<LibraryModel[]>([])
  const [image, setImage] = useState<LibraryModel[]>([])
  const [angles, setAngles] = useState<AngleStatus | null>(null)
  const [saved, setSaved] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    modelLibraryApi
      .search({ task: 'video', source: 'local' })
      .then((r) => !cancelled && setVideo(r.models))
      .catch((e) => !cancelled && setError(errText(e)))
    modelLibraryApi
      .search({ task: 'image', source: 'local' })
      .then((r) => !cancelled && setImage(r.models))
      .catch((e) => !cancelled && setError(errText(e)))
    modelManagerApi
      .angleStatus()
      .then((s) => !cancelled && setAngles(s))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  const save = (label: string, patch: Parameters<typeof updateSettings>[0]) => {
    updateSettings(patch)
    setSaved(label)
    window.setTimeout(() => setSaved((s) => (s === label ? '' : s)), 1800)
  }

  const videoOpts = useMemo(() => defaultOptions(video, 'video', settings.defaultVideoModel), [video, settings.defaultVideoModel])
  const imageOpts = useMemo(() => defaultOptions(image, 'image', settings.defaultImageModel), [image, settings.defaultImageModel])
  const angleOpts = useMemo(() => angleOptions(angles?.choices ?? []), [angles])

  const rows: { label: string; value: string; options: ReturnType<typeof angleOptions>; patch: (v: string) => Parameters<typeof updateSettings>[0]; now?: string }[] = [
    { label: 'Video generation', value: settings.defaultVideoModel, options: videoOpts, patch: (v) => ({ defaultVideoModel: v }) },
    { label: 'Image generation', value: settings.defaultImageModel, options: imageOpts, patch: (v) => ({ defaultImageModel: v }) },
    {
      label: 'Multiple angles — characters & scenes',
      value: settings.characterAngleModel,
      options: angleOpts,
      patch: (v) => ({ characterAngleModel: v }),
      now: angles?.characters,
    },
    {
      label: 'Multiple angles — objects',
      value: settings.objectAngleModel,
      options: angleOpts,
      patch: (v) => ({ objectAngleModel: v }),
      now: angles?.objects,
    },
  ]

  return (
    <Section title="Default models" hint="The model each task uses unless you pick another one on the spot.">
      <ErrorLine text={error} />
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.label} data-testid="default-model-row" className="flex items-center gap-3 rounded-lg bg-zinc-800/50 p-3">
            <div className="w-56 shrink-0">
              <p className="text-sm text-zinc-200">{r.label}</p>
              {r.now !== undefined && <p className="text-xs text-zinc-500">Now: {r.now}</p>}
            </div>
            <SearchableSelect
              className="min-w-0 flex-1"
              value={r.value}
              options={r.options}
              label={r.label}
              placeholder="Automatic"
              onChange={(v) => save(r.label, r.patch(v))}
            />
            <span className="w-12 text-xs text-emerald-400">{saved === r.label ? 'Saved' : ''}</span>
          </div>
        ))}
      </div>
    </Section>
  )
}

// --------------------------------------------------------------- installed

function InstalledList({
  inventory,
  onChange,
}: {
  inventory: InstalledInventory | null
  onChange: (inv: InstalledInventory) => void
}) {
  const [busy, setBusy] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  if (!inventory) return <p className="text-xs text-zinc-500">Loading installed models…</p>
  const groups = groupInstalled(inventory.models)

  const uninstall = async (m: InstalledModel) => {
    if (
      !window.confirm(
        `Uninstall ${m.name}? Its files (${formatBytes(m.size_bytes)}) are deleted. Files other installed models share are kept.`,
      )
    )
      return
    setBusy(m.id)
    setErrors((e) => ({ ...e, [m.id]: '' }))
    try {
      onChange(await modelManagerApi.uninstall(m.id))
    } catch (e) {
      setErrors((prev) => ({ ...prev, [m.id]: errText(e) }))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-400">
        {inventory.models.length} models · {formatBytes(inventory.total_bytes)}
      </p>
      {groups.map((g) => (
        <div key={g.title} className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">{g.title}</p>
          {g.models.map((m) => (
            <div key={m.id} data-testid="installed-model-row" className="rounded-lg bg-zinc-800/50 p-3">
              <div className="flex items-center gap-3">
                <HardDrive className="h-4 w-4 shrink-0 text-zinc-500" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-zinc-200">{m.name}</p>
                  {m.note && <p className="truncate text-xs text-zinc-500">{m.note}</p>}
                </div>
                <span className="shrink-0 text-xs text-zinc-300">
                  {formatBytes(m.size_bytes)}
                  {m.shared_bytes > 0 && <span className="text-zinc-500"> + {formatBytes(m.shared_bytes)} shared</span>}
                </span>
                <button
                  type="button"
                  data-testid="uninstall-model"
                  disabled={busy === m.id}
                  onClick={() => void uninstall(m)}
                  className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                >
                  {busy === m.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Uninstall
                </button>
              </div>
              {errors[m.id] && <p className="mt-1.5 text-xs text-red-300">{errors[m.id]}</p>}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------- add

function DownloadProgress({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const [state, setState] = useState({ status: 'queued', progress: 0, phase: '', error: '' })
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    let stopped = false
    const tick = async () => {
      try {
        const { job } = await jobsApi.get(jobId)
        if (stopped) return
        setState({ status: job.status, progress: job.progress, phase: job.phase, error: job.error ?? '' })
        if (job.status === 'complete' || job.status === 'failed' || job.status === 'cancelled') {
          window.clearInterval(timer)
          if (job.status === 'complete') doneRef.current()
        }
      } catch {
        /* keep polling */
      }
    }
    const timer = window.setInterval(() => void tick(), 1000)
    void tick()
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [jobId])

  const active = state.status === 'queued' || state.status === 'running'
  return (
    <div className="space-y-1 rounded-lg bg-zinc-800/50 p-3">
      <div className="flex items-center gap-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-700">
          <div className="h-full bg-blue-500 transition-all" style={{ width: `${Math.max(0, Math.min(100, state.progress))}%` }} />
        </div>
        <span className="w-10 text-right text-xs text-zinc-300">{Math.round(state.progress)}%</span>
        {active && (
          <button
            type="button"
            onClick={() => void modelManagerApi.cancelDownload(jobId).catch(() => undefined)}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
          >
            <X className="h-3.5 w-3.5" /> Cancel
          </button>
        )}
      </div>
      <p className="text-xs text-zinc-500">
        {state.status}
        {state.phase ? ` · ${state.phase}` : ''}
      </p>
      {state.error && <p className="text-xs text-red-300">{state.error}</p>}
    </div>
  )
}

function AddModel({ onInstalled }: { onInstalled: () => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HubModel[]>([])
  const [searching, setSearching] = useState(false)
  const [repo, setRepo] = useState<HubModel | null>(null)
  const [files, setFiles] = useState<HubFile[]>([])
  const [fileDest, setFileDest] = useState<Record<string, StorageAreaId>>({})
  const [link, setLink] = useState('')
  const [linkDest, setLinkDest] = useState<StorageAreaId>('checkpoints')
  const [jobs, setJobs] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    const q = query.trim()
    if (!q) {
      setResults([])
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      setSearching(true)
      modelManagerApi
        .search(q, 20)
        .then((r) => !cancelled && (setResults(r), setError('')))
        .catch((e) => !cancelled && setError(errText(e)))
        .finally(() => !cancelled && setSearching(false))
    }, 400)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [query])

  const open = async (m: HubModel) => {
    setRepo(m)
    setFiles([])
    try {
      setFiles(await modelManagerApi.files(m.repo_id))
    } catch (e) {
      setError(errText(e))
    }
  }

  const start = async (body: Parameters<typeof modelManagerApi.download>[0]) => {
    setError('')
    try {
      const { job_id } = await modelManagerApi.download(body)
      setJobs((j) => [...j, job_id])
    } catch (e) {
      setError(errText(e))
    }
  }

  return (
    <Section title="Add a model" hint="Downloads start only when you press Download.">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-500" />
        <input
          data-testid="model-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Hugging Face models…"
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 py-1.5 pl-8 pr-2 text-sm text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-zinc-500"
        />
      </div>
      {searching && <p className="text-xs text-zinc-500">Searching…</p>}
      {results.length > 0 && (
        <div className="max-h-56 space-y-1 overflow-y-auto">
          {results.map((m) => (
            <button
              key={m.repo_id}
              type="button"
              onClick={() => void open(m)}
              className={`flex w-full items-center gap-3 rounded-lg p-2 text-left hover:bg-zinc-800 ${repo?.repo_id === m.repo_id ? 'bg-zinc-800' : 'bg-zinc-800/40'}`}
            >
              <span className="min-w-0 flex-1 truncate text-sm text-zinc-200">{m.repo_id}</span>
              <span className="shrink-0 text-xs text-zinc-500">{m.pipeline_tag || 'model'}</span>
              <span className="shrink-0 text-xs text-zinc-500">{m.downloads.toLocaleString()} downloads</span>
              <span className="shrink-0 rounded-full bg-amber-950/70 px-1.5 py-0.5 text-[10px] text-amber-300">
                {m.license || 'licence unknown'}
              </span>
            </button>
          ))}
        </div>
      )}
      {repo && (
        <div className="space-y-1.5 rounded-lg border border-zinc-800 p-3">
          <p className="text-sm text-zinc-200">
            {repo.repo_id}{' '}
            <span className="rounded-full bg-amber-950/70 px-1.5 py-0.5 text-[10px] text-amber-300">
              Licence: {repo.license || 'unknown'}
            </span>
          </p>
          {files.length === 0 && <p className="text-xs text-zinc-500">No weight files found (or still loading).</p>}
          {files.map((f) => (
            <div key={f.path} className="flex items-center gap-3">
              <span className="min-w-0 flex-1 truncate text-xs text-zinc-300">{f.path}</span>
              <span className="shrink-0 text-xs text-zinc-500">{formatBytes(f.size_bytes)}</span>
              <DestinationSelect
                value={fileDest[f.path] ?? 'checkpoints'}
                onChange={(v) => setFileDest((d) => ({ ...d, [f.path]: v }))}
              />
              <button
                type="button"
                onClick={() =>
                  void start({ repo_id: repo.repo_id, path: f.path, destination: fileDest[f.path] ?? 'checkpoints' })
                }
                className="flex shrink-0 items-center gap-1 rounded-md bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-500"
              >
                <Download className="h-3.5 w-3.5" /> Download
              </button>
            </div>
          ))}
        </div>
      )}

      <p className="pt-1 text-xs text-zinc-400">Or paste a direct link</p>
      <div className="flex items-center gap-2">
        <input
          data-testid="model-link-input"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder="https://…/model.safetensors"
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 outline-none focus:border-zinc-500"
        />
        <DestinationSelect value={linkDest} onChange={setLinkDest} />
        <button
          type="button"
          disabled={!isValidLink(link)}
          onClick={() => void start({ url: link.trim(), destination: linkDest })}
          className="flex shrink-0 items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1.5 text-xs text-white hover:bg-blue-500 disabled:opacity-40"
        >
          <Download className="h-3.5 w-3.5" /> Download
        </button>
      </div>
      {link.trim() !== '' && !isValidLink(link) && (
        <p className="text-xs text-zinc-500">Use an https link to a .safetensors, .gguf, .ckpt, .pt, .pth or .bin file.</p>
      )}
      <ErrorLine text={error} />
      {jobs.map((id) => (
        <DownloadProgress key={id} jobId={id} onDone={onInstalled} />
      ))}
    </Section>
  )
}

// --------------------------------------------------------------- storage

function StorageRow({
  area,
  disabled,
  onMoved,
}: {
  area: StorageArea
  disabled: boolean
  onMoved: (m: InstalledInventory['move']) => void
}) {
  const [dest, setDest] = useState('')
  const [error, setError] = useState('')
  const canPick = typeof window !== 'undefined' && !!window.electronAPI?.showOpenDirectoryDialog

  const move = async () => {
    let target = dest.trim()
    if (canPick) {
      const picked = await window.electronAPI.showOpenDirectoryDialog({ title: `Move ${area.label} to…` })
      if (!picked) return
      target = picked
    }
    if (!target) return
    if (
      !window.confirm(
        `Move ${area.label} (${formatBytes(area.size_bytes)}) to ${target}? Renders must be stopped. The old folder is replaced by a link, so nothing else changes.`,
      )
    )
      return
    setError('')
    try {
      onMoved(await modelManagerApi.moveStorage(area.id, target))
    } catch (e) {
      setError(errText(e))
    }
  }

  return (
    <div data-testid="storage-area-row" className="space-y-1.5 rounded-lg bg-zinc-800/50 p-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-zinc-200">{area.label}</p>
          <p className="truncate text-xs text-zinc-500">{area.path}</p>
          {area.moved_to && <p className="truncate text-xs text-sky-400">moved to {area.moved_to}</p>}
        </div>
        <div className="shrink-0 text-right text-xs text-zinc-300">
          <p>{formatBytes(area.size_bytes)}</p>
          <p className="text-zinc-500">{formatBytes(area.free_bytes)} free on drive</p>
        </div>
        {!canPick && (
          <input
            value={dest}
            onChange={(e) => setDest(e.target.value)}
            placeholder="Absolute destination folder"
            aria-label={`Destination folder for ${area.label}`}
            className="w-56 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 outline-none"
          />
        )}
        <button
          type="button"
          data-testid="move-storage"
          disabled={disabled}
          onClick={() => void move()}
          className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700 disabled:opacity-50"
        >
          <FolderInput className="h-3.5 w-3.5" /> Move…
        </button>
      </div>
      <ErrorLine text={error} />
    </div>
  )
}

function Storage({ inventory, onMoveStatus }: { inventory: InstalledInventory | null; onMoveStatus: (m: InstalledInventory['move']) => void }) {
  if (!inventory) return null
  const { move } = inventory
  return (
    <Section title="Storage" hint="Where each kind of model lives. Moving a folder leaves a link behind, so apps keep finding it.">
      {inventory.areas.map((a) => (
        <StorageRow key={a.id} area={a} disabled={move.running} onMoved={onMoveStatus} />
      ))}
      {move.running && (
        <div className="space-y-1">
          <div className="h-1.5 overflow-hidden rounded-full bg-zinc-700">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${move.total_bytes > 0 ? Math.min(100, (move.copied_bytes / move.total_bytes) * 100) : 0}%` }}
            />
          </div>
          <p className="text-xs text-zinc-400">
            Moving {move.area} to {move.destination}: {formatBytes(move.copied_bytes)} / {formatBytes(move.total_bytes)}
          </p>
        </div>
      )}
      <ErrorLine text={move.error} />
    </Section>
  )
}

// ------------------------------------------------------------------ tab

export function ModelsSettings() {
  const [inventory, setInventory] = useState<InstalledInventory | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setInventory(await modelManagerApi.installed())
      setError('')
    } catch (e) {
      setError(errText(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const moving = inventory?.move.running ?? false
  useEffect(() => {
    if (!moving) return
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(timer)
  }, [moving, refresh])

  const applyMove = (move: InstalledInventory['move']) => {
    setInventory((inv) => (inv ? { ...inv, move } : inv))
    void refresh()
  }

  return (
    <div data-testid="models-settings" className="space-y-8">
      <ErrorLine text={error} />
      <DefaultModels />
      <Section title="Installed models" hint="What is on this computer and how much room it takes.">
        <InstalledList inventory={inventory} onChange={setInventory} />
      </Section>
      <AddModel onInstalled={() => void refresh()} />
      <Storage inventory={inventory} onMoveStatus={applyMove} />
    </div>
  )
}
