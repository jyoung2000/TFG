import { useCallback, useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, Sparkles, Wand2, X } from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import { Button } from '../../components/ui/button'
import {
  CAMERA_MOVES,
  SHOT_SIZES,
  type DirectorContextDetails,
  type FilmBuildPlan,
  type FilmBuildScene,
  type FilmBuildShot,
} from '../../types/film'

const inputClass =
  'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

/**
 * "Build Film with AI": idea → structured, editable plan (characters,
 * locations, scenes, shots) → apply. Nothing is persisted until Apply; the
 * user can edit every field of the plan first. Works without any AI key via
 * the deterministic planner (standard coverage per beat).
 */
export function BuildFilmDialog({ onClose, onApplied }: { onClose: () => void; onApplied: () => void }) {
  const { film, refresh } = useFilm()
  const { hasDirectorProvider } = useAppSettings()
  const [idea, setIdea] = useState('')
  const [style, setStyle] = useState('')
  const [targetScenes, setTargetScenes] = useState(3)
  const [targetShots, setTargetShots] = useState(3)
  const [plan, setPlan] = useState<FilmBuildPlan | null>(null)
  const [context, setContext] = useState<DirectorContextDetails | null>(null)
  const [usedLlm, setUsedLlm] = useState(false)
  const [busy, setBusy] = useState<'plan' | 'apply' | null>(null)
  const [error, setError] = useState('')
  const [openScenes, setOpenScenes] = useState<Record<number, boolean>>({ 0: true })

  const build = useCallback(
    async (useLlm: boolean) => {
      if (!film || !idea.trim()) return
      setBusy('plan')
      setError('')
      try {
        const result = await filmApi.buildFilm(film.id, {
          idea: idea.trim(),
          style: style.trim(),
          target_scenes: targetScenes,
          target_shots_per_scene: targetShots,
          use_llm: useLlm,
        })
        setPlan(result.plan)
        setContext(result.context)
        setUsedLlm(result.used_llm)
        setOpenScenes({ 0: true })
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(null)
      }
    },
    [film, idea, style, targetScenes, targetShots],
  )

  const apply = useCallback(async () => {
    if (!film || !plan) return
    const hasScenes = film.scenes.length > 0
    if (hasScenes && !window.confirm('Replace the existing storyboard with this plan?')) return
    setBusy('apply')
    setError('')
    try {
      await filmApi.applyBuild(film.id, plan, hasScenes)
      await refresh()
      onApplied()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [film, plan, refresh, onApplied])

  const updateScene = (index: number, patch: Partial<FilmBuildScene>) =>
    setPlan(p => (p ? { ...p, scenes: p.scenes.map((s, i) => (i === index ? { ...s, ...patch } : s)) } : p))
  const updateShot = (sceneIndex: number, shotIndex: number, patch: Partial<FilmBuildShot>) =>
    setPlan(p =>
      p
        ? {
            ...p,
            scenes: p.scenes.map((s, i) =>
              i === sceneIndex ? { ...s, shots: s.shots.map((sh, j) => (j === shotIndex ? { ...sh, ...patch } : sh)) } : s,
            ),
          }
        : p,
    )
  const removeShot = (sceneIndex: number, shotIndex: number) =>
    setPlan(p =>
      p
        ? { ...p, scenes: p.scenes.map((s, i) => (i === sceneIndex ? { ...s, shots: s.shots.filter((_, j) => j !== shotIndex) } : s)) }
        : p,
    )
  const removeScene = (sceneIndex: number) =>
    setPlan(p => (p ? { ...p, scenes: p.scenes.filter((_, i) => i !== sceneIndex) } : p))

  const totalShots = plan?.scenes.reduce((n, s) => n + s.shots.length, 0) ?? 0

  return (
    <div className="fixed inset-0 z-[52] flex items-center justify-center" role="dialog" aria-modal="true" aria-labelledby="build-film-title">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-3xl mx-4 max-h-[88vh] flex flex-col">
        <div className="flex items-center gap-2 px-5 py-3 border-b border-zinc-800">
          <Sparkles className="h-4 w-4 text-violet-400" />
          <h2 id="build-film-title" className="text-sm font-semibold text-white">
            Build Film with AI
          </h2>
          <span className="text-[11px] text-zinc-500">idea → editable plan → storyboard</span>
          <span className="flex-1" />
          <button onClick={onClose} aria-label="Close build film dialog" className="p-1 rounded hover:bg-zinc-800 text-zinc-400">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Idea */}
          <div className="space-y-2">
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide">What is the film about?</span>
              <textarea
                value={idea}
                onChange={e => setIdea(e.target.value)}
                onKeyDown={e => e.stopPropagation()}
                placeholder="A courier races across a flooded city to deliver a package before dawn. When she finally opens it, it's empty — and she laughs."
                className={`${inputClass} mt-1 h-20 resize-none`}
              />
            </label>
            <div className="grid grid-cols-[1fr_6rem_6rem] gap-2">
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Visual style (optional)</span>
                <input
                  value={style}
                  onChange={e => setStyle(e.target.value)}
                  onKeyDown={e => e.stopPropagation()}
                  placeholder="neo-noir, 35mm, teal and amber"
                  className={`${inputClass} mt-1`}
                />
              </label>
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Scenes</span>
                <input type="number" min={1} max={12} value={targetScenes} onChange={e => setTargetScenes(Number(e.target.value) || 1)} className={`${inputClass} mt-1`} />
              </label>
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Shots / scene</span>
                <input type="number" min={1} max={8} value={targetShots} onChange={e => setTargetShots(Number(e.target.value) || 1)} className={`${inputClass} mt-1`} />
              </label>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={() => void build(true)}
                disabled={busy !== null || !idea.trim() || !hasDirectorProvider}
                className="gap-1.5"
                title={hasDirectorProvider ? 'Plan with the configured AI Director model' : 'Add an OpenRouter or Gemini key in Settings → API Keys'}
              >
                {busy === 'plan' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                Plan with AI
              </Button>
              <Button size="sm" variant="secondary" onClick={() => void build(false)} disabled={busy !== null || !idea.trim()} className="gap-1.5" title="Deterministic coverage — no API key needed">
                <Wand2 className="h-3.5 w-3.5" /> Plan offline
              </Button>
              {!hasDirectorProvider && (
                <span className="text-[11px] text-amber-400">No AI key configured — offline planning still works.</span>
              )}
              {error && <span className="text-[11px] text-red-400 truncate">{error}</span>}
            </div>
          </div>

          {/* Plan editor */}
          {plan && (
            <div className="space-y-3 border-t border-zinc-800 pt-3">
              <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                <span>
                  {plan.scenes.length} scenes · {totalShots} shots · {plan.characters.length} characters · {plan.locations.length} locations
                </span>
                <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">{usedLlm ? `AI · ${context?.model ?? ''}` : 'offline planner'}</span>
                {context && (
                  <span className="text-zinc-600" title={context.scope}>
                    {context.prompt_tokens != null ? `${context.prompt_tokens} in / ${context.completion_tokens} out tokens` : `${context.prompt_chars} chars sent`}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Title</span>
                  <input value={plan.title} onChange={e => setPlan({ ...plan, title: e.target.value })} className={`${inputClass} mt-1`} />
                </label>
                <label className="block">
                  <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Logline</span>
                  <input value={plan.logline} onChange={e => setPlan({ ...plan, logline: e.target.value })} className={`${inputClass} mt-1`} />
                </label>
              </div>

              {(plan.characters.length > 0 || plan.locations.length > 0) && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Characters</div>
                    {plan.characters.map((c, i) => (
                      <div key={i} className="grid grid-cols-[6rem_1fr] gap-1">
                        <input value={c.name} onChange={e => setPlan({ ...plan, characters: plan.characters.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} className={inputClass} aria-label="Character name" />
                        <input value={c.wardrobe} placeholder="wardrobe" onChange={e => setPlan({ ...plan, characters: plan.characters.map((x, j) => (j === i ? { ...x, wardrobe: e.target.value } : x)) })} className={inputClass} aria-label="Character wardrobe" />
                      </div>
                    ))}
                  </div>
                  <div className="space-y-1">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Locations</div>
                    {plan.locations.map((l, i) => (
                      <div key={i} className="grid grid-cols-[6rem_1fr] gap-1">
                        <input value={l.name} onChange={e => setPlan({ ...plan, locations: plan.locations.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} className={inputClass} aria-label="Location name" />
                        <input value={l.environment} placeholder="environment" onChange={e => setPlan({ ...plan, locations: plan.locations.map((x, j) => (j === i ? { ...x, environment: e.target.value } : x)) })} className={inputClass} aria-label="Location environment" />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {plan.scenes.map((scene, sceneIndex) => {
                  const open = openScenes[sceneIndex] ?? false
                  return (
                    <div key={sceneIndex} className="rounded-lg border border-zinc-800">
                      <div className="flex items-center gap-2 px-2 py-1.5">
                        <button onClick={() => setOpenScenes(o => ({ ...o, [sceneIndex]: !open }))} className="text-zinc-500 hover:text-white" aria-label={open ? 'Collapse scene' : 'Expand scene'}>
                          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        </button>
                        <span className="text-[10px] text-zinc-600">{String(sceneIndex + 1).padStart(2, '0')}</span>
                        <input value={scene.title} onChange={e => updateScene(sceneIndex, { title: e.target.value })} className={`${inputClass} flex-1 py-1`} aria-label="Scene title" />
                        <input value={scene.location} placeholder="location" onChange={e => updateScene(sceneIndex, { location: e.target.value })} className={`${inputClass} w-32 py-1`} aria-label="Scene location" />
                        <span className="text-[10px] text-zinc-600">{scene.shots.length} shots</span>
                        <button onClick={() => removeScene(sceneIndex)} className="text-zinc-600 hover:text-red-400 text-[10px]">
                          remove
                        </button>
                      </div>
                      {open && (
                        <div className="px-2 pb-2 space-y-1.5">
                          <textarea value={scene.description} onChange={e => updateScene(sceneIndex, { description: e.target.value })} className={`${inputClass} h-12 resize-none`} aria-label="Scene description" />
                          {scene.shots.map((shot, shotIndex) => (
                            <div key={shotIndex} className="grid grid-cols-[1.5rem_1fr_6.5rem_6.5rem_3.5rem_auto] gap-1 items-start">
                              <span className="text-[10px] text-zinc-600 pt-1.5">{shotIndex + 1}</span>
                              <textarea value={shot.description} onChange={e => updateShot(sceneIndex, shotIndex, { description: e.target.value })} className={`${inputClass} h-12 resize-none`} aria-label="Shot description" />
                              <select value={shot.shot_size} onChange={e => updateShot(sceneIndex, shotIndex, { shot_size: e.target.value as FilmBuildShot['shot_size'] })} className={inputClass} aria-label="Shot size">
                                {SHOT_SIZES.map(s => (
                                  <option key={s.id} value={s.id}>
                                    {s.label}
                                  </option>
                                ))}
                              </select>
                              <select value={shot.camera_move} onChange={e => updateShot(sceneIndex, shotIndex, { camera_move: e.target.value as FilmBuildShot['camera_move'] })} className={inputClass} aria-label="Camera move">
                                {CAMERA_MOVES.map(m => (
                                  <option key={m.id} value={m.id}>
                                    {m.label}
                                  </option>
                                ))}
                              </select>
                              <input type="number" min={1} max={20} step={0.5} value={shot.duration_seconds} onChange={e => updateShot(sceneIndex, shotIndex, { duration_seconds: Number(e.target.value) || 1 })} className={inputClass} aria-label="Duration seconds" />
                              <button onClick={() => removeShot(sceneIndex, shotIndex)} className="text-zinc-600 hover:text-red-400 pt-1.5" aria-label="Remove shot">
                                <X className="h-3 w-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 px-5 py-3 border-t border-zinc-800">
          <span className="text-[11px] text-zinc-600">{plan ? 'Review and edit the plan, then apply it to the storyboard. Shots are created as drafts — nothing renders yet.' : 'Plans are drafts; you can edit everything before it touches the storyboard.'}</span>
          <span className="flex-1" />
          <Button size="sm" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void apply()} disabled={!plan || totalShots === 0 || busy !== null} className="gap-1.5">
            {busy === 'apply' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Apply to storyboard
          </Button>
        </div>
      </div>
    </div>
  )
}
