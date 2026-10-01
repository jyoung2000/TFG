/**
 * Original photo + live preview of it as the 3D model is edited (asked
 * 2026-10-01). The edited preview is the person from the original photo,
 * re-rendered by FLUX.2 into the pose and framing of the viewfinder; it
 * re-renders once edits pause (`PreviewScheduler`).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, RefreshCw } from 'lucide-react'
import { filmApi, filmMediaUrl } from '../../../lib/film-api'
import { analysisFrameUrl, videoAnalysisApi } from '../../../lib/video-analysis-api'
import type { FilmProject, FilmShot } from '../../../types/film'
import { PreviewScheduler } from './previewScheduler'
import { underlaySource } from './sceneFromAnalysis'
import type { ComposerScene } from './composerScene'

/** Long side of a preview render: quick enough to feel live (~5 s on a 4070). */
const PREVIEW_EDGE = 768

interface Props {
  projectId: string
  shot: FilmShot
  film: FilmProject | null
  getComposer: () => ComposerScene | null
  /** Bumps on every edit of the scene. */
  editTick: number
  prompt: string
}

export function PosePreviewPanel({ projectId, shot, film, getComposer, editTick, prompt }: Props) {
  const [open, setOpen] = useState(true)
  const [live, setLive] = useState(true)
  const [originalUrl, setOriginalUrl] = useState('')
  const [originalAspect, setOriginalAspect] = useState(9 / 16)
  const [photoPath, setPhotoPath] = useState('')
  const [preview, setPreview] = useState('')
  const [status, setStatus] = useState('')
  const [rendering, setRendering] = useState(false)
  // The photo's pose: the figure as saved when the composer opened. Only the
  // limbs edited away from it are spelled out to the image model.
  const [baseline] = useState(() => shot.composition?.objects.find(o => o.type === 'figure')?.pose ?? null)

  // The original: what the composer shows behind the viewfinder. The photo the
  // preview keeps must be a project file - for a video frame, the cast's image.
  useEffect(() => {
    let active = true
    const castPhoto = shot.characters.map(c => film?.assets.find(a => a.id === c.asset_id)?.reference_images[0]).find(Boolean) ?? ''
    const source = underlaySource(shot)
    void (async () => {
      try {
        let url = ''
        let path = castPhoto
        if (source?.kind === 'capture') {
          url = await filmMediaUrl(projectId, source.path)
          path = source.path
        } else if (source?.kind === 'analysis') {
          const analysis = await videoAnalysisApi.get(source.analysisId)
          const analysed = analysis.shots.find(s => s.id === source.shotId)
          const frame = analysed?.frames.find(f => f.role === 'start') ?? analysed?.frames[0]
          if (frame) url = await analysisFrameUrl(source.analysisId, frame.path)
        } else if (castPhoto) {
          url = await filmMediaUrl(projectId, castPhoto)
        }
        if (!active) return
        setOriginalUrl(url)
        setPhotoPath(path)
      } catch {
        if (active) setStatus('Original photo unavailable')
      }
    })()
    return () => { active = false }
  }, [projectId, shot, film])

  const renderPreview = useCallback(async () => {
    const composer = getComposer()
    if (!composer || !photoPath) return
    const width = originalAspect >= 1 ? PREVIEW_EDGE : Math.round(PREVIEW_EDGE * originalAspect)
    const height = originalAspect >= 1 ? Math.round(PREVIEW_EDGE / originalAspect) : PREVIEW_EDGE
    setRendering(true)
    setStatus('Rendering the edit…')
    try {
      // The viewfinder at the photo's shape: the same framing the photo has.
      const guide = composer.capture(width, height)
      const pose = composer.describePose(baseline)
      const result = await filmApi.previewRender(projectId, { guide_base64: guide, reference_path: photoPath, prompt, pose, width, height })
      setPreview(result.image)
      setStatus(`Updated in ${result.seconds.toFixed(1)} s`)
    } catch (e) {
      setStatus(`Preview failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setRendering(false)
    }
  }, [getComposer, photoPath, originalAspect, projectId, prompt, baseline])

  const renderRef = useRef(renderPreview)
  renderRef.current = renderPreview
  const schedulerRef = useRef<PreviewScheduler | null>(null)
  if (!schedulerRef.current) schedulerRef.current = new PreviewScheduler(() => renderRef.current())
  useEffect(() => () => schedulerRef.current?.dispose(), [])

  // Live: every edit re-renders once the edits pause.
  useEffect(() => {
    if (editTick > 0 && live && open && photoPath) schedulerRef.current?.edited()
  }, [editTick, live, open, photoPath])

  return (
    <div className="absolute bottom-3 left-3 z-10 rounded-lg border border-zinc-700 bg-zinc-900/90 shadow-lg" data-testid="pose-preview">
      <div className="flex items-center gap-2 px-2 py-1 text-[11px] text-zinc-300">
        <button onClick={() => setOpen(o => !o)} className="flex items-center gap-1 font-medium" aria-expanded={open}>
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />} Preview
        </button>
        <label className="flex items-center gap-1 text-zinc-400" title="Re-render the preview after every edit">
          <input type="checkbox" checked={live} onChange={e => setLive(e.target.checked)} data-testid="pose-preview-live" /> Live
        </label>
        <button onClick={() => void schedulerRef.current?.now()} disabled={!photoPath} className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40" data-testid="pose-preview-render">
          {rendering ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Render now
        </button>
      </div>
      {open && (
        <div className="flex gap-2 px-2 pb-2">
          <figure className="space-y-0.5">
            <div className="relative h-44 rounded overflow-hidden bg-black ring-2 ring-teal-500/70" style={{ aspectRatio: String(originalAspect) }}>
              <span className="absolute left-1 top-1 rounded bg-teal-500 px-1 text-[9px] font-bold uppercase text-black">Original</span>
              {originalUrl && (
                <img src={originalUrl} alt="Original photo" className="w-full h-full object-cover" data-testid="pose-preview-original"
                  onLoad={e => { const img = e.currentTarget; if (img.naturalWidth && img.naturalHeight) setOriginalAspect(img.naturalWidth / img.naturalHeight) }} />
              )}
            </div>
          </figure>
          <figure className="space-y-0.5">
            <div className="relative h-44 rounded overflow-hidden bg-black ring-2 ring-violet-500/70" style={{ aspectRatio: String(originalAspect) }}>
              <span className="absolute left-1 top-1 z-10 rounded bg-violet-600 px-1 text-[9px] font-bold uppercase text-white">Edited</span>
              {preview ? (
                <img src={preview} alt="Edited preview" className={`w-full h-full object-cover ${rendering ? 'opacity-60' : ''}`} data-testid="pose-preview-image" />
              ) : (
                <div className="w-full h-full flex items-center justify-center p-2 text-center text-[10px] text-zinc-500">
                  {photoPath ? 'Edit the pose — the photo re-renders here' : 'No original photo for this shot'}
                </div>
              )}
              {rendering && <Loader2 className="absolute right-1 top-1 h-3.5 w-3.5 animate-spin text-violet-200" />}
            </div>
          </figure>
        </div>
      )}
      {open && status && <p className="px-2 pb-1.5 text-[10px] text-zinc-500 max-w-[22rem] truncate" role="status" title={status}>{status}</p>}
    </div>
  )
}
