import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const iosRoot = fileURLToPath(new URL('../src-capacitor/ios/', import.meta.url))
const localConfig = fileURLToPath(new URL('../src-capacitor/ios/WechatAI.local.xcconfig', import.meta.url))

const secureUrl = (value) => {
  const url = new URL(value)
  if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search || url.hash || url.hostname.endsWith('.invalid')) {
    throw new Error('iOS 生产 API 必须是无凭据、无 query/hash 的绝对 HTTPS 地址，且不能使用 .invalid 占位域名。')
  }
  return url.href.replace(/\/$/, '')
}

const apiUrl = secureUrl(process.env.WECHAT_AI_API_BASE_URL ?? '')
const rendererApiUrl = secureUrl(process.env.VITE_API_BASE_URL_NATIVE ?? '')
if (apiUrl !== rendererApiUrl) throw new Error('WECHAT_AI_API_BASE_URL 必须与 VITE_API_BASE_URL_NATIVE 完全一致。')

const oauthRedirect = secureUrl(process.env.VITE_OAUTH_REDIRECT_URI_NATIVE ?? '')
const oauthUrl = new URL(oauthRedirect)
if (!/^\/official-accounts(?:\/|$)/.test(oauthUrl.pathname)) {
  throw new Error('VITE_OAUTH_REDIRECT_URI_NATIVE 必须使用 /official-accounts 回跳路径。')
}
const oauthHost = process.env.WECHAT_AI_OAUTH_HOST ?? ''
if (!oauthHost || oauthHost !== oauthUrl.hostname || !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(oauthHost)) {
  throw new Error('WECHAT_AI_OAUTH_HOST 必须与正式 HTTPS 回调 URL 的主机名完全一致。')
}

// In xcconfig, a literal // starts a comment. $() expands to an empty value and
// safely preserves the URL's double slash in the final Xcode build setting.
const xcconfigUrl = apiUrl.replace('://', ':/$()/')
writeFileSync(localConfig, `WECHAT_AI_API_BASE_URL = ${xcconfigUrl}\nWECHAT_AI_OAUTH_HOST = ${oauthHost}\n`, { encoding: 'utf8', mode: 0o600 })

if (process.platform === 'darwin') {
  const output = execFileSync('xcodebuild', [
    '-project', `${iosRoot}App/App.xcodeproj`,
    '-scheme', 'App',
    '-configuration', 'Release',
    '-showBuildSettings',
  ], { encoding: 'utf8' })
  const setting = (name) => output.match(new RegExp(`^\\s*${name} = (.+)$`, 'm'))?.[1]?.trim()
  if (setting('WECHAT_AI_API_BASE_URL') !== apiUrl || setting('WECHAT_AI_OAUTH_HOST') !== oauthHost) {
    throw new Error('Xcode 最终 NativeAuth/API 或 Universal Link Build Setting 与构建输入不一致。')
  }
}
