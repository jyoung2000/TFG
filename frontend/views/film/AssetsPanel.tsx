import { useCallback, useEffect, useState } from 'react'
import { ImagePlus, Loader2, MapPin, Package, Palette, Plus, Sparkles, Trash2, User, Wand2 } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi, filmMediaUrl } from '../../lib/film-api'
import type { FilmAsset, FilmAssetKind } from '../../types/film'

const KIND_META: Record<FilmAssetKind, { label: string; plural: string; icon: React.ReactNode; color: string }> = {
  character: { label: 'Character', plural: 'Characters', icon: <User className="h-4 w-4" />, color: 'bg-amber-600/20 text-amber-300' },
  location: { label: 'Location', plural: 'Locations', icon: <MapPin className="h-4 w-4" />, color: 'bg-emerald-600/20 text-emerald-300' },
  prop: { label: 'Prop', plural: 'Props', icon: <Package className="h-4 w-4" />, color: 'bg-sky-600/20 text-sky-300' },
  style: { label: 'Style', plural: 'Styles', icon: <Palette className="h-4 w-4" />, color: 'bg-fuchsia-600/20 text-fuchsia-300' },
}

const inputClass = 'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

function paletteSwatch(label: string): string {
  const value = label.trim().toLowerCase()
  if (/^#[0-9a-f]{3,8}$/i.test(value) || /^rgba?\(/i.test(value)) return value
  if (value.includes('brass') || value.includes('gold') || value.includes('amber')) return '#b88a42'
  if (value.includes('cream') || value.includes('ivory')) return '#eee2bd'
  if (value.includes('charcoal') || value.includes('black')) return '#383838'
  if (value.includes('white')) return '#efefef'
  if (value.includes('blue') || value.includes('navy')) return '#4779a8'
  if (value.includes('green') || value.includes('olive')) return '#668056'
  if (value.includes('red') || value.includes('rust')) return '#a94d3d'
  if (value.includes('brown') || value.includes('tan')) return '#94704f'
  if (value.includes('gray') || value.includes('grey') || value.includes('silver')) return '#92969a'
  return '#777777'
}

const KIND_FIELDS: Record<FilmAssetKind, { key: keyof FilmAsset; label: string }[]> = {
  character: [
    { key: 'description', label: 'Identity / role' }, { key: 'appearance', label: 'Appearance' },
    { key: 'wardrobe', label: 'Wardrobe' }, { key: 'accessories', label: 'Accessories' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  location: [
    { key: 'description', label: 'Description' }, { key: 'environment', label: 'Environment' },
    { key: 'lighting', label: 'Lighting' }, { key: 'atmosphere', label: 'Atmosphere' },
    { key: 'time_of_day', label: 'Time of day' }, { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  prop: [
    { key: 'description', label: 'Description' }, { key: 'prop_details', label: 'Details' },
    { key: 'continuity_notes', label: 'Continuity notes' },
  ],
  style: [
    { key: 'description', label: 'Description' }, { key: 'style_prompt', label: 'Style prompt (appended to every shot)' },
  ],
}

function ReferenceThumb({ path }: { path: string }) {
  const { film } = useFilm()
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => { if (film) filmMediaUrl(film.id, path).then(setUrl).catch(() => {}) }, [film, path])
  if (!url) return null
  return <img src={url} alt="Asset visual reference" className="h-32 w-44 object-contain rounded border border-zinc-800 bg-black/40" />
}

function useAssetThumb(asset: FilmAsset): string | null {
  const { film } = useFilm()
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false; setUrl(null)
    void (async () => {
      const first = asset.reference_images[0]; if (!film || !first) return
      try { const r = await filmMediaUrl(film.id, first); if (!cancelled) setUrl(r) } catch {}
    })()
    return () => { cancelled = true }
  }, [film, asset.reference_images])
  return url
}

function AssetCard({ asset, selected, onSelect, onRemove }: {
  asset: FilmAsset; selected: boolean; onSelect: () => void; onRemove: () => void
}) {
  const thumb = useAssetThumb(asset)
  const meta = KIND_META[asset.kind]
  const hasGuide = !!asset.style_guide
  return (
    <div onClick={onSelect} className={"group relative rounded-xl overflow-hidden border cursor-pointer transition-all " + (selected ? "border-violet-500 ring-2 ring-violet-500/30" : "border-zinc-800 hover:border-zinc-600")} title={asset.name}>
      <div className="aspect-[4/3] bg-zinc-950 flex items-center justify-center relative">
        {thumb ? <img src={thumb} alt="" className="w-full h-full object-cover" /> : <span className="text-zinc-700">{meta.icon}</span>}
        <div className="absolute top-2 left-2 flex items-center gap-1">
          <span className={"px-1.5 py-0.5 rounded text-[10px] font-medium " + meta.color}>{meta.label}</span>
          {hasGuide && <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-600/30 text-violet-300">Guide</span>}
        </div>
        <button onClick={e => { e.stopPropagation(); onRemove() }} className="absolute top-2 right-2 p-1.5 rounded-lg bg-zinc-950/70 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity" aria-label={"Delete " + asset.name}><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <div className="px-3 py-2 bg-zinc-900/95"><span className="block text-xs font-semibold text-zinc-100 truncate">{asset.name}</span><span className="block text-[10px] text-zinc-500 truncate mt-0.5">{asset.description || "No description"}</span></div>
    </div>
  )
}

function StyleGuidePanel({ asset }: { asset: FilmAsset }) {
  const sg = asset.style_guide
  if (!sg) return <p className="text-xs text-zinc-600">Upload a reference image, then click "Generate style guide" to let the vision model extract key traits, colors, mood and a reusable generation prompt.</p>
  return (
    <div className="space-y-2.5">
      {sg.key_traits.length > 0 && <div><span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Key traits</span><div className="flex flex-wrap gap-1 mt-1">{sg.key_traits.map((t, i) => <span key={i} className="px-2 py-0.5 rounded-full bg-zinc-800 text-[10px] text-zinc-300">{t}</span>)}</div></div>}
      {sg.color_palette.length > 0 && <div><span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Color palette</span><div className="flex gap-1.5 mt-1 flex-wrap">{sg.color_palette.map((c, i) => <span key={i} className="flex items-center gap-1.5 text-[10px] text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded"><span className="w-3 h-3 rounded-sm border border-zinc-700" style={{background: paletteSwatch(c)}} />{c}</span>)}</div></div>}
      {sg.mood && <div><span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Mood</span><p className="text-xs text-zinc-300 mt-0.5">{sg.mood}</p></div>}
      {sg.recommended_prompt && <div><span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Generation prompt</span><p className="text-xs text-zinc-400 mt-0.5 bg-zinc-800/50 rounded p-2 border border-zinc-700/50">{sg.recommended_prompt}</p></div>}
    </div>
  )
}

export function AssetsPanel() {
  const { film, refresh } = useFilm()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Partial<FilmAsset>>({})
  const [note, setNote] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generatingGuide, setGeneratingGuide] = useState(false)
  const selected = film?.assets.find(a => a.id === selectedId) ?? null

  useEffect(() => { if (selected) setDraft({ ...selected }) }, [selectedId, selected])

  const create = useCallback(async (kind: FilmAssetKind) => {
    if (!film) return
    const count = film.assets.filter(a => a.kind === kind).length
    const asset = await filmApi.createAsset(film.id, { kind, name: KIND_META[kind].label + ' ' + (count + 1) })
    await refresh(); setSelectedId(asset.id)
  }, [film, refresh])

  const save = useCallback(async () => {
    if (!film || !selected) return
    const updates: Record<string, unknown> = {}
    for (const key of ['name','description','appearance','wardrobe','accessories','environment','lighting','atmosphere','time_of_day','prop_details','style_prompt','continuity_notes'] as const) {
      if (draft[key] !== undefined && draft[key] !== selected[key]) updates[key] = draft[key]
    }
    if (Object.keys(updates).length === 0) return
    await filmApi.updateAsset(film.id, selected.id, updates)
    await refresh(); setNote('Saved'); setTimeout(() => setNote(''), 1500)
  }, [film, selected, draft, refresh])

  const remove = useCallback(async (asset: FilmAsset) => {
    if (!film || !window.confirm('Delete ' + asset.name + '?')) return
    await filmApi.deleteAsset(film.id, asset.id)
    if (selectedId === asset.id) setSelectedId(null)
    await refresh()
  }, [film, selectedId, refresh])

  const addReference = useCallback(async () => {
    if (!film || !selected) return
    const input = document.createElement('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return
      const reader = new FileReader()
      reader.onload = async () => {
        try { await filmApi.addAssetReference(film.id, selected.id, String(reader.result), file.name); await refresh() }
        catch (e) { setNote('Upload failed: ' + (e instanceof Error ? e.message : String(e))) }
      }
      reader.readAsDataURL(file)
    }
    input.click()
  }, [film, selected, refresh])

  const generateReference = useCallback(async () => {
    if (!film || !selected) return
    setGenerating(true); setNote('')
    try { await filmApi.generateAssetReference(film.id, selected.id); await refresh(); setNote('Generated') }
    catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setGenerating(false) }
  }, [film, selected, refresh])

  const generateStyleGuide = useCallback(async () => {
    if (!film || !selected || !selected.reference_images.length) { setNote('Add a reference image first'); return }
    setGeneratingGuide(true); setNote('')
    try { await filmApi.generateAssetStyleGuide(film.id, selected.id); await refresh(); setNote('Style guide ready') }
    catch (e) { setNote('Style guide failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setGeneratingGuide(false) }
  }, [film, selected, refresh])

  if (!film) return null

  return (
    <div className="flex h-full min-h-0">
      <div className="w-80 shrink-0 border-r border-zinc-800 overflow-y-auto p-2 space-y-3">
        {(Object.keys(KIND_META) as FilmAssetKind[]).map(kind => (
          <div key={kind}>
            <div className="flex items-center gap-1.5 px-1 pb-1.5">
              <span className="text-zinc-500">{KIND_META[kind].icon}</span>
              <span className="flex-1 text-[10px] font-semibold text-zinc-400 uppercase tracking-wide">{KIND_META[kind].plural}</span>
              <button onClick={() => void create(kind)} className="p-0.5 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-300"><Plus className="h-3.5 w-3.5" /></button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {film.assets.filter(a => a.kind === kind).map(asset => (
                <AssetCard key={asset.id} asset={asset} selected={selectedId === asset.id} onSelect={() => setSelectedId(asset.id)} onRemove={() => void remove(asset)} />
              ))}
              {film.assets.filter(a => a.kind === kind).length === 0 && <p className="col-span-2 px-2 text-[11px] text-zinc-700 py-4 text-center">No {KIND_META[kind].plural.toLowerCase()} yet</p>}
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-5">
        {selected ? (
          <div className="max-w-4xl space-y-4">
            <div className="flex items-center gap-2">
              <span className="text-zinc-500">{KIND_META[selected.kind].icon}</span>
              <input className="flex-1 bg-transparent text-lg font-semibold text-white focus:outline-none border-b border-transparent focus:border-violet-600" value={(draft.name as string) ?? ''} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} />
              {note && <span className={'text-[11px] ' + (note.includes('Failed') || note.includes('Style guide failed') ? 'text-red-400' : note.startsWith('Add') ? 'text-amber-400' : 'text-emerald-400')}>{note}</span>}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => void addReference()} className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"><ImagePlus className="h-3 w-3" /> Add image</button>
              <button onClick={() => void generateReference()} disabled={generating} className="flex items-center gap-1 px-2 py-1 rounded bg-violet-800/70 hover:bg-violet-700 disabled:opacity-40 text-[10px] text-violet-100">{generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} Generate image</button>
              <button onClick={() => void generateStyleGuide()} disabled={generatingGuide || selected.reference_images.length === 0} title="Analyze reference image with vision AI" className="flex items-center gap-1 px-2 py-1 rounded bg-amber-800/70 hover:bg-amber-700 disabled:opacity-40 text-[10px] text-amber-100">{generatingGuide ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />} Generate style guide</button>
            </div>
            {selected.reference_images.length > 0 && <div className="flex gap-1.5 overflow-x-auto pb-1">{selected.reference_images.map((p, i) => <ReferenceThumb key={i} path={p} />)}</div>}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="space-y-3">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Details</span>
                {KIND_FIELDS[selected.kind].map(field => (
                  <label key={String(field.key)} className="block">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{field.label}</span>
                    <textarea className={inputClass + ' mt-0.5 resize-none h-14'} value={String(draft[field.key] ?? '')} onChange={e => setDraft(d => ({ ...d, [field.key]: e.target.value }))} />
                  </label>
                ))}
              </div>
              <div className="space-y-3">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Style Guide</span>
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-3 min-h-[120px]"><StyleGuidePanel asset={selected} /></div>
              </div>
            </div>
            <button onClick={() => void save()} className="px-4 py-1.5 rounded bg-violet-700 hover:bg-violet-600 text-xs font-medium text-white">Save {KIND_META[selected.kind].label.toLowerCase()}</button>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-center">
            <div>
              <User className="h-8 w-8 text-zinc-800 mx-auto mb-2" />
              <p className="text-sm text-zinc-500">Reusable characters, locations, props and styles</p>
              <p className="text-xs text-zinc-600 mt-1 max-w-xs">Define them once — every shot that references them inherits their look. Add a reference image, then generate a style guide to extract traits automatically.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
