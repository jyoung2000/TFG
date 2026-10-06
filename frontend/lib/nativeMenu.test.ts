import { describe, expect, it, vi } from 'vitest'
import { toNativeMenu } from './nativeMenu'
import type { MenuDefinition } from '../components/MenuBar'

/* Asked 2026-10-01: the window's File / Edit menu (Electron's default) sat
 * above the video editor's own; the window menu now carries the editor's
 * commands. The page sends the menus as plain data and keeps the commands. */

describe('toNativeMenu', () => {
  const importMedia = vi.fn()
  const twice = vi.fn()
  const menus: MenuDefinition[] = [
    { id: 'file', label: 'File', items: [
      { id: 'import-media', label: 'Import Media...', shortcut: 'Ctrl+I', action: importMedia },
      { id: 'sep-1', label: '', separator: true },
      { id: 'export', label: 'Export...', disabled: true, action: () => {} },
    ] },
    { id: 'clip', label: 'Clip', items: [
      { id: 'speed', label: 'Speed', submenu: [{ id: '2x', label: '2x', action: twice }] },
    ] },
  ]

  it('describes the menus as plain data the window can build', () => {
    const { spec } = toNativeMenu(menus)
    expect(JSON.parse(JSON.stringify(spec))).toEqual(spec)
    expect(spec[0]).toEqual({ id: 'file', label: 'File', items: [
      { id: 'file/import-media', label: 'Import Media...', shortcut: 'Ctrl+I', disabled: false },
      { id: 'file/sep-1', label: '', separator: true },
      { id: 'file/export', label: 'Export...', disabled: true },
    ] })
    expect(spec[1].items[0].submenu?.[0].id).toBe('clip/speed/2x')
  })

  it("keeps each item's command under its id, sub-menus included", () => {
    const { actions } = toNativeMenu(menus)
    actions.get('file/import-media')?.()
    actions.get('clip/speed/2x')?.()
    expect(importMedia).toHaveBeenCalledOnce()
    expect(twice).toHaveBeenCalledOnce()
    expect(actions.has('file/sep-1')).toBe(false)
  })
})
