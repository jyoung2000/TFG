import { useCallback, useEffect, useState } from 'react'

/**
 * Simple vs advanced UI. Simple hides power-user surfaces (script/models
 * tabs, export/import, quality profiles, context details) so a first film
 * is just: assets → storyboard → generate. Stored per machine.
 */
export type UiMode = 'simple' | 'advanced'

const KEY = 'ltx-ui-mode'
const EVENT = 'ltx-ui-mode-change'

export function readUiMode(): UiMode {
  try {
    return localStorage.getItem(KEY) === 'simple' ? 'simple' : 'advanced'
  } catch {
    return 'advanced'
  }
}

export function writeUiMode(mode: UiMode): void {
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    // best effort
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: mode }))
}

export function useUiMode(): [UiMode, (mode: UiMode) => void] {
  const [mode, setMode] = useState<UiMode>(() => readUiMode())
  useEffect(() => {
    const handler = (event: Event) => {
      const next = (event as CustomEvent<UiMode>).detail
      if (next === 'simple' || next === 'advanced') setMode(next)
    }
    window.addEventListener(EVENT, handler)
    return () => window.removeEventListener(EVENT, handler)
  }, [])
  const update = useCallback((next: UiMode) => {
    setMode(next)
    writeUiMode(next)
  }, [])
  return [mode, update]
}
