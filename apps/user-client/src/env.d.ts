/// <reference types="vite/client" />

declare interface Window {
  desktopBridge?: {
    openExternal: (url: string) => Promise<void>
    selectFiles: () => Promise<string[]>
    getVersion: () => Promise<string>
    loginSession: (input: {
      identifier: string
      password: string
      deviceName: string
    }) => Promise<{ status: number; payload: Record<string, unknown> }>
    loginCodeSession: (input: {
      identifier: string
      verificationToken: string
      deviceName: string
    }) => Promise<{ status: number; payload: Record<string, unknown> }>
    refreshSession: () => Promise<{ status: number; payload: Record<string, unknown> }>
    logoutSession: (
      accessToken?: string,
    ) => Promise<{ status: number; payload: Record<string, unknown> }>
    clearRefreshToken: () => Promise<void>
  }
}
