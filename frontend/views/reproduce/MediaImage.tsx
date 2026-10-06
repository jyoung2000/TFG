import { useEffect, useState } from 'react'
import { reproduceMediaUrl } from '../../lib/reproduce-api'

/** An image from a reproduce job, with a visible error state (never an empty box). */
export function MediaImage({ jobId, path, alt, className, onClick }: { jobId: string; path: string; alt: string; className?: string; onClick?: () => void }) {
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    setUrl('')
    setFailed(false)
    reproduceMediaUrl(jobId, path).then(next => { if (active) setUrl(next) }).catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [jobId, path])
  if (failed) return <div role="img" aria-label={`${alt} unavailable`} className={`flex items-center justify-center text-[11px] text-red-300 bg-red-950/30 ${className ?? ''}`}>unavailable</div>
  if (!url) return <div className={`animate-pulse bg-zinc-900 ${className ?? ''}`} aria-label={`Loading ${alt}`} />
  return <img src={url} alt={alt} loading="lazy" onError={() => setFailed(true)} onClick={onClick} className={className} />
}

export function useMediaUrl(jobId: string, path: string): string {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true
    if (!path) { setUrl(''); return }
    reproduceMediaUrl(jobId, path).then(next => { if (active) setUrl(next) }).catch(() => { if (active) setUrl('') })
    return () => { active = false }
  }, [jobId, path])
  return url
}
