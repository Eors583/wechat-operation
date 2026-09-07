# 微信公众号 AI 运营助手用户端

Vue 3 + TypeScript + Quasar CLI/Vite 用户端，默认连接后端 API 与开发数据库，覆盖 Web/PWA、Electron 与 Capacitor 的平台边界。

## 本地开发

```bash
pnpm install
pnpm dev
pnpm verify
pnpm test:e2e
```

开发服务固定监听 `0.0.0.0:9000`。本地开发请先启动 `services/platform-backend`，用户、项目、任务和文章数据均来自后端数据库；数据库为空时页面应展示空状态。

复制 `.env.example` 为 `.env` 后可调整 `VITE_API_BASE_URL` 指向的后端（Web 默认 `/api/v1`）。用户端运行时只连接真实后端接口，不提供本地 Mock 数据模式。Electron 与 Capacitor 生产包必须分别配置 `VITE_API_BASE_URL_ELECTRON`、`VITE_API_BASE_URL_NATIVE` 为绝对 HTTPS 地址，不能带账号密码、query/hash，不能指向设备 `localhost` 或 `.invalid` 占位域名。原生认证通道不信任 WebView 传入的目标地址：Capacitor 生产构建必须在构建进程/CI 环境中同时把 `VITE_API_BASE_URL_NATIVE` 与 `WECHAT_AI_API_BASE_URL` 设为完全相同的 HTTPS API 地址，预检不一致会直接终止。Android 会把后者写入签名包；iOS 的 `prepare:ios-config` 会生成未纳入版本控制的 `WechatAI.local.xcconfig`，并在 macOS 上通过 `xcodebuild -showBuildSettings` 校验最终值，不再依赖手工修改 Xcode 工程。公众号授权回调也必须使用后台与微信共同登记的精确 HTTPS 地址；移动端的 `VITE_OAUTH_REDIRECT_URI_NATIVE` 同时配置为 Universal Link/App Link，并在构建进程中设置 `WECHAT_AI_OAUTH_HOST`（未设置时 iOS 预检从该回调 URL 提取）。Android 也可通过 `-PoauthRedirectHost=app.example.com` 写入同一主机名。域名还必须发布 Android `/.well-known/assetlinks.json` 和 Apple `/.well-known/apple-app-site-association`，并填入正式签名证书/Team ID，否则操作系统不会把 HTTPS 回调交给应用。仓库中的 `app.example.invalid` 与 `api.example.invalid` 只是不接管真实域名的安全占位值，发布门禁会拒绝它们。

原生刷新令牌不写 Web Storage：Electron 通过主进程 `safeStorage` 加密后写入应用数据目录，iOS/Android 通过系统 Keychain/Keystore 插件保存。Web 端继续使用 HttpOnly 刷新 Cookie 与 CSRF Cookie。

## 多端构建

```bash
pnpm build
pnpm build:pwa
pnpm build:electron
pnpm build:capacitor:android
pnpm build:capacitor:ios
```

Capacitor 原生工程已包含安全存储和 HTTPS App/Universal Link 回跳；正式发布仍需产品自己的域名关联文件、应用签名和 Apple Team ID。移动端刻意使用 WebView 标准 `fetch` 以保留 Android/iOS 的 SSE 流式增量，不要开启会在 iOS 端整包缓冲响应的 Capacitor 全局 HTTP patch。后端 CORS 允许列表除 Web 与 Electron 域名外，还必须包含 Android 的 `https://localhost` 和 iOS 的 `capacitor://localhost`。Electron 的主进程保持 `nodeIntegration: false`、`contextIsolation: true` 和沙箱开启，只通过 preload 暴露文件选择、外链打开、版本查询及刷新令牌安全存储这组窄接口；生产包加载本地构建产物，不依赖开发服务器。

## 容器

```bash
docker build --target development -t wechat-ai-user-client:dev .
docker run --rm -p 9000:9000 wechat-ai-user-client:dev
docker build --target production -t wechat-ai-user-client .
```

生产镜像由 Nginx 托管 SPA，并将历史路由回退到 `index.html`。健康检查端点为 `/healthz`。
