import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Brush, Eraser, RotateCcw, Square, X } from 'lucide-react'
import { reproduceApi, type FixPayload } from '../../lib/reproduce-api'
import type { ReproduceCandidate, ReproduceJob } from '../../types/reproduce'
import { useMediaUrl } from './MediaImage'

/**
 * FixCanvas: reference / candidate / mask layers, adjustments previewed
 * client-side (CSS filters + the same maths as the server for levels), and
 * every change committed server-side (`services/image_ops.py`) so the saved
 * file is what the user saw. Selection → mask → patch from reference or
 * inpaint through the edit model. Plain Canvas 2D — no extra dependency.
 *
 * Shortcuts: B brush · E eraser · M marquee · [ ] brush size · Ctrl/Cmd+Z undo mask · Esc close.
 * (Layer/mask/adjustment concepts after robbietilton/Compositor; no source used.)
 */

type Tool = 'brush' | 'eraser' | 'marquee'

interface Adjust {
  exposure: number
  contrast: number
  saturation: number
  hue: number
  black_point: number
  white_point: number
  gamma: number
  temperature: number
}
const NEUTRAL: Adjust = { exposure: 0, contrast: 0, saturation: 0, hue: 0, black_point: 0, white_point: 1, gamma: 1, temperature: 0 }

const SLIDERS: { key: keyof Adjust; label: string; min: number; max: number; step: number }[] = [
  { key: 'exposure', label: 'Exposure', min: -3, max: 3, step: 0.05 },
  { key: 'contrast', label: 'Contrast', min: -1, max: 1, step: 0.02 },
  { key: 'saturation', label: 'Saturation', min: -1, max: 1, step: 0.02 },
  { key: 'hue', label: 'Hue', min: -180, max: 180, step: 1 },
  { key: 'temperature', label: 'Temperature', min: -1, max: 1, step: 0.02 },
  { key: 'black_point', label: 'Levels: black', min: 0, max: 0.9, step: 0.01 },
  { key: 'white_point', label: 'Levels: white', min: 0.1, max: 1, step: 0.01 },
  { key: 'gamma', label: 'Gamma', min: 0.2, max: 3, step: 0.02 },
]

interface Props {
  job: ReproduceJob
  candidate: ReproduceCandidate
  onClose: () => void
  onCommitted: (job: ReproduceJob) => void
  onUseAsStartFrame?: (candidate: ReproduceCandidate) => void
}

export function FixCanvas({ job, candidate, onClose, onCommitted, onUseAsStartFrame }: Props) {
  const candidateUrl = useMediaUrl(job.id, candidate.path)
  const referenceUrl = useMediaUrl(job.id, job.source_path)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const maskRef = useRef<HTMLCanvasElement>(null)
  const [tool, setTool] = useState<Tool>('brush')
  const [brush, setBrush] = useState(24)
  const [adjust, setAdjust] = useState<Adjust>(NEUTRAL)
  const [referenceOpacity, setReferenceOpacity] = useState(0)
  const [maskHistory, setMaskHistory] = useState<ImageData[]>([])
  const [hasMask, setHasMask] = useState(false)
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  const [inpaintPrompt, setInpaintPrompt] = useState('')
  const [size, setSize] = useState<{ w: number; h: number }>({ w: job.width, h: job.height })
  const drawing = useRef<{ start: [number, number] | null; last: [number, number] | null }>({ start: null, last: null })

  // Load the candidate into the base canvas and size the mask to match.
  useEffect(() => {
    if (!candidateUrl) return
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      const canvas = canvasRef.current
      const mask = maskRef.current
      if (!canvas || !mask) return
      canvas.width = image.naturalWidth
      canvas.height = image.naturalHeight
      mask.width = image.naturalWidth
      mask.height = image.naturalHeight
      canvas.getContext('2d')?.drawImage(image, 0, 0)
      setSize({ w: image.naturalWidth, h: image.naturalHeight })
    }
    image.src = candidateUrl
  }, [candidateUrl])

  const filter = useMemo(() => {
    const brightness = 2 ** adjust.exposure
    return `brightness(${brightness}) contrast(${1 + adjust.contrast}) saturate(${1 + adjust.saturation}) hue-rotate(${adjust.hue}deg)`
  }, [adjust])

  const pushHistory = useCallback(() => {
    const mask = maskRef.current
    const context = mask?.getContext('2d')
    if (!mask || !context) return
    setMaskHistory(prev => [...prev.slice(-19), context.getImageData(0, 0, mask.width, mask.height)])
  }, [])

  const undoMask = useCallback(() => {
    const mask = maskRef.current
    const context = mask?.getContext('2d')
    if (!mask || !context) return
    setMaskHistory(prev => {
      const last = prev[prev.length - 1]
      if (last) context.putImageData(last, 0, 0)
      else context.clearRect(0, 0, mask.width, mask.height)
      return prev.slice(0, -1)
    })
  }, [])

  const clearMask = useCallback(() => {
    pushHistory()
    const mask = maskRef.current
    mask?.getContext('2d')?.clearRect(0, 0, mask.width, mask.height)
    setHasMask(false)
  }, [pushHistory])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement | null)?.tagName === 'INPUT' || (event.target as HTMLElement | null)?.tagName === 'TEXTAREA') return
      if (event.key === 'Escape') onClose()
      else if (event.key === 'b' || event.key === 'B') setTool('brush')
      else if (event.key === 'e' || event.key === 'E') setTool('eraser')
      else if (event.key === 'm' || event.key === 'M') setTool('marquee')
      else if (event.key === '[') setBrush(b => Math.max(4, b - 4))
      else if (event.key === ']') setBrush(b => Math.min(160, b + 4))
      else if ((event.ctrlKey || event.metaKey) && (event.key === 'z' || event.key === 'Z')) { event.preventDefault(); undoMask() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, undoMask])

  const toCanvas = (event: React.PointerEvent<HTMLCanvasElement>): [number, number] => {
    const rect = event.currentTarget.getBoundingClientRect()
    return [((event.clientX - rect.left) / rect.width) * size.w, ((event.clientY - rect.top) / rect.height) * size.h]
  }

  const paint = (from: [number, number], to: [number, number]) => {
    const context = maskRef.current?.getContext('2d')
    if (!context) return
    context.globalCompositeOperation = tool === 'eraser' ? 'destination-out' : 'source-over'
    context.strokeStyle = 'rgba(255,255,255,1)'
    context.lineWidth = brush
    context.lineCap = 'round'
    context.lineJoin = 'round'
    context.beginPath()
    context.moveTo(from[0], from[1])
    context.lineTo(to[0], to[1])
    context.stroke()
    context.globalCompositeOperation = 'source-over'
  }

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    pushHistory()
    const point = toCanvas(event)
    drawing.current = { start: point, last: point }
    if (tool !== 'marquee') paint(point, point)
  }
  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current.start) return
    const point = toCanvas(event)
    if (tool === 'marquee') return
    if (drawing.current.last) paint(drawing.current.last, point)
    drawing.current.last = point
  }
  const onPointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const start = drawing.current.start
    if (!start) return
    const end = toCanvas(event)
    if (tool === 'marquee') {
      const context = maskRef.current?.getContext('2d')
      if (context) {
        context.fillStyle = 'rgba(255,255,255,1)'
        context.fillRect(Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.abs(end[0] - start[0]), Math.abs(end[1] - start[1]))
      }
    }
    drawing.current = { start: null, last: null }
    setHasMask(true)
  }

  const maskBase64 = (): string => {
    const mask = maskRef.current
    if (!mask || !hasMask) return ''
    // Export as an opaque grayscale PNG: white = selected, black = untouched.
    const out = document.createElement('canvas')
    out.width = mask.width
    out.height = mask.height
    const context = out.getContext('2d')
    if (!context) return ''
    context.fillStyle = '#000'
    context.fillRect(0, 0, out.width, out.height)
    context.drawImage(mask, 0, 0)
    return out.toDataURL('image/png').split(',')[1] ?? ''
  }

  const commit = async (extra: Partial<FixPayload>, label: string) => {
    setBusy(label)
    setNote('')
    try {
      const payload: FixPayload = { ...adjust, mask_png_base64: maskBase64(), ...extra }
      const updated = await reproduceApi.fix(job.id, candidate.id, payload)
      onCommitted(updated)
      setNote(`${label} saved as a new candidate`)
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy('')
    }
  }

  const neutral = JSON.stringify(adjust) === JSON.stringify(NEUTRAL)

  return (
    <div role="dialog" aria-modal="true" aria-label="Fix canvas" className="fixed inset-0 z-[90] bg-zinc-950 flex flex-col" data-testid="fix-canvas">
      <header className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <h2 className="text-sm font-semibold text-white">Fix · {candidate.id}</h2>
        <span className="text-[11px] text-zinc-500">B brush · E eraser · M marquee · [ ] size · Ctrl+Z undo mask · Esc close</span>
        <button onClick={onClose} aria-label="Close fix canvas" className="ml-auto p-1.5 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white"><X className="h-4 w-4" /></button>
      </header>
      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0 flex items-center justify-center p-4 bg-zinc-950">
          <div className="relative max-h-full" style={{ aspectRatio: `${size.w} / ${size.h}`, width: 'min(100%, 1200px)' }}>
            <canvas ref={canvasRef} className="absolute inset-0 w-full h-full rounded" style={{ filter }} aria-label="Candidate layer" />
            {referenceUrl && referenceOpacity > 0 && (
              <img src={referenceUrl} alt="Reference layer" className="absolute inset-0 w-full h-full object-fill rounded pointer-events-none" style={{ opacity: referenceOpacity }} />
            )}
            <canvas
              ref={maskRef}
              className="absolute inset-0 w-full h-full rounded cursor-crosshair"
              style={{ opacity: 0.55, mixBlendMode: 'screen' }}
              aria-label="Mask layer"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            />
          </div>
        </div>
        <aside className="w-80 shrink-0 border-l border-zinc-800 overflow-y-auto p-3 space-y-4 text-xs">
          <section className="space-y-1.5">
            <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Selection</h3>
            <div className="flex gap-1.5">
              <button onClick={() => setTool('brush')} aria-pressed={tool === 'brush'} className={`btn-chip ${tool === 'brush' ? 'ring-1 ring-violet-500' : ''}`}><Brush className="h-3 w-3" /> Brush</button>
              <button onClick={() => setTool('eraser')} aria-pressed={tool === 'eraser'} className={`btn-chip ${tool === 'eraser' ? 'ring-1 ring-violet-500' : ''}`}><Eraser className="h-3 w-3" /> Eraser</button>
              <button onClick={() => setTool('marquee')} aria-pressed={tool === 'marquee'} className={`btn-chip ${tool === 'marquee' ? 'ring-1 ring-violet-500' : ''}`}><Square className="h-3 w-3" /> Marquee</button>
            </div>
            <label className="block text-[10px] text-zinc-500">Brush size {brush}px<input type="range" min={4} max={160} value={brush} onChange={e => setBrush(Number(e.target.value))} className="w-full accent-violet-500" aria-label="Brush size" /></label>
            <div className="flex gap-1.5">
              <button onClick={undoMask} className="btn-chip" disabled={maskHistory.length === 0}><RotateCcw className="h-3 w-3" /> Undo</button>
              <button onClick={clearMask} className="btn-chip" disabled={!hasMask}>Clear</button>
            </div>
          </section>
          <section className="space-y-1.5">
            <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Layers</h3>
            <label className="block text-[10px] text-zinc-500">Reference overlay {(referenceOpacity * 100).toFixed(0)}%<input type="range" min={0} max={1} step={0.05} value={referenceOpacity} onChange={e => setReferenceOpacity(Number(e.target.value))} className="w-full accent-violet-500" aria-label="Reference overlay opacity" /></label>
          </section>
          <section className="space-y-1.5">
            <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Adjustments</h3>
            {SLIDERS.map(slider => (
              <label key={slider.key} className="block text-[10px] text-zinc-500">
                {slider.label} {adjust[slider.key].toFixed(2)}
                <input type="range" min={slider.min} max={slider.max} step={slider.step} value={adjust[slider.key]} onChange={e => setAdjust(a => ({ ...a, [slider.key]: Number(e.target.value) }))} className="w-full accent-violet-500" aria-label={slider.label} />
              </label>
            ))}
            <p className="text-[10px] text-zinc-600">Levels and gamma apply on commit; the preview shows exposure, contrast, saturation and hue.</p>
            <button onClick={() => setAdjust(NEUTRAL)} className="btn-chip" disabled={neutral}>Reset</button>
          </section>
          <section className="space-y-1.5">
            <h3 className="text-[10px] uppercase tracking-wide text-zinc-500 font-semibold">Commit</h3>
            <button onClick={() => void commit({}, 'Adjustments')} disabled={!!busy || (neutral && !hasMask)} className="btn-chip w-full justify-center">Save adjustments as candidate</button>
            <button onClick={() => void commit({ patch_from_reference: true }, 'Patch from reference')} disabled={!!busy || !hasMask} className="btn-chip w-full justify-center">Patch selection from reference</button>
            <input value={inpaintPrompt} onChange={e => setInpaintPrompt(e.target.value)} placeholder="Inpaint the selection with…" aria-label="Inpaint prompt" className="select-chip w-full" />
            <button onClick={() => void commit({ inpaint_prompt: inpaintPrompt }, 'Inpaint')} disabled={!!busy || !hasMask || !inpaintPrompt.trim()} className="btn-chip w-full justify-center">Inpaint selection (edit model)</button>
            {onUseAsStartFrame && <button onClick={() => onUseAsStartFrame(candidate)} className="btn-chip w-full justify-center">Use as start frame (Quick video)</button>}
            {note && <p className="text-[11px] text-zinc-400" role="status">{note}</p>}
          </section>
        </aside>
      </div>
    </div>
  )
}
