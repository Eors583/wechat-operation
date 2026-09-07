import { Capacitor, registerPlugin } from '@capacitor/core'
import { App } from '@capacitor/app'
import { Browser } from '@capacitor/browser'
import type { NativeAuthResponse, PlatformAdapter } from './types'
import { chooseFiles } from './web'

interface NativeAuthPlugin {
  loginSession(options: {
    identifier: string
    password: string
    deviceName: string
  }): Promise<NativeAuthResponse>
  loginCodeSession(options: {
    identifier: string
    verificationToken: string
    deviceName: string
  }): Promise<NativeAuthResponse>
  refreshSession(): Promise<NativeAuthResponse>
  logoutSession(options: { accessToken?: string }): Promise<NativeAuthResponse>
  clearRefreshToken(): Promise<void>
}

const NativeAuth = registerPlugin<NativeAuthPlugin>('NativeAuth')

export const capacitorPlatform: PlatformAdapter = {
  platform: Capacitor.getPlatform() === 'ios' ? 'ios' : 'android',
  native: true,
  async openExternal(url) {
    await Browser.open({ url })
  },
  pickFiles: chooseFiles,
  async downloadFile(file) {
    if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file] })
    else throw new Error('当前设备不支持文件保存，请在电脑浏览器下载。')
  },
  async share(title, text, url) {
    if (navigator.share) await navigator.share({ title, text, url })
    else await navigator.clipboard.writeText([title, text, url].filter(Boolean).join('\n'))
  },
  async getAppVersion() {
    return import.meta.env.VITE_APP_VERSION ?? 'mobile'
  },
  async loginSession(input) {
    return NativeAuth.loginSession(input)
  },
  async loginCodeSession(input) {
    return NativeAuth.loginCodeSession(input)
  },
  async refreshSession() {
    return NativeAuth.refreshSession()
  },
  async logoutSession(accessToken) {
    return NativeAuth.logoutSession({ accessToken })
  },
  async clearRefreshToken() {
    await NativeAuth.clearRefreshToken()
  },
  oauthRedirectUri() {
    const redirect = import.meta.env.VITE_OAUTH_REDIRECT_URI_NATIVE
    if (!redirect || !/^https:\/\//.test(redirect))
      throw new Error('移动端尚未配置 HTTPS Universal Link 授权回调地址。')
    return redirect
  },
  async onOAuthCallback(listener) {
    const handle = await App.addListener('appUrlOpen', ({ url }) => {
      void Browser.close().catch(() => undefined)
      listener(url)
    })
    return () => {
      void handle.remove()
    }
  },
}
