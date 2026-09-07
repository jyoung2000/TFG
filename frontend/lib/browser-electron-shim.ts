/**
 * Dev-only fallback for running the renderer in a plain browser (no Electron
 * preload). Provides just enough of `window.electronAPI` for the app to boot
 * against a locally running backend on port 8000 — used for browser-based
 * development and automated UI verification. No-ops when the real preload
 * bridge is present.
 */

const BROWSER_BACKEND_URL = 'http://localhost:8000'

export function installBrowserElectronShim(): void {
  if (typeof window === 'undefined' || window.electronAPI) return

  const resolved = <T>(value: T) => () => Promise.resolve(value)

  const shim = {
    getBackend: resolved({ url: BROWSER_BACKEND_URL, token: '' }),
    getModelsPath: resolved(''),
    readLocalFile: () => Promise.reject(new Error('Not available in browser mode')),
    approveLocalPath: resolved(true),
    checkGpu: resolved({ available: false }),
    getAppInfo: resolved({
      version: 'browser-dev',
      isPackaged: false,
      modelsPath: '',
      userDataPath: '',
    }),
    checkFirstRun: resolved({ needsSetup: false, needsLicense: false }),
    acceptLicense: resolved(true),
    completeSetup: resolved(true),
    fetchLicenseText: resolved(''),
    getNoticesText: resolved(''),
    openLtxApiKeyPage: resolved(true),
    openFalApiKeyPage: resolved(true),
    openParentFolderOfFile: resolved(undefined),
    showItemInFolder: resolved(undefined),
    getLogs: resolved({ logPath: '', lines: [] }),
    getLogPath: resolved({ logPath: '', logDir: '' }),
    openLogFolder: resolved(true),
    getResourcePath: resolved(null),
    getDownloadsPath: resolved(''),
    copyToProjectAssets: resolved({ success: false, error: 'Not available in browser mode' }),
    getProjectAssetsPath: resolved(''),
    setProjectAssetsPath: resolved({ success: false, error: 'Not available in browser mode' }),
    showSaveDialog: resolved(null),
    saveFile: resolved({ success: false, error: 'Not available in browser mode' }),
    saveBinaryFile: resolved({ success: false, error: 'Not available in browser mode' }),
    showOpenDirectoryDialog: resolved(null),
    searchDirectoryForFiles: resolved({}),
    checkFilesExist: resolved({}),
    showOpenFileDialog: resolved(null),
    exportNative: resolved({ ok: false, error: 'Not available in browser mode' }),
    exportCancel: resolved({ ok: false }),
    checkPythonReady: resolved({ ready: true }),
    startPythonSetup: resolved(undefined),
    startPythonBackend: resolved(undefined),
    getBackendHealthStatus: resolved({ status: 'alive' as const }),
    onPythonSetupProgress: () => {},
    removePythonSetupProgress: () => {},
    onBackendHealthStatus: () => {},
    extractVideoFrame: () => Promise.reject(new Error('Not available in browser mode')),
    writeLog: resolved(undefined),
    getAnalyticsState: resolved({ analyticsEnabled: false, installationId: 'browser-dev' }),
    setAnalyticsEnabled: resolved(undefined),
    sendAnalyticsEvent: resolved(undefined),
    platform: 'browser',
  }

  // The preload bridge exposes a superset; the shim covers what the app calls.
  ;(window as unknown as { electronAPI: typeof shim }).electronAPI = shim
}
