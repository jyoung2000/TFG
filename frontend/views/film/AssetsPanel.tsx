import { useCallback, useEffect, useState } from 'react'
import { ImagePlus, MapPin, Package, Palette, Plus, Trash2, User } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi, filmMediaUrl } from '../../lib/film-api'
import type { FilmAsset, FilmAssetKind } from '../../types/film'

const KIND_META: Record<FilmAssetKind, { label: string; plural: string; icon: React.ReactNode }> = {
  character: { label: 'Character', plural: 'Characters', icon: <User className="h-3.5 w-3.5" /> },
  location: { label: 'Location', plural: 'Locations', icon: <MapPin className="h-3.5 w-3.5" /> },
  prop: { label: 'Prop', plural: 'Props', icon: <Package className="h-3.5 w-3.5" /> },
  style: { label: 'Style', plural: 'Styles', icon: <Palette className="h-3.5 w-3.5" /> },
}

const inputClass =
  'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

const KIND_FIELDS: Record<FilmAssetKind, { key: keyof FilmAsset; label: string }[]> = {
  character: [
    { key: 'description', label: 'Identity / role' },
    { key: 'appearance', label: 'Appearance' },
    { key: 'wardrobe', label: 'Wardrobe' },
    { key: 'accessories', label: 'Accessories' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  location: [
    { key: 'description', label: 'Description' },
    { key: 'environment', label: 'Environment / architecture' },
    { key: 'lighting', label: 'Lighting' },
    { key: 'atmosphere', label: 'Atmosphere' },
    { key: 'time_of_day', label: 'Time of day' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  prop: [
    { key: 'description', label: 'Description' },
    { key: 'prop_details', label: 'Details' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  style: [
    { key: 'description', label: 'Description' },
    { key: 'style_prompt', label: 'Style prompt (appended to every shot)' },
  ],
}

function ReferenceStrip({ asset }: { asset: FilmAsset }) {
  const { film } = useFilm()
  const [urls, setUrls] = useState<string[]>([])
  useEffect(() => {
    let cancelled = false
    void (async () => {
      if (!film) return
      const next = await Promise.all(asset.reference_images.map(p => filmMediaUrl(film.id, p)))
      if (!cancelled) setUrls(next)
    })()
    return () => {
      cancelled = true
    }
  }, [film, asset.reference_images])
  if (urls.length === 0) return null
  return (
    <div className="flex gap-1.5 overflow-x-auto">
      {urls.map((url, i) => (
        <img key={i} src={url} alt="" className="h-14 w-14 object-cover rounded border border-zinc-800" />
      ))}
    </div>
  )
}

export function AssetsPanel() {
  const { film, refresh } = useFilm()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Partial<FilmAsset>>({})
  const [note, setNote] = useState('')

  const selected = film?.assets.find(a => a.id === selectedId) ?? null

  useEffect(() => {
    if (selected) setDraft({ ...selected })
  }, [selectedId, selected])

  const create = useCallback(
    async (kind: FilmAssetKind) => {
      if (!film) return
      const count = film.assets.filter(a => a.kind === kind).length
      const asset = await filmApi.createAsset(film.id, {
        kind,
        name: `${KIND_META[kind].label} ${count + 1}`,
      })
      await refresh()
      setSelectedId(asset.id)
    },
    [film, refresh],
  )

  const save = useCallback(async () => {
    if (!film || !selected) return
    const updates: Record<string, unknown> = {}
    for (const key of ['name', 'description', 'appearance', 'wardrobe', 'accessories', 'environment', 'lighting', 'atmosphere', 'time_of_day', 'prop_details', 'style_prompt', 'continuity_notes'] as const) {
      if (draft[key] !== undefined && draft[key] !== selected[key]) updates[key] = draft[key]
    }
    if (Object.keys(updates).length === 0) return
    await filmApi.updateAsset(film.id, selected.id, updates)
    await refresh()
    setNote('Saved')
    setTimeout(() => setNote(''), 1500)
  }, [film, selected, draft, refresh])

  const remove = useCallback(
    async (asset: FilmAsset) => {
      if (!film) return
      if (!window.confirm(`Delete ${asset.name}? Shots referencing it will drop the reference.`)) return
      await filmApi.deleteAsset(film.id, asset.id)
      if (selectedId === asset.id) setSelectedId(null)
      await refresh()
    },
    [film, selectedId, refresh],
  )

  const addReference = useCallback(async () => {
    if (!film || !selected) return
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          await filmApi.addAssetReference(film.id, selected.id, String(reader.result), file.name)
          await refresh()
        } catch (e) {
          setNote(`Upload failed: ${e instanceof Error ? e.message : e}`)
        }
      }
      reader.readAsDataURL(file)
    }
    input.click()
  }, [film, selected, refresh])

  if (!film) return null

  return (
    <div className="flex h-full min-h-0">
      {/* Asset list by kind */}
      <div className="w-64 border-r border-zinc-800 overflow-y-auto p-2 space-y-3">
        {(Object.keys(KIND_META) as FilmAssetKind[]).map(kind => (
          <div key={kind}>
            <div className="flex items-center gap-1.5 px-1 pb-1">
              <span className="text-zinc-500">{KIND_META[kind].icon}</span>
              <span className="flex-1 text-[10px] font-semibold text-zinc-400 uppercase tracking-wide">
                {KIND_META[kind].plural}
              </span>
              <button
                onClick={() => void create(kind)}
                className="p-0.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300"
                title={`New ${KIND_META[kind].label.toLowerCase()}`}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="space-y-0.5">
              {film.assets
                .filter(a => a.kind === kind)
                .map(asset => (
                  <div
                    key={asset.id}
                    onClick={() => setSelectedId(asset.id)}
                    className={`group flex items-center gap-1.5 px-2 py-1.5 rounded text-xs cursor-pointer ${
                      selectedId === asset.id
                        ? 'bg-violet-600/25 text-white'
                        : 'text-zinc-300 hover:bg-zinc-800'
                    }`}
                  >
                    <span className="flex-1 truncate">{asset.name}</span>
                    <button
                      onClick={e => {
                        e.stopPropagation()
                        void remove(asset)
                      }}
                      className="opacity-0 group-hover:opacity-100 text-zinc-600 hover:text-red-400"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              {film.assets.filter(a => a.kind === kind).length === 0 && (
                <p className="px-2 text-[11px] text-zinc-700">None yet</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-y-auto p-4">
        {selected ? (
          <div className="max-w-lg space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-zinc-500">{KIND_META[selected.kind].icon}</span>
              <input
                className="flex-1 bg-transparent text-lg font-semibold text-white focus:outline-none border-b border-transparent focus:border-violet-600"
                value={(draft.name as string) ?? ''}
                onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
              />
              {note && <span className="text-[11px] text-emerald-400">{note}</span>}
            </div>
            {KIND_FIELDS[selected.kind].map(field => (
              <label key={String(field.key)} className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{field.label}</span>
                <textarea
                  className={`${inputClass} mt-0.5 resize-none h-14`}
                  value={String(draft[field.key] ?? '')}
                  onChange={e => setDraft(d => ({ ...d, [field.key]: e.target.value }))}
                />
              </label>
            ))}
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">
                  Visual references
                </span>
                <button
                  onClick={() => void addReference()}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"
                >
                  <ImagePlus className="h-3 w-3" /> Add image
                </button>
              </div>
              <ReferenceStrip asset={selected} />
            </div>
            <button
              onClick={() => void save()}
              className="px-4 py-1.5 rounded bg-violet-700 hover:bg-violet-600 text-xs font-medium text-white"
            >
              Save {KIND_META[selected.kind].label.toLowerCase()}
            </button>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-center">
            <div>
              <User className="h-8 w-8 text-zinc-800 mx-auto mb-2" />
              <p className="text-sm text-zinc-500">
                Reusable characters, locations, props and styles
              </p>
              <p className="text-xs text-zinc-600 mt-1 max-w-xs">
                Define them once — every shot that references them inherits their look, and
                continuity checks watch for drift.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
