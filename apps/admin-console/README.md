# 微信公众号 AI 运营助手 · 管理控制台

独立的 Vue 3 + TypeScript + Element Plus 管理 Web。实现模型与路由、提示词、官方技能、用户与额度、微信平台、公众号连接、任务对账、系统设置、管理员账号和审计日志等管理能力。

## 本地运行

要求 Node.js `>=22.22.0`、pnpm `>=11`。

```bash
pnpm install --frozen-lockfile
pnpm dev
```

开发服务器监听 `0.0.0.0:9004`。复制 `.env.example` 可调整后台地址：

```dotenv
VITE_ADMIN_API_BASE=/admin-api/v1
```

管理端只连接真实后台接口和数据库，不提供浏览器内置演示数据。`src/api/client.ts` 提供带 Cookie、CSRF、幂等键和结构化错误的 API 客户端，浏览器不会保存平台密钥或模型密钥明文。

## 页面

| 路径               | 能力                                                   |
| ------------------ | ------------------------------------------------------ |
| `/`                | 运行总览、AI 成功率、公众号连接、失败任务和最近发布    |
| `/ai/config`       | 模型供应商、部署与逻辑路由，测试、发布、停用与降级顺序 |
| `/ai/prompts`      | 提示词版本、样例测试、发布和历史版本恢复               |
| `/skills`          | 官方技能、新版本、测试、排序、发布、停用与恢复         |
| `/users`           | 用户状态、额度、能力开关和受控诊断入口                 |
| `/wechat/platform` | 开放平台配置、掩码密钥、连通性测试和发布               |
| `/wechat/accounts` | 公众号连接、Token/权限状态与重新授权                   |
| `/tasks`           | 失败任务、冻结快照重试、UNKNOWN 结果强制对账和取消     |
| `/settings`        | 全局业务设置的草稿、测试和发布                         |
| `/settings/admins` | 管理员、角色、状态和会话撤销                           |
| `/settings/audit`  | 只读审计查询与导出                                     |

配置对象遵循 `draft → testing → published → disabled` 生命周期。发布只影响发布后的新任务；运行中任务继续使用冻结快照。微信结果为 `UNKNOWN` 时不能直接重试，必须先通过外部业务 ID 对账。管理端默认不展示用户文章正文、完整对话或原始文件内容。

## 质量门禁

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

Playwright 会启动迁移后的隔离数据库和真实 FastAPI 服务，通过真实管理员登录覆盖全部管理页面，并在 `1024 / 1280 / 1440` 三档桌面视口检查接口错误、浏览器运行时错误和根节点水平溢出。测试中的模型与微信外部供应商仍使用后端测试适配器，不会消耗真实供应商额度。

## 容器

```bash
docker build --target development -t wechat-ai-admin-dev .
docker build --target production -t wechat-ai-admin .
```

`development` target 在 `9000` 端口运行 Vite；`production` target 由 Nginx 提供 SPA 回退、`/healthz` 健康检查并把 `/admin-api/` 转发给 Compose 中的 `backend-api:8000`。
