import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Copy, Image as ImageIcon, Loader2, Pin, Play, RefreshCw, Send, Sparkles, Square, Star, Trash2, Wand2 } from 'lucide-react'
import { Lightbox, type LightboxItem } from '../../components/Lightbox'
import { LoraPicker } from '../../components/LoraPicker'
import type { LoraUse } from '../../types/training'
import { useProjects } from '../../contexts/ProjectContext'
import { previewPrompt } from '../../lib/shotspec/formatters'
import { logger } from '../../lib/logger'
import { reproduceApi, reproduceMediaUrl } from '../../lib/reproduce-api'
import { toFileUrl } from '../../lib/file-url'
import { PROMPT_STYLES, SPEC_TARGETS, type PromptStyle, type SpecSection } from '../../types/shotspec'
import { isBusy, type ReproduceCandidate, type ReproduceJob } from '../../types/reproduce'
import { CandidateCompare, MetricBars } from './CandidateCompare'
import { FixCanvas } from './FixCanvas'
import { MediaImage } from './MediaImage'
import { SpecBlocks } from './SpecBlocks'
import { WhyPanel } from './WhyPanel'

const TARGET_LABEL: Record<string, string> = {
  ltx2: 'LTX-2', wan22: 'Wan 2.2', z_image: 'Z-Image', qwen_image_edit: 'Qwen-Image-Edit', flux: 'FLUX', sdxl: 'SDXL', cloud_generic: 'Hosted',
}

export function ImageReproduce() {
  const { goHome, pendingAnalysis, clearPendingAnalysis, openQuickMode, setQuickPreset, setGenSpaceEditImageUrl, openProject, projects } = useProjects()
  const [items, setItems] = useState<ReproduceJob[]>([])
  const [job, setJob] = useState<ReproduceJob | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [target, setTarget] = useState<string>('z_image')
  const [style, setStyle] = useState<PromptStyle>('tagged')
  const [promptDraft, setPromptDraft] = useState('')
  const [budget, setBudget] = useState({ candidates_per_round: 6, max_rounds: 3, target_score: 0.9 })
  const [seed, setSeed] = useState<string>('')
  const [useVlm, setUseVlm] = useState(false)
  const [loras, setLoras] = useState<LoraUse[]>([])
  const [fixing, setFixing] = useState<ReproduceCandidate | null>(null)
  const [lightbox, setLightbox] = useState<{ items: LightboxItem[]; index: number } | null>(null)
  const [serverPrompt, setServerPrompt] = useState<string>('')
  const [note, setNote] = useState('')

  const refresh = useCallback(async () => {
    try { setItems(await reproduceApi.list()) } catch (err) { logger.warn(`Could not list reproduce jobs: ${err}`) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  useEffect(() => {
    if (!pendingAnalysis || pendingAnalysis.kind !== 'image') return
    const id = pendingAnalysis.id
    clearPendingAnalysis()
    void reproduceApi.get(id).then(setJob).catch(err => setError(err instanceof Error ? err.message : String(err)))
  }, [pendingAnalysis, clearPendingAnalysis])

  // Poll while the loop runs.
  useEffect(() => {
    if (!job || !isBusy(job)) return
    const timer = window.setInterval(async () => {
      try { setJob(await reproduceApi.get(job.id)) } catch { /* deleted */ }
    }, 1200)
    return () => window.clearInterval(timer)
  }, [job])

  useEffect(() => {
    if (!job) return
    setTarget(job.target)
    setStyle(job.style ?? (job.target === 'z_image' || job.target === 'sdxl' ? 'tagged' : 'narrative'))
    setPromptDraft(job.prompt_override || job.prompt)
    setBudget(job.budget)
    if (!selectedId || !job.candidates.some(c => c.id === selectedId)) setSelectedId(job.best_candidate_id)
  }, [job, selectedId])

  // Authoritative compile for the current target/style (client preview is instant, server wins).
  useEffect(() => {
    if (!job || job.prompt_override) { setServerPrompt(''); return }
    let cancelled = false
    reproduceApi.compileAll(job.spec, [target], [style]).then(r => {
      if (cancelled) return
      const key = Object.keys(r.results)[0]
      setServerPrompt(key ? r.results[key].prompt : '')
    }).catch(() => { if (!cancelled) setServerPrompt('') })
    return () => { cancelled = true }
  }, [job, target, style])

  const preview = useMemo(() => (job ? previewPrompt(job.spec, target, style) : null), [job, target, style])
  const shownPrompt = job?.prompt_override || serverPrompt || preview?.prompt || ''

  const run = async (label: string, work: () => Promise<ReproduceJob>) => {
    setBusy(label)
    setError('')
    try {
      const next = await work()
      setJob(next)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const pick = async () => {
    try {
      const paths = await window.electronAPI.showOpenFileDialog({ title: 'Select reference image', filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'webp'] }], properties: ['openFile'] })
      if (paths?.[0]) await run('Importing', () => reproduceApi.import(paths[0]))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }

  const best = job?.candidates.find(c => c.id === job.best_candidate_id) ?? null
  const selected = job?.candidates.find(c => c.id === selectedId) ?? best
  const busyJob = job ? isBusy(job) : false

  const openLightbox = async (index: number) => {
    if (!job) return
    const list: LightboxItem[] = []
    for (const c of job.candidates) {
      try { list.push({ url: await reproduceMediaUrl(job.id, c.path), kind: 'image', label: `${c.id} · ${(c.scores.composite * 100).toFixed(0)}%`, caption: c.prompt }) } catch { /* skip */ }
    }
    setLightbox({ items: list, index: Math.min(index, list.length - 1) })
  }

  const copyPrompt = async () => {
    try { await navigator.clipboard.writeText(shownPrompt); setNote('Prompt copied') } catch { setNote('Clipboard unavailable') }
  }

  const sendToQuick = (candidate?: ReproduceCandidate) => {
    if (!job) return
    setQuickPreset({ prompt: shownPrompt, negativePrompt: job.negative_prompt, params: { model: 'fast', resolution: '540p', duration: 6, fps: 24 }, seed: candidate?.seed ?? null })
    openQuickMode()
  }

  const sendToCreate = async (candidate?: ReproduceCandidate) => {
    if (!job) return
    const path = candidate ? `${job.id}/${candidate.path}` : ''
    if (path) setGenSpaceEditImageUrl(toFileUrl(path))
    const first = projects[0]
    if (first) openProject(first.id, 'gen-space')
    else setNote('Create a project on Home first; the prompt is on the clipboard.')
    await copyPrompt()
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-zinc-800">
        <button onClick={goHome} aria-label="Back to home" className="p-2 rounded-lg hover:bg-zinc-800"><ArrowLeft className="h-4 w-4" /></button>
        <ImageIcon className="h-4 w-4 text-teal-400" />
        <h1 className="text-sm font-semibold">Reproduce image</h1>
        <span className="text-xs text-zinc-500">analyse a reference → editable ShotSpec → scored candidates that improve round over round</span>
        <button onClick={() => void pick()} disabled={!!busy} className="ml-auto btn-chip"><ImageIcon className="h-3.5 w-3.5" /> Import reference image</button>
      </header>
      {error && <p className="px-4 py-2 text-xs text-red-300 bg-red-950/30 border-b border-red-900/50" role="alert">{error}</p>}
      <div className="flex-1 min-h-0 flex">
        <aside className="w-56 shrink-0 border-r border-zinc-800 overflow-y-auto p-2">
          <h2 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold px-2 mb-1">Recent images</h2>
          {items.length === 0 && <p className="px-2 text-xs text-zinc-600">Import a reference to begin.</p>}
          {items.map(item => (
            <div key={item.id} className={`flex items-center gap-1 rounded ${job?.id === item.id ? 'bg-zinc-800' : ''}`}>
              <button onClick={() => { setJob(item); setSelectedId('') }} className="flex-1 text-left text-xs truncate px-2 py-1.5 hover:bg-zinc-800 rounded" data-testid="reproduce-item">{item.title}</button>
              <button aria-label={`Delete ${item.title}`} onClick={() => void reproduceApi.remove(item.id).then(async () => { if (job?.id === item.id) setJob(null); await refresh() }).catch(e => setError(String(e)))} className="p-1 text-zinc-600 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </aside>
        <main className="flex-1 min-w-0 overflow-y-auto p-4 space-y-4">
          {!job ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <ImageIcon className="h-8 w-8 text-zinc-800 mb-2" />
              <p className="text-sm text-zinc-400">Pick a reference image to reproduce</p>
              <p className="text-xs text-zinc-600 mt-1 max-w-md">The local vision stack reads it (Florence-2, CLIP, depth, measured stats), you edit the ShotSpec blocks, and the loop renders, scores and refines until the candidates match.</p>
            </div>
          ) : (
            <>
              <section className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm font-semibold text-white">{job.title}</h2>
                <span className="text-xs text-zinc-500">{job.width}×{job.height} · {job.image_model}{job.vision_model ? ` · read by ${job.vision_model}` : ''}</span>
                <span className={`text-xs ${job.status === 'failed' ? 'text-red-300' : busyJob ? 'text-violet-300' : 'text-zinc-400'}`} data-testid="reproduce-status">{job.status}{busyJob ? ` ${Math.round(job.progress)}% · ${job.message}` : job.message ? ` · ${job.message}` : ''}</span>
                <div className="ml-auto flex gap-1.5">
                  <button onClick={() => void run('Analysing', () => reproduceApi.analyze(job.id))} disabled={!!busy || busyJob} className="btn-chip">{busy === 'Analysing' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Analyse</button>
                  {busyJob ? (
                    <button onClick={() => void run('Cancelling', () => reproduceApi.cancel(job.id))} className="btn-chip text-red-300"><Square className="h-3.5 w-3.5" /> Cancel</button>
                  ) : (
                    <button onClick={() => void run('Starting', () => reproduceApi.start(job.id, budget, seed.trim() ? Number(seed) : null, useVlm, loras))} disabled={!!busy || !shownPrompt} className="btn-chip bg-violet-700 hover:bg-violet-600 text-white"><Play className="h-3.5 w-3.5" /> Start loop</button>
                  )}
                </div>
              </section>
              <LoraPicker model={target} value={loras} onChange={setLoras} disabled={busyJob} compact />
              {busyJob && (
                <div className="h-1.5 rounded bg-zinc-800 overflow-hidden" role="progressbar" aria-valuenow={Math.round(job.progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Reproduce progress">
                  <div className="h-full bg-violet-500 transition-all" style={{ width: `${Math.max(2, job.progress)}%` }} />
                </div>
              )}

              <CandidateCompare job={job} candidate={best} />

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <section className="space-y-2">
                  <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">ShotSpec blocks · edit and lock</h3>
                  <SpecBlocks
                    spec={job.spec}
                    disabled={busyJob}
                    onCommit={(section: SpecSection, value, lock) => void run('Updating', () => reproduceApi.updateSpec(job.id, { [section]: value } as never, lock ? { [section]: true } : undefined))}
                    onToggleLock={(section, locked) => void run('Locking', () => reproduceApi.updateSpec(job.id, {}, { [section]: locked }))}
                  />
                  <details className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
                    <summary className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold cursor-pointer">Why · evidence per block</summary>
                    <div className="mt-2"><WhyPanel job={job} /></div>
                  </details>
                </section>

                <section className="space-y-2">
                  <div className="flex items-center gap-1 flex-wrap" role="tablist" aria-label="Compile target">
                    {SPEC_TARGETS.map(t => (
                      <button key={t} role="tab" aria-selected={target === t} onClick={() => setTarget(t)} className={`px-2 py-1 rounded-md text-[11px] ${target === t ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:text-white'}`}>{TARGET_LABEL[t] ?? t}</button>
                    ))}
                    <select aria-label="Prompt style" value={style} onChange={e => setStyle(e.target.value as PromptStyle)} className="select-chip ml-auto">
                      {PROMPT_STYLES.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
                  <textarea
                    aria-label="Prompt"
                    value={job.prompt_override ? promptDraft : shownPrompt}
                    onChange={e => setPromptDraft(e.target.value)}
                    onFocus={() => { if (!job.prompt_override) setPromptDraft(shownPrompt) }}
                    readOnly={!job.prompt_override && busyJob}
                    className="w-full h-32 bg-zinc-900 border border-zinc-800 rounded-lg p-2 text-xs text-zinc-200 focus:outline-none focus:border-violet-600"
                    data-testid="reproduce-prompt"
                  />
                  <p className="text-[10px] text-zinc-500">Negative: {job.negative_prompt || preview?.negative_prompt}</p>
                  <div className="flex gap-1.5 flex-wrap">
                    <button onClick={() => void run('Saving prompt', () => reproduceApi.setPrompt(job.id, promptDraft, target, style))} disabled={!!busy || busyJob} className="btn-chip">Use this prompt &amp; target</button>
                    {job.prompt_override && <button onClick={() => void run('Reverting', () => reproduceApi.setPrompt(job.id, '', target, style))} disabled={!!busy || busyJob} className="btn-chip">Back to compiled prompt</button>}
                    <button onClick={() => void copyPrompt()} className="btn-chip"><Copy className="h-3.5 w-3.5" /> Copy</button>
                    <button onClick={() => sendToQuick(best ?? undefined)} className="btn-chip"><Send className="h-3.5 w-3.5" /> Send to Quick video</button>
                    <button onClick={() => void sendToCreate(best ?? undefined)} className="btn-chip"><Send className="h-3.5 w-3.5" /> Send to Create</button>
                    <button disabled className="btn-chip" title="Lands with the 3D storyboard"><Send className="h-3.5 w-3.5" /> Send to Composer</button>
                    <button disabled className="btn-chip" title="Lands with the Train tab"><Send className="h-3.5 w-3.5" /> Send to Train</button>
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-[10px] text-zinc-500">
                    <label>Candidates / round<input type="number" min={1} max={12} value={budget.candidates_per_round} onChange={e => setBudget(b => ({ ...b, candidates_per_round: Number(e.target.value) }))} className="select-chip w-full" aria-label="Candidates per round" /></label>
                    <label>Rounds<input type="number" min={1} max={8} value={budget.max_rounds} onChange={e => setBudget(b => ({ ...b, max_rounds: Number(e.target.value) }))} className="select-chip w-full" aria-label="Max rounds" /></label>
                    <label>Target score<input type="number" min={0} max={1} step={0.01} value={budget.target_score} onChange={e => setBudget(b => ({ ...b, target_score: Number(e.target.value) }))} className="select-chip w-full" aria-label="Target score" /></label>
                    <label>Seed<input value={seed} onChange={e => setSeed(e.target.value)} placeholder="random" className="select-chip w-full" aria-label="Seed" /></label>
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-zinc-400"><input type="checkbox" checked={useVlm} onChange={e => setUseVlm(e.target.checked)} className="accent-violet-500" /> Ask the VLM to compare when a round plateaus</label>
                  {note && <p className="text-[11px] text-zinc-400" role="status">{note}</p>}
                </section>
              </div>

              {job.rounds.length > 0 && (
                <section className="space-y-1.5">
                  <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Rounds</h3>
                  <ol className="space-y-1" data-testid="round-history">
                    {job.rounds.map(round => (
                      <li key={round.index} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-2 text-[11px]">
                        <div className="flex gap-2 text-zinc-300"><span className="font-semibold">Round {round.index}</span><span className="text-zinc-500">{round.target}/{round.style} · seeds {round.seeds.join(', ')}</span><span className="ml-auto">best {(round.best_score * 100).toFixed(0)}%</span></div>
                        {round.hints_applied.length > 0 && <p className="text-violet-300">Knowledge hints: {round.hints_applied.join(', ')}</p>}
                        {round.patches.map((p, i) => <p key={i} className="text-zinc-400">↳ {p.reason}{p.metric ? ` (${p.metric} ${(p.value * 100).toFixed(0)}%)` : ''} → “{p.phrase}”</p>)}
                        {round.note && <p className="text-zinc-500">{round.note}</p>}
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {job.candidates.length > 0 && (
                <section className="space-y-1.5">
                  <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Candidates ({job.candidates.length})</h3>
                  <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(180px,1fr))]" data-testid="candidate-grid">
                    {job.candidates.map((candidate, index) => (
                      <div key={candidate.id} className={`rounded-lg border p-1.5 ${selected?.id === candidate.id ? 'border-violet-500' : 'border-zinc-800'} ${job.picked_candidate_id === candidate.id ? 'ring-1 ring-amber-400/60' : ''}`} data-testid="candidate-card">
                        <div className="aspect-video rounded overflow-hidden bg-black cursor-zoom-in" onClick={() => setSelectedId(candidate.id)}>
                          <MediaImage jobId={job.id} path={candidate.path} alt={`Candidate ${candidate.id}`} className="w-full h-full object-cover" onClick={() => void openLightbox(index)} />
                        </div>
                        <div className="flex items-center gap-1 mt-1 text-[10px] text-zinc-400">
                          <span className="font-semibold text-zinc-200">{(candidate.scores.composite * 100).toFixed(0)}%</span>
                          <span>r{candidate.round}{candidate.source !== 'render' ? ` · ${candidate.source}` : ''}{candidate.seed !== null ? ` · ${candidate.seed}` : ''}</span>
                          <span className="ml-auto flex gap-0.5">
                            <button onClick={() => void run('Pinning', () => reproduceApi.pin(job.id, job.reference_candidate_id === candidate.id ? '' : candidate.id))} aria-label={`Pin ${candidate.id} as reference`} aria-pressed={job.reference_candidate_id === candidate.id} className={`p-0.5 rounded ${job.reference_candidate_id === candidate.id ? 'text-teal-300' : 'hover:text-white'}`}><Pin className="h-3 w-3" /></button>
                            <button onClick={() => void run('Picking', () => reproduceApi.pick(job.id, candidate.id))} aria-label={`Pick ${candidate.id}`} className={`p-0.5 rounded ${job.picked_candidate_id === candidate.id ? 'text-amber-300' : 'hover:text-white'}`}><Star className="h-3 w-3" /></button>
                            <button onClick={() => setFixing(candidate)} aria-label={`Fix ${candidate.id}`} className="p-0.5 rounded hover:text-white"><Wand2 className="h-3 w-3" /></button>
                          </span>
                        </div>
                        {selected?.id === candidate.id && <div className="mt-1"><MetricBars scores={candidate.scores} /></div>}
                      </div>
                    ))}
                  </div>
                </section>
              )}
              {job.candidates.length === 0 && job.status === 'complete' && (
                <p className="text-xs text-zinc-500 flex items-center gap-1"><RefreshCw className="h-3 w-3" /> No candidate was produced — check the image model in Settings → AI Models, then start again.</p>
              )}
            </>
          )}
        </main>
      </div>
      {fixing && job && (
        <FixCanvas job={job} candidate={fixing} onClose={() => setFixing(null)} onCommitted={next => { setJob(next); setFixing(null) }} onUseAsStartFrame={c => { setFixing(null); sendToQuick(c) }} />
      )}
      {lightbox && <Lightbox items={lightbox.items} index={lightbox.index} onClose={() => setLightbox(null)} onIndexChange={i => setLightbox(l => (l ? { ...l, index: i } : l))} />}
    </div>
  )
}
