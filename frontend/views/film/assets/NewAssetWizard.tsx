/**
 * Layout 3 — "New asset": one seed image (or a text prompt) → the AI
 * builds the consistency kit with the existing endpoints, sequenced by
 * `useNewAssetPipeline`. The engine indicator reads the project's real
 * media provider — image-model choice is project-global, so it is shown,
 * not faked as a per-request switch.
 */

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Check, Cloud, HardDrive, ImagePlus, Loader2, RefreshCw, Sparkles, Upload, X } from 'lucide-react'
import { useAppSettings } from '../../../contexts/AppSettingsContext'
import { useFilm } from '../../../contexts/FilmContext'
import { filmApi } from '../../../lib/film-api'
import type { AssetStyleGuide, FilmAssetKind } from '../../../types/film'
import { SHEET_VIEWS, consistencyOf, sheetImages } from './consistency'
import { ConsistencyPips } from './AssetCard'
import { EMPTY_GUIDE, StyleGuideEditor } from './StyleGuideEditor'
import { KIND_META, ThumbError, inputClass, readFileAsDataUrl, useFilmMediaUrl } from './shared'
import { STYLE_SAMPLE_SUBJECTS, useNewAssetPipeline, type PipelineStep } from './useNewAssetPipeline'

const KINDS: FilmAssetKind[] = ['character', 'location', 'prop', 'style']

export function NewAssetWizard({ onClose, onDone }: { onClose: () => void; onDone: (assetId: string) => void }) {
  const { film, refresh } = useFilm()
  const { settings } = useAppSettings()
  const pipeline = useNewAssetPipeline()
  const [kind, setKind] = useState<FilmAssetKind>('character')
  const [name, setName] = useState('')
  const [seed, setSeed] = useState<{ imageBase64: string; fileName: string } | null>(null)
  const [textPrompt, setTextPrompt] = useState('')
  const [useTextPrompt, setUseTextPrompt] = useState(false)
  const [guideDraft, setGuideDraft] = useState<AssetStyleGuide>(EMPTY_GUIDE)
  const [guideSeeded, setGuideSeeded] = useState(false)
  const [busyTile, setBusyTile] = useState('')
  const fileInput = useRef<HTMLInputElement | null>(null)

  const asset = film?.assets.find(a => a.id === pipeline.assetId) ?? null
  const started = pipeline.assetId !== null
  const allDone = pipeline.steps.every(s => s.status === 'done')
  const failedStep = pipeline.steps.find(s => s.status === 'error')

  // The AI draft arrives when the guide step lands; edits stay local until Create.
  useEffect(() => {
    if (asset?.style_guide && !guideSeeded) { setGuideDraft(asset.style_guide); setGuideSeeded(true) }
  }, [asset?.style_guide, guideSeeded])

  const provider = (film?.settings.media_provider || settings.mediaProvider || 'local').trim() || 'local'
  const local = provider === 'local'
  const engine = local ? 'local' : provider
  const model = local ? 'local image model' : film?.settings.image_model || settings.defaultImageModel || 'not set'

  const pickFile = async (file: File) => {
    try { setSeed({ imageBase64: await readFileAsDataUrl(file), fileName: file.name }) }
    catch { setSeed(null) }
  }

  const build = () => {
    if (!film) return
    void pipeline.run({ kind, name, seed: useTextPrompt ? { prompt: textPrompt.trim() } : seed! })
  }

  const skipAi = async () => {
    if (!film) return
    const count = film.assets.filter(a => a.kind === kind).length
    const created = await filmApi.createAsset(film.id, { kind, name: name.trim() || `${KIND_META[kind].label} ${count + 1}` })
    await refresh()
    onDone(created.id)
  }

  const create = async () => {
    if (!film || !pipeline.assetId) return
    if (asset?.style_guide && JSON.stringify(guideDraft) !== JSON.stringify(asset.style_guide)) {
      await filmApi.updateAsset(film.id, pipeline.assetId, { style_guide: guideDraft })
      await refresh()
    }
    onDone(pipeline.assetId)
  }

  const cancel = () => {
    if (!pipeline.assetId) { onClose(); return }
    if (window.confirm('Delete the asset built so far? OK deletes it; Cancel keeps it as a manual asset.')) {
      void pipeline.discard().then(onClose)
    } else onClose()
  }

  const reExtract = () => {
    if (!film || !pipeline.assetId) return
    if (guideSeeded && asset?.style_guide && JSON.stringify(guideDraft) !== JSON.stringify(asset.style_guide)
      && !window.confirm('Re-extract the style guide? Your manual edits are overwritten.')) return
    void filmApi.generateAssetStyleGuide(film.id, pipeline.assetId).then(async updated => {
      await refresh()
      if (updated.style_guide) setGuideDraft(updated.style_guide)
    })
  }

  const regenerateView = async (view: string) => {
    if (!film || !pipeline.assetId) return
    setBusyTile(view)
    try {
      const prompt = [asset?.style_guide?.recommended_prompt ?? '', view, 'consistent character sheet, same person, same outfit'].filter(Boolean).join(', ')
      await filmApi.generateAssetReference(film.id, pipeline.assetId, prompt)
      await refresh()
    } finally { setBusyTile('') }
  }

  const deleteRef = async (path: string) => {
    if (!film || !pipeline.assetId) return
    await filmApi.deleteAssetReference(film.id, pipeline.assetId, path)
    await refresh()
  }

  const replaceRef = (path: string) => {
    if (!film || !pipeline.assetId) return
    const input = document.createElement('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file || !film || !pipeline.assetId) return
      await filmApi.deleteAssetReference(film.id, pipeline.assetId, path)
      await filmApi.addAssetReference(film.id, pipeline.assetId, await readFileAsDataUrl(file), file.name)
      await refresh()
    }
    input.click()
  }

  const addExtra = () => {
    if (!film || !pipeline.assetId) return
    const input = document.createElement('input'); input.type = 'file'; input.accept = 'image/png,image/jpeg,image/webp'
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file || !film || !pipeline.assetId) return
      await filmApi.addAssetReference(film.id, pipeline.assetId, await readFileAsDataUrl(file), file.name)
      await refresh()
    }
    input.click()
  }

  if (!film) return null
  const canBuild = !pipeline.running && !started && (useTextPrompt ? textPrompt.trim().length > 0 : seed !== null)
  const stepLabel = (step: PipelineStep): { label: string; caption: string } => {
    switch (step.id) {
      case 'source': return useTextPrompt
        ? { label: 'Generate seed image', caption: `text prompt · ${engine}` }
        : { label: 'Attach source image', caption: 'your seed image' }
      case 'guide': return { label: 'Analyze image & write style guide', caption: local ? 'vision model · local' : `vision model · ${provider}` }
      case 'renders': return kind === 'style'
        ? { label: `Render 4 sample looks${step.progress ? ` · ${step.progress}` : ''}`, caption: `four subjects, one look · ${engine}` }
        : { label: 'Render turnaround · 4 views', caption: `one seed · ${engine}` }
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="new-asset-wizard">
      <div className="h-14 shrink-0 border-b border-zinc-800 px-4 flex items-center gap-3">
        <h2 className="text-sm font-semibold text-white">New asset</h2>
        <div className="flex items-center gap-1.5 text-[10px]">
          <StepChip n={1} label="Source" done={started} active={!started} />
          <span className="text-zinc-700">→</span>
          <StepChip n={2} label="AI builds the kit" done={allDone && started} active={started && !allDone} />
          <span className="text-zinc-700">→</span>
          <StepChip n={3} label="Review & create" done={false} active={allDone && started} />
        </div>
        <div className="flex-1" />
        <button onClick={cancel} aria-label="Close wizard" className="p-1.5 rounded hover:bg-zinc-800 text-zinc-400"><X className="h-4 w-4" /></button>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Column 1 — source */}
        <div className="w-80 shrink-0 border-r border-zinc-800 p-4 space-y-4 overflow-y-auto">
          <div>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Kind</span>
            <div className="grid grid-cols-2 gap-1.5 mt-1.5">
              {KINDS.map(k => (
                <button key={k} onClick={() => setKind(k)} disabled={started} aria-pressed={kind === k}
                  className={'flex items-center gap-1.5 px-2 py-2 rounded-lg border text-[11px] transition-colors disabled:opacity-50 ' + (kind === k ? 'border-violet-600 bg-violet-950/40 text-zinc-100' : 'border-zinc-800 text-zinc-400 hover:border-zinc-600')}>
                  <span className={KIND_META[k].color.split(' ')[1]}>{KIND_META[k].icon}</span>{KIND_META[k].label}
                </button>
              ))}
            </div>
            {kind === 'style' && <p className="text-[10px] text-fuchsia-300/80 mt-1.5">A style is a look — film stock, grade, lighting — not a subject. The seed image defines the look; four sample renders show it applied.</p>}
          </div>

          <label className="block">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Name</span>
            <input className={inputClass + ' mt-1'} value={name} onChange={e => setName(e.target.value)} disabled={started}
              placeholder={`${KIND_META[kind].label} name`} aria-label="New asset name" />
          </label>

          <div>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Seed image — just one</span>
            {!useTextPrompt ? (
              <>
                <div onDragOver={e => e.preventDefault()}
                  onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) void pickFile(f) }}
                  onPaste={e => { const f = e.clipboardData.files?.[0]; if (f) void pickFile(f) }}
                  className={'mt-1.5 aspect-[4/3] rounded-lg border-2 border-dashed flex items-center justify-center relative overflow-hidden ' + (seed ? 'border-emerald-800' : 'border-zinc-800 hover:border-violet-700')}>
                  {seed ? (
                    <>
                      <img src={seed.imageBase64} alt="Seed" className="w-full h-full object-cover" />
                      <span className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded bg-emerald-900/80 text-[10px] text-emerald-300">Source ✓</span>
                      <button onClick={() => fileInput.current?.click()} disabled={started}
                        className="absolute bottom-1.5 right-1.5 px-1.5 py-0.5 rounded bg-zinc-950/80 text-[10px] text-zinc-300 hover:text-white disabled:opacity-50">replace</button>
                    </>
                  ) : (
                    <button onClick={() => fileInput.current?.click()} className="flex flex-col items-center gap-1.5 text-zinc-600 hover:text-violet-300">
                      <Upload className="h-5 w-5" />
                      <span className="text-[11px]">Drop, paste or pick an image</span>
                    </button>
                  )}
                </div>
                {seed && <p className="text-[10px] text-zinc-600 mt-1 truncate">{seed.fileName}</p>}
                <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" aria-label="Seed image"
                  data-testid="wizard-seed-file" onChange={e => { const f = e.target.files?.[0]; if (f) void pickFile(f) }} />
                <button onClick={() => setUseTextPrompt(true)} disabled={started} className="text-[10px] text-violet-400 hover:text-violet-300 mt-1 disabled:opacity-50">
                  generate from a text prompt instead
                </button>
              </>
            ) : (
              <>
                <textarea className={inputClass + ' mt-1.5 resize-none h-20'} value={textPrompt} onChange={e => setTextPrompt(e.target.value)}
                  disabled={started} placeholder="Describe the seed image to generate…" aria-label="Seed image prompt" />
                <button onClick={() => setUseTextPrompt(false)} disabled={started} className="text-[10px] text-violet-400 hover:text-violet-300 mt-1 disabled:opacity-50">
                  use an image instead
                </button>
              </>
            )}
          </div>

          <div className="rounded-lg border border-zinc-800 p-2.5">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Engine</span>
            <div className="flex items-center gap-1.5 mt-1 text-[11px] text-zinc-300">
              {local ? <HardDrive className="h-3.5 w-3.5 text-emerald-400" /> : <Cloud className="h-3.5 w-3.5 text-sky-400" />}
              {local ? 'Local · GPU' : `Cloud API · ${provider}`}
              <span className="text-zinc-600">·</span>
              <span className="text-zinc-500 truncate">{model}</span>
            </div>
            <p className="text-[10px] text-zinc-600 mt-1">Image models are chosen per project — change them in the Models tab.</p>
          </div>

          <button onClick={build} disabled={!canBuild} data-testid="wizard-build"
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-xs font-medium text-white">
            {pipeline.running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Build kit with AI
          </button>
          {!started && (
            <button onClick={() => void skipAi()} className="w-full text-[10px] text-zinc-500 hover:text-zinc-300">
              Skip AI — create manually
            </button>
          )}
        </div>

        {/* Column 2 — pipeline + image kit */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <section className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">AI pipeline</span>
              {pipeline.steps.map((step, i) => {
                const text = stepLabel(step)
                return (
                  <div key={step.id} className="flex items-start gap-2" data-testid={`pipeline-step-${i + 1}`}>
                    <span className={'mt-0.5 flex items-center justify-center w-4 h-4 rounded-full border shrink-0 ' + (
                      step.status === 'done' ? 'bg-emerald-900/60 border-emerald-700 text-emerald-300'
                        : step.status === 'running' ? 'border-violet-600 text-violet-300'
                          : step.status === 'error' ? 'border-red-800 text-red-300' : 'border-zinc-700 text-transparent')}>
                      {step.status === 'done' ? <Check className="h-2.5 w-2.5" />
                        : step.status === 'running' ? <Loader2 className="h-2.5 w-2.5 animate-spin" />
                          : step.status === 'error' ? <AlertCircle className="h-2.5 w-2.5" /> : <Check className="h-2.5 w-2.5" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className={'text-[11px] ' + (step.status === 'pending' ? 'text-zinc-600' : 'text-zinc-200')}>{text.label}</span>
                        <span className="text-[9px] text-zinc-600">{text.caption}</span>
                        {step.status === 'error' && (
                          <button onClick={() => void pipeline.retry()} className="ml-auto flex items-center gap-1 text-[10px] text-amber-300 hover:text-amber-200">
                            <RefreshCw className="h-2.5 w-2.5" /> retry
                          </button>
                        )}
                      </div>
                      {step.error && <p className="text-[10px] text-red-300 mt-0.5">{step.error}</p>}
                    </div>
                  </div>
                )
              })}
              {failedStep && <p className="text-[10px] text-zinc-600">Completed steps are kept — the asset already exists, so cancelling still leaves a valid manual asset.</p>}
            </section>

            <section>
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Image kit</span>
              <div className="grid grid-cols-3 xl:grid-cols-5 gap-2 mt-1.5">
                <KitTile label="Source" testid="kit-tile-source" path={asset?.reference_images[0] ?? null}
                  fallback={seed?.imageBase64 ?? null} highlight />
                {kind === 'style'
                  ? STYLE_SAMPLE_SUBJECTS.map((subject, i) => (
                    <KitTile key={subject} label={`Look ${i + 1}`} testid={`kit-tile-look-${i + 1}`}
                      path={asset?.reference_images[i + 1] ?? null}
                      rendering={pipeline.steps[2].status === 'running'} caption={subject} />
                  ))
                  : SHEET_VIEWS.map(view => {
                    const path = asset ? sheetImages(asset).find(s => s.view === view)?.path ?? null : null
                    const short = view.replace(' view', '')
                    return (
                      <KitTile key={view} label={short} testid={`kit-tile-${short.replace(' ', '-')}`} path={path}
                        rendering={pipeline.steps[2].status === 'running' || busyTile === view} caption={local ? 'local · one seed' : `${provider} · one seed`}
                        actions={path ? {
                          regenerate: () => void regenerateView(view),
                          replace: () => replaceRef(path),
                          remove: () => void deleteRef(path),
                        } : undefined} />
                    )
                  })}
                <button onClick={addExtra} disabled={!started} aria-label="Add another image"
                  className="aspect-[4/3] rounded-lg border-2 border-dashed border-zinc-800 hover:border-violet-700 text-zinc-600 hover:text-violet-300 disabled:opacity-40 flex flex-col items-center justify-center gap-1">
                  <ImagePlus className="h-4 w-4" /><span className="text-[10px]">Add image</span>
                </button>
              </div>
            </section>
          </div>

          <div className="shrink-0 border-t border-zinc-800 px-4 py-2.5 flex items-center gap-3">
            {asset ? <div className="w-56"><ConsistencyPips asset={asset} /></div> : <span className="text-[10px] text-zinc-600">ON CREATE: REF · GUIDE · SEED from the pipeline; bind a LoRA later from the Consistency Kit.</span>}
            {asset && asset.kind !== 'style' && !consistencyOf(asset).lora && <span className="text-[10px] text-zinc-600">bind a LoRA later from the Consistency Kit</span>}
            <div className="flex-1" />
            <button onClick={cancel} className="px-3 py-1.5 rounded text-xs text-zinc-400 hover:text-zinc-200">Cancel</button>
            <button onClick={() => void create()} disabled={!started || pipeline.running} data-testid="wizard-create"
              className="px-4 py-1.5 rounded bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-xs font-medium text-white">
              Create asset{asset ? ` · ${asset.reference_images.length} image${asset.reference_images.length === 1 ? '' : 's'}` : ''}
            </button>
          </div>
        </div>

        {/* Column 3 — editable style guide */}
        <div className="w-[372px] shrink-0 border-l border-zinc-800 p-4 space-y-3 overflow-y-auto">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Style guide — the AI draft, yours to edit</span>
            <button onClick={reExtract} disabled={!asset?.style_guide} className="ml-auto flex items-center gap-1 text-[10px] text-amber-300 hover:text-amber-200 disabled:opacity-40">
              <RefreshCw className="h-2.5 w-2.5" /> Re-extract
            </button>
          </div>
          {guideSeeded
            ? <StyleGuideEditor guide={guideDraft} onChange={setGuideDraft} />
            : <p className="text-[11px] text-zinc-600">The style guide appears here once the analysis step finishes, ready to edit before you create the asset.</p>}
          {asset && (asset.appearance || asset.wardrobe || asset.description) && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-2.5 space-y-1">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide font-semibold">Auto-filled asset fields</span>
              {asset.description && <p className="text-[10px] text-zinc-400"><span className="text-zinc-600">description · </span>{asset.description}</p>}
              {asset.appearance && <p className="text-[10px] text-zinc-400"><span className="text-zinc-600">appearance · </span>{asset.appearance}</p>}
              {asset.wardrobe && <p className="text-[10px] text-zinc-400"><span className="text-zinc-600">wardrobe · </span>{asset.wardrobe}</p>}
              <p className="text-[9px] text-zinc-600">Editable on the asset after you create it.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StepChip({ n, label, done, active }: { n: number; label: string; done: boolean; active: boolean }) {
  return (
    <span className={'flex items-center gap-1 px-2 py-0.5 rounded-full border ' + (done ? 'border-emerald-800 text-emerald-300' : active ? 'border-violet-700 text-violet-200' : 'border-zinc-800 text-zinc-600')}>
      {done ? <Check className="h-2.5 w-2.5" /> : <span className="font-semibold">{n}</span>} {label}
    </span>
  )
}

function KitTile({ label, testid, path, fallback = null, rendering = false, caption = '', highlight = false, actions }: {
  label: string
  testid: string
  path: string | null
  fallback?: string | null
  rendering?: boolean
  caption?: string
  highlight?: boolean
  actions?: { regenerate: () => void; replace: () => void; remove: () => void }
}) {
  const state = useFilmMediaUrl(path ?? undefined)
  const border = highlight ? 'border-emerald-800' : 'border-zinc-800'
  return (
    <div data-testid={testid}>
      <div className={`group relative aspect-[4/3] rounded-lg border ${border} bg-zinc-950 overflow-hidden`}>
        {path && state.status === 'ready' ? (
          <img src={state.url} alt="" loading="lazy" className="w-full h-full object-cover" />
        ) : path && state.status === 'error' ? (
          <ThumbError className="w-full h-full" message={state.message} />
        ) : path ? (
          <div className="w-full h-full bg-zinc-900 animate-pulse" />
        ) : fallback ? (
          <img src={fallback} alt="" className="w-full h-full object-cover" />
        ) : rendering ? (
          <div className="w-full h-full flex flex-col items-center justify-center gap-1 text-violet-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            {caption && <span className="text-[9px] text-zinc-500">{caption}</span>}
          </div>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-zinc-700">queued</div>
        )}
        {actions && path && (
          <div className="absolute inset-x-0 bottom-0 hidden group-hover:flex items-center justify-center gap-1 bg-zinc-950/80 py-1">
            <button onClick={actions.regenerate} className="text-[9px] text-violet-300 hover:text-violet-200">regenerate</button>
            <span className="text-zinc-700 text-[9px]">·</span>
            <button onClick={actions.replace} className="text-[9px] text-zinc-300 hover:text-white">replace</button>
            <span className="text-zinc-700 text-[9px]">·</span>
            <button onClick={actions.remove} className="text-[9px] text-red-300 hover:text-red-200">delete</button>
          </div>
        )}
      </div>
      <span className="block text-center text-[10px] text-zinc-500 mt-0.5 capitalize">{label}</span>
    </div>
  )
}
