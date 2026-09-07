import type { PlatformAdapter } from './types'

export async function downloadFile(file: File): Promise<void> {
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = file.name
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

const chooseFiles = (accept = '*/*') =>
  new Promise<File[]>((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.accept = accept
    input.onchange = () => resolve(Array.from(input.files ?? []))
    input.click()
  })

export const webPlatform: PlatformAdapter = {
  platform: window.matchMedia('(display-mode: standalone)').matches ? 'pwa' : 'web',
  native: false,
  async openExternal(url) {
    window.open(url, '_blank', 'noopener,noreferrer')
  },
  pickFiles: chooseFiles,
  downloadFile,
  async share(title, text, url) {
    if (navigator.share) await navigator.share({ title, text, url })
    else await navigator.clipboard.writeText([title, text, url].filter(Boolean).join('\n'))
  },
  async getAppVersion() {
    return import.meta.env.VITE_APP_VERSION ?? 'web'
  },
  async loginSession() {
    throw new Error('浏览器端应使用 Cookie 认证流程。')
  },
  async loginCodeSession() {
    throw new Error('浏览器端应使用 Cookie 认证流程。')
  },
  async refreshSession() {
    throw new Error('浏览器端应使用 HttpOnly 会话 Cookie。')
  },
  async logoutSession() {
    throw new Error('浏览器端应使用 HttpOnly 会话 Cookie。')
  },
  async clearRefreshToken() {
    /* Web refresh state is server-managed. */
  },
  oauthRedirectUri(path) {
    return (
      import.meta.env.VITE_OAUTH_REDIRECT_URI_WEB ||
      new URL(path, window.location.origin).toString()
    )
  },
  async onOAuthCallback() {
    return () => undefined
  },
}

export { chooseFiles }
