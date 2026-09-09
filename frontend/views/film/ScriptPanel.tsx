import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { filmApi } from '../../lib/film-api'
import { Button } from '../../components/ui/button'

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

  useEffect(() => {
    if (film && loadedProjectRef.current !== film.id) {
      loadedProjectRef.current = film.id
      setContent(film.script.content)
      setSavedContent(film.script.content)
    }
  }, [film])

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
      </div>
      <textarea
        value={content}
        onChange={e => setContent(e.target.value)}
        placeholder={EXAMPLE}
        spellCheck={false}
        className="flex-1 bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-sm text-zinc-200 font-mono leading-relaxed resize-none focus:outline-none focus:border-violet-700 placeholder:text-zinc-700"
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
