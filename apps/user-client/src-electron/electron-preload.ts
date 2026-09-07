import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('desktopBridge', {
  openExternal: (url: string) => ipcRenderer.invoke('app:open-external', url),
  selectFiles: () => ipcRenderer.invoke('app:select-files'),
  getVersion: () => ipcRenderer.invoke('app:get-version'),
  loginSession: (input: { identifier: string; password: string; deviceName: string }) => ipcRenderer.invoke('auth:login-session', input),
  loginCodeSession: (input: { identifier: string; verificationToken: string; deviceName: string }) => ipcRenderer.invoke('auth:login-code-session', input),
  refreshSession: () => ipcRenderer.invoke('auth:refresh-session'),
  logoutSession: (accessToken?: string) => ipcRenderer.invoke('auth:logout-session', accessToken),
  clearRefreshToken: () => ipcRenderer.invoke('auth:clear-refresh-token'),
})
