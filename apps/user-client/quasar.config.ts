import { defineConfig } from '@quasar/app-vite'

const normalizedUrl = (value = '') => value.replace(/\/$/, '')
const secureApiUrl = (value = '') => {
  try {
    const url = new URL(value)
    if (
      url.protocol !== 'https:' ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.hostname.endsWith('.invalid')
    )
      return ''
    return normalizedUrl(url.href)
  } catch {
    return ''
  }
}
const secureOAuthCallback = (value = '') => {
  const url = secureApiUrl(value)
  if (!url) return null
  const parsed = new URL(url)
  return /^\/official-accounts(?:\/|$)/.test(parsed.pathname) ? parsed : null
}
const clientEnvValue = (env: Record<string, string>, key: string) => {
  const encoded = env[`import.meta.env.${key}`]
  if (encoded === undefined) return process.env[key]
  try {
    const decoded = JSON.parse(encoded) as unknown
    return typeof decoded === 'string' ? decoded : String(decoded)
  } catch {
    return encoded
  }
}

export default defineConfig((ctx) => {
  const requestedApiMode = process.env.VITE_API_MODE
  if (requestedApiMode && requestedApiMode !== 'mock' && requestedApiMode !== 'remote')
    throw new Error('VITE_API_MODE 只能是 mock 或 remote。')
  if (!ctx.dev && requestedApiMode === 'mock' && process.env.VITE_ALLOW_MOCK_BUILD !== 'true') {
    throw new Error(
      '生产构建默认禁止 Mock API；仅独立演示包可显式设置 VITE_ALLOW_MOCK_BUILD=true。',
    )
  }
  return {
    boot: ['pinia', 'query', 'theme'],
    css: ['app.scss'],
    extras: ['material-icons'],
    build: {
      env: {
        clientPrefix: 'VITE_',
        filter: (env, type) => {
          if (type !== 'client') return env
          const mode = clientEnvValue(env, 'VITE_API_MODE') ?? (ctx.dev ? 'mock' : 'remote')
          if (mode !== 'mock' && mode !== 'remote')
            throw new Error('VITE_API_MODE 只能是 mock 或 remote。')
          if (
            !ctx.dev &&
            mode === 'mock' &&
            clientEnvValue(env, 'VITE_ALLOW_MOCK_BUILD') !== 'true'
          ) {
            throw new Error(
              '生产构建默认禁止 Mock API；仅独立演示包可显式设置 VITE_ALLOW_MOCK_BUILD=true。',
            )
          }
          if (!ctx.dev && ctx.modeName === 'capacitor') {
            const rendererApi = secureApiUrl(clientEnvValue(env, 'VITE_API_BASE_URL_NATIVE'))
            const nativeAuthApi = secureApiUrl(process.env.WECHAT_AI_API_BASE_URL)
            const oauthCallback = secureOAuthCallback(
              clientEnvValue(env, 'VITE_OAUTH_REDIRECT_URI_NATIVE'),
            )
            const oauthHost = process.env.WECHAT_AI_OAUTH_HOST
            if (!rendererApi || !nativeAuthApi || rendererApi !== nativeAuthApi) {
              throw new Error(
                'Capacitor 生产构建要求 VITE_API_BASE_URL_NATIVE 与 WECHAT_AI_API_BASE_URL 是同一个正式 HTTPS API 地址。',
              )
            }
            if (!oauthCallback || !oauthHost || oauthHost !== oauthCallback.hostname) {
              throw new Error(
                'Capacitor 生产构建要求正式 HTTPS 授权回调，且 WECHAT_AI_OAUTH_HOST 必须与其主机名完全一致。',
              )
            }
          }
          if (
            !ctx.dev &&
            ctx.modeName === 'electron' &&
            !secureApiUrl(clientEnvValue(env, 'VITE_API_BASE_URL_ELECTRON'))
          ) {
            throw new Error(
              'Electron 生产构建要求 VITE_API_BASE_URL_ELECTRON 是绝对 HTTPS API 地址。',
            )
          }
          return { ...env, 'import.meta.env.VITE_API_MODE': JSON.stringify(mode) }
        },
      },
      target: {
        browser: ['es2022', 'firefox115', 'chrome115', 'safari14'],
        node: 'node22',
      },
      vueRouterMode:
        ctx.modeName === 'electron' || ctx.modeName === 'capacitor' ? 'hash' : 'history',
    },
    devServer: {
      host: '0.0.0.0',
      allowedHosts: ['.cpolar.cn'],
      port: Number(process.env.PORT || 9003),
      strictPort: true,
      open: false,
      proxy: {
        '/api/': {
          target: process.env.DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        },
      },
    },
    framework: {
      config: {
        brand: {
          primary: '#047a3a',
          secondary: '#176b49',
          accent: '#2677ff',
          dark: '#161b22',
          positive: '#047a3a',
          negative: '#d94848',
          warning: '#ee8b21',
          info: '#2677ff',
        },
      },
      plugins: ['Dialog', 'Notify', 'Loading'],
    },
    animations: [],
    pwa: {
      workboxMode: 'GenerateSW',
      injectPwaMetaTags: true,
      swFilename: 'sw.js',
      manifestFilename: 'manifest.json',
    },
    electron: {
      inspectPort: 5858,
      bundler: 'builder',
      packager: {
        appId: 'com.wechat.ai.operations',
        productName: '微信公众号 AI 运营助手',
      },
      builder: {
        appId: 'com.wechat.ai.operations',
        productName: '微信公众号 AI 运营助手',
        win: { target: 'nsis', icon: 'icons/icon.ico' },
      },
    },
    capacitor: {
      hideSplashscreen: true,
      ...(ctx.modeName === 'capacitor' && 'targetName' in ctx && ctx.targetName === 'ios'
        ? { capacitorCliPreparationParams: ['copy', 'ios'] }
        : {}),
    },
  }
})
