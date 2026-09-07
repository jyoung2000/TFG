import { useCallback, useState } from 'react'
import { Loader2, Megaphone, Send } from 'lucide-react'
import { useAppSettings } from '../../contexts/AppSettingsContext'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'

/**
 * AI Director input: a natural-language instruction is planned into structured
 * commands by the backend and executed against the same film store the UI
 * reads — results land in the storyboard immediately after the refresh.
 */
export function DirectorBar({
  selectedSceneId,
  selectedShotId,
}: {
  selectedSceneId: string | null
  selectedShotId: string | null
}) {
  const { film, refresh } = useFilm()
  const { settings } = useAppSettings()
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')

  const run = useCallback(async () => {
    if (!film || !instruction.trim() || busy) return
    setBusy(true)
    setFeedback('')
    try {
      const result = await filmApi.directorInstruct(
        film.id,
        instruction.trim(),
        selectedSceneId ?? undefined,
        selectedShotId ?? undefined,
      )
      const failed = result.results.filter(r => !r.ok)
      setFeedback(
        failed.length === 0
          ? `✓ ${result.plan_summary || 'Done'} (${result.results.length} steps)`
          : `Stopped at "${failed[0].name}": ${failed[0].error}`,
      )
      setInstruction('')
      await refresh()
    } catch (e) {
      setFeedback(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [film, instruction, busy, selectedSceneId, selectedShotId, refresh])

  const enabled = settings.hasGeminiApiKey

  return (
    <div className="border-t border-zinc-800 bg-zinc-900/80 px-3 py-2">
      <div className="flex items-center gap-2 max-w-4xl mx-auto">
        <Megaphone className="h-4 w-4 text-violet-400 shrink-0" />
        <input
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') void run()
          }}
          placeholder={
            enabled
              ? 'Direct the film: "Create a six second medium OTS shot — Sarah foreground left, looking toward John, slow push-in"'
              : 'AI Director needs a Gemini API key (Settings → API Keys)'
          }
          disabled={!enabled || busy}
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600 disabled:opacity-50"
        />
        <button
          onClick={() => void run()}
          disabled={!enabled || busy || !instruction.trim()}
          className="p-1.5 rounded-lg bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
        </button>
      </div>
      {feedback && (
        <p className="max-w-4xl mx-auto mt-1 text-[11px] text-zinc-400 truncate">{feedback}</p>
      )}
    </div>
  )
}
