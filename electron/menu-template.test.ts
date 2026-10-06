import { describe, expect, it, vi } from 'vitest'
import type { MenuItemConstructorOptions } from 'electron'
import { buildMenuTemplate, toAccelerator, type NativeMenuSpec } from './menu-template'

/* Asked 2026-10-01 (screenshot): "Why are the file, edit, tool bar repeated,
 * fix the windows file and edit toolbar to include the needed menu options
 * and functionality for a image / video editor". The window showed
 * Electron's default menu (File Edit View Window Help, none of it the app's)
 * above the video editor's own File / Edit / Clip / Sequence menu. The
 * window menu now carries the app's commands, and the editor's while it is
 * open. */

const labels = (template: MenuItemConstructorOptions[]) => template.map(m => m.label)
const items = (template: MenuItemConstructorOptions[], label: string) => (template.find(m => m.label === label)?.submenu ?? []) as MenuItemConstructorOptions[]

const EDITOR: NativeMenuSpec[] = [
  { id: 'file', label: 'File', items: [
    { id: 'file/import-media', label: 'Import Media...', shortcut: 'Ctrl+I' },
    { id: 'file/sep-1', label: '', separator: true },
    { id: 'file/export-timeline', label: 'Export Timeline...', shortcut: 'Ctrl+E', disabled: true },
  ] },
  { id: 'edit', label: 'Edit', items: [
    { id: 'edit/undo', label: 'Undo', shortcut: 'Ctrl+Z' },
    { id: 'edit/redo', label: 'Redo', shortcut: 'Ctrl+Shift+Z' },
  ] },
  { id: 'clip', label: 'Clip', items: [
    { id: 'clip/split', label: 'Split at Playhead', shortcut: 'Ctrl+K' },
    { id: 'clip/speed', label: 'Speed', submenu: [{ id: 'clip/speed/2x', label: '2x' }] },
  ] },
  { id: 'view', label: 'View', items: [{ id: 'view/zoom-in', label: 'Zoom In Timeline', shortcut: '=' }] },
]

describe('the window menu without the editor', () => {
  it("is the app's: home, settings, text editing, full screen and zoom, the window, help", () => {
    const onAction = vi.fn()
    const template = buildMenuTemplate(null, onAction)
    expect(labels(template)).toEqual(['File', 'Edit', 'View', 'Window', 'Help'])
    const file = items(template, 'File')
    file.find(i => i.label === 'Settings...')?.click?.({} as never, undefined, {} as never)
    expect(onAction).toHaveBeenCalledWith('app/settings')
    expect(file.some(i => i.role === 'quit')).toBe(true)
    expect(items(template, 'Edit').map(i => i.role)).toEqual(expect.arrayContaining(['undo', 'redo', 'cut', 'copy', 'paste', 'selectAll']))
    expect(items(template, 'View').map(i => i.role)).toEqual(expect.arrayContaining(['togglefullscreen', 'zoomIn', 'zoomOut', 'resetZoom']))
  })
})

describe('the window menu in the video editor', () => {
  it("carries the editor's menus, in its order, with the app's window and help after them", () => {
    const template = buildMenuTemplate(EDITOR, () => {})
    expect(labels(template)).toEqual(['File', 'Edit', 'Clip', 'View', 'Window', 'Help'])
  })

  it("runs the editor's command when an item is clicked, and keeps disabled items disabled", () => {
    const onAction = vi.fn()
    const template = buildMenuTemplate(EDITOR, onAction)
    const file = items(template, 'File')
    file.find(i => i.label === 'Import Media...')?.click?.({} as never, undefined, {} as never)
    expect(onAction).toHaveBeenCalledWith('file/import-media')
    expect(file.find(i => i.label === 'Export Timeline...')?.enabled).toBe(false)
    expect(file.some(i => i.type === 'separator')).toBe(true)
    // The app's own File items follow the editor's: settings and exit stay reachable.
    expect(file.some(i => i.role === 'quit')).toBe(true)
    const speed = items(template, 'Clip').find(i => i.label === 'Speed')?.submenu as MenuItemConstructorOptions[]
    speed[0].click?.({} as never, undefined, {} as never)
    expect(onAction).toHaveBeenCalledWith('clip/speed/2x')
  })

  it("uses the editor's Edit menu (its undo is the timeline's), not the text-editing one", () => {
    const edit = items(buildMenuTemplate(EDITOR, () => {}), 'Edit')
    expect(edit.map(i => i.label)).toEqual(['Undo', 'Redo'])
    expect(edit.some(i => i.role === 'undo')).toBe(false)
  })

  it('shows shortcuts without taking over the keys (the editor handles its own)', () => {
    const importItem = items(buildMenuTemplate(EDITOR, () => {}), 'File').find(i => i.label === 'Import Media...')
    expect(importItem?.accelerator).toBe('CmdOrCtrl+I')
    expect(importItem?.registerAccelerator).toBe(false)
    // The editor's View items come first, then full screen and zoom for the window.
    expect(items(buildMenuTemplate(EDITOR, () => {}), 'View').map(i => i.label ?? i.role)[0]).toBe('Zoom In Timeline')
  })
})

describe('toAccelerator', () => {
  it("turns the editor's shortcut labels into Electron accelerators", () => {
    expect(toAccelerator('Ctrl+Shift+Z')).toBe('CmdOrCtrl+Shift+Z')
    expect(toAccelerator('Space')).toBe('Space')
    expect(toAccelerator('←')).toBe('Left')
    expect(toAccelerator('Del')).toBe('Delete')
    expect(toAccelerator('Bksp')).toBe('Backspace')
    expect(toAccelerator('Esc')).toBe('Escape')
    expect(toAccelerator('Alt+=')).toBe('Alt+=')
    expect(toAccelerator('+')).toBe('Plus')
  })

  it('drops what Electron could not parse instead of breaking the menu', () => {
    expect(toAccelerator('')).toBeUndefined()
    expect(toAccelerator(undefined)).toBeUndefined()
    expect(toAccelerator('Ctrl+é')).toBeUndefined()
  })
})
