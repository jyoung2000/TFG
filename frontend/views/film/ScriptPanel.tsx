import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FileText, ImageIcon, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { filmApi } from '../../lib/film-api'
import { Button } from '../../components/ui/button'
import type { FilmProject, FilmShot } from '../../types/film'
import { useShotThumb } from './ShotCard'
import { matchBeats } from './scriptBeats'

/** The picture of a shot next to its script line: render, capture, frame or blockout. */
function BeatThumb({ film, shot, onDraw, drawing }: { film: FilmProject; shot: FilmShot; onDraw: () => void; drawing: boolean }) {
  const { thumb, onThumbError } = useShotThumb(film, shot)
  return (
    <div className="relative w-44 shrink-0 aspect-video rounded-md overflow-hidden bg-zinc-900 border border-zinc-800" data-testid="beat-thumb">
      {thumb?.kind === 'video' ? (
        <video src={thumb.url} muted preload="metadata" onError={onThumbError} className="w-full h-full object-cover" />
      ) : thumb ? (
        <img src={thumb.url} alt={shot.title} className={`w-full h-full ${thumb.kind === 'blockout' ? 'object-contain bg-zinc-950' : 'object-cover'}`} />
      ) : (
        <button onClick={onDraw} disabled={drawing} className="w-full h-full flex flex-col items-center justify-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-200 disabled:opacity-50">
          {drawing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" />} Draw frame
        </button>
      )}
      {thumb?.kind === 'blockout' && (
        <button onClick={onDraw} disabled={drawing} className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/70 text-[9px] text-zinc-200 hover:bg-black">
          {drawing ? '…' : 'Draw frame'}
        </button>
      )}
    </div>
  )
}

const EXAMPLE = `INT. COFFEE SHOP - DAY

Sunlight cuts across empty tables. SARAH sits alone, staring at an unopened letter.

SARAH
I can't keep pretending this never happened.

She tears the envelope open.

EXT. CITY STREET - NIGHT

JOHN walks fast through the rain, phone pressed to his ear.`

export function ScriptPanel({ onStoryboardCreated }: { onStoryboardCreated: () => void }) {
  const { film, refresh, setFilm } = useFilm()
  const { hasDirectorProvider } = useAppSettings()
  const [content, setContent] = useState('')
  const [savedContent, setSavedContent] = useState('')
  const [busy, setBusy] = useState<'save' | 'generate' | null>(null)
  const [note, setNote] = useState('')
  const loadedProjectRef = useRef<string | null>(null)
  // Lines + frames: every script beat next to the picture of the shot it became.
  const [view, setView] = useState<'write' | 'frames'>('write')
  const [drawing, setDrawing] = useState<string | null>(null)
  const shots = useMemo(
    () => (film ? [...film.scenes].sort((a, b) => a.order - b.order).flatMap(sc => [...sc.shots].sort((a, b) => a.order - b.order).map(shot => ({ scene: sc, shot }))) : []),
    [film],
  )
  const beats = useMemo(
    () => matchBeats(content, shots.map(({ shot }) => ({ id: shot.id, title: shot.title, description: shot.description, action: shot.action, dialogue: shot.dialogue }))),
    [content, shots],
  )

  const drawFrame = useCallback(async (sceneId: string, shotId: string) => {
    if (!film) return
    setDrawing(shotId)
    try {
      await filmApi.shotFrame(film.id, sceneId, shotId)
      await refresh()
    } catch (e) {
      setNote(`Frame failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setDrawing(null)
    }
  }, [film, refresh])

  const drawMissingFrames = useCallback(async () => {
    if (!film) return
    setDrawing('all')
    setNote('Drawing a frame for every shot without a picture…')
    try {
      const result = await filmApi.storyboardFrames(film.id, true)
      await refresh()
      setNote(`Drew ${result.generated} frame${result.generated === 1 ? '' : 's'}` + (result.failed.length ? ` · ${result.failed.length} failed` : ''))
    } catch (e) {
      setNote(`Frames failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setDrawing(null)
    }
  }, [film, refresh])

  useEffect(() => {
    if (film && loadedProjectRef.current !== film.id) {
      loadedProjectRef.current = film.id
      setContent(film.script.content)
      setSavedContent(film.script.content)
    } else if (film && film.script.content !== savedContent && content === savedContent) {
      // Changed elsewhere (the Director, an import) with no unsaved edits here:
      // show it (QA 2026-10-01: the tab kept the old text).
      setContent(film.script.content)
      setSavedContent(film.script.content)
    }
  }, [film, content, savedContent])

  const save = useCallback(async () => {
    if (!film) return
    setBusy('save')
    try {
      const updated = await filmApi.updateScript(film.id, content)
      setFilm(updated)
      setSavedContent(content)
      setNote('Script saved')
    } catch (e) {
      setNote(`Save failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [film, content, setFilm])

  const generateStoryboard = useCallback(
    async (useLlm: boolean) => {
      if (!film) return
      setBusy('generate')
      setNote('')
      try {
        if (content !== savedContent) {
          const updated = await filmApi.updateScript(film.id, content)
          setFilm(updated)
          setSavedContent(content)
        }
        const hasScenes = film.scenes.length > 0
        if (hasScenes && !window.confirm('Replace the existing storyboard with a new draft?')) {
          setBusy(null)
          return
        }
        const result = await filmApi.generateStoryboard(film.id, {
          use_llm: useLlm,
          replace_existing: hasScenes,
        })
        await refresh()
        setNote(
          `Draft storyboard created: ${result.scenes_created} scenes, ${result.shots_created} shots` +
            (result.characters_created > 0 ? `, ${result.characters_created} characters` : '') +
            ' — review it before generating.',
        )
        onStoryboardCreated()
      } catch (e) {
        setNote(`Storyboard generation failed: ${e instanceof Error ? e.message : e}`)
      } finally {
        setBusy(null)
      }
    },
    [film, content, savedContent, refresh, setFilm, onStoryboardCreated],
  )

  const dirty = content !== savedContent

  return (
    <div className="h-full flex flex-col p-4 gap-3 max-w-4xl mx-auto w-full">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 text-zinc-500" />
        <h2 className="text-sm font-semibold text-white">Script</h2>
        <span className="text-[11px] text-zinc-600">
          INT./EXT. headings split scenes · ALL-CAPS names read as dialogue
        </span>
        <span className="flex-1" />
        {note && <span className="text-[11px] text-zinc-400 max-w-md truncate">{note}</span>}
        <div className="flex rounded-lg border border-zinc-700 overflow-hidden text-[11px]" role="group" aria-label="Script view">
          <button onClick={() => setView('write')} aria-pressed={view === 'write'} className={`px-2 py-1 ${view === 'write' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}>Write</button>
          <button onClick={() => setView('frames')} aria-pressed={view === 'frames'} data-testid="script-view-frames" className={`px-2 py-1 ${view === 'frames' ? 'bg-zinc-700 text-white' : 'text-zinc-400 hover:bg-zinc-800'}`}>Lines + frames</button>
        </div>
      </div>
      {view === 'frames' && (
        <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-1" data-testid="script-frames">
          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <span>Each line of the script next to the shot it became.</span>
            <span className="flex-1" />
            <Button size="sm" variant="secondary" disabled={drawing !== null || shots.length === 0} onClick={() => void drawMissingFrames()} className="gap-1.5" data-testid="draw-missing-frames">
              {drawing === 'all' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />} Draw missing frames
            </Button>
          </div>
          {shots.length === 0 && <p className="text-[11px] text-zinc-600">Generate a storyboard from the script first — then every line gets its picture here.</p>}
          {beats.map((beat, index) => {
            const match = beat.shotId ? shots.find(s => s.shot.id === beat.shotId) : undefined
            if (beat.kind === 'heading') {
              return <h3 key={index} className="pt-2 text-[11px] font-semibold uppercase tracking-wide text-violet-300">{beat.text}</h3>
            }
            return (
              <div key={index} className="flex gap-3 items-start rounded-lg border border-zinc-800 bg-zinc-900/40 p-2" data-testid="script-beat">
                {match && film ? (
                  <BeatThumb film={film} shot={match.shot} drawing={drawing === match.shot.id || drawing === 'all'} onDraw={() => void drawFrame(match.scene.id, match.shot.id)} />
                ) : (
                  <div className="w-44 shrink-0 aspect-video rounded-md border border-dashed border-zinc-800 flex items-center justify-center text-[10px] text-zinc-600">no shot</div>
                )}
                <div className="min-w-0 space-y-0.5">
                  <p className={`text-xs leading-relaxed ${beat.kind === 'dialogue' ? 'text-amber-100 italic' : 'text-zinc-200'}`}>{beat.text}</p>
                  {match && <p className="text-[10px] text-zinc-500">{match.scene.title} · {match.shot.title}</p>}
                </div>
              </div>
            )
          })}
        </div>
      )}
      <textarea
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder={EXAMPLE}
        spellCheck={false}
        className={`flex-1 bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-sm text-zinc-200 font-mono leading-relaxed resize-none focus:outline-none focus:border-violet-700 placeholder:text-zinc-700 ${view === 'frames' ? 'hidden' : ''}`}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => void save()} disabled={busy !== null || !dirty} className="gap-1.5">
          {busy === 'save' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {dirty ? 'Save script' : 'Saved'}
        </Button>
        <span className="flex-1" />
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void generateStoryboard(false)}
          disabled={busy !== null || !content.trim()}
          className="gap-1.5"
          title="Deterministic parser — works fully offline"
        >
          {busy === 'generate' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
          Generate Storyboard
        </Button>
        <Button
          size="sm"
          onClick={() => void generateStoryboard(true)}
          disabled={busy !== null || !content.trim() || !hasDirectorProvider}
          className="gap-1.5"
          title={
            hasDirectorProvider
              ? 'The AI Director model breaks the script into cinematographed shots'
              : 'Connect an AI Director provider in Settings → API Keys to enable AI storyboarding'
          }
        >
          <Sparkles className="h-3.5 w-3.5" />
          AI Storyboard
        </Button>
      </div>
    </div>
  )
}
