/**
 * Installs the window menu (see `menu-template.ts`) and relays its clicks to
 * the page: the renderer sends the menus it wants (`set-app-menu`, null for
 * the app's own), and gets `menu-action` with the clicked item's id.
 */

import { BrowserWindow, ipcMain, Menu } from 'electron'
import { buildMenuTemplate, type NativeMenuSpec } from './menu-template'
import { getMainWindow } from './window'

function sendAction(id: string): void {
  const window = getMainWindow() ?? BrowserWindow.getFocusedWindow()
  window?.webContents.send('menu-action', id)
}

export function installAppMenu(spec: NativeMenuSpec[] | null): void {
  Menu.setApplicationMenu(Menu.buildFromTemplate(buildMenuTemplate(spec, sendAction)))
}

export function registerMenuHandlers(): void {
  ipcMain.on('set-app-menu', (_event, spec: NativeMenuSpec[] | null) => {
    installAppMenu(Array.isArray(spec) ? spec : null)
  })
}
