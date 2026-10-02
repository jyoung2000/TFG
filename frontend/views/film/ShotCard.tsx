import { useEffect, useState } from 'react'
import { Aperture, Clapperboard, Clock, Copy, Play, Trash2, Users } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { aiTileLabel, referenceSource, referenceUrl, type AiSource } from './storyboardTiles'
import { filmMediaUrl, filmOutputUrl } from '../../lib/film-api'
import type { FilmProject, FilmShot } from '../../types/film'
import { CONTINUITY_LEVEL_META, SHOT_STATUS_META, framingLabel } from '../../types/film'

interface ShotCardProps {
  film: FilmProject
  shot: FilmShot
  sceneNumber: number
  shotNumber: number
  isSelected: boolean
  onOpen: () => void
  onCompose: () => void
  onDuplicate: () => void
  onDelete: () => void
  onDragStart: (event: React.DragEvent) => void
  onDragOver: (event: React.DragEvent) => void
  onDrop: (event: React.DragEvent) => void
}

/** Thumbnail preference: current version output (video) → composer capture → storyboard frame → 3D blockout. */
export function useShotThumb(film: FilmProject, shot: FilmShot) {
  const [thumb, setThumb] = useState<{ kind: 'video' | 'image' | 'blockout'; url: string; source: AiSource } | null>(null)
  const [videoFallbackUrl, setVideoFallbackUrl] = useState<string | null>(null)
  const [videoFailed, setVideoFailed] = useState(false)
  const version = shot.current_version != null ? shot.versions.find(v => v.number === shot.current_version) : undefined
  const outputPath = version?.status === 'complete' ? version.output_path : ''
  const capturePath = shot.capture_path
  const framePath = shot.frame_path ?? ''
  const blockoutPath = shot.blockout_path

  useEffect(() => {
    let cancelled = false
    void (async () => {
      if (outputPath) {
        const url = await filmOutputUrl(outputPath)
        if (!cancelled) setThumb({ kind: 'video', url, source: 'version' })
      } else if (capturePath) {
        const url = await filmMediaUrl(film.id, capturePath)
        if (!cancelled) setThumb({ kind: 'image', url, source: 'capture' })
      } else if (framePath) {
        const url = await filmMediaUrl(film.id, framePath)
        if (!cancelled) setThumb({ kind: 'image', url, source: 'frame' })
      } else if (blockoutPath) {
        // A 3D storyboard build leaves an isometric blockout until the shot is captured or rendered.
        const url = await filmMediaUrl(film.id, blockoutPath)
        if (!cancelled) setThumb({ kind: 'blockout', url, source: 'blockout' })
      } else {
        setThumb(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [film.id, outputPath, capturePath, framePath, blockoutPath])

  // When the video thumbnail errors (404, codec, interrupted download), fall
  // back to the composition capture so the card still shows the shot's
  // framing instead of an empty black box.
  useEffect(() => {
    setVideoFailed(false)
  }, [thumb])

  useEffect(() => {
    if (thumb?.kind !== 'video') return
    if (!capturePath) return
    let cancelled = false
    void filmMediaUrl(film.id, capturePath).then(url => {
      if (!cancelled) setVideoFallbackUrl(url)
    })
    return () => {
      cancelled = true
    }
  }, [film.id, thumb?.kind, capturePath])

  return {
    thumb: videoFailed && videoFallbackUrl
      ? { kind: 'image' as const, url: videoFallbackUrl, source: 'capture' as const }
      : thumb,
    onThumbError: () => setVideoFailed(true),
  }
}

/** The image this shot remakes, if any (see storyboardTiles). */
function useShotReference(film: FilmProject, shot: FilmShot): { url: string } | null {
  const source = referenceSource(shot)
  const key = source ? (source.kind === 'project' ? source.path : `${source.analysisId}/${source.shotId}`) : ''
  const [url, setUrl] = useState('')
  useEffect(() => {
    setUrl('')
    if (!source) return
    let cancelled = false
    referenceUrl(film.id, source).then(next => { if (!cancelled) setUrl(next) }).catch(() => undefined)
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [film.id, key])
  return source ? { url } : null
}

export function ShotCard({
  film,
  shot,
  sceneNumber,
  shotNumber,
  isSelected,
  onOpen,
  onCompose,
  onDuplicate,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
}: ShotCardProps) {
  const { thumb, onThumbError } = useShotThumb(film, shot)
  const reference = useShotReference(film, shot)
  const { continuityLevelFor } = useFilm()
  const level = continuityLevelFor(shot.id)
  const levelMeta = level ? CONTINUITY_LEVEL_META[level] : null
  const status = SHOT_STATUS_META[shot.status]
  const characterNames = shot.characters
    .map(c => film.assets.find(a => a.id === c.asset_id)?.name)
    .filter((n): n is string => !!n)
  const location = shot.location_id ? film.assets.find(a => a.id === shot.location_id)?.name : null

  return (
    <div
      draggable
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      aria-label={`Shot ${sceneNumber}.${shotNumber}${shot.title ? `: ${shot.title}` : ''} — ${status.label}${levelMeta && level !== 'good' ? `, ${levelMeta.label}` : ''}`}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onClick={onOpen}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen()
        } else if (event.key.toLowerCase() === 'c' && !event.metaKey && !event.ctrlKey) {
          onCompose()
        }
      }}
      className={`group w-52 shrink-0 rounded-lg border bg-zinc-900 overflow-hidden cursor-pointer transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 ${
        isSelected ? 'border-violet-500' : 'border-zinc-800 hover:border-zinc-600'
      }`}
    >
      {/* Reference above, its AI remake below (a shot made from scratch has just its picture). */}
      {reference && (
        <div className="relative aspect-video bg-zinc-950 flex items-center justify-center" data-testid="shot-reference">
          {reference.url ? <img src={reference.url} alt="Reference" className="w-full h-full object-cover" /> : <Clapperboard className="h-7 w-7 text-zinc-700" />}
          <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide bg-teal-500 text-black">Reference</span>
        </div>
      )}
      <div className={`relative aspect-video bg-zinc-950 flex items-center justify-center ${reference ? 'border-t-2 border-violet-600/70' : ''}`} data-testid={reference ? 'shot-ai-result' : undefined}>
        {reference && (
          <span className="absolute bottom-1.5 left-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide bg-violet-600 text-white">{aiTileLabel(thumb?.source ?? null, shot)}</span>
        )}
        {thumb ? (
          thumb.kind === 'video' ? (
            <video
              src={thumb.url}
              muted
              playsInline
              preload="metadata"
              onError={onThumbError}
              className="w-full h-full object-cover"
            />
          ) : (
            <img src={thumb.url} alt={thumb.kind === 'blockout' ? '3D blockout' : ''} data-testid={thumb.kind === 'blockout' ? 'shot-thumb-blockout' : undefined} className="w-full h-full object-cover" />
          )
        ) : (
          <Clapperboard className="h-7 w-7 text-zinc-700" />
        )}
        <span className="absolute top-1.5 left-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-black/70 text-zinc-300">
          {sceneNumber}.{shotNumber}
          {levelMeta && level !== 'good' && (
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${levelMeta.dot}`}
              title={levelMeta.label}
              aria-label={levelMeta.label}
            />
          )}
        </span>
        <span className={`absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${status.className}`}>
          {status.label}
        </span>
        {thumb?.kind === 'video' && (
          <Play className="absolute bottom-1.5 right-1.5 h-4 w-4 text-white/80" />
        )}
      </div>

      {/* Body */}
      <div className="p-2 space-y-1">
        <div className="flex items-center gap-1.5">
          <span className="flex-1 text-xs font-medium text-zinc-200 truncate">
            {shot.title || `Shot ${shotNumber}`}
          </span>
          <span className="flex items-center gap-0.5 text-[10px] text-zinc-500">
            <Clock className="h-3 w-3" />
            {shot.duration_seconds.toFixed(1)}s
          </span>
        </div>
        <div className="text-[10px] text-zinc-500 truncate">{framingLabel(shot.framing)}</div>
        <div className="flex items-center gap-1 text-[10px] text-zinc-600 truncate">
          <span className="truncate" title="Generation model">
            {shot.generation.model || film.settings.default_model || 'project model'}
          </span>
          {shot.versions.length > 0 && (
            <span className="shrink-0 px-1 rounded bg-zinc-800 text-zinc-400" title="Rendered versions">
              v{shot.current_version ?? shot.versions.length}/{shot.versions.length}
            </span>
          )}
          {shot.status === 'approved' && <span className="shrink-0 text-emerald-400">approved</span>}
          {shot.status === 'rejected' && <span className="shrink-0 text-red-400">rejected</span>}
        </div>
        {(characterNames.length > 0 || location) && (
          <div className="flex items-center gap-1 text-[10px] text-zinc-500 truncate">
            {characterNames.length > 0 && (
              <>
                <Users className="h-3 w-3 shrink-0" />
                <span className="truncate">{characterNames.join(', ')}</span>
              </>
            )}
            {location && <span className="truncate text-zinc-600">· {location}</span>}
          </div>
        )}
        <div className="flex items-center gap-1 pt-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            onClick={event => {
              event.stopPropagation()
              onCompose()
            }}
            className="flex-1 flex items-center justify-center gap-1 px-1.5 py-1 rounded bg-violet-700/80 hover:bg-violet-600 text-[10px] font-medium text-white"
          >
            <Aperture className="h-3 w-3" /> Compose
          </button>
          <button
            onClick={event => {
              event.stopPropagation()
              onDuplicate()
            }}
            title="Duplicate shot"
            aria-label="Duplicate shot"
            className="p-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400"
          >
            <Copy className="h-3 w-3" />
          </button>
          <button
            onClick={event => {
              event.stopPropagation()
              onDelete()
            }}
            title="Delete shot"
            aria-label="Delete shot"
            className="p-1 rounded bg-zinc-800 hover:bg-red-900/70 text-zinc-400 hover:text-red-300"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  )
}
