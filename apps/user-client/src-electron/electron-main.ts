import { app, BrowserWindow, dialog, ipcMain, net, protocol, safeStorage, shell } from 'electron'
import type { IpcMainInvokeEvent } from 'electron'
import { promises as fs } from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { registerQuasarRuntime } from '#q-app/electron/main'

let mainWindow: BrowserWindow | null = null
const rendererOrigin = 'https://app.wechat-ai.local'
const rendererCsp = "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob: https:; connect-src 'self' https:; worker-src 'self' blob:; frame-src 'self' blob:; manifest-src 'self'; upgrade-insecure-requests"
const secretPath = () => path.join(app.getPath('userData'), 'refresh-token.bin')
const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL_ELECTRON || import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const assertSecureStorage = () => {
  if (!safeStorage.isEncryptionAvailable()) throw new Error('OS credential encryption is unavailable')
}

const readRefreshToken = async () => {
  assertSecureStorage()
  try {
    return safeStorage.decryptString(await fs.readFile(secretPath()))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

const storeRefreshToken = async (value: string) => {
  assertSecureStorage()
  if (!value || value.length > 8192) throw new Error('Invalid refresh token')
  await fs.writeFile(secretPath(), safeStorage.encryptString(value), { mode: 0o600 })
}

const clearRefreshToken = () => fs.rm(secretPath(), { force: true })

const authEndpoint = (pathName: string) => {
  if (!configuredApiBaseUrl) throw new Error('VITE_API_BASE_URL_ELECTRON is required for desktop authentication')
  const url = new URL(`${configuredApiBaseUrl}${pathName}`)
  if (url.protocol !== 'https:' && !import.meta.env.QUASAR_DEV) throw new Error('Desktop production authentication requires HTTPS')
  return url.toString()
}

const nativeAuthRequest = async (
  pathName: '/auth/login' | '/auth/login-code' | '/auth/refresh' | '/auth/logout',
  requestBody: Record<string, unknown> = {},
  accessToken?: string,
) => {
  if (pathName === '/auth/refresh' || pathName === '/auth/logout') {
    const refreshToken = await readRefreshToken()
    if (!refreshToken) return { status: 401, payload: { code: 'REFRESH_TOKEN_REQUIRED', message: '登录凭据已失效，请重新登录。' } }
    requestBody.refresh_token = refreshToken
  }
  const headers = new Headers({ Accept: 'application/json', 'Content-Type': 'application/json' })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await net.fetch(authEndpoint(pathName), {
    method: 'POST',
    headers,
    body: JSON.stringify(requestBody),
    redirect: 'error',
  })
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>
  if (response.ok && (pathName === '/auth/login' || pathName === '/auth/login-code' || pathName === '/auth/refresh')) {
    const rotated = typeof payload.refresh_token === 'string' ? payload.refresh_token : ''
    if (!rotated) throw new Error('Refresh response did not rotate the native credential')
    await storeRefreshToken(rotated)
    delete payload.refresh_token
  }
  return { status: response.status, payload }
}

const isSafeExternalUrl = (url: string) => {
  try { return new URL(url).protocol === 'https:' } catch { return false }
}

const expectedRendererOrigin = () => import.meta.env.QUASAR_DEV
  ? new URL(import.meta.env.QUASAR_APP_URL).origin
  : rendererOrigin

const assertTrustedSender = (event: IpcMainInvokeEvent) => {
  const senderUrl = event.senderFrame?.url || event.sender.getURL()
  try {
    if (new URL(senderUrl).origin === expectedRendererOrigin()) return
  } catch {
    // Reject malformed and origin-less renderer URLs.
  }
  throw new Error('IPC request rejected for an untrusted renderer')
}

const rendererResponse = async (request: Request) => {
  const url = new URL(request.url)
  if (url.origin !== rendererOrigin) return net.fetch(request, { bypassCustomProtocolHandlers: true })
  if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 })

  let requestedPath: string
  try { requestedPath = decodeURIComponent(url.pathname).replace(/^\/+/, '') } catch { return new Response('Bad request', { status: 400 }) }
  const relativePath = requestedPath && path.extname(requestedPath) ? requestedPath : 'index.html'
  const absolutePath = path.resolve(__dirname, relativePath)
  const relativeToRenderer = path.relative(__dirname, absolutePath)
  if (relativeToRenderer.startsWith('..') || path.isAbsolute(relativeToRenderer)) return new Response('Not found', { status: 404 })
  const response = await net.fetch(pathToFileURL(absolutePath).toString(), { method: request.method })
  const headers = new Headers(response.headers)
  headers.set('Content-Security-Policy', rendererCsp)
  headers.set('X-Content-Type-Options', 'nosniff')
  headers.set('Referrer-Policy', 'no-referrer')
  headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
}

const createWindow = async () => {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    show: false,
    webPreferences: {
      preload: path.resolve(__dirname, 'electron-preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  })
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    let targetOrigin = ''
    try { targetOrigin = new URL(url).origin } catch { /* Block malformed navigation below. */ }
    if (targetOrigin === expectedRendererOrigin()) return
    event.preventDefault()
    if (isSafeExternalUrl(url)) void shell.openExternal(url)
  })
  mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))

  if (import.meta.env.QUASAR_DEV) await mainWindow.loadURL(import.meta.env.QUASAR_APP_URL)
  else await mainWindow.loadURL(`${rendererOrigin}/`)
}

void app.whenReady().then(() => {
  registerQuasarRuntime()
  protocol.handle('https', rendererResponse)
  ipcMain.handle('app:open-external', (event, url: string) => {
    assertTrustedSender(event)
    return isSafeExternalUrl(url) ? shell.openExternal(url) : undefined
  })
  ipcMain.handle('app:select-files', async (event) => {
    assertTrustedSender(event)
    return (await dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'] })).filePaths
  })
  ipcMain.handle('app:get-version', (event) => {
    assertTrustedSender(event)
    return app.getVersion()
  })
  ipcMain.handle('auth:login-session', async (event, input: { identifier?: unknown; password?: unknown; deviceName?: unknown }) => {
    assertTrustedSender(event)
    if (typeof input?.identifier !== 'string' || typeof input.password !== 'string' || typeof input.deviceName !== 'string') throw new Error('Invalid desktop login request')
    return nativeAuthRequest('/auth/login', {
      identifier: input.identifier,
      password: input.password,
      platform: 'windows',
      device_name: input.deviceName.slice(0, 120),
    })
  })
  ipcMain.handle('auth:login-code-session', async (event, input: { identifier?: unknown; verificationToken?: unknown; deviceName?: unknown }) => {
    assertTrustedSender(event)
    if (typeof input?.identifier !== 'string' || typeof input.verificationToken !== 'string' || typeof input.deviceName !== 'string') throw new Error('Invalid desktop code-login request')
    return nativeAuthRequest('/auth/login-code', {
      identifier: input.identifier,
      verification_token: input.verificationToken,
      platform: 'windows',
      device_name: input.deviceName.slice(0, 120),
    })
  })
  ipcMain.handle('auth:refresh-session', async (event) => {
    assertTrustedSender(event)
    return nativeAuthRequest('/auth/refresh')
  })
  ipcMain.handle('auth:logout-session', async (event, accessToken?: string) => {
    assertTrustedSender(event)
    let result = await nativeAuthRequest('/auth/logout', {}, accessToken)
    if (result.status === 401) {
      const refreshed = await nativeAuthRequest('/auth/refresh')
      const freshAccessToken = typeof refreshed.payload.access_token === 'string' ? refreshed.payload.access_token : ''
      if (refreshed.status >= 200 && refreshed.status < 300 && freshAccessToken) {
        result = await nativeAuthRequest('/auth/logout', {}, freshAccessToken)
      } else {
        result = refreshed
      }
    }
    return result
  })
  ipcMain.handle('auth:clear-refresh-token', async (event) => {
    assertTrustedSender(event)
    await clearRefreshToken()
  })
  void createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow()
  })
})

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
