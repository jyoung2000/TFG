/**
 * The window menu from the page's side (asked 2026-10-01: the window's File /
 * Edit menu - Electron's default - repeated above the video editor's own).
 * The page sends its menus as plain data (`electronAPI.setAppMenu`) and keeps
 * the commands here, keyed by item id; a click comes back as that id
 * (`electronAPI.onMenuAction`). See electron/menu-template.ts.
 */

import { useEffect, useRef } from 'react'
import type { MenuDefinition, MenuItem } from '../components/MenuBar'

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

export function toNativeMenu(menus: MenuDefinition[]): { spec: NativeMenuSpec[]; actions: Map<string, () => void> } {
  const actions = new Map<string, () => void>()
  const item = (entry: MenuItem, parent: string): NativeMenuItemSpec => {
    const id = `${parent}/${entry.id}`
    if (entry.separator) return { id, label: '', separator: true }
    if (entry.submenu?.length) return { id, label: entry.label, disabled: !!entry.disabled, submenu: entry.submenu.map(child => item(child, id)) }
    if (entry.action) actions.set(id, entry.action)
    const spec: NativeMenuItemSpec = { id, label: entry.label, disabled: !!entry.disabled }
    if (entry.shortcut) spec.shortcut = entry.shortcut
    return spec
  }
  const spec = menus.map(menu => ({ id: menu.id, label: menu.label, items: menu.items.map(entry => item(entry, menu.id)) }))
  return { spec, actions }
}

/** True in the desktop app, where the window has a menu bar (not in a plain browser). */
export function hasNativeMenu(): boolean {
  return typeof window !== 'undefined' && typeof window.electronAPI?.setAppMenu === 'function'
}

/**
 * While `active`, the window menu shows `menus` and runs their commands;
 * otherwise (and on unmount) it goes back to the app's own menu.
 */
export function useNativeMenu(menus: MenuDefinition[] | null, active: boolean): void {
  const actionsRef = useRef(new Map<string, () => void>())
  useEffect(() => {
    if (!hasNativeMenu() || !active || !menus) return
    const { spec, actions } = toNativeMenu(menus)
    actionsRef.current = actions
    window.electronAPI.setAppMenu?.(spec)
  }, [menus, active])
  useEffect(() => {
    if (!hasNativeMenu() || !active) return
    const off = window.electronAPI.onMenuAction?.(id => actionsRef.current.get(id)?.())
    return () => {
      off?.()
      window.electronAPI.setAppMenu?.(null)
    }
  }, [active])
}
