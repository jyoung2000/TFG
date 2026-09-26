/**
 * Layout 2 — one asset: reference-sheet hero, uploads strip, the "what
 * every shot inherits" preview, the per-kind detail fields, and on the
 * right the Consistency Kit checklist, the editable style guide and where
 * the asset is used. All handlers are the pre-redesign ones.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Check, Copy, ImagePlus, Layers, Loader2, Lock, Plus, Sparkles, Wand2, X } from 'lucide-react'
import { useFilm } from '../../../contexts/FilmContext'
import { filmApi } from '../../../lib/film-api'
import { trainingApi } from '../../../lib/training-api'
import type { LoraEntry } from '../../../types/training'
import type { AssetStyleGuide, FilmAsset, FilmProject } from '../../../types/film'
import { consistencyOf, inheritedPrompt, looseReferences, sheetImages } from './consistency'
import { EMPTY_GUIDE, StyleGuideEditor } from './StyleGuideEditor'
import { GalleryThumb, KIND_FIELDS, KIND_META, ThumbError, inputClass, readFileAsDataUrl, useFilmMediaUrl } from './shared'

export function AssetDetail({ asset, onBack, onOpenLightbox }: {
  asset: FilmAsset
  onBack: () => void
  onOpenLightbox: (index: number) => void
}) {
  const { film, refresh } = useFilm()
  const [draft, setDraft] = useState<Partial<FilmAsset>>({ ...asset })
  const [note, setNote] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generatingGuide, setGeneratingGuide] = useState(false)
  const [busySheet, setBusySheet] = useState(false)
  useEffect(() => { setDraft({ ...asset }) }, [asset.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const c = consistencyOf(asset)
  const meta = KIND_META[asset.kind]

  const save = useCallback(async () => {
    if (!film) return
    const updates: Record<string, unknown> = {}
    for (const key of ['name','description','appearance','wardrobe','accessories','environment','lighting','atmosphere','time_of_day','prop_details','style_prompt','continuity_notes'] as const) {
      if (draft[key] !== undefined && draft[key] !== asset[key]) updates[key] = draft[key]
    }
    if (Object.keys(updates).length === 0) return
    await filmApi.updateAsset(film.id, asset.id, updates)
    await refresh(); setNote('Saved'); setTimeout(() => setNote(''), 1500)
  }, [film, asset, draft, refresh])

  const addReference = useCallback(async () => {
    if (!film) return
    const input = document.createElement('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return
      try { await filmApi.addAssetReference(film.id, asset.id, await readFileAsDataUrl(file), file.name); await refresh() }
      catch (e) { setNote('Upload failed: ' + (e instanceof Error ? e.message : String(e))) }
    }
    input.click()
  }, [film, asset.id, refresh])

  const generateReference = useCallback(async () => {
    if (!film) return
    setGenerating(true); setNote('')
    try { await filmApi.generateAssetReference(film.id, asset.id); await refresh(); setNote('Generated') }
    catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setGenerating(false) }
  }, [film, asset.id, refresh])

  const generateStyleGuide = useCallback(async () => {
    if (!film || !asset.reference_images.length) { setNote('Add a reference image first'); return }
    setGeneratingGuide(true); setNote('')
    try { await filmApi.generateAssetStyleGuide(film.id, asset.id); await refresh(); setNote('Style guide ready') }
    catch (e) { setNote('Style guide failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setGeneratingGuide(false) }
  }, [film, asset, refresh])

  const sheet = useCallback(async () => {
    if (!film) return
    setBusySheet(true); setNote('')
    try {
      const result = await filmApi.referenceSheet(film.id, asset.id)
      await refresh(); setNote(`Reference sheet: ${result.reference_paths.length} views at seed ${result.seed ?? '?'}`)
    } catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setBusySheet(false) }
  }, [film, asset.id, refresh])

  const deleteReference = useCallback(async (path: string) => {
    if (!film || !window.confirm('Remove this reference image? The file is deleted.')) return
    try { await filmApi.deleteAssetReference(film.id, asset.id, path); await refresh() }
    catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
  }, [film, asset.id, refresh])

  if (!film) return null
  const openPath = (path: string) => onOpenLightbox(Math.max(0, asset.reference_images.indexOf(path)))

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="asset-detail">
      <div className="h-14 shrink-0 border-b border-zinc-800 px-4 flex items-center gap-2.5">
        <button onClick={onBack} aria-label="Back to all assets" className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400"><ArrowLeft className="h-4 w-4" /></button>
        <span className={'px-1.5 py-0.5 rounded text-[10px] font-medium ' + meta.color}>{meta.label}</span>
        <input className="bg-transparent text-base font-semibold text-white focus:outline-none border-b border-transparent focus:border-violet-600 min-w-0 flex-1 max-w-xs"
          value={(draft.name as string) ?? ''} aria-label="Asset name"
          onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} onBlur={() => void save()} />
        {asset.kind !== 'style' && (
          <span className={'flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ' + (c.locked ? 'bg-emerald-900/60 text-emerald-300' : 'bg-amber-900/50 text-amber-300')}>
            {c.locked && <Lock className="h-2.5 w-2.5" />} Consistency {c.count} / 4
          </span>
        )}
        {note && <span className={'text-[11px] ' + (note.includes('Failed') || note.includes('Style guide failed') ? 'text-red-400' : note.startsWith('Add') ? 'text-amber-400' : 'text-emerald-400')}>{note}</span>}
        <div className="flex-1" />
        <button onClick={() => void addReference()} className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-[10px] text-zinc-300"><ImagePlus className="h-3 w-3" /> Add image</button>
        <button onClick={() => void generateReference()} disabled={generating} className="flex items-center gap-1 px-2 py-1 rounded bg-violet-800/70 hover:bg-violet-700 disabled:opacity-40 text-[10px] text-violet-100">{generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} Generate image</button>
        <button onClick={() => void generateStyleGuide()} disabled={generatingGuide || asset.reference_images.length === 0} title="Analyze reference image with vision AI" className="flex items-center gap-1 px-2 py-1 rounded bg-amber-800/70 hover:bg-amber-700 disabled:opacity-40 text-[10px] text-amber-100">{generatingGuide ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wand2 className="h-3 w-3" />} {asset.style_guide ? 'Regenerate style guide' : 'Generate style guide'}</button>
      </div>

      <div className="flex flex-1 min-h-0 overflow-y-auto">
        <div className="flex-1 min-w-0 p-4 space-y-4">
          {asset.kind !== 'style' && (
            <section>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">
                  Reference sheet · one seed{asset.seed_lock !== null ? ` · ${asset.seed_lock}` : ''}
                </span>
                <button onClick={() => void sheet()} disabled={busySheet} data-testid="reference-sheet"
                  className="ml-auto flex items-center gap-1 px-2 py-1 rounded bg-fuchsia-800/70 hover:bg-fuchsia-700 disabled:opacity-40 text-[10px] text-fuchsia-100">
                  {busySheet ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} {sheetImages(asset).some(s => s.path) ? 'Re-render 4 views' : 'Render 4 views'}
                </button>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {sheetImages(asset).map(({ view, path }) => (
                  <SheetTile key={view} view={view} path={path} onOpen={() => path && openPath(path)} />
                ))}
              </div>
            </section>
          )}
          <section>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">References</span>
            <div className="flex gap-1.5 flex-wrap mt-1.5">
              {(asset.kind === 'style' ? asset.reference_images : looseReferences(asset)).map(path => (
                <span key={path} className="relative group">
                  <GalleryThumb path={path} onOpen={() => openPath(path)} size="w-14 h-14" />
                  <button onClick={() => void deleteReference(path)} aria-label={`Delete reference ${path.split('/').pop() ?? ''}`}
                    className="absolute -top-1 -right-1 hidden group-hover:flex items-center justify-center w-4 h-4 rounded-full bg-zinc-900 border border-zinc-700 text-zinc-400 hover:text-red-300"><X className="h-2.5 w-2.5" /></button>
                </span>
              ))}
              <button onClick={() => void addReference()} aria-label="Upload a reference image"
                className="w-14 h-14 rounded border-2 border-dashed border-zinc-800 hover:border-violet-700 text-zinc-600 hover:text-violet-300 flex items-center justify-center"><Plus className="h-4 w-4" /></button>
            </div>
            <p className="text-[10px] text-zinc-600 mt-1">The first image drives the style guide.</p>
          </section>
          <InheritedPromptCard asset={asset} film={film} />
          <section>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Details</span>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-4 gap-y-2 mt-1.5">
              {KIND_FIELDS[asset.kind].map(field => (
                <label key={String(field.key)} className="block">
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{field.label}</span>
                  <textarea className={inputClass + ' mt-0.5 resize-none h-14'} value={String(draft[field.key] ?? '')}
                    onChange={e => setDraft(d => ({ ...d, [field.key]: e.target.value }))} />
                </label>
              ))}
            </div>
            <button onClick={() => void save()} className="mt-2 px-4 py-1.5 rounded bg-violet-700 hover:bg-violet-600 text-xs font-medium text-white">
              Save {meta.label.toLowerCase()}
            </button>
          </section>
        </div>

        <div className="w-[400px] shrink-0 border-l border-zinc-800 p-4 space-y-4">
          {asset.kind !== 'style' && <ConsistencyKit film={film} asset={asset} refresh={async () => { await refresh() }} setNote={setNote} />}
          <StyleGuideCard film={film} asset={asset} setNote={setNote} />
          <UsedInShots film={film} asset={asset} />
        </div>
      </div>
    </div>
  )
}

function SheetTile({ view, path, onOpen }: { view: string; path: string | null; onOpen: () => void }) {
  const state = useFilmMediaUrl(path ?? undefined)
  return (
    <div>
      {path === null ? (
        <div className="h-40 rounded-lg border border-dashed border-zinc-800 bg-zinc-950 flex items-center justify-center text-[10px] text-zinc-700">not rendered</div>
      ) : state.status === 'loading' ? (
        <div className="h-40 rounded-lg bg-zinc-900 animate-pulse" />
      ) : state.status === 'error' ? (
        <ThumbError className="h-40 w-full" message={state.message} />
      ) : (
        <button type="button" onClick={onOpen} className="block w-full cursor-zoom-in" aria-label={`Open reference image ${path.split('/').pop() ?? ''}`}>
          <img src={state.url} alt="" loading="lazy" className="h-40 w-full object-cover rounded-lg border border-zinc-800" />
        </button>
      )}
      <span className="block text-center text-[10px] text-zinc-500 mt-1 capitalize">{view.replace(' view', '')}</span>
    </div>
  )
}

const SOURCE_STYLE: Record<string, string> = {
  trigger: 'px-1.5 py-0.5 rounded bg-violet-900/60 text-violet-200 font-semibold',
  name: 'text-zinc-200',
  field: 'text-zinc-400',
  wardrobe: 'text-amber-300 underline decoration-amber-700',
  guide: 'text-emerald-300 underline decoration-emerald-700',
  style: 'text-fuchsia-300 underline decoration-dotted decoration-fuchsia-700',
}

function InheritedPromptCard({ asset, film }: { asset: FilmAsset; film: FilmProject }) {
  const [copied, setCopied] = useState(false)
  const parts = useMemo(() => inheritedPrompt(asset, film.assets), [asset, film.assets])
  const plain = parts.map(p => p.text).join(', ')
  const loraFile = asset.lora_id ? asset.lora_id : ''
  return (
    <section className="rounded-lg border border-violet-900/50 bg-violet-950/20 p-3 space-y-2" data-testid="inherited-prompt">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-violet-300 uppercase tracking-wide font-semibold">What every shot inherits</span>
        <button onClick={() => { void navigator.clipboard?.writeText(plain).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) }) }}
          aria-label="Copy inherited prompt" className="ml-auto p-1 rounded hover:bg-violet-900/40 text-violet-300">
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <p className="font-mono text-[11px] leading-relaxed">
        {parts.map((part, i) => (
          <span key={i}><span className={SOURCE_STYLE[part.source]}>{part.text}</span>{i < parts.length - 1 ? <span className="text-zinc-600">, </span> : null}</span>
        ))}
        {parts.length === 0 && <span className="text-zinc-600">Fill the fields below — shots quote them verbatim.</span>}
      </p>
      <div className="flex items-center gap-2 flex-wrap text-[9px] text-zinc-500">
        <span><span className="text-violet-300">■</span> trigger</span>
        <span><span className="text-amber-300">■</span> wardrobe</span>
        <span><span className="text-emerald-300">■</span> style guide</span>
        <span><span className="text-fuchsia-300">■</span> project style</span>
        <span className="flex-1" />
        {asset.reference_images.length > 0 && <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400">LTX-2 · image_refs ✓</span>}
        <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400">Wan 2.2 VACE · guide video ✓</span>
        {loraFile && <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400">{asset.lora_trigger || 'LoRA'} @ {asset.lora_multiplier}</span>}
      </div>
    </section>
  )
}

function StyleGuideCard({ film, asset, setNote }: { film: FilmProject; asset: FilmAsset; setNote: (n: string) => void }) {
  const { refresh } = useFilm()
  const [guideDraft, setGuideDraft] = useState<AssetStyleGuide>(asset.style_guide ?? EMPTY_GUIDE)
  useEffect(() => { setGuideDraft(asset.style_guide ?? EMPTY_GUIDE) }, [asset.id, asset.style_guide])
  if (!asset.style_guide) {
    return (
      <section className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Style guide</span>
        <p className="text-xs text-zinc-600 mt-1.5">Upload a reference image, then click "Generate style guide" to let the vision model extract key traits, colors, mood and a reusable generation prompt.</p>
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3" data-testid="style-guide-card">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Style guide</span>
      <div className="mt-2">
        <StyleGuideEditor guide={guideDraft} onChange={setGuideDraft}
          onCommit={next => {
            void filmApi.updateAsset(film.id, asset.id, { style_guide: next }).then(() => refresh()).then(() => setNote('Style guide saved'))
              .catch(e => setNote('Failed: ' + (e instanceof Error ? e.message : String(e))))
          }} />
      </div>
    </section>
  )
}

function UsedInShots({ film, asset }: { film: FilmProject; asset: FilmAsset }) {
  const uses = film.scenes.flatMap(scene =>
    scene.shots
      .filter(shot => shot.characters.some(ch => ch.asset_id === asset.id) || shot.location_id === asset.id || shot.prop_ids.includes(asset.id))
      .map(shot => ({ scene, shot })),
  )
  if (asset.kind === 'style') return null
  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Used in shots</span>
      {uses.length === 0
        ? <p className="text-[11px] text-zinc-600 mt-1.5">Not placed in any shot yet.</p>
        : (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {uses.map(({ scene, shot }) => (
              <span key={shot.id} title={shot.title} className="px-1.5 py-0.5 rounded bg-zinc-800 text-[10px] text-zinc-300 font-mono">
                S{scene.order + 1}·{shot.order + 1}
              </span>
            ))}
            <span className="text-[10px] text-zinc-600 self-center">{uses.length} shot{uses.length === 1 ? '' : 's'}</span>
          </div>
        )}
    </section>
  )
}

/**
 * Consistency Kit (phase 7), restyled as the 4-row checklist. Same
 * handlers, same aria-labels and the same explainer sentence as before —
 * the e2e suite depends on them.
 */
function ConsistencyKit({ film, asset, refresh, setNote }: { film: FilmProject; asset: FilmAsset; refresh: () => Promise<void>; setNote: (note: string) => void }) {
  const [loras, setLoras] = useState<LoraEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [seedDraft, setSeedDraft] = useState(asset.seed_lock === null ? '' : String(asset.seed_lock))
  const [multiplier, setMultiplier] = useState(asset.lora_multiplier || 1)
  const [trigger, setTrigger] = useState(asset.lora_trigger)
  useEffect(() => { trainingApi.listLoras().then(setLoras).catch(() => setLoras([])) }, [])
  useEffect(() => { setSeedDraft(asset.seed_lock === null ? '' : String(asset.seed_lock)); setMultiplier(asset.lora_multiplier || 1); setTrigger(asset.lora_trigger) }, [asset.id, asset.seed_lock, asset.lora_multiplier, asset.lora_trigger])
  const c = consistencyOf(asset)

  const update = async (data: Record<string, unknown>, note: string) => {
    setBusy(true)
    try { await filmApi.updateAsset(film.id, asset.id, data as Partial<FilmAsset>); await refresh(); setNote(note) }
    catch (e) { setNote('Failed: ' + (e instanceof Error ? e.message : String(e))) }
    finally { setBusy(false) }
  }
  const bind = (loraId: string) => {
    const entry = loras.find(l => l.id === loraId)
    void update({ lora_id: loraId, lora_trigger: entry?.trigger ?? '', lora_multiplier: entry?.default_multiplier ?? 1 }, loraId ? 'LoRA bound' : 'LoRA cleared')
  }
  const saveSeed = () => {
    const value = seedDraft.trim()
    if (value === '') { if (asset.seed_lock !== null) void update({ clear_seed_lock: true }, 'Seed unlocked'); return }
    const seed = Number(value)
    if (!Number.isInteger(seed) || seed < 0) { setNote('Failed: the seed must be a whole number'); return }
    if (seed !== asset.seed_lock) void update({ seed_lock: seed }, 'Seed locked')
  }
  const bound = loras.find(l => l.id === asset.lora_id)

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2" data-testid="consistency-kit">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold flex items-center gap-1"><Layers className="h-3 w-3" /> Consistency kit</span>
        <span className={'ml-auto text-[10px] font-semibold ' + (c.locked ? 'text-emerald-300' : 'text-amber-300')}>{c.count} / 4</span>
      </div>
      <div className="flex gap-0.5">
        {[c.ref, c.guide, c.lora, c.seed].map((on, i) => (
          <span key={i} className={'h-1 flex-1 rounded-full ' + (on ? 'bg-emerald-500' : 'bg-zinc-800')} />
        ))}
      </div>
      <KitRow done={c.ref} label="Reference images" detail={c.ref ? `${asset.reference_images.length} image${asset.reference_images.length === 1 ? '' : 's'}` : 'none yet'} />
      <KitRow done={c.guide} label="Style guide" detail={c.guide ? 'extracted' : 'generate from the first image'} />
      <KitRow done={c.lora} label="LoRA bound" detail={c.lora ? bound?.name ?? asset.lora_id : 'optional but strongest'}>
        <div className="flex items-center gap-1.5 flex-wrap mt-1">
          <select value={asset.lora_id} disabled={busy} onChange={e => bind(e.target.value)} aria-label="Bound LoRA" className="bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[11px] text-zinc-200">
            <option value="">none</option>
            {loras.map(l => <option key={l.id} value={l.id}>{l.name} · {l.target}</option>)}
          </select>
          {asset.lora_id && (
            <>
              <input value={trigger} disabled={busy} onChange={e => setTrigger(e.target.value)} onBlur={() => { if (trigger !== asset.lora_trigger) void update({ lora_trigger: trigger }, 'Trigger saved') }} aria-label="LoRA trigger word" placeholder="trigger" className="w-24 bg-violet-950/40 border border-violet-800 rounded-full px-2 py-0.5 text-[11px] text-violet-200" />
              <input type="number" step="0.05" min="0" max="2" value={multiplier} disabled={busy} onChange={e => setMultiplier(Number(e.target.value))} onBlur={() => { if (multiplier !== asset.lora_multiplier) void update({ lora_multiplier: multiplier }, 'Strength saved') }} aria-label="LoRA strength" className="w-14 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[11px] text-zinc-200" />
            </>
          )}
        </div>
      </KitRow>
      <KitRow done={c.seed} label="Seed locked" detail={c.seed ? '' : 'the sheet locks one for you'}>
        <div className="flex items-center gap-1.5 mt-1">
          <input value={seedDraft} disabled={busy} placeholder="none" onChange={e => setSeedDraft(e.target.value)} onBlur={saveSeed} onKeyDown={e => { if (e.key === 'Enter') saveSeed() }} aria-label="Seed lock" className="w-24 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[11px] text-zinc-200" />
          {asset.seed_lock !== null && <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-900/50 text-[10px] font-mono text-emerald-300"><Lock className="h-2.5 w-2.5" /> {asset.seed_lock}</span>}
        </div>
      </KitRow>
      <p className="text-[10px] text-zinc-600">Shots with this {asset.kind} inherit the LoRA{bound?.trigger || asset.lora_trigger ? ` and put “${asset.lora_trigger || bound?.trigger}” in the prompt` : ''}{asset.seed_lock !== null ? `, and render with seed ${asset.seed_lock} unless the shot sets its own` : ''}. The reference sheet renders front, three-quarter, profile and back views with one seed{asset.seed_lock === null ? ' and locks it' : ''}.</p>
    </section>
  )
}

function KitRow({ done, label, detail, children }: { done: boolean; label: string; detail: string; children?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className={'mt-0.5 flex items-center justify-center w-4 h-4 rounded-full border shrink-0 ' + (done ? 'bg-emerald-900/60 border-emerald-700 text-emerald-300' : 'border-zinc-700 text-transparent')}>
        <Check className="h-2.5 w-2.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={'text-[11px] font-medium ' + (done ? 'text-zinc-200' : 'text-zinc-500')}>{label}</span>
          {detail && <span className="text-[10px] text-zinc-600 truncate">{detail}</span>}
        </div>
        {children}
      </div>
    </div>
  )
}
