import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  Clapperboard,
  Film,
  FolderPlus,
  History,
  Image as ImageIcon,
  Info,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  Wand2,
  X,
} from 'lucide-react'
import { useAppSettings } from '../contexts/AppSettingsContext'
import { useProjects } from '../contexts/ProjectContext'
import { useGeneration } from '../hooks/use-generation'
import { copyToAssetFolder } from '../lib/asset-copy'
import { filmApi } from '../lib/film-api'
import { importClipAsShot } from '../lib/film-conversion'
import { fileUrlToPath } from '../lib/url-to-path'
import { logger } from '../lib/logger'
import {
  FORCED_API_VIDEO_RESOLUTIONS,
  getAllowedForcedApiDurations,
  sanitizeForcedApiVideoSettings,
} from '../lib/api-video-options'
import { ErrorNotice } from '../components/ErrorNotice'
import { LtxLogo } from '../components/LtxLogo'
import { Button } from '../components/ui/button'
import { requestSettings } from '../lib/error-messages'
import type { GenerationSettings } from '../components/SettingsPanel'
import type { DirectorChatMessage, DirectorContextDetails } from '../types/film'

const LOCAL_RESOLUTIONS = ['540p', '720p', '1080p'] as const
const LOCAL_MAX_DURATION: Record<string, number> = { '540p': 20, '720p': 10, '1080p': 5 }
const HISTORY_KEY = 'ltx-quick-history'
const HISTORY_LIMIT = 24

interface QuickSettings {
  model: 'fast' | 'pro'
  duration: number
  videoResolution: string
  fps: number
  aspectRatio: '16:9' | '9:16'
  audio: boolean
}

interface QuickResult {
  id: string
  prompt: string
  negativePrompt: string
  settings: QuickSettings
  seed: number | null
  videoPath: string
  videoUrl: string
  createdAt: number
  /** file:// URL of the reference image when this was an image-to-video run. */
  referenceImage?: string | null
}

interface ChatTurn extends DirectorChatMessage {
  suggestedPrompt?: string
  suggestedNegative?: string
  suggestedDuration?: number | null
  context?: DirectorContextDetails
  error?: boolean
}

const DEFAULT_QUICK_SETTINGS: QuickSettings = {
  model: 'fast',
  duration: 5,
  videoResolution: '540p',
  fps: 24,
  aspectRatio: '16:9',
  audio: false,
}

function loadHistory(): QuickResult[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as QuickResult[]).filter(r => r && typeof r.videoPath === 'string') : []
  } catch {
    return []
  }
}

function saveHistory(items: QuickResult[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, HISTORY_LIMIT)))
  } catch (e) {
    logger.warn(`Could not persist quick history: ${e}`)
  }
}

function toGenerationSettings(quick: QuickSettings): GenerationSettings {
  return {
    model: quick.model,
    duration: quick.duration,
    videoResolution: quick.videoResolution,
    fps: quick.fps,
    audio: quick.audio,
    cameraMotion: 'none',
    aspectRatio: quick.aspectRatio,
    imageResolution: '1080p',
    imageAspectRatio: quick.aspectRatio,
    imageSteps: 8,
    variations: 1,
  }
}

function projectNameFromPrompt(prompt: string): string {
  const words = prompt.trim().split(/\s+/).slice(0, 6).join(' ')
  return (words.length > 40 ? `${words.slice(0, 40)}…` : words) || 'Quick video'
}

/**
 * Quick Mode: idea → (optional AI chat) → prompt → generate → result actions.
 * Uses the same generation hook and backend route as Gen Space, so the
 * execution path (WanGP / API / local) and settings semantics are identical.
 * "Edit in Film Maker" converts the result into a film project with the clip
 * as Scene 1 / Shot 1 / version 1.
 */
export function QuickMode() {
  const { goHome, createProject, addAsset, updateAsset, openProject, projects } = useProjects()
  const { shouldVideoGenerateWithLtxApi, hasDirectorProvider } = useAppSettings()
  const generation = useGeneration()

  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [settings, setSettings] = useState<QuickSettings>(DEFAULT_QUICK_SETTINGS)
  const [chat, setChat] = useState<ChatTurn[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatBusy, setChatBusy] = useState(false)
  const [showContext, setShowContext] = useState<number | null>(null)
  const [history, setHistory] = useState<QuickResult[]>(() => loadHistory())
  const [result, setResult] = useState<QuickResult | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [actionNote, setActionNote] = useState('')
  const [saveTargetId, setSaveTargetId] = useState<string>('new')
  const [referenceImage, setReferenceImage] = useState<string | null>(null)
  const [refDragOver, setRefDragOver] = useState(false)
  const refInputRef = useRef<HTMLInputElement>(null)
  const submittedRef = useRef<{ prompt: string; negativePrompt: string; settings: QuickSettings; referenceImage: string | null } | null>(null)
  const lastVideoRef = useRef<string | null>(null)

  /** Accept an image File (Electron exposes its path) as the I2V reference. */
  const acceptReferenceFile = useCallback((file: File | undefined) => {
    if (!file || !file.type.startsWith('image/')) return
    const filePath = (file as File & { path?: string }).path
    if (filePath) {
      const normalized = filePath.replace(/\\/g, '/')
      setReferenceImage(normalized.startsWith('/') ? `file://${normalized}` : `file:///${normalized}`)
    } else {
      setActionNote('Pick the image with the file dialog so its path can be used as the reference.')
    }
  }, [])

  const forcedApi = shouldVideoGenerateWithLtxApi

  const effectiveSettings = useMemo(() => {
    if (forcedApi) {
      return sanitizeForcedApiVideoSettings(settings)
    }
    const maxDuration = LOCAL_MAX_DURATION[settings.videoResolution] ?? 20
    return { ...settings, duration: Math.min(settings.duration, maxDuration) }
  }, [settings, forcedApi])

  const durationOptions = useMemo<number[]>(() => {
    if (forcedApi) {
      return [...getAllowedForcedApiDurations(effectiveSettings.model, effectiveSettings.videoResolution, effectiveSettings.fps)]
    }
    const max = LOCAL_MAX_DURATION[effectiveSettings.videoResolution] ?? 20
    const options: number[] = []
    for (let d = 2; d <= max; d += 1) options.push(d)
    return options
  }, [forcedApi, effectiveSettings.model, effectiveSettings.videoResolution, effectiveSettings.fps])

  const resolutionOptions: readonly string[] = forcedApi ? FORCED_API_VIDEO_RESOLUTIONS : LOCAL_RESOLUTIONS

  // Capture a finished generation as a result + history entry (once per video).
  useEffect(() => {
    if (generation.isGenerating || !generation.videoUrl || !generation.videoPath) return
    if (lastVideoRef.current === generation.videoPath) return
    lastVideoRef.current = generation.videoPath
    const submitted = submittedRef.current
    const entry: QuickResult = {
      id: `quick-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      prompt: submitted?.prompt ?? prompt,
      negativePrompt: submitted?.negativePrompt ?? negativePrompt,
      settings: submitted?.settings ?? effectiveSettings,
      seed: generation.videoSeed,
      videoPath: generation.videoPath,
      videoUrl: generation.videoUrl,
      createdAt: Date.now(),
      referenceImage: submitted?.referenceImage ?? null,
    }
    setResult(entry)
    setHistory(prev => {
      const next = [entry, ...prev].slice(0, HISTORY_LIMIT)
      saveHistory(next)
      return next
    })
    setActionNote('')
  }, [generation.isGenerating, generation.videoUrl, generation.videoPath, generation.videoSeed, prompt, negativePrompt, effectiveSettings])

  const runGeneration = useCallback(
    async (overridePrompt?: string, overrideSettings?: QuickSettings, overrideNegative?: string, overrideReference?: string | null) => {
      const usePrompt = (overridePrompt ?? prompt).trim()
      if (!usePrompt || generation.isGenerating) return
      const useSettings = overrideSettings ?? effectiveSettings
      const useNegative = overrideNegative ?? negativePrompt
      const useReference = overrideReference === undefined ? referenceImage : overrideReference
      submittedRef.current = { prompt: usePrompt, negativePrompt: useNegative, settings: useSettings, referenceImage: useReference }
      setResult(null)
      await generation.generate(usePrompt, useReference ? fileUrlToPath(useReference) : null, toGenerationSettings(useSettings))
    },
    [prompt, negativePrompt, effectiveSettings, generation, referenceImage],
  )

  const sendChat = useCallback(async () => {
    const text = chatInput.trim()
    if (!text || chatBusy) return
    setChatBusy(true)
    setChatInput('')
    const nextTurns: ChatTurn[] = [...chat, { role: 'user', content: text }]
    setChat(nextTurns)
    try {
      const response = await filmApi.directorChat(
        nextTurns.filter(t => !t.error).map(t => ({ role: t.role, content: t.content })),
        { role: 'prompt_refinement', model_hint: `LTX ${effectiveSettings.model}`, duration_seconds: effectiveSettings.duration },
      )
      setChat(prev => [
        ...prev,
        {
          role: 'assistant',
          content: response.reply,
          suggestedPrompt: response.suggested_prompt,
          suggestedNegative: response.suggested_negative_prompt,
          suggestedDuration: response.suggested_duration_seconds,
          context: response.context,
        },
      ])
    } catch (e) {
      setChat(prev => [...prev, { role: 'assistant', content: e instanceof Error ? e.message : String(e), error: true }])
    } finally {
      setChatBusy(false)
    }
  }, [chatInput, chatBusy, chat, effectiveSettings.model, effectiveSettings.duration])

  const applySuggestion = useCallback(
    (turn: ChatTurn) => {
      if (turn.suggestedPrompt) setPrompt(turn.suggestedPrompt)
      if (turn.suggestedNegative) setNegativePrompt(turn.suggestedNegative)
      if (turn.suggestedDuration && durationOptions.length > 0) {
        const nearest = durationOptions.reduce((best, d) =>
          Math.abs(d - turn.suggestedDuration!) < Math.abs(best - turn.suggestedDuration!) ? d : best,
        )
        setSettings(s => ({ ...s, duration: nearest }))
      }
    },
    [durationOptions],
  )

  const persistToProject = useCallback(
    async (target: QuickResult, projectId: string) => {
      const copied = await copyToAssetFolder(target.videoPath, projectId)
      const path = copied?.path ?? target.videoPath
      const url = copied?.url ?? target.videoUrl
      const asset = addAsset(projectId, {
        type: 'video',
        path,
        url,
        prompt: target.prompt,
        resolution: target.settings.videoResolution,
        duration: target.settings.duration,
        generationParams: {
          mode: target.referenceImage ? 'image-to-video' : 'text-to-video',
          prompt: target.prompt,
          model: target.settings.model,
          duration: target.settings.duration,
          resolution: target.settings.videoResolution,
          fps: target.settings.fps,
          audio: target.settings.audio,
          cameraMotion: 'none',
          imageAspectRatio: target.settings.aspectRatio,
          inputImageUrl: target.referenceImage ?? undefined,
        },
        takes: [{ url, path, createdAt: Date.now() }],
        activeTakeIndex: 0,
      })
      return { asset, path }
    },
    [addAsset],
  )

  const editInFilmMaker = useCallback(
    async (target: QuickResult) => {
      setActionBusy('film')
      setActionNote('')
      try {
        const name = projectNameFromPrompt(target.prompt)
        const project = createProject(name)
        const { path, asset } = await persistToProject(target, project.id)
        const result = await importClipAsShot(project.id, {
          outputPath: path,
          prompt: target.prompt,
          negativePrompt: target.negativePrompt,
          model: target.settings.model,
          resolution: target.settings.videoResolution,
          durationSeconds: target.settings.duration,
          fps: target.settings.fps,
          seed: target.seed,
          aspectRatio: target.settings.aspectRatio,
          mode: target.referenceImage ? 'image-to-video' : 'text-to-video',
          inputImagePath: target.referenceImage ? (fileUrlToPath(target.referenceImage) ?? undefined) : undefined,
          title: 'Shot 1',
          projectName: name,
        })
        updateAsset(project.id, asset.id, {
          filmRef: { projectId: project.id, sceneId: result.sceneId, shotId: result.shotId, versionNumber: result.versionNumber },
        })
        openProject(project.id, 'storyboard')
      } catch (e) {
        logger.error(`Edit in Film Maker failed: ${e}`)
        setActionNote(`Could not open in Film Maker: ${e instanceof Error ? e.message : e}`)
      } finally {
        setActionBusy(null)
      }
    },
    [createProject, persistToProject, openProject, updateAsset],
  )

  const saveToProject = useCallback(
    async (target: QuickResult, openTab: 'gen-space' | 'video-editor') => {
      setActionBusy(openTab)
      setActionNote('')
      try {
        const projectId = saveTargetId === 'new' ? createProject(projectNameFromPrompt(target.prompt)).id : saveTargetId
        await persistToProject(target, projectId)
        openProject(projectId, openTab)
      } catch (e) {
        setActionNote(`Could not save: ${e instanceof Error ? e.message : e}`)
      } finally {
        setActionBusy(null)
      }
    },
    [saveTargetId, createProject, persistToProject, openProject],
  )

  const remake = useCallback(
    (entry: QuickResult) => {
      setPrompt(entry.prompt)
      setNegativePrompt(entry.negativePrompt)
      setSettings(entry.settings)
      setReferenceImage(entry.referenceImage ?? null)
      setResult(entry)
      lastVideoRef.current = entry.videoPath
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
    [],
  )

  const selectClass =
    'bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-violet-600'

  return (
    <div className="h-screen bg-background flex flex-col">
      <header className="flex items-center gap-3 px-4 py-3 border-b border-zinc-800">
        <button onClick={goHome} aria-label="Back to home" className="p-2 rounded-lg hover:bg-zinc-800 transition-colors">
          <ArrowLeft className="h-5 w-5 text-zinc-400" />
        </button>
        <LtxLogo className="h-5 w-auto text-white" />
        <span className="text-white font-medium">Quick video</span>
        <span className="text-xs text-zinc-500">describe it, generate it, then keep going in the Film Maker</span>
      </header>

      <main className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] overflow-hidden">
        {/* Left: idea → prompt */}
        <section className="min-h-0 overflow-y-auto border-r border-zinc-800 p-5 space-y-5">
          {/* Idea chat */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800">
              <MessageSquare className="h-3.5 w-3.5 text-violet-400" />
              <span className="text-xs font-semibold text-white">Talk through the idea</span>
              {hasDirectorProvider ? (
                <span className="text-[10px] text-zinc-600">the assistant drafts a prompt you can use</span>
              ) : (
                <button onClick={() => requestSettings('apiKeys')} className="text-[10px] text-zinc-500 hover:text-white underline underline-offset-2">
                  optional — connect an AI provider (or a local server) to enable
                </button>
              )}
            </div>
            {chat.length > 0 && (
              <div className="max-h-56 overflow-y-auto px-3 py-2 space-y-2" role="log" aria-live="polite">
                {chat.map((turn, index) => (
                  <div key={index} className="text-xs">
                    {turn.error ? (
                      <ErrorNotice error={turn.content} compact />
                    ) : (
                      <div className={turn.role === 'user' ? 'text-zinc-300' : 'text-violet-200'}>
                        <span className="text-zinc-600 mr-1">{turn.role === 'user' ? 'You' : 'Assistant'}</span>
                        {turn.content}
                      </div>
                    )}
                    {turn.suggestedPrompt && (
                      <div className="mt-1 rounded border border-zinc-800 bg-zinc-950/60 p-2">
                        <div className="text-[11px] text-zinc-300 leading-snug">{turn.suggestedPrompt}</div>
                        <div className="flex items-center gap-2 mt-1.5">
                          <button onClick={() => applySuggestion(turn)} className="text-[10px] px-2 py-0.5 rounded bg-violet-700 hover:bg-violet-600 text-white">
                            Use this prompt
                          </button>
                          {turn.context && (
                            <button onClick={() => setShowContext(showContext === index ? null : index)} className="inline-flex items-center gap-0.5 text-[10px] text-zinc-500 hover:text-zinc-300 underline underline-offset-2">
                              <Info className="h-2.5 w-2.5" /> context details
                            </button>
                          )}
                        </div>
                        {turn.context && showContext === index && (
                          <div className="mt-1 text-[10px] text-zinc-500 font-mono">
                            {turn.context.provider} · {turn.context.model} · {turn.context.prompt_chars} chars
                            {turn.context.prompt_tokens != null ? ` · ${turn.context.prompt_tokens}/${turn.context.completion_tokens} tokens` : ''} · {turn.context.scope}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2 px-3 py-2">
              <input
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') void sendChat()
                }}
                disabled={!hasDirectorProvider || chatBusy}
                aria-label="Describe your idea"
                placeholder={hasDirectorProvider ? 'e.g. something moody at sea, one person, dawn' : 'Assistant unavailable without an AI key'}
                className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600 disabled:opacity-50"
              />
              <button
                onClick={() => void sendChat()}
                disabled={!hasDirectorProvider || chatBusy || !chatInput.trim()}
                aria-label="Send idea"
                className="p-1.5 rounded-lg bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white"
              >
                {chatBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>

          {/* Prompt + settings */}
          <div className="space-y-3">
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Prompt</span>
              <textarea
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                placeholder="A lone fisherman rows through thick fog at dawn, lantern light glinting on calm water, slow push-in, cinematic."
                aria-label="Video prompt"
                className="mt-1 w-full h-28 bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-sm text-zinc-200 placeholder:text-zinc-600 resize-none focus:outline-none focus:border-violet-700"
              />
            </label>
            <label className="block">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Avoid (negative prompt, optional)</span>
              <input
                value={negativePrompt}
                onChange={e => setNegativePrompt(e.target.value)}
                aria-label="Negative prompt"
                placeholder="blurry, text, watermark"
                className="mt-1 w-full bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-700"
              />
            </label>
            <div className="grid grid-cols-4 gap-2">
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Model</span>
                <select value={effectiveSettings.model} onChange={e => setSettings(s => ({ ...s, model: e.target.value as 'fast' | 'pro' }))} className={`${selectClass} mt-1 w-full`} aria-label="Model">
                  <option value="fast">Fast</option>
                  <option value="pro">Pro</option>
                </select>
              </label>
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Resolution</span>
                <select value={effectiveSettings.videoResolution} onChange={e => setSettings(s => ({ ...s, videoResolution: e.target.value }))} className={`${selectClass} mt-1 w-full`} aria-label="Resolution">
                  {resolutionOptions.map(r => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Seconds</span>
                <select value={effectiveSettings.duration} onChange={e => setSettings(s => ({ ...s, duration: Number(e.target.value) }))} className={`${selectClass} mt-1 w-full`} aria-label="Duration">
                  {durationOptions.map(d => (
                    <option key={d} value={d}>
                      {d}s
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wide">Aspect</span>
                <select value={effectiveSettings.aspectRatio} onChange={e => setSettings(s => ({ ...s, aspectRatio: e.target.value as '16:9' | '9:16' }))} className={`${selectClass} mt-1 w-full`} aria-label="Aspect ratio">
                  <option value="16:9">16:9</option>
                  <option value="9:16">9:16</option>
                </select>
              </label>
            </div>
            {/* Optional reference image → image-to-video */}
            <div className="flex items-center gap-3">
              <div
                role="button"
                tabIndex={0}
                aria-label={referenceImage ? 'Reference image (click to replace)' : 'Add a reference image for image-to-video'}
                onClick={() => refInputRef.current?.click()}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') refInputRef.current?.click()
                }}
                onDragOver={e => {
                  e.preventDefault()
                  setRefDragOver(true)
                }}
                onDragLeave={() => setRefDragOver(false)}
                onDrop={e => {
                  e.preventDefault()
                  setRefDragOver(false)
                  acceptReferenceFile(e.dataTransfer.files?.[0])
                }}
                className={`relative w-16 h-10 rounded-lg border-2 border-dashed flex items-center justify-center cursor-pointer overflow-hidden ${
                  refDragOver ? 'border-violet-500 bg-violet-500/10' : 'border-zinc-700 hover:border-zinc-500'
                }`}
              >
                {referenceImage ? (
                  <>
                    <img src={referenceImage} alt="" className="w-full h-full object-cover" />
                    <button
                      onClick={e => {
                        e.stopPropagation()
                        setReferenceImage(null)
                      }}
                      aria-label="Remove reference image"
                      className="absolute -top-0.5 -right-0.5 p-0.5 rounded-full bg-zinc-900 text-zinc-300 hover:text-white"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </>
                ) : (
                  <ImageIcon className="h-4 w-4 text-zinc-500" />
                )}
                <input
                  ref={refInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={e => {
                    acceptReferenceFile(e.target.files?.[0])
                    e.target.value = ''
                  }}
                />
              </div>
              <div className="text-[11px] text-zinc-500">
                {referenceImage ? (
                  <>
                    <span className="text-violet-300">Image to video</span> — the clip starts from this frame.
                  </>
                ) : (
                  'Optional: drop a reference image to animate it (image-to-video).'
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={() => void runGeneration()} disabled={!prompt.trim() || generation.isGenerating} className="gap-1.5">
                {generation.isGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                Generate
              </Button>
              {generation.isGenerating && (
                <Button variant="secondary" onClick={() => void generation.cancel()} className="gap-1.5">
                  <Square className="h-3 w-3" /> Cancel
                </Button>
              )}
              <span className="text-[11px] text-zinc-600">
                {forcedApi ? 'LTX cloud API' : 'local generation'} · {effectiveSettings.model} · {effectiveSettings.videoResolution} · {effectiveSettings.duration}s
                {referenceImage ? ' · image-to-video' : ''}
              </span>
            </div>
            {generation.error && <ErrorNotice error={generation.error} onRetry={() => void runGeneration()} />}
          </div>

          {/* History */}
          {history.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[10px] text-zinc-500 uppercase tracking-wide">
                <History className="h-3 w-3" /> Recent quick videos
                <button
                  onClick={() => {
                    setHistory([])
                    saveHistory([])
                  }}
                  className="ml-auto text-zinc-600 hover:text-red-400 normal-case tracking-normal"
                >
                  clear
                </button>
              </div>
              <div className="space-y-1">
                {history.map(entry => (
                  <button
                    key={entry.id}
                    onClick={() => remake(entry)}
                    className={`w-full text-left rounded-lg border px-3 py-2 hover:border-violet-700 ${result?.id === entry.id ? 'border-violet-700 bg-violet-950/20' : 'border-zinc-800 bg-zinc-900/40'}`}
                  >
                    <div className="text-xs text-zinc-200 truncate">{entry.prompt}</div>
                    <div className="text-[10px] text-zinc-600">
                      {entry.settings.model} · {entry.settings.videoResolution} · {entry.settings.duration}s{entry.seed != null ? ` · seed ${entry.seed}` : ''} · {new Date(entry.createdAt).toLocaleString()}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Right: progress / result */}
        <section className="min-h-0 overflow-y-auto p-5">
          {generation.isGenerating ? (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <Loader2 className="h-8 w-8 text-violet-500 animate-spin mb-3" />
              <div className="text-sm text-white">{generation.statusMessage || 'Generating…'}</div>
              <div className="w-64 h-1.5 bg-zinc-800 rounded-full mt-3 overflow-hidden" role="progressbar" aria-valuenow={generation.progress} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full bg-violet-500 transition-all" style={{ width: `${generation.progress}%` }} />
              </div>
              <div className="text-[11px] text-zinc-500 mt-2">{generation.progress}%</div>
            </div>
          ) : result ? (
            <div className="space-y-4 max-w-2xl mx-auto">
              <video src={result.videoUrl} controls autoPlay loop playsInline className="w-full rounded-xl bg-black aspect-video" />
              <div className="text-xs text-zinc-300 leading-relaxed">{result.prompt}</div>
              <div className="text-[11px] text-zinc-500 font-mono">
                {result.settings.model} · {result.settings.videoResolution} · {result.settings.duration}s · {result.settings.fps} fps · {result.settings.aspectRatio}
                {result.seed != null ? ` · seed ${result.seed}` : ' · seed chosen by API'}
                {result.referenceImage ? ' · image-to-video' : ''}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Button onClick={() => void editInFilmMaker(result)} disabled={actionBusy !== null} className="gap-1.5 bg-violet-700 hover:bg-violet-600" title="Create a film project with this clip as Scene 1 / Shot 1 (prompt, model, seed and output preserved)">
                  {actionBusy === 'film' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clapperboard className="h-3.5 w-3.5" />}
                  Edit in Film Maker
                </Button>
                <Button variant="secondary" onClick={() => void runGeneration(result.prompt, result.settings, result.negativePrompt, result.referenceImage ?? null)} disabled={actionBusy !== null} className="gap-1.5" title="Same prompt, settings and reference image; a new seed unless seed lock is on">
                  <RefreshCw className="h-3.5 w-3.5" /> Generate again
                </Button>
                <Button variant="secondary" onClick={() => void saveToProject(result, 'gen-space')} disabled={actionBusy !== null} className="gap-1.5">
                  {actionBusy === 'gen-space' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderPlus className="h-3.5 w-3.5" />}
                  Save to project
                </Button>
                <Button variant="secondary" onClick={() => void saveToProject(result, 'video-editor')} disabled={actionBusy !== null} className="gap-1.5">
                  {actionBusy === 'video-editor' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                  Open in Video Editor
                </Button>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                <span>Save into:</span>
                <select value={saveTargetId} onChange={e => setSaveTargetId(e.target.value)} className={selectClass} aria-label="Target project">
                  <option value="new">New project</option>
                  {projects.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <button onClick={() => setPrompt(result.prompt)} className="ml-auto inline-flex items-center gap-1 text-zinc-400 hover:text-white">
                  <Wand2 className="h-3 w-3" /> Edit prompt
                </button>
              </div>
              {actionNote && <div className="text-xs text-red-300">{actionNote}</div>}
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-center">
              <div className="max-w-sm">
                <Sparkles className="h-10 w-10 text-zinc-800 mx-auto mb-3" />
                <h3 className="text-sm font-semibold text-zinc-300">Your video will appear here</h3>
                <p className="text-xs text-zinc-600 mt-1">
                  Write a prompt (or ask the assistant to draft one), pick a length, and press Generate. Afterwards you can
                  regenerate, save it into a project, or continue in the Film Maker where it becomes Scene 1 / Shot 1.
                </p>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
