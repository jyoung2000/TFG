/**
 * Dev-only stand-in for the Electron preload bridge.
 *
 * Lets the renderer run in a plain browser, either against a real backend on
 * port 8000 or — with `pnpm dev:ui` — against the mock backend the Vite dev
 * server hosts on this same origin (`devtools/ui-mock`). No-ops when the real
 * preload bridge is present, so it never affects the packaged app.
 *
 * Where Electron would touch the filesystem or the OS, the shim answers with a
 * plausible synthetic result rather than rejecting: a dialog that never
 * resolves leaves a UI path untestable, which is the opposite of the point.
 */

/** The standalone HTML build: the mock backend runs in this tab. */
const STANDALONE = import.meta.env.VITE_UI_STANDALONE === '1'

/** True in either UI-only mode; compiled out of production builds. */
const UI_MOCK = import.meta.env.VITE_UI_MOCK === '1' || STANDALONE

/**
 * `pnpm dev:ui` talks to the dev server it was served from. The standalone
 * build has no origin to talk to — a `file://` page has none — so it leaves
 * backend URLs relative for the patched `fetch` to answer.
 */
const BROWSER_BACKEND_URL = STANDALONE ? '' : UI_MOCK ? window.location.origin : 'http://localhost:8000'

const MOCK_HOME = '/home/you/LTX Desktop'

export function installBrowserElectronShim(): void {
  if (typeof window === 'undefined' || window.electronAPI) return

  const resolved = <T>(value: T) => () => Promise.resolve(value)
  const unsupported = (what: string) => () =>
    Promise.reject(new Error(`${what} is not available in browser mode. Run the full app for this.`))

  // In UI-only mode a fake path keeps the flow going; against a real backend on
  // :8000 the browser genuinely cannot pick files, so those still reject.
  const pretendPath = (path: string) => (UI_MOCK ? Promise.resolve(path) : Promise.resolve(null))
  const pretendWrite = (path: string) =>
    UI_MOCK
      ? Promise.resolve({ success: true, path })
      : Promise.resolve({ success: false, error: 'Not available in browser mode' })

  const shim = {
    getBackend: resolved({ url: BROWSER_BACKEND_URL, token: '' }),
    getModelsPath: resolved(UI_MOCK ? `${MOCK_HOME}/models` : ''),
    readLocalFile: unsupported('Reading a local file'),
    approveLocalPath: resolved(true),
    checkGpu: resolved(
      UI_MOCK
        ? { available: true, name: 'NVIDIA GeForce RTX 4070', vram: 12 }
        : { available: false },
    ),
    getAppInfo: resolved({
      version: UI_MOCK ? 'ui-only' : 'browser-dev',
      isPackaged: false,
      modelsPath: UI_MOCK ? `${MOCK_HOME}/models` : '',
      userDataPath: UI_MOCK ? MOCK_HOME : '',
    }),
    checkFirstRun: resolved({ needsSetup: false, needsLicense: false }),
    acceptLicense: resolved(true),
    completeSetup: resolved(true),
    fetchLicenseText: resolved(
      UI_MOCK ? 'UI-only mode: the licence text is loaded from disk by the packaged app.' : '',
    ),
    getNoticesText: resolved(
      UI_MOCK ? 'UI-only mode: third-party notices are loaded from disk by the packaged app.' : '',
    ),
    openLtxApiKeyPage: resolved(true),
    openFalApiKeyPage: resolved(true),
    openParentFolderOfFile: resolved(undefined),
    showItemInFolder: resolved(undefined),
    getLogs: resolved({
      logPath: UI_MOCK ? `${MOCK_HOME}/logs/app.log` : '',
      lines: UI_MOCK ? ['UI-only mode: logs come from the Electron main process in the real app.'] : [],
    }),
    getLogPath: resolved({
      logPath: UI_MOCK ? `${MOCK_HOME}/logs/app.log` : '',
      logDir: UI_MOCK ? `${MOCK_HOME}/logs` : '',
    }),
    openLogFolder: resolved(true),
    getResourcePath: resolved(null),
    getDownloadsPath: resolved(UI_MOCK ? `${MOCK_HOME}/Downloads` : ''),
    copyToProjectAssets: (srcPath: string) =>
      UI_MOCK
        ? Promise.resolve({
            success: true,
            path: srcPath,
            url: `/api/__ui_mock/file?path=${encodeURIComponent(srcPath)}`,
          })
        : Promise.resolve({ success: false, error: 'Not available in browser mode' }),
    getProjectAssetsPath: resolved(UI_MOCK ? `${MOCK_HOME}/projects` : ''),
    setProjectAssetsPath: () => pretendWrite(`${MOCK_HOME}/projects`),
    showSaveDialog: (options: { defaultPath?: string } = {}) =>
      pretendPath(options.defaultPath || `${MOCK_HOME}/Downloads/export.ltxfilm`),
    saveFile: (filePath: string) => pretendWrite(filePath),
    saveBinaryFile: (filePath: string) => pretendWrite(filePath),
    showOpenDirectoryDialog: () => pretendPath(`${MOCK_HOME}/projects`),
    searchDirectoryForFiles: resolved({}),
    checkFilesExist: resolved({}),
    showOpenFileDialog: () =>
      UI_MOCK ? Promise.resolve([`${MOCK_HOME}/Downloads/example.ltxfilm`]) : Promise.resolve(null),
    exportNative: resolved(
      UI_MOCK
        ? { success: false, error: 'Video export needs ffmpeg from the Electron main process. Run the full app.' }
        : { ok: false, error: 'Not available in browser mode' },
    ),
    exportCancel: resolved({ ok: true }),
    checkPythonReady: resolved({ ready: true }),
    startPythonSetup: resolved(undefined),
    startPythonBackend: resolved(undefined),
    getBackendHealthStatus: resolved({ status: 'alive' as const }),
    onPythonSetupProgress: () => {},
    removePythonSetupProgress: () => {},
    onBackendHealthStatus: () => () => {},
    // Frame extraction is ffmpeg's job in the real app; the mock serves a
    // labelled placeholder so callers get a usable URL instead of an error.
    extractVideoFrame: (_videoUrl: string, seekTime: number) =>
      UI_MOCK
        ? Promise.resolve({
            path: `ui-mock/frames/frame-${Math.round(seekTime * 1000)}.png`,
            url: `/api/__ui_mock/file?path=${encodeURIComponent(`frames/frame-${Math.round(seekTime * 1000)}.png`)}`,
          })
        : Promise.reject(new Error('Not available in browser mode')),
    writeLog: resolved(undefined),
    getAnalyticsState: resolved({ analyticsEnabled: false, installationId: 'browser-dev' }),
    setAnalyticsEnabled: resolved(undefined),
    sendAnalyticsEvent: resolved(undefined),
    platform: 'browser',
  }

  // The preload bridge exposes a superset; the shim covers what the app calls.
  ;(window as unknown as { electronAPI: typeof shim }).electronAPI = shim
}
