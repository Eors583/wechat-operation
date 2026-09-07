export type AppPlatform = 'web' | 'pwa' | 'electron' | 'ios' | 'android'

export interface NativeAuthResponse {
  status: number
  payload: Record<string, unknown>
}

export interface PlatformAdapter {
  readonly platform: AppPlatform
  readonly native: boolean
  openExternal(url: string): Promise<void>
  pickFiles(accept?: string): Promise<File[]>
  downloadFile(file: File): Promise<void>
  share(title: string, text: string, url?: string): Promise<void>
  getAppVersion(): Promise<string>
  loginSession(input: {
    identifier: string
    password: string
    deviceName: string
  }): Promise<NativeAuthResponse>
  loginCodeSession(input: {
    identifier: string
    verificationToken: string
    deviceName: string
  }): Promise<NativeAuthResponse>
  refreshSession(): Promise<NativeAuthResponse>
  logoutSession(accessToken?: string): Promise<NativeAuthResponse>
  clearRefreshToken(): Promise<void>
  oauthRedirectUri(path: string): string
  onOAuthCallback(listener: (url: string) => void): Promise<() => void>
}
