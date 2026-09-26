import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Image as ImageIcon, Loader2, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { useProjects } from '../contexts/ProjectContext'
import { imageAnalysisApi, imageAnalysisMediaUrl, type ImageAnalysis, type ImageCandidate } from '../lib/image-analysis-api'

function Preview({ id, path, alt }: { id: string; path: string; alt: string }) {
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    setUrl('')
    setFailed(false)
    void imageAnalysisMediaUrl(id, path).then(next => { if (active) setUrl(next) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [id, path])
  return url && !failed ? <img src={url} alt={alt} onError={() => setFailed(true)} className="w-full h-full object-contain bg-zinc-950 rounded-lg" />
    : <div role="status" className="flex items-center justify-center h-full text-zinc-400 text-sm">{failed ? 'Preview unavailable' : 'Loading preview…'}</div>
}

export function AnalyzeImage() {
  const { goHome, pendingAnalysis, clearPendingAnalysis } = useProjects()
  const [items, setItems] = useState<ImageAnalysis[]>([])
  const [job, setJob] = useState<ImageAnalysis | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')
  const [draft, setDraft] = useState('')
  useEffect(() => { setDraft(job?.prompt || '') }, [job?.id, job?.prompt])
  const refresh = useCallback(async () => setItems(await imageAnalysisApi.list()), [])
  useEffect(() => { void refresh().catch(() => undefined) }, [refresh])
  // Opened from History with a specific analysis: load it, then forget the request.
  useEffect(() => {
    if (!pendingAnalysis || pendingAnalysis.kind !== 'image') return
    const id = pendingAnalysis.id
    clearPendingAnalysis()
    void imageAnalysisApi.get(id).then(setJob).catch(err => setError(err instanceof Error ? err.message : String(err)))
  }, [pendingAnalysis, clearPendingAnalysis])
  const run = async (name: string, task: () => Promise<ImageAnalysis>) => {
    setBusy(name)
    setError('')
    try { const next = await task(); setJob(next); await refresh() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }
  const pick = async () => {
    try {
      const paths = await window.electronAPI.showOpenFileDialog({ title: 'Select reference image', filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'webp'] }], properties: ['openFile'] })
      if (paths?.[0]) await run('Importing', () => imageAnalysisApi.import(paths[0]))
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }
  const best = job?.candidates.find(c => c.id === job.best_candidate_id)
  const current = job?.candidates.find(c => c.id === selected) ?? best
  const button = 'px-3 py-2 rounded-lg border border-zinc-700 text-sm font-medium hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed'
  return <div className="h-screen flex flex-col bg-zinc-950 text-zinc-100">
    <header className="h-14 shrink-0 border-b border-zinc-800 flex items-center gap-3 px-5">
      <button onClick={goHome} aria-label="Back to home" className="text-zinc-400 hover:text-white"><ArrowLeft size={18} /></button>
      <ImageIcon size={18} className="text-teal-400" /><h1 className="text-sm font-semibold">Recreate from image</h1>
      {job && <span className="text-xs text-zinc-400 truncate">{job.title} · {job.width}×{job.height}</span>}
      {busy && <span role="status" className="ml-auto flex items-center gap-2 text-xs text-teal-300"><Loader2 size={14} className="animate-spin" />{busy}…</span>}
    </header>
    {error && <div role="alert" className="m-4 p-3 bg-red-950/40 border border-red-800 rounded-lg text-sm text-red-200">{error}</div>}
    <div className="flex flex-1 min-h-0">
      <aside className="w-64 shrink-0 border-r border-zinc-800 p-4 overflow-y-auto space-y-4">
        <button onClick={() => void pick()} disabled={!!busy} className="w-full py-2 rounded-lg bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-sm font-medium">Import reference image</button>
        <p className="text-xs text-zinc-400">PNG, JPG or WebP · max 20 MB. Vision AI reads the image; the recommended local model is qwen2.5vl:7b. Images render with {job?.image_model || 'your configured image generator'}.</p>
        <h2 className="uppercase tracking-wide text-xs text-zinc-500">Recent images</h2>
        {items.map(item => <div key={item.id} className="flex items-center gap-1"><button onClick={() => { setJob(item); setSelected(''); setError('') }} className="flex-1 text-left text-sm truncate p-2 rounded hover:bg-zinc-800">{item.title}</button><button aria-label={`Delete ${item.title}`} onClick={() => void imageAnalysisApi.remove(item.id).then(async () => { if (job?.id === item.id) setJob(null); await refresh() }).catch(e => setError(String(e)))}><Trash2 size={14} /></button></div>)}
      </aside>
      <main className="flex-1 min-w-0 overflow-y-auto p-5 space-y-5">
        {!job ? <div className="h-full flex items-center justify-center text-zinc-400 text-sm">Choose a reference image to begin.</div> : <>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <section className="space-y-2"><h2 className="font-medium text-sm">Reference</h2><div className="aspect-video rounded-lg border border-zinc-800 bg-zinc-900"><Preview id={job.id} path={job.source_path} alt="Reference image" /></div></section>
            <section className="space-y-2"><h2 className="font-medium text-sm">{current ? `Candidate · ${Math.round(current.score * 100)}% relative likeness` : 'Best candidate'}</h2><div className="aspect-video rounded-lg border border-zinc-800 bg-zinc-900">{current ? <Preview id={job.id} path={current.path} alt="Generated candidate" /> : <div className="h-full flex items-center justify-center text-sm text-zinc-500">Generate candidates to compare with your reference.</div>}</div></section>
          </div>
          <div className="flex flex-wrap items-center gap-2"><button className={button} disabled={!!busy} onClick={() => void run('Analyzing image', () => imageAnalysisApi.analyze(job.id))}><Sparkles size={14} className="inline mr-2" />Analyze image</button><button className={button} disabled={!!busy || !job.prompt || draft !== job.prompt} onClick={() => void run('Generating candidates', () => imageAnalysisApi.render(job.id, 2))}>Generate 2 candidates</button><button className={button} disabled={!!busy || !best || job.revisions.length >= 2} onClick={() => void run('Comparing and refining', () => imageAnalysisApi.refine(job.id))}><RefreshCw size={14} className="inline mr-2" />Compare & refine</button></div>
          <p className="text-xs text-zinc-400">Relative scores compare actual rendered pixels and spatial regions at equal size; they are not calibrated accuracy or a guarantee of identical reproduction. Compare visually before accepting a result. Two revisions and nine total candidates maximum.</p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <section className="space-y-2"><h2 className="font-medium text-sm">Evidence-based prompt</h2><p className="text-xs text-zinc-500">Vision: {job.vision_model || 'Not analyzed'} · Image generator: {job.image_model}</p><textarea aria-label="Image generation prompt" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Analyze the image to draft a prompt, or write your own." className="w-full h-32 bg-zinc-900 border border-zinc-700 rounded-lg p-3 text-sm text-white resize-y" /><button disabled={!!busy || !draft.trim() || draft === job.prompt} className={button} onClick={() => void run('Saving prompt', () => imageAnalysisApi.editPrompt(job.id, draft))}>Save prompt</button>{draft !== job.prompt && <p className="text-xs text-amber-300">Save edits before generating.</p>}<div className="text-xs text-zinc-400 space-y-1">{(['subjects','composition','colors','lighting','style'] as const).map(key => job[key] && <p key={key}><span className="capitalize text-zinc-500">{key}: </span>{job[key]}</p>)}</div></section>
            <section className="space-y-2"><h2 className="font-medium text-sm">Revisions and visible differences</h2>{job.revisions.length ? job.revisions.map((rev, i) => <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-xs"><p className="text-amber-300">Round {i + 1}: {rev.differences}</p><p className="mt-2 text-zinc-300">{rev.prompt}</p></div>) : <p className="text-zinc-500 text-sm">Generate a candidate, then compare to find concrete differences.</p>}</section>
          </div>
          {job.candidates.length > 0 && <section className="space-y-2"><h2 className="font-medium text-sm">All candidates · choose to inspect</h2><div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">{job.candidates.map((candidate: ImageCandidate) => <button key={candidate.id} onClick={() => setSelected(candidate.id)} className={`rounded-lg border p-2 text-left ${current?.id === candidate.id ? 'border-teal-400' : 'border-zinc-700'}`}><div className="aspect-video"><Preview id={job.id} path={candidate.path} alt={`Candidate ${candidate.id}`} /></div><p className="text-xs mt-2">Round {candidate.round} · {Math.round(candidate.score * 100)}%{candidate.id === job.best_candidate_id ? ' · best' : ''}</p></button>)}</div></section>}
        </>}
      </main>
    </div>
  </div>
}
