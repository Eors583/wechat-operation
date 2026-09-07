import type { PlatformAdapter } from './types'
import { chooseFiles, downloadFile } from './web'

export const electronPlatform: PlatformAdapter = {
  platform: 'electron',
  native: true,
  async openExternal(url) {
    await window.desktopBridge?.openExternal(url)
  },
  pickFiles: chooseFiles,
  downloadFile,
  async share(_title, text, url) {
    await navigator.clipboard.writeText([text, url].filter(Boolean).join('\n'))
  },
  async getAppVersion() {
    return window.desktopBridge?.getVersion() ?? 'electron'
  },
  async loginSession(input) {
    if (!window.desktopBridge) throw new Error('桌面认证通道不可用。')
    return window.desktopBridge.loginSession(input)
  },
  async loginCodeSession(input) {
    if (!window.desktopBridge) throw new Error('桌面认证通道不可用。')
    return window.desktopBridge.loginCodeSession(input)
  },
  async refreshSession() {
    if (!window.desktopBridge) throw new Error('桌面认证通道不可用。')
    return window.desktopBridge.refreshSession()
  },
  async logoutSession(accessToken) {
    if (!window.desktopBridge) throw new Error('桌面认证通道不可用。')
    return window.desktopBridge.logoutSession(accessToken)
  },
  async clearRefreshToken() {
    await window.desktopBridge?.clearRefreshToken()
  },
  oauthRedirectUri() {
    const redirect = import.meta.env.VITE_OAUTH_REDIRECT_URI_ELECTRON
    if (!redirect || !/^https:\/\//.test(redirect))
      throw new Error('桌面端尚未配置 HTTPS 公众号授权回调地址。')
    return redirect
  },
  async onOAuthCallback() {
    return () => undefined
  },
}
