import { useEffect, useState } from 'react'
import { Loader2, PlugZap, Server } from 'lucide-react'
import { resetBackendCredentials } from '../../lib/backend'
import { Button } from '../ui/button'

const inputClass = 'w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-violet-600'

/**
 * Settings → General: run this desktop against a TFG backend elsewhere (the
 * compose stack on an Unraid box, a workstation, a rented GPU). URL + token,
 * a health check that names the GPU it found, then one switch. The Python
 * process on this machine is stopped while a remote is in use, and media
 * comes through the authenticated output route rather than file://.
 */
export function RemoteBackendCard() {
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [probe, setProbe] = useState<{ ok: boolean; status?: string; gpu?: string; error?: string } | null>(null)
  const [busy, setBusy] = useState<'test' | 'use' | 'local' | ''>('')

  useEffect(() => {
    window.electronAPI.getRemoteBackend().then(cfg => { setUrl(cfg.url); setToken(cfg.token); setEnabled(cfg.enabled) }).catch(() => undefined)
  }, [])

  const test = async () => {
    setBusy('test'); setProbe(null)
    try { setProbe(await window.electronAPI.testRemoteBackend(url, token)) } finally { setBusy('') }
  }
  const apply = async (nextEnabled: boolean) => {
    setBusy(nextEnabled ? 'use' : 'local')
    try {
      const result = await window.electronAPI.setRemoteBackend({ url, token, enabled: nextEnabled })
      setProbe(result)
      if (result.ok) {
        setEnabled(nextEnabled)
        resetBackendCredentials()
        // Every cached URL, media element and SSE feed must re-resolve.
        window.location.reload()
      }
    } finally { setBusy('') }
  }

  return (
    <div className="space-y-2" data-testid="remote-backend">
      <div className="flex items-center gap-2">
        <Server className="h-4 w-4 text-sky-300" />
        <h3 className="text-sm font-semibold text-white">Remote backend</h3>
        {enabled && <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-900/50 text-sky-200">in use</span>}
      </div>
      <p className="text-xs text-zinc-500">
        Point this app at a TFG backend running elsewhere — the container stack (docs/CONTAINERS.md) on a NAS or a bigger GPU. The local Python process stays off while a remote is in use; renders are fetched over HTTP, never from this disk.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr] gap-2">
        <label className="block text-[11px] text-zinc-400">URL
          <input value={url} onChange={e => setUrl(e.target.value)} placeholder="http://unraid.local:8000" aria-label="Remote backend URL" className={`${inputClass} mt-0.5 font-mono`} />
        </label>
        <label className="block text-[11px] text-zinc-400">Token (LTX_AUTH_TOKEN)
          <input value={token} onChange={e => setToken(e.target.value)} type="password" placeholder="from deploy/.env" aria-label="Remote backend token" className={`${inputClass} mt-0.5 font-mono`} />
        </label>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <Button size="sm" variant="ghost" disabled={!url || !!busy} onClick={() => void test()} className="h-7 px-2 text-xs text-zinc-200 hover:text-white hover:bg-zinc-700">
          {busy === 'test' ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <PlugZap className="h-3.5 w-3.5 mr-1" />} Test connection
        </Button>
        <Button size="sm" disabled={!url || !!busy || !probe?.ok} onClick={() => void apply(true)} className="h-7 px-2 text-xs bg-sky-700 hover:bg-sky-600 text-white" aria-label="Use remote backend">
          {busy === 'use' ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null} Use this backend
        </Button>
        {enabled && (
          <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void apply(false)} className="h-7 px-2 text-xs text-zinc-300 hover:text-white hover:bg-zinc-700">
            {busy === 'local' ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null} Back to this computer
          </Button>
        )}
        {probe && (
          <span className={`text-[11px] ${probe.ok ? 'text-emerald-300' : 'text-red-300'}`} role="status" data-testid="remote-probe">
            {probe.ok ? `Reachable · ${probe.gpu ? probe.gpu : 'GPU not reported'}` : probe.error ?? `Backend answered ${probe.status ?? 'unexpectedly'}`}
          </span>
        )}
      </div>
    </div>
  )
}
