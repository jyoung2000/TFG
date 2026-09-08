import { useCallback, useState } from 'react'
import { Download, Loader2, Package, Upload } from 'lucide-react'
import { useFilm } from '../../contexts/FilmContext'
import { filmApi } from '../../lib/film-api'
import type { PackageSummary } from '../../types/film'

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

/**
 * Export the current film project as a self-contained .ltxfilm package or
 * import one into it. The backend writes/reads the file at the path chosen
 * in the native dialogs; the renderer never handles the archive bytes.
 */
export function PackageMenu() {
  const { film, refresh } = useFilm()
  const [busy, setBusy] = useState<'export' | 'import' | null>(null)
  const [note, setNote] = useState('')

  const exportPackage = useCallback(async () => {
    if (!film) return
    const suggested = `${(film.name || 'film').replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 60) || 'film'}.ltxfilm`
    const destination = await window.electronAPI.showSaveDialog({
      title: 'Export film package',
      defaultPath: suggested,
      filters: [{ name: 'LTX film package', extensions: ['ltxfilm'] }],
    })
    if (!destination) return
    const includeOutputs = window.confirm('Include generated videos in the package? (Cancel exports the project without renders.)')
    setBusy('export')
    setNote('')
    try {
      const summary: PackageSummary = await filmApi.exportPackage(film.id, destination, includeOutputs)
      setNote(`Exported ${summary.scenes} scenes / ${summary.shots} shots, ${summary.media_files} files (${formatBytes(summary.total_bytes)})`)
      void window.electronAPI.showItemInFolder(summary.path)
    } catch (e) {
      setNote(`Export failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [film])

  const importPackage = useCallback(async () => {
    if (!film) return
    const picked = await window.electronAPI.showOpenFileDialog({
      title: 'Import film package',
      filters: [{ name: 'LTX film package', extensions: ['ltxfilm', 'zip'] }],
      properties: ['openFile'],
    })
    const packagePath = picked?.[0]
    if (!packagePath) return
    setBusy('import')
    setNote('')
    try {
      const preview = await filmApi.inspectPackage(packagePath)
      const hasContent = film.scenes.length > 0 || film.assets.length > 0 || film.script.content.trim().length > 0
      const message =
        `Import "${preview.project_name || preview.project_id}" — ${preview.scenes} scenes, ${preview.shots} shots, ` +
        `${preview.assets} assets, ${preview.media_files} media files (${formatBytes(preview.total_bytes)})` +
        (hasContent ? '\n\nThis REPLACES the current storyboard, assets and script of this project.' : '')
      if (!window.confirm(message)) return
      const result = await filmApi.importPackage(film.id, packagePath, hasContent)
      await refresh()
      setNote(`Imported ${result.summary.scenes} scenes / ${result.summary.shots} shots`)
    } catch (e) {
      setNote(`Import failed: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }, [film, refresh])

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => void exportPackage()}
        disabled={!film || busy !== null}
        className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[11px] text-zinc-300"
        title="Export this film (project.json + captures + references + renders) as a portable .ltxfilm package"
      >
        {busy === 'export' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
        Export
      </button>
      <button
        onClick={() => void importPackage()}
        disabled={!film || busy !== null}
        className="flex items-center gap-1 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-[11px] text-zinc-300"
        title="Import a .ltxfilm package into this project (validated before anything is written)"
      >
        {busy === 'import' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
        Import
      </button>
      {note && (
        <span className="flex items-center gap-1 text-[10px] text-zinc-500 max-w-[16rem] truncate" title={note}>
          <Package className="h-3 w-3 shrink-0" /> {note}
        </span>
      )}
    </div>
  )
}
