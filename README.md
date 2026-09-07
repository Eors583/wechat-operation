# 微信公众号 AI 运营助手

本仓库是微信公众号 AI 运营助手的项目集仓库，包含产品与技术文档、部署编排、接口契约、跨项目验收，以及三个独立子项目：

- `apps/user-client`：Vue 3 + Quasar 用户端，面向 Web/PWA、Windows、iOS 与 Android。
- `apps/admin-console`：Vue 3 + Quasar 管理 Web。
- `services/platform-backend`：FastAPI 模块化单体、Celery Worker 与 Scheduler。

业务实现以 `docs/微信公众号AI运营助手_完整技术设计文档_v3.0.md` 为最高技术基线。用户端 PDF、管理端需求与 PNG 原型用于补充交互和视觉细节；旧材料与 V3.0 冲突时以 V3.0 为准。

## 本地启动

前置依赖：Git、Docker Desktop、Node.js 24+、pnpm 11+、Python 3.12+ 与 uv。

```powershell
Copy-Item .env.example .env
node scripts/bootstrap.mjs
docker compose -f deploy/compose/compose.dev.yml up --build
```

默认入口：

- 用户端：`http://localhost:9000/`
- 管理端：`http://localhost:9000/admin/`
- 用户 API 文档：`http://localhost:9000/api/docs`
- 管理 API 文档：`http://localhost:9000/admin-api/docs`
- RabbitMQ：`http://localhost:15672/`
- MinIO：`http://localhost:9001/`
- Grafana（启用 `monitoring` profile）：`http://localhost:3000/`

单独运行两个前端的 `pnpm dev` 时，用户端固定为 `9003`、管理端固定为 `9004`；后端固定为 `8000`。Web 接口分别使用同源路径 `/api/v1` 和 `/admin-api/v1`，开发服务器自动代理到 `http://127.0.0.1:8000`，不要在前端 `.env.local` 写入旧端口 `9010`。Docker 内部代理通过服务名 `backend-api:8000` 连接；网关与穿透访问继续使用 `9000`。如确需更换代理目标，在启动开发服务器的进程环境中设置 `DEV_API_PROXY_TARGET`，无需修改浏览器端接口地址。修改 `.env.local` 后刷新页面；若开发服务器未自动重载，重启对应前端。

开发、预发布和生产业务服务均强制使用 PostgreSQL，检索使用独立 PostgreSQL+pgvector；禁止 SQLite 自动回退。旧 `.db` 文件只作为离线恢复材料保留，不再连接运行服务。只有显式 `APP_ENV=test` 的隔离单元测试可使用临时 SQLite。不要为了启动方便给真实业务服务设置 `APP_ENV=test`。

启动后端、网关和两个独立前端后，运行 `node scripts/check-dev-api.mjs` 检查上述入口是否都能到达后端。该检查发送空登录参数，预期返回后端的 422 校验响应，不需要账号密码，也不会登录或修改账号。

本地与生产环境使用同一套真实服务适配器。未填写模型、短信、对象存储、文档处理、内容安全或微信凭据时，相应操作会明确失败，不会生成替代结果。

## 本地开发微信第三方平台扫码授权

本地联调时，把公网 HTTPS 穿透到开发网关 `http://127.0.0.1:9000`，不要只穿透后端 `8000` 端口；这样同一个公网域名能同时访问授权发起页、API、回调和域名校验文件。ngrok、cpolar、frp 或花生壳均可，推荐使用不会随重启变化的固定域名。

项目根目录的本机 `.env` 已预留以下配置；在新环境中如果该文件不存在，可先复制 `.env.example`。只填写 `WECHAT_PUBLIC_BASE_URL` 时，两个回调地址会自动派生；如需不同地址，再显式填写 `WECHAT_AUTHORIZATION_CALLBACK_URL` 和 `WECHAT_TICKET_CALLBACK_URL` 覆盖：

```dotenv
WECHAT_PROVIDER_MODE=direct
WECHAT_COMPONENT_APP_ID=你的第三方平台AppID
WECHAT_COMPONENT_APP_SECRET=你的第三方平台AppSecret
WECHAT_MESSAGE_TOKEN=开放平台后台填写的消息校验Token
WECHAT_ENCODING_AES_KEY=开放平台后台生成的43位EncodingAESKey
WECHAT_PUBLIC_BASE_URL=https://你的固定穿透域名
WECHAT_AUTHORIZATION_CALLBACK_URL=
WECHAT_TICKET_CALLBACK_URL=

# 开放平台要求校验业务域名时，填写下载文件的文件名和文件正文；不需要时保持为空。
WECHAT_DOMAIN_VERIFICATION_FILENAME=MP_verify_xxxxxxxxxxxxxxxx.txt
WECHAT_DOMAIN_VERIFICATION_CONTENT=xxxxxxxxxxxxxxxx
```

随后执行：

```powershell
uv --directory services/platform-backend run alembic upgrade head
docker compose -f deploy/compose/compose.dev.yml up --build
```

在微信开放平台第三方平台的开发配置中：

1. “授权事件接收 URL”填写 `https://你的穿透域名/callbacks/v1/wechat/tickets`，Token 和 EncodingAESKey 必须与 `.env` 完全一致。
2. “消息与事件接收 URL”填写 `https://你的穿透域名/callbacks/v1/wechat/messages/$APPID$`，其中 `$APPID$` 必须原样保留给微信替换。
3. “登录授权的发起页域名”填写穿透域名的主机名，不带 `https://`、路径和末尾斜杠。
4. 在“授权测试公众号列表”添加测试公众号的原始 ID；全网发布前只有列表内账号能授权。
5. 如果要求上传校验文件，确认浏览器访问 `https://你的穿透域名/MP_verify_xxx.txt` 能原样看到文件正文。

API 兼容 GET `echostr` 签名校验，并接收真正的加密 POST 通知。收到 `component_verify_ticket` 后会验签、解密并加密持久化；平台 Token 同样加密缓存，因此本地 API 重启不会清空 Ticket。进入公网域名的用户端，打开“公众号管理 → 授权新公众号”即可生成微信官方二维码；扫码完成后电脑端会自动刷新，手机端不会被错误地跳转到手机自己的 `localhost`。

若改用管理端录入密钥，先保存配置并把回调地址同步到微信开放平台，等待“票据推送”变为正常，再运行全链路测试并发布。真实密钥只放 `.env` 或管理端密钥框，不能提交到仓库。

## 验证

```powershell
node scripts/verify.mjs
docker compose -f deploy/compose/compose.test.yml up --build --abort-on-container-exit --exit-code-from suite-tests
```

`verify.mjs` 依次执行两个前端的格式、类型、单元测试和生产构建，以及后端的 Ruff、mypy、pytest、迁移与 OpenAPI 导出。根级组合测试覆盖登录边界、数据隔离、文章库两条来源、Render 最终确认和微信幂等边界。

## 安全说明

- `.env.example` 只含开发占位符；任何真实 Key、Token 或微信加密参数都不得提交。
- 用户 Cookie 与管理员 Cookie、CSRF Token、路由和权限依赖完全分离。
- 管理员默认不可读取用户正文；受控排障必须填写原因并写审计日志。
- 生产部署必须替换全部示例口令，使用 Secret Manager/KMS 或 Docker Secret，并启用 HTTPS、备份、告警和恢复演练。

## 仓库关系

当前 GitHub 仓库按 monorepo 维护，项目集与三个业务目录统一在 `main` 分支提交；目录职责边界保持不变。克隆后直接执行：

```powershell
node scripts/check-submodules.mjs
```

该检查同时兼容未来重新拆分为 Submodule 的结构。接口兼容顺序固定为：后端扩展兼容 API → 前端升级 → 数据回填 → 切换默认 → 后续版本清理旧契约。
