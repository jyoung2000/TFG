/**
 * The window menu (asked 2026-10-01: "Why are the file, edit, tool bar
 * repeated, fix the windows file and edit toolbar to include the needed menu
 * options and functionality for a image / video editor"). The window showed
 * Electron's default menu - none of it the app's - above the video editor's
 * own menu bar. Now there is one menu, the window's:
 *
 *   - everywhere: File (home, settings, exit), Edit (text editing), View
 *     (full screen, zoom), Window and Help;
 *   - in the video editor, the editor's own File / Edit / Clip / Sequence /
 *     Tools / View / Help, each item running the editor's command, with the
 *     app's File and View items after the editor's.
 *
 * Plain data in, Electron menu template out - no Electron runtime here, so it
 * is testable; `menu.ts` builds and installs it.
 */

import type { MenuItemConstructorOptions } from 'electron'

/** One menu item as the renderer describes it (actions stay in the renderer, keyed by id). */
export interface NativeMenuItemSpec {
  id: string
  label: string
  shortcut?: string
  disabled?: boolean
  separator?: boolean
  submenu?: NativeMenuItemSpec[]
}

export interface NativeMenuSpec {
  id: string
  label: string
  items: NativeMenuItemSpec[]
}

const KEY_NAMES: Record<string, string> = {
  Ctrl: 'CmdOrCtrl',
  Cmd: 'CmdOrCtrl',
  Shift: 'Shift',
  Alt: 'Alt',
  Space: 'Space',
  Del: 'Delete',
  Delete: 'Delete',
  Bksp: 'Backspace',
  Backspace: 'Backspace',
  Esc: 'Escape',
  Escape: 'Escape',
  Enter: 'Enter',
  Tab: 'Tab',
  Home: 'Home',
  End: 'End',
  PageUp: 'PageUp',
  PageDown: 'PageDown',
  '←': 'Left',
  '→': 'Right',
  '↑': 'Up',
  '↓': 'Down',
  '+': 'Plus',
}

const PLAIN_KEY = /^([A-Za-z0-9]|F([1-9]|1[0-9]|2[0-4])|[-=,./\\;'`[\]])$/

/** The editor's shortcut label ("Ctrl+Shift+Z", "←", "Del") as an Electron accelerator; undefined if it has none. */
export function toAccelerator(shortcut?: string): string | undefined {
  if (!shortcut) return undefined
  // "+" alone is the key; otherwise "+" joins the parts.
  const parts = shortcut === '+' ? ['+'] : shortcut.endsWith('++') ? [...shortcut.slice(0, -2).split('+'), '+'] : shortcut.split('+')
  const out: string[] = []
  for (const part of parts) {
    const named = KEY_NAMES[part]
    if (named) out.push(named)
    else if (PLAIN_KEY.test(part)) out.push(part.length === 1 ? part.toUpperCase() : part)
    else return undefined
  }
  return out.join('+')
}

function toItem(spec: NativeMenuItemSpec, onAction: (id: string) => void): MenuItemConstructorOptions {
  if (spec.separator) return { type: 'separator' }
  const item: MenuItemConstructorOptions = { label: spec.label, enabled: !spec.disabled }
  if (spec.submenu?.length) {
    item.submenu = spec.submenu.map(child => toItem(child, onAction))
    return item
  }
  item.click = () => onAction(spec.id)
  const accelerator = toAccelerator(spec.shortcut)
  if (accelerator) {
    // Shown, not registered: the editor already handles its keys (registering
    // them would run each command twice, or steal keys from text fields).
    item.accelerator = accelerator
    item.registerAccelerator = false
  }
  return item
}

function appMenus(onAction: (id: string) => void): Record<'File' | 'Edit' | 'View' | 'Window' | 'Help', MenuItemConstructorOptions[]> {
  return {
    File: [
      { label: 'Home', click: () => onAction('app/home') },
      { label: 'Settings...', click: () => onAction('app/settings') },
      { type: 'separator' },
      { role: 'quit', label: 'Exit' },
    ],
    Edit: [
      { role: 'undo' },
      { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      { role: 'delete' },
      { type: 'separator' },
      { role: 'selectAll' },
    ],
    View: [
      { role: 'togglefullscreen', label: 'Full Screen' },
      { type: 'separator' },
      { role: 'zoomIn', label: 'Zoom In (interface)' },
      { role: 'zoomOut', label: 'Zoom Out (interface)' },
      { role: 'resetZoom', label: 'Actual Size (interface)' },
      { type: 'separator' },
      { role: 'reload' },
      { role: 'toggleDevTools' },
    ],
    Window: [{ role: 'minimize' }, { role: 'zoom', label: 'Maximize' }, { type: 'separator' }, { role: 'close' }],
    Help: [{ label: 'Open Log Folder', click: () => onAction('app/logs') }],
  }
}

/**
 * The window menu: the app's menus, or - with `spec` (the video editor's
 * menus) - the editor's in its order, the app's File / View / Help items
 * appended to the editor's menus of the same name, and Window / Help added.
 * The editor's Edit menu replaces text editing (its undo is the timeline's).
 */
export function buildMenuTemplate(spec: NativeMenuSpec[] | null, onAction: (id: string) => void): MenuItemConstructorOptions[] {
  const app = appMenus(onAction)
  if (!spec?.length) {
    return (['File', 'Edit', 'View', 'Window', 'Help'] as const).map(label => ({ label, submenu: app[label] }))
  }
  const template: MenuItemConstructorOptions[] = spec.map(menu => {
    const own = menu.items.map(item => toItem(item, onAction))
    const extra = menu.label === 'File' || menu.label === 'View' || menu.label === 'Help' ? app[menu.label] : []
    return { label: menu.label, submenu: extra.length ? [...own, { type: 'separator' }, ...extra] : own }
  })
  const have = new Set(spec.map(menu => menu.label))
  for (const label of ['View', 'File'] as const) {
    if (!have.has(label)) template.unshift({ label, submenu: app[label] })
  }
  template.push({ label: 'Window', submenu: app.Window })
  if (!have.has('Help')) template.push({ label: 'Help', submenu: app.Help })
  else {
    // Help belongs last.
    const index = template.findIndex(m => m.label === 'Help')
    template.push(...template.splice(index, 1))
  }
  return template
}
