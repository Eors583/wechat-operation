# 微信公众号AI运营助手完整技术设计文档

**版本：V3.0**  
**文档性质：研发实施与Codex执行基线**  
**作者：Manus AI**  
**业务依据：用户端需求V2.1、管理端需求、最新UI与用户补充决策**

---

## 1. 文档目标

本文将微信公众号AI运营助手的用户端、管理端、共享后端、文章库与知识库、AI智能体、排版和微信公众号流程统一为一套可实施技术基线。文档重点解决Codex在首次阅读材料后提出的未确认问题，并固化仓库组织、前端样式与组件规范、文章库形成过程、数据库、接口、失败恢复、安全、测试和渐进式开发规则。

> **总体结论：**系统采用一个母仓库统一管理三个独立Git子仓库：用户端、管理端和共享Python后端。用户端使用Vue 3、TypeScript、Quasar和SCSS覆盖多端；管理端使用Vue 3、TypeScript、Element Plus和SCSS，仅构建桌面Web。两个前端分别构建、测试和发布；后端采用FastAPI模块化单体、Celery异步Worker、PostgreSQL业务库、独立PostgreSQL+pgvector检索库、Redis、RabbitMQ和S3兼容对象存储。文章库以自建事实库和混合检索为主，腾讯乐享作为可选外部知识源。

## 2. 已确认边界

| 主题 | 正式要求 | 技术处理 |
|---|---|---|
| Git结构 | 母仓库包含用户端、管理端和后端子项目；三者是独立Git仓库 | 母仓库使用Git Submodule锁定三个子仓库的确定提交；母仓库保存文档、部署编排和跨仓验收脚本。Git官方说明Submodule可将独立仓库放入母仓库目录并记录具体提交。[1] [2] |
| 前端关系 | 用户端和管理端是两个独立项目 | 用户端采用Vue/Quasar，管理端采用Vue/Element Plus；不共享业务页面、路由和状态，共用同一个后端API契约 |
| 后端关系 | 用户端与管理端共用后端 | 一个共享FastAPI模块化单体仓库；用户API和管理API具有独立路由、认证依赖、Cookie命名、权限和审计策略 |
| 用户范围 | 首版个人用户；以后增加团队、成员和付费 | 首版只实现个人用户；资源保留`owner_type/owner_id`，不提前实现团队UI、审批和支付 |
| 多端 | Web和Windows完整；iOS、Android完整创作和运营能力，复杂模板编辑采用分步页面 | 用户端一套Vue业务代码构建Web/PWA、Electron Windows、Capacitor iOS/Android；管理端首版只构建Web |
| 样式 | 响应式、自适应、禁止硬编码、以后支持深浅主题 | 统一SCSS模块、语义设计Token、CSS Custom Properties、Quasar主题桥接和五档视口测试 |
| 组件 | 使用现成组件库，同时自行封装高频组件 | Quasar作为基础；建设Base、Composite、Business三层组件体系，禁止页面复制高频交互 |
| 文章库来源 | 用户上传文件；AI文章保存草稿或发布 | 两条写入流水线统一进入`library_items`读模型，事实数据分别存文件/文档表与文章/版本表 |
| 模型 | 管理端配置，不限制供应商 | 自建Model Gateway，业务按逻辑用途调用；LiteLLM作为协议适配，不把业务规则交给代理层 |
| 数据规模 | 1,000—50,000注册用户、20—200路AI并发、1—20TB文件 | API和Worker横向扩展；大文件进入对象存储；业务库与检索库独立扩容 |
| 部署 | 服务器环境不限定；必须Docker部署 | 首期Docker Compose；镜像和持久化边界保持可迁移到Kubernetes，但首版不建设Kubernetes |

## 3. Codex未确认问题的正式答复

| 问题 | 最终选择 |
|---|---|
| Node包管理器 | `pnpm`；用户端和管理端分别维护`pnpm-lock.yaml`，母仓库不跨子仓库建立workspace。pnpm使用内容寻址存储和非扁平依赖结构。[8] |
| Python依赖与锁文件 | `uv + pyproject.toml + uv.lock`；Ruff负责格式和Lint，mypy负责类型检查。uv支持项目、锁文件、工具和Docker/CI集成。[9] |
| 前端测试 | Vitest + Vue Test Utils负责单元与组件测试；Playwright负责E2E、浏览器、响应式和视觉回归。Vue官方推荐Vite项目使用Vitest，并将Playwright列为E2E方案之一。[10] |
| 后端测试 | pytest、pytest-asyncio、HTTPX；PostgreSQL、Redis和RabbitMQ集成测试使用Testcontainers或专用Compose环境。pytest支持夹具、参数化和复杂功能测试。[11] |
| Worker | Celery + RabbitMQ，按AI、文件、Embedding、微信、同步和维护任务分队列；Celery可通过Broker把任务分发给多个Worker并横向扩展。[12] [13] |
| CI平台 | GitHub Actions。每个子仓库执行本仓测试和镜像构建；母仓库执行子仓版本、OpenAPI契约和端到端组合验收 |
| 对象存储 | 开发MinIO；生产腾讯云COS或兼容S3服务；统一`StorageProvider`适配 |
| 密钥 | 开发使用不入库的`.env`；生产使用SecretProvider，优先腾讯云Secrets Manager/KMS，通过运行时注入或Docker Secret提供 |
| OCR | 本地容器化PaddleOCR为默认；复杂或低置信度页面可配置腾讯云OCR回退 |
| ASR | 采用`SpeechProvider`接口，生产优先腾讯云ASR；没有音视频需求时不启动对应Worker |
| 病毒扫描 | ClamAV独立容器；文件先进入隔离区，扫描通过后进入正式对象区 |
| 内容安全 | `ContentSafetyProvider`接口；生产可接腾讯云文本/图片内容安全，模型拒答不能通过切换模型绕过 |
| 可观测 | OpenTelemetry统一Trace、Metric和Log关联，后接Prometheus、Grafana、Loki、Tempo；前端错误使用Sentry或兼容服务。OpenTelemetry是厂商中立的遥测框架。[14] [15] |
| 管理员登录 | 账号+密码；连续失败后显示图形验证码并限流；首个管理员由CLI初始化 |
| 管理员账号管理 | 阶段1建立首个管理员与独立认证；管理员新增、停用和角色调整归入管理端系统设置阶段 |
| 微信平台配置 | 在微信公众号授权阶段同步实现管理端配置页，不延后到管理端收尾阶段 |
| 模型策略 | 管理端配置主模型和可排序备用链；逻辑用途包括意图、创作、快速任务、视觉、Embedding、Rerank和摘要 |
| 管理任务重试 | 只能用冻结的原输入、上下文和配置版本重放明确失败任务；管理员不能修改用户要求后重新创作 |

## 4. 仓库与项目集架构

### 4.1 仓库关系

```text
wechat-ai-suite/                         # 母仓库：项目集与综合管理
  .gitmodules
  README.md
  AGENTS.md
  docs/                                 # 产品、技术、路线图、ADR、API说明
  deploy/
    compose/                             # 开发、测试、演示环境编排
    gateway/                             # Nginx/Caddy配置
    monitoring/                          # OTel Collector、Prometheus等
  scripts/                               # bootstrap、verify、release、submodule检查
  contracts/                             # 后端导出的OpenAPI快照与兼容报告
  apps/
    user-client/                         # Git Submodule：用户端独立仓库
    admin-console/                       # Git Submodule：管理端独立仓库
  services/
    platform-backend/                    # Git Submodule：共享后端独立仓库
```

Git Submodule在母仓库中记录子仓库提交，因此母仓库的一个发布标签能够对应用户端、管理端和后端的确定组合版本。[1] [3] 新成员使用`git clone --recurse-submodules`克隆；CI必须运行`git submodule status --recursive`并拒绝未提交、未推送或与母仓库指针不一致的子仓状态。

### 4.2 仓库职责

| 仓库 | 保存内容 | 不允许保存 |
|---|---|---|
| 母仓库 | 项目说明、统一文档、Submodule指针、Compose、反向代理、监控、跨仓E2E和发布清单 | 用户端/管理端业务源码、后端领域源码、生产Secret |
| 用户端 | Vue/Quasar用户应用、Electron、Capacitor、用户端组件、用户端测试 | 管理端路由和管理业务页面 |
| 管理端 | Vue/Element Plus管理Web、管理组件、配置页面和测试 | 用户创作页面、Electron/Capacitor构建 |
| 后端 | FastAPI、数据库迁移、Worker、Model Gateway、微信、知识库和管理API | 前端视觉实现、真实生产密钥 |

子仓库独立分支、评审、版本和CI。跨仓改动采用兼容顺序：先后端添加兼容API并发布，再升级两个前端，最后在后续版本清理旧API。母仓库只在三个子仓库均通过验收后更新Submodule指针并打项目集发布标签。

### 4.3 接口契约

后端OpenAPI是唯一HTTP契约源。用户端和管理端分别从锁定的OpenAPI快照生成TypeScript Client，不手写重复DTO。CI执行OpenAPI Breaking Change检查；删除字段、收紧类型、改变状态码或语义必须经过兼容版本和迁移期。

设计Token采用独立JSON规范，由母仓库脚本生成两个前端各自的SCSS和TypeScript文件。首版不建立复杂私有npm平台；当至少三个跨仓组件稳定复用后，再把纯基础Token和基础组件发布为版本化内部包。业务组件永远留在各自仓库。

## 5. 系统总体架构

![系统总体技术架构](https://private-us-east-1.manuscdn.com/sessionFile/IglcVpCDUlpjmvdipNZnXg/sandbox/ztViZktgNWc4MhLQVsr4Bl-images_1788147983436_na1fn_L2hvbWUvdWJ1bnR1L3dlY2hhdF9haV90ZWNoZG9jX3YzL2RpYWdyYW1zLzAxX-ezu-e7n-aAu-S9k-aKgOacr-aetuaehF92Mw.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvSWdsY1ZwQ0RVbHBqbXZkaXBOWm5YZy9zYW5kYm94L3p0Vmlaa3RnTldjNE1oTFFWc3I0QmwtaW1hZ2VzXzE3ODgxNDc5ODM0MzZfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzZGxZMmhoZEY5aGFWOTBaV05vWkc5algzWXpMMlJwWVdkeVlXMXpMekF4WC1lenUtZTduLWFBdS1TOWstYUtnT2Fjci1hZXR1YWVoRjkyTXcucG5nIiwiQ29uZGl0aW9uIjp7IkRhdGVMZXNzVGhhbiI6eyJBV1M6RXBvY2hUaW1lIjoxNzkwODEyODAwfX19XX0_&Key-Pair-Id=K2QY5QTL8JSY6C&Signature=MEQCIB4uC-64mV1Em9L3oN~dvEtyOP94pW-gZBjZ-jTs4EfpAiAOyovhN0Y-Vzfk-PNRxLn0h9OKIj0abhov1wUYF-UwAA__)

系统分为五层。第一层是用户端多端应用和管理Web；第二层是统一入口、TLS、限流和静态资源；第三层是共享FastAPI应用，其中用户API与管理API拥有独立认证边界；第四层是按任务类型拆分的Celery Worker；第五层是业务PostgreSQL、检索PostgreSQL+pgvector、Redis、RabbitMQ、对象存储与外部服务。

首版采用模块化单体，不拆大量微服务。所有领域在一个后端仓库内拥有独立模型、应用服务和基础设施适配器；模块之间通过应用服务或领域事件协作，禁止跨领域直接更新对方表。API、Worker和Scheduler使用同一镜像，通过不同启动命令运行。

## 6. 多端前端完整设计

### 6.1 用户端技术栈

| 层次 | 选型 | 说明 |
|---|---|---|
| 核心 | Vue 3、TypeScript、Composition API | 所有业务组件强类型 |
| UI与构建 | Quasar CLI with Vite | SPA/PWA、Electron与Capacitor构建；Quasar提供统一Vue应用框架、Electron模式和Capacitor模式。[16] [17] [18] |
| 包管理 | pnpm | 独立锁文件与可重复安装 |
| 路由与状态 | Vue Router、Pinia | 路由、认证和客户端业务状态 |
| 服务端状态 | TanStack Query for Vue | 缓存、失效、并发去重、请求状态和受控重试 |
| 编辑器 | Tiptap + 自定义NodeView | 结构化文章节点、局部AI修改和历史恢复。[19] |
| 样式 | SCSS模块 + CSS Custom Properties | 编译期尺度与运行时主题切换 |
| 测试 | Vitest、Vue Test Utils、Playwright | 单元、组件、E2E、响应式与视觉回归 |

Web和Windows提供完整功能；iOS与Android提供创作、文章库、技能、公众号、预览和提交能力，多模板精细编辑拆成“模板—模块—样式—预览”分步页面。四端共享领域逻辑和组件，文件选择、安全存储、授权回跳、下载、分享和更新差异集中在`PlatformAdapter`。

### 6.2 管理端技术栈

管理端使用Vue 3、TypeScript、Element Plus、SCSS、Pinia和自动生成API Client。它是仅面向桌面Web的独立仓库，不包含Electron、Capacitor或移动端适配代码，也不能导入用户端页面。管理端复用语义Token命名，但组件实现以Element Plus为主并独立版本化，避免用户端多端发布节奏影响管理端。

### 6.3 SCSS与主题规范

Sass的`@use/@forward`提供模块命名空间和受控公共API，避免传统全局导入造成变量污染；Quasar同时提供可覆盖的Sass/SCSS变量入口。[4] [7] 两个前端统一采用：

```text
src/styles/
  tokens/_primitive.scss
  tokens/_semantic.scss
  tokens/_breakpoints.scss
  tokens/_z-index.scss
  tokens/_motion.scss
  tokens/_index.scss
  themes/_light.scss
  themes/_dark.scss
  mixins/_responsive.scss
  mixins/_text.scss
  mixins/_focus.scss
  foundations/_typography.scss
  quasar.variables.scss
  app.scss
```

SCSS保存基础尺度、断点、函数和Mixin；运行时可变颜色使用语义CSS变量。组件只能使用`--app-bg-surface`、`--app-text-primary`、`--app-border-default`、`--app-action-primary`等语义Token，不允许散落十六进制颜色、任意间距、任意圆角和任意`z-index`。

主题偏好支持`light/dark/system`。应用在Vue挂载前设置主题，Quasar Dark Plugin与`body--light/body--dark`及CSS变量同步，避免首次渲染闪烁。Quasar官方暗色模式会根据主题设置页面和带`dark`属性的组件。[5]

### 6.4 组件分层与复用习惯

![前端主题与组件架构](https://private-us-east-1.manuscdn.com/sessionFile/IglcVpCDUlpjmvdipNZnXg/sandbox/ztViZktgNWc4MhLQVsr4Bl-images_1788147983436_na1fn_L2hvbWUvdWJ1bnR1L3dlY2hhdF9haV90ZWNoZG9jX3YzL2RpYWdyYW1zLzAzX-WJjeerr-S4u-mimOS4jue7hOS7tuaetuaehF92Mw.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvSWdsY1ZwQ0RVbHBqbXZkaXBOWm5YZy9zYW5kYm94L3p0Vmlaa3RnTldjNE1oTFFWc3I0QmwtaW1hZ2VzXzE3ODgxNDc5ODM0MzZfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzZGxZMmhoZEY5aGFWOTBaV05vWkc5algzWXpMMlJwWVdkeVlXMXpMekF6WC1XSmplZXJyLVM0dS1taW1PUzRqdWU3aE9TN3R1YWV0dWFlaEY5Mk13LnBuZyIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTc5MDgxMjgwMH19fV19&Key-Pair-Id=K2QY5QTL8JSY6C&Signature=MEUCIQC29tlVrJQszx~EcMIHsxjGgJIOKWHkrow2DQrBkkAC6AIgMtNh8kOu4a5gKu6f3atbw~tAWsU2HuYlAtbShc-lJXU_)

| 层级 | 典型组件 | 约束 |
|---|---|---|
| Base | `AppButton`、`AppInput`、`AppDialog`、`AppTooltip`、`AppIcon`、`AppSkeleton` | 统一Quasar默认、尺寸、Token、焦点和错误状态；无业务语义 |
| Composite | `PageHeader`、`FilterBar`、`ResponsiveTable`、`FileUploader`、`AsyncStatePanel`、`ActionFooter` | 跨页面高频交互，不直接访问领域API |
| Business | `ArticlePreviewPanel`、`WechatFinalPreview`、`LayoutTemplateSelector`、`SkillCard`、`OfficialAccountCard` | 封装稳定业务交互，只在对应前端仓库内复用 |

同一种结构第二次出现时必须先考虑参数化复用；第三次出现且交互稳定时必须抽取组件。禁止复制整段模板和SCSS，也禁止创建包含大量布尔参数的“万能组件”。高复用组件必须有Story或示例页，并覆盖长文本、空数据、加载、错误、禁用、小屏和暗色主题。

### 6.5 响应式与防变形

断点统一为`xs < 600`、`sm 600—1023`、`md 1024—1439`、`lg 1440—1919`、`xl ≥ 1920`。优先使用Grid、Flex、容器查询和Quasar响应式CSS；只有行为变化时才读取Screen Plugin，Quasar官方也建议能使用CSS时优先使用CSS。[6]

所有Grid/Flex子项必须设置`min-width:0`。短标题使用省略号与Tooltip；摘要按设备截断；正文、URL和文件名使用`overflow-wrap:anywhere`。图片使用`max-inline-size:100%`和`block-size:auto`；封面使用宽高比容器。移动端弹层转换为全屏路由并适配Safe Area。CI在375、768、1024、1440和1920像素宽度检查非预期横向滚动、文本遮挡、按钮不可见、图片变形和弹层越界。

### 6.6 三种文章视图

编辑视图、公众号排版预览和微信提交前最终预览必须分离。编辑视图保存结构化内容；排版预览展示可修改模板效果；最终预览加载已锁定`render_id`，只读展示真正提交给微信的内容。桌面创作页采用任务导航、对话和非阻塞文章侧栏；手机使用单页对话与全屏预览。

## 7. 共享Python后端设计

### 7.1 技术栈与进程

后端使用Python 3.12、FastAPI、Pydantic、SQLAlchemy 2.0、Alembic和asyncpg。API进程负责鉴权、参数校验、查询、轻量事务和SSE；文件解析、AI生成、Embedding、模板提取、排版、微信操作与同步任务交给Celery Worker。Celery使用RabbitMQ作为Broker，Redis只承担缓存、限流、短锁和短期进度，不作为业务事实库。

```text
platform-backend/
  app/
    entrypoints/
      user_api.py
      admin_api.py
      worker.py
      scheduler.py
    api/
      user_v1/
      admin_v1/
      callbacks/
    domains/
      identity/
      quota/
      workspace/
      conversation/
      article/
      library/
      asset/
      retrieval/
      skill/
      memory/
      model_gateway/
      layout/
      wechat/
      admin/
    application/
    infrastructure/
    common/
  migrations/
  tests/
  pyproject.toml
  uv.lock
```

### 7.2 用户API与管理API隔离

两个前端使用同一后端代码和数据库，但不共用认证会话。用户端使用`/api/v1/*`，管理端使用`/admin-api/v1/*`；回调使用`/callbacks/v1/*`。三套路由拥有不同认证依赖、限流策略和审计等级。

| 维度 | 用户端 | 管理端 |
|---|---|---|
| 会话Cookie | `ua_session` | `admin_session` |
| 登录方式 | 手机/邮箱+密码或验证码 | 账号+密码；失败后图形验证码 |
| 权限 | 资源所有权和用户能力 | 管理权限码；不能默认读取用户正文 |
| CSRF | 双提交或服务端Token | 独立CSRF Token与更短有效期 |
| 日志 | 行为和错误，不记录正文 | 所有配置、额度、重试和排障动作写审计 |
| OpenAPI | 用户端契约 | 管理端契约 |

用户禁用后撤销全部用户会话；管理员账号停用只影响管理会话。管理Cookie不能调用用户资源接口，用户Cookie也不能调用管理接口。管理员如需查看涉及正文的故障，必须进入受控排障模式、填写原因并生成审计记录。

### 7.3 Docker运行单元

| 容器 | 职责 | 扩展依据 |
|---|---|---|
| `user-web` | 用户Web静态资源 | Web访问量 |
| `admin-web` | 管理Web静态资源 | 管理访问量 |
| `backend-api` | 用户/管理REST、SSE、回调 | HTTP、SSE连接、CPU |
| `worker-ai` | 模型调用、结构检查、摘要与偏好 | AI队列、模型RPM/TPM |
| `worker-parser` | 扫描、解析、OCR、ASR | 文件页数、CPU/GPU |
| `worker-embedding` | 切块、向量化、索引 | 待索引块数、Embedding限流 |
| `worker-wechat` | 图片、草稿、发布、状态查询 | 微信调用量与限流 |
| `worker-sync` | 腾讯乐享与外部知识同步 | 同步积压 |
| `scheduler` | 超时扫描、令牌刷新、Outbox、清理 | 单实例+分布式锁 |
| `otel-collector` | 汇聚Trace、Metric和Log | 遥测量 |

开发环境由母仓库Compose启动业务PostgreSQL、检索PostgreSQL、Redis、RabbitMQ、MinIO、ClamAV、后端和两个Web应用。生产环境复用相同镜像，持久化服务可以替换为托管服务。

## 8. 业务模块实现

| 模块 | 主要实现 | 关键失败处理 |
|---|---|---|
| 身份与会话 | Argon2id密码、短访问令牌、可撤销刷新令牌族、设备会话、独立管理员短会话 | 刷新令牌重放撤销令牌族；401并发只刷新一次；用户禁用即时撤销 |
| 用户与额度 | 个人账户、积分余额、不可变流水、能力和通用配额 | AI预占、完成结算、失败释放；相同业务ID不重复记账 |
| 项目与任务 | 项目可选；首条消息原子创建任务；任务可移动项目 | 删除项目默认转未分类；历史上下文快照不回写 |
| 对话与AI运行 | 消息、AI运行、阶段事件、SSE和断线续传 | 断线不取消任务；用户停止只停止后续步骤并保留已保存内容 |
| 文章 | 结构化内容树、不可变版本、自动保存、历史恢复 | 乐观锁冲突返回409；恢复历史生成新版本，不覆盖旧版本 |
| 文章库 | 用户上传和AI文章两条来源；统一读模型与筛选 | 事实写入与列表强一致；全文/向量索引失败不影响列表和发布 |
| 文件 | 预签名分片上传、隔离、扫描、解析、OCR/ASR、切块 | 阶段检查点重试；恶意文件隔离；失败文件不进入AI上下文 |
| 知识检索 | 权限过滤、全文+向量召回、RRF融合、重排与引用 | 乐享和向量服务故障时降级全文检索；绝不取消用户过滤 |
| 技能 | 官方/个人技能、版本、启停、主技能选择 | 运行开始固化技能版本；停用不改变历史结果 |
| 记忆 | 最近消息、任务摘要、项目要求、偏好候选 | 低置信度不生效；用户可查看、修改、删除和撤销 |
| 模型网关 | 供应商、部署、能力、用途路由、有序备用链和用量 | 429/5xx有限重试后切备用；鉴权错误禁用部署并告警 |
| 排版 | 公众号链接提取、多模板、StyleToken、微信兼容HTML和不可变Render | 提取失败不覆盖模板；文章或模板变化使旧确认失效 |
| 微信 | 第三方授权、令牌、图片、草稿、发布、回调和状态查询 | 幂等、结果不确定对账、迟到回调不倒退状态 |
| 管理端 | 模型、提示词、技能、用户、公众号、任务和系统设置 | 配置测试后发布；管理员只能重放冻结的失败任务 |

## 9. API、事件与并发控制

### 9.1 通用协议

REST前缀为`/api/v1`和`/admin-api/v1`，主键使用UUIDv7，时间使用UTC ISO 8601。列表采用游标分页。错误响应统一为：

```json
{
  "code": "ARTICLE_VERSION_CONFLICT",
  "message": "文章已在其他设备更新，请刷新后继续。",
  "request_id": "req_01...",
  "retryable": false,
  "details": {"current_version": 8}
}
```

高风险命令使用`Idempotency-Key`请求头。相同键和相同请求哈希返回首次结果；相同键和不同请求返回409。客户端通用拦截器不得自动重试保存文章、扣积分、存微信草稿和发布。

### 9.2 核心用户接口

| 领域 | 接口 | 说明 |
|---|---|---|
| 认证 | `POST /auth/register`、`/login`、`/refresh`、`/logout`、`/logout-all` | 会话创建、轮换、过期与撤销 |
| 项目 | `POST/GET/PATCH/DELETE /projects` | 项目可选，删除默认转未分类 |
| 任务 | `POST /tasks`、`GET /tasks`、`PATCH /tasks/{id}` | 首条消息也可原子创建任务 |
| 对话 | `POST /tasks/{id}/messages`、`GET /ai-runs/{id}/events`、`POST /ai-runs/{id}/cancel` | 运行ID、SSE和取消 |
| 上传 | `POST /uploads`、`POST /uploads/{id}/complete` | 预签名分片直传 |
| 文章库 | `GET /library-items`、`GET /library-items/{id}`、`DELETE /library-items/{id}` | 全库默认、项目可选筛选、来源状态统一 |
| 文档 | `GET /documents/{id}`、`POST /documents/{id}/reparse` | 查看解析结果和重试 |
| 文章 | `GET /articles/{id}`、`PUT /articles/{id}/content`、`POST /articles/{id}/save-local` | 乐观锁、版本和本地草稿 |
| 排版 | `POST /layout-templates/extract`、`POST /article-renders`、`GET /article-renders/{id}` | 提取模板、渲染和只读预览 |
| 技能 | `GET /skills`、`PATCH /skills/{id}/setting` | 官方/个人技能与启停 |
| 公众号 | `POST /official-accounts/authorize-url`、`GET /official-accounts`、`DELETE /official-accounts/{id}` | 授权、列表和解绑 |
| 微信 | `POST /wechat-drafts`、`POST /wechat-publishes`、`GET /wechat-operations/{id}` | 两者均要求最终预览确认与幂等键 |

### 9.3 核心管理接口

管理端提供模型供应商、模型部署、逻辑用途路由、提示词版本、官方技能、用户额度、公众号平台配置、失败任务、管理员账号和系统设置接口。配置对象采用`draft → testing → published → disabled`；发布新版本只影响新任务，运行中任务使用开始时固化的配置快照。

### 9.4 SSE事件

AI运行事件至少包括`run.accepted`、`stage.changed`、`text.delta`、`article.ready`、`warning`、`run.completed`、`run.failed`和`run.cancelled`。事件包含单调递增`seq`；客户端使用`Last-Event-ID`重连，服务端先补发`ai_run_events`中的缺失事件，再转实时流。

## 10. 核心业务流程

### 10.1 AI创作

用户进入空白页不创建任务。发送第一条消息时，后端在同一事务创建任务、消息、积分预占、`ai_run`和Outbox。Context Builder加载本轮要求、当前任务摘要、最近消息、已确认偏好、可选项目要求、用户选定资料和检索结果；模型输出结构化文章节点树。文章服务校验后创建不可变文章版本。

### 10.2 保存与文章库

AI流式文本本身不直接进入文章库。用户选择存本地草稿、确认存公众号草稿或确认发布时，文章服务在事务内保存当前版本并Upsert文章库列表项。用户上传文件在完成对象校验后立即创建文件类文章库条目，后续解析和索引异步完成。

### 10.3 排版、草稿与发布

```text
模型生成/用户修改结构化文章
→ 文章服务保存版本
→ 用户选择已启用模板或临时模板
→ 排版服务生成不可变微信兼容render_id
→ 用户普通排版预览并修改
→ 点击“存公众号草稿箱”或“直接发布”
→ 打开同一render_id的只读最终预览
→ 用户点击“确认存入草稿箱”或“确认发布”
→ 微信服务处理图片并创建/更新草稿
→ 若为发布，再提交同一草稿media_id并等待结果
```

排版服务不负责发布，微信服务不重新排版。最终预览、公众号草稿和正式发布必须使用同一`render_id`与校验值。文章、封面、目标公众号、模板或模板版本变化后，原确认立即失效。

## 11. 文章库与知识库详细设计

### 11.1 文章库的两条形成路径

![文章库形成与检索架构](https://private-us-east-1.manuscdn.com/sessionFile/IglcVpCDUlpjmvdipNZnXg/sandbox/ztViZktgNWc4MhLQVsr4Bl-images_1788147983436_na1fn_L2hvbWUvdWJ1bnR1L3dlY2hhdF9haV90ZWNoZG9jX3YzL2RpYWdyYW1zLzAyX-aWh-eroOW6k-W9ouaIkOS4juajgOe0ouaetuaehF92Mw.png?Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9wcml2YXRlLXVzLWVhc3QtMS5tYW51c2Nkbi5jb20vc2Vzc2lvbkZpbGUvSWdsY1ZwQ0RVbHBqbXZkaXBOWm5YZy9zYW5kYm94L3p0Vmlaa3RnTldjNE1oTFFWc3I0QmwtaW1hZ2VzXzE3ODgxNDc5ODM0MzZfbmExZm5fTDJodmJXVXZkV0oxYm5SMUwzZGxZMmhoZEY5aGFWOTBaV05vWkc5algzWXpMMlJwWVdkeVlXMXpMekF5WC1hV2gtZXJvT1c2ay1XOW91YUlrT1M0anVhamdPZTBvdWFldHVhZWhGOTJNdy5wbmciLCJDb25kaXRpb24iOnsiRGF0ZUxlc3NUaGFuIjp7IkFXUzpFcG9jaFRpbWUiOjE3OTA4MTI4MDB9fX1dfQ__&Key-Pair-Id=K2QY5QTL8JSY6C&Signature=MEUCIQCjtkwMA-uEAToYDYZszRFwHDCzajBuJ-YY6CksgvGGKQIgOp7xBzzouSFz9v-vpNEPnpWiFg7UnF~UoITgH5JMg4M_)

| 来源 | 事实对象 | 进入文章库的时点 | 后续处理 |
|---|---|---|---|
| 用户上传文件 | `asset + document` | 对象大小和哈希校验成功后立即创建`library_item` | 扫描、解析、OCR/ASR、切块、全文与向量索引 |
| AI生成文章 | `article + article_version` | 第一次存本地草稿、确认公众号草稿或确认发布时Upsert `library_item` | 文章纯文本切块、索引、偏好候选和微信状态聚合 |

`library_items`是文章库高性能列表读模型，不替代事实表。列表查询不需要临时联合大量版本和微信表，因此可以快速提供全库、项目、来源、状态、时间和关键词筛选。上传或保存成功后，列表强一致可见；向量检索最终一致。

文章库默认展示当前用户全部内容，项目仅作为可选筛选。`project_id = NULL`统一显示“未分类”。用户A的列表、全文索引、向量检索、预览、下载和AI引用都必须带`owner_id`过滤，数据库再以Row Level Security或受控连接角色作为第二道防线。

### 11.2 事实存储和检索副本

| 数据 | 唯一事实位置 | 是否可重建 |
|---|---|---:|
| 用户、任务、文章、版本、项目、模板、公众号和状态 | PostgreSQL业务主库 | 否 |
| 原文件、图片、解析产物和Render HTML | S3兼容对象存储 | 原文件不可重建；派生物可重建 |
| 文章库列表索引 | 业务库`library_items` | 可以从事实表重建 |
| 文本块、全文索引和向量 | 独立PostgreSQL+pgvector | 可以从标准化内容重建 |
| 腾讯乐享知识节点 | 乐享；本地保存映射、权限和缓存 | 由外部系统维护 |

### 11.3 自建还是外接

本项目采用**自建为主、乐享可选连接的混合方案**。腾讯乐享提供开放接口与不同产品版本能力，但具体知识API、容量、限流和授权范围应以购买版本和商务确认为准。[21] [22] 自建部分掌握用户隔离、文章版本、排版、微信状态和检索算法；乐享只用于检索企业已有知识，或同步用户明确选择的精选内容。乐享不可用时，本地文章库、创作、排版和微信流程必须正常工作。

首期不采购独立向量数据库，但向量检索不能与核心交易表使用同一个实例。独立`retrieval-db`启用pgvector、GIN全文索引和HNSW。pgvector提供HNSW、IVFFlat、halfvec和过滤能力，适合首期实现全文与向量混合检索。[20]

出现以下任一条件时，对pgvector与腾讯云VectorDB进行真实数据AB压测：有效文本块超过500万且持续快速增长；纯检索P95连续超出300毫秒；HNSW无法维持内存和缓存命中；检索负载影响业务库；需要多分片、多副本或在线索引重建。迁移使用双写、历史回填、影子读、灰度切换和回滚窗口，业务主库中的正文、权限和`chunk_id`保持不变。

### 11.4 文件处理流水线

```text
上传登记
→ 预签名分片直传隔离区
→ 大小、哈希、MIME和Magic Number校验
→ ClamAV扫描
→ 格式识别
→ 结构解析/OCR/ASR
→ 标准化文本和结构
→ 结构化切块
→ 全文索引
→ Embedding
→ 可选Rerank评测
→ 文章库标记“可检索”
```

解析器按PDF、DOCX/WPS、PPTX、XLSX/CSV、TXT/Markdown/HTML、图片和音视频分别适配。PDF保留页码，PPT保留页，表格保留工作表和行列，音视频保留时间戳。普通文本块目标600—900个中文字符或约400—700 tokens，重叠80—120 tokens；切块参数必须版本化，不能写死在解析代码中。

上传文件安全遵循扩展名、MIME和文件签名联合校验、随机对象键、隔离区、病毒扫描、大小限制和权限检查等原则；OWASP建议文件存储在Web根目录之外或独立服务器，并限制扩展名、内容类型和大小。[28]

### 11.5 混合检索

```text
owner/project/document权限过滤
→ 查询规范化和必要改写
→ PostgreSQL全文Top 50
→ pgvector语义Top 50
→ RRF融合和去重Top 30
→ 可选Rerank Top 10~15
→ 来源多样性和时间过滤
→ Top 6~10进入模型上下文
```

每条结果必须包含`document_id`、`chunk_id`、来源名称、页码/章节/时间戳、片段和来源类型。AI只能引用真正进入上下文的片段。检索评测至少覆盖100—300条真实问题，目标为权限泄露0、Recall@10不低于90%、纯检索P95低于300毫秒，并支持回到原文。

### 11.6 推荐起步配置

| 服务 | 商业起步配置 | 扩展方式 |
|---|---|---|
| 业务PostgreSQL | 8—16 vCPU、32—64GB、500GB高性能SSD、连接池、持续备份 | 读副本、分区、扩容；文件不入库 |
| 检索PostgreSQL | 16 vCPU、64GB、1TB NVMe/高性能SSD、pgvector、HNSW | 扩内存/SSD；达到阈值迁移VectorDB |
| 对象存储 | 初始2—5TB可用容量，按增长扩容 | 生命周期转低频/归档、跨区备份 |
| Redis | 4—8GB起，高可用 | 只存缓存、限流、短锁和短期状态 |
| RabbitMQ | 托管高可用或3节点 | 独立队列、死信、告警和Worker扩容 |
| API | 至少2个容器，每个2—4 vCPU、4—8GB | 无状态水平扩展 |
| AI Worker | 4—8个容器，每个4 vCPU、8GB | 受模型RPM/TPM、队列和预算控制 |
| 解析Worker | 4—8个CPU Worker | 扫描件多时增加GPU OCR节点 |

以上是容量规划起点，不是无条件性能承诺。正式资源必须用真实文件统计平均页数、解析比例、文本块数、Embedding维度、峰值QPS和模型配额后压测确定。

## 12. PostgreSQL数据库设计

### 12.1 通用规则

业务库使用PostgreSQL 16+，检索库为独立PostgreSQL实例。主键使用UUIDv7；时间使用`timestamptz`并保存UTC；状态使用`varchar + CHECK`而不是数据库ENUM；删除默认软删除。数据库变更只通过Alembic迁移，采用扩展—回填—切换—清理的向前兼容流程。

用户资源使用`owner_type + owner_id`。首版`owner_type = 'user'`，未来增加团队时可以引入`workspace`而不改变核心资源主键。所有普通用户查询必须绑定当前身份，不能接受客户端传入的任意`owner_id`。

### 12.2 身份、管理员与额度

| 表 | 核心字段 | 关键约束 |
|---|---|---|
| `users` | 手机、邮箱、显示名、状态、密码哈希、主题偏好、最后登录 | 手机/邮箱部分唯一；密码仅哈希 |
| `auth_identities` | 用户、登录类型、外部主体、验证时间 | `(provider, provider_subject)`唯一 |
| `refresh_tokens` | 用户、令牌哈希、令牌族、设备、平台、过期/撤销 | 只保存哈希；令牌哈希唯一 |
| `admins` | 账号、密码哈希、状态、权限 | 账号唯一；管理员会话与用户会话隔离 |
| `admin_sessions` | 管理员、令牌哈希、设备、过期/撤销 | 与用户会话完全分离 |
| `quota_accounts` | 所有者、余额、版本 | 所有者唯一；余额非负 |
| `quota_ledger` | 账户、方向、数量、原因、业务类型/ID、余额 | 相同业务动作唯一；流水不可修改 |
| `resource_limits` | 所有者、AI额度、存储、单文件、公众号数量 | 通用配额模型；模块按阶段启用 |

### 12.3 项目、任务、对话与AI运行

| 表 | 核心字段 | 关键索引/约束 |
|---|---|---|
| `projects` | 所有者、名称、说明、写作要求、排序 | 用户+排序；软删除 |
| `tasks` | 所有者、可空项目、标题、状态、当前文章、最后消息 | `(owner_id,last_message_at desc,id)` |
| `messages` | 任务、角色、结构化内容、纯文本、客户端消息ID | `(task_id,created_at,id)`；客户端ID幂等 |
| `ai_runs` | 用户、任务、运行类型、状态、模型路由、提示词版本、上下文快照、幂等键、错误 | 用户+幂等键唯一；状态和时间索引 |
| `ai_run_attempts` | 运行、模型部署、序号、输入/输出token、耗时、成本、请求ID、状态 | `(run_id,attempt_no)`唯一 |
| `ai_run_events` | 运行、序号、事件类型、载荷、时间 | `(run_id,seq)`唯一；按月分区 |
| `context_snapshots` | 任务、摘要、消息、资料、偏好、技能和Token预算引用 | 任务+创建时间 |

### 12.4 文件、文章库与检索

| 表 | 核心字段 | 关键索引/约束 |
|---|---|---|
| `assets` | 所有者、项目/任务、文件名、MIME、大小、哈希、对象键、扫描状态 | 对象键唯一；用户+哈希+大小 |
| `upload_sessions` | 文件、对象上传ID、分片数、过期和完成 | 上传ID唯一 |
| `documents` | 文件、所有者、项目、来源、标题、解析器版本、状态、页数、标准化对象键 | 用户/项目/状态；外部来源ID部分唯一 |
| `document_sections` | 文档、父节、类型、标题、文本/JSON、页码、顺序 | 文档+顺序唯一 |
| `library_items` | 所有者、类型、来源ID、项目、标题、摘要、显示状态、搜索文本、时间 | 所有者+类型+来源唯一；列表与GIN索引 |
| `document_chunks` | 文档、章节、所有者、项目、块号、文本、Token、`tsvector`、`halfvec(1024)`、模型和状态 | GIN全文、HNSW向量、权限过滤索引 |
| `retrieval_queries` | 用户、任务、原查询、改写、过滤、总耗时 | 用户/任务/时间；按月分区 |
| `retrieval_results` | 查询、文档块、全文/向量/融合/重排分数、名次 | 查询+阶段+块唯一 |
| `external_knowledge_sources` | 类型、配置、凭据引用、范围、状态 | 类型+名称唯一 |
| `external_knowledge_mappings` | 外部源、节点、文档、版本、同步状态 | 外部源+节点唯一 |

### 12.5 文章、版本、排版与微信

| 表 | 核心字段 | 关键索引/约束 |
|---|---|---|
| `articles` | 所有者、项目、来源任务、标题、摘要、状态、当前版本 | 用户/项目/状态/更新时间 |
| `article_versions` | 文章、版本号、Tiptap JSON、纯文本、哈希、来源、创建人 | 文章+版本唯一；不可变 |
| `article_assets` | 版本、文件、用途、节点ID、顺序 | 复合唯一 |
| `layout_templates` | 用户、公众号、名称、启用状态、来源链接、当前版本 | 公众号+更新时间；允许多个启用模板 |
| `layout_template_versions` | 模板、版本、StyleToken、来源快照、提取器版本 | 模板+版本唯一；不可变 |
| `article_renders` | 文章版本、模板版本、公众号、封面、HTML对象键、结构、校验值、微信校验 | 输入组合和校验值唯一 |
| `article_confirmations` | Render、用户、动作、确认/失效时间 | 有效确认部分索引 |
| `official_accounts` | 用户、授权AppID、名称、头像、状态、令牌引用、到期时间 | 用户+授权AppID唯一 |
| `wechat_operations` | 用户、公众号、文章/版本/Render、操作类型、状态、幂等键、media_id、publish_id、结果 | 用户+幂等键唯一；状态/时间 |
| `wechat_callbacks` | 事件键、类型、加密载荷、接收与处理时间 | 事件键唯一；按月分区 |

用户界面不显示账号类型、原始ID和“已授权能力”列表列，因此`official_accounts`不为这些旧UI字段建立业务依赖。若微信协议内部必须保存技术标识，放在加密技术元数据中，不直接暴露给用户。

### 12.6 技能、提示词、模型与记忆

| 表 | 核心字段 | 关键约束 |
|---|---|---|
| `skills/skill_versions` | 范围、所有者、代码、状态、指令、输入输出Schema、工具策略 | 官方代码唯一；发布版本不可变 |
| `user_skill_settings` | 用户、技能、启用状态 | 用户+技能唯一 |
| `prompt_bundles/prompt_versions` | 代码、状态、系统模板、操作模板、变量Schema、输出Schema、校验值 | 代码+版本唯一；已发布不可变 |
| `model_providers` | 代码、适配器、基础URL、密钥引用、状态 | 代码唯一；不存明文Key |
| `model_deployments` | 供应商、模型ID、别名、能力、上下文、RPM/TPM、成本、状态 | 供应商内别名唯一 |
| `model_route_versions` | 逻辑用途、主模型、有序备用链、策略、状态 | 每用途单一活动版本 |
| `user_preferences` | 用户、类型、值、范围、置信度、来源、状态 | 用户+类型+状态 |
| `task_memory_summaries` | 任务、消息范围、摘要、事实JSON、版本 | 任务+范围唯一 |

### 12.7 可靠性和审计

`idempotency_records`保存幂等键、请求哈希、执行状态和首次响应；`outbox_events`与业务事务同提交；`inbox_messages`用于Worker消费去重；`job_records`记录阶段、进度、重试和错误；`audit_logs`记录管理员和高风险用户动作。大表按月分区并配置保留策略。

## 13. AI模型、提示词、技能与记忆

### 13.1 单主智能体与确定性工作流

用户只面对一个内容创作智能体。模型负责理解意图、必要追问、选择已启用技能、规划资料检索、生成与修改文章；后端状态机负责版本保存、额度、排版、最终确认、微信草稿和发布。模型不能直接执行正式发布，也不能绕过资源所有权检查。

### 13.2 Model Gateway

管理端按照“供应商 → 模型部署 → 逻辑用途路由”配置AI。业务模块只发送逻辑用途，不接触真实模型名和Key。逻辑用途至少包括：

| 用途 | 任务 |
|---|---|
| `intent_detection` | 判断聊天、写作、修改、标题、总结、排版等意图 |
| `fast_task` | 标题生成、简单分类和轻量提取 |
| `article_planning` | 结构和论点规划 |
| `article_generation` | 完整文章生成 |
| `article_revision` | 全文或选中节点修改 |
| `content_check` | 结构、引用和明显错误检查 |
| `vision` | 图片/页面理解的可选模型 |
| `memory_summary` | 任务摘要和偏好候选 |
| `layout_extraction` | 辅助识别文章结构和样式 |
| `embedding` | 文本向量化 |
| `rerank` | 候选重排 |

Model Gateway负责权限、额度、提示词、上下文、审计、路由版本和用量；LiteLLM仅负责供应商协议转换、能力适配和基础故障切换，不承载业务授权和文章状态。[27] 每条用途路由保存主模型和可排序备用链。运行开始时固化路由、模型、提示词、技能和上下文版本，管理端发布新配置不影响正在执行的任务。

### 13.3 提示词存储与编排

提示词按Bundle和Version存储，不能直接覆盖生产文本。一个运行时Prompt由以下层次组成：

> **平台安全边界 → 当前操作协议 → 用户本轮要求 → 项目要求 → 用户选择的技能 → 已确认偏好 → 检索资料 → 任务摘要与最近消息 → 输出Schema。**

用户本轮明确要求高于历史偏好和项目默认。外部文件、公众号网页和乐享内容始终放在不可信资料区，不能变成系统指令。提示词变量必须由JSON Schema定义并经过白名单校验。管理端采用草稿、固定案例测试、发布和回滚流程；运行记录保存版本ID、输入变量哈希和校验值，不在普通日志中保存完整正文。

### 13.4 AI状态与失败恢复

```text
ACCEPTED → VALIDATING → CLARIFYING? → RETRIEVING
→ PLANNING → GENERATING → VALIDATING_OUTPUT
→ SAVING_VERSION → READY_FOR_FORMATTING → COMPLETED
```

排版是模型生成完成后的独立服务，不是模型状态机中的发布步骤。模型输出结构化文章节点树；不支持JSON Schema的模型允许一次结构修复，仍无效则切换备用模型或失败。429按`Retry-After`等待，连接和5xx有限重试后切备用；鉴权错误立即停用部署并告警；内容安全阻止不能通过换模型绕过。

一次业务运行可以有多个模型Attempt，但只允许产生一个最终文章版本和一次额度结算。用户取消后停止后续步骤、释放未使用额度，并保留已经提交的消息和文章版本。

### 13.5 技能

技能由版本化指令、输入输出Schema和允许工具策略组成。官方技能由管理端发布，个人技能由用户创建；实际可调用集合是“可见技能 ∩ 用户已启用 ∩ 模型能力满足 ∩ 当前场景允许”。首版一次创作最多一个主技能。技能不能直接提交微信；文件、排版和发布仍由确定性服务执行。

### 13.6 会话与长期记忆

短期上下文包含最新消息、当前文章版本、用户本轮选择的资料、任务摘要和未完成事项。Context Builder按模型窗口分配预算，超限时优先删除低分资料和更早消息，不得截断用户最新要求。

长文件/粘贴文本处理：原始消息及文件服务返回全文保留在运行快照中；超出单次模型输入预算时，工作进程逐段阅读全部文字并分层汇总，不通过截取前若干字符代替全文。分段附带来源路径、内容哈希、字符起止位置与片段编号，汇总明确标记有损，不宣称模型无损记忆全部细节。按路由窗口、输出预留和提示词开销约束最终上下文；短内容不增加模型调用，同轮缓存复用已生成的汇总。分段空输出、不收敛或超出工作上限均明确失败，不能静默跳段。原始文件仍走原有供应商上传流程，不以本地摘要冒充原文件上传。

归并收敛：单段笔记预算不按原文件总段数均分；中间笔记能放进窗口时整体归并，避免反复细切。模型超出单段目标时最多尝试3次，若仍超目标但有真实净缩短，可继续下一层归并；最终上下文预算仍为硬限制，不得将超限内容直接提交生成。所有重试均计入总调用上限。

资源边界：文件解析文字总量最多200万字符，每次上下文压缩最多160次分段/归并调用；直接粘贴仍遵守消息接口10万字符上限。长资料会增加模型成本和延迟，汇总不是逐字校对或无损转换；原生不透明附件的读取能力仍由供应商决定。原有网页检索与链接全文预算边界不在该分段文件能力中放宽。

长期偏好来自用户明确表达、重复修改模式和最终确认文章。AI初稿和外部参考风格不能直接成为用户偏好。偏好保存类型、自然语言值、置信度、来源、范围和状态；低置信度只作为候选。用户可以查看、修改、删除和撤销。

日常创作偏好学习实现：发送用户消息时提取可确定的写作反馈；`memory_summary` 调用同时返回任务摘要和带用户原句证据的风格候选。文章创作先提交文章版本和确定性摘要，再通过事务 Outbox 异步补充模型摘要与偏好候选，不阻塞 `article.ready`；普通讨论及偏好设置仍在当前流程内完成摘要，以便确认回复反映实际保存状态。仅使用所属用户的本轮消息作为证据，不从附件、助手输出或旧摘要推断偏好。明确长期表达可确认；一般反馈先作为候选，同范围、同类型和值在两个不同任务中重复后可确认，不能通过同任务重试升级。本篇、本次、引用示例及敏感信息不纳入学习；关闭任务偏好时不执行该任务的对话学习。

意图边界：仅描述未来默认或要求记录偏好的消息属于非创作对话，即使句中包含“生成文章”也不能视为本轮写作授权。不执行文章规划、生成或创建版本；确认回复依据实际偏好保存状态产生，不透传模型虚构的“已生成”或“已记住”。同时明确要求本轮写作、修改当前文章的混合消息仍按创作处理，当前指令优先。

复用 `user_preferences`，对话来源为 `dialogue_feedback`，`source_id` 指向用户消息；`preference.feedback` 审计记录消息和任务 ID，不复制正文。学习按用户行锁串行化、按消息去重，撤销记录不自动恢复；明确的新同类偏好可替代旧偏好，个人和项目范围互不替代。新任务继续通过 Context Builder 读取已确认且范围匹配的偏好，本轮要求优先。历史任务不自动回填。

## 14. 公众号多模板、微信兼容排版与发布

### 14.1 模板管理

每个公众号可以拥有多个模板，模板可启用或停用。授权失效不影响模板创建、编辑和预览，只在存公众号草稿或发布时要求有效授权。用户在模板管理中粘贴微信公众号文章链接并点击“提取模板”；抓取器限制HTTPS、受控域名、重定向、响应大小和私网地址，防止SSRF。

系统识别标题、导语、一级标题、二级标题、正文、重点论点、引用、列表、图片说明和分隔线，转换为受控StyleToken。用户通过选择框调整字号、字重、颜色、对齐、间距、背景、边框和缩进，不能输入任意脚本或CSS。选择左侧模板后，中间显示模块设置，右侧主体显示完整排版效果。

### 14.2 排版服务

模型只生成结构化内容，不直接生成最终微信HTML。排版服务以`article_version_id + template_version_id + cover_asset_id + official_account_id`为输入，输出不可变`article_render`。渲染器只允许白名单HTML标签和内联样式，检查移动端宽度、换行、图片、字符限制和危险内容。

普通预览和提交前最终预览都加载后端生成的Render，不能由前端另拼一套HTML。最终预览只读。文章、模板、封面或公众号变化后，原Render标记过期，既有确认失效。

### 14.3 微信授权与平台配置

系统接入的是微信开放平台的**公众号第三方平台**，不是企业微信开放平台。管理端在微信授权阶段配置`component_appid`、AppSecret密钥引用、消息Token、EncodingAESKey、票据回调、授权回调和权限集。第三方授权需要预授权码和公众号管理员确认，实际能力由平台权限集、公众号授权范围和公众号资格共同决定。[23]

公众号正文中的外部图片需要由服务端上传微信并替换成微信返回的URL；新增草稿和发布均由服务端调用接口。[24] [25] [26]

### 14.4 草稿与发布流程

| 用户动作 | 最终预览 | 确认按钮 | 后端执行 |
|---|---|---|---|
| 存本地草稿箱 | 不需要微信最终预览 | 存本地草稿箱 | 保存版本并写入文章库 |
| 存公众号草稿箱 | 必须 | 确认存入草稿箱 | 处理图片，创建或更新微信草稿 |
| 直接发布 | 必须 | 确认发布 | 先创建/复用草稿，再提交发布并等待结果 |

草稿和发布共用已经确认的同一`render_id`。如果草稿创建成功但发布提交失败，保存`DRAFT_CREATED_PUBLISH_FAILED`并复用原`media_id`重试，不能再次创建重复草稿。微信接口返回受理不等于最终发布成功；系统保存`publish_id`，依赖回调或状态查询完成最终状态。[25]

## 15. 请求失败、幂等和数据一致性

### 15.1 失败分类

| 类型 | 自动重试 | 处理 |
|---|---:|---|
| 参数、权限、余额、版本冲突 | 否 | 返回用户可修改原因，保留输入 |
| 连接、DNS、外部5xx | 是 | 指数退避加抖动，到上限进入死信 |
| 429 | 是 | 尊重等待时间，按供应商或公众号隔离限流 |
| 401或令牌过期 | 条件重试 | 刷新一次；再次失败要求重新连接或管理员修复 |
| 请求已发出但响应丢失 | 不直接重放 | 标记`UNKNOWN`，根据外部ID查询对账 |
| 内容审核或格式失败 | 否 | 保留文章和Render，修改后创建新版本 |
| 客户端断网 | 不取消后台 | SSE重连或查询运行状态 |

### 15.2 Outbox与消费去重

API在同一PostgreSQL事务中提交业务数据和`outbox_events`。Relay发布到RabbitMQ；Worker处理前写`inbox_messages`，重复消息返回已有结果。所有Worker以业务资源和阶段检查点实现幂等，保证重复投递不会重复创建文章、重复扣积分、重复索引或重复提交微信。

### 15.3 并发与乐观锁

文章保存携带`base_version_no`；冲突返回409，不能静默覆盖。额度账户使用版本列和业务唯一键。微信操作锁定文章版本、Render、封面、公众号和Checksum。定时任务使用数据库顾问锁或Redis短锁，但锁不作为事实状态。

## 16. 安全与数据隔离

用户资源查询必须从认证上下文取得`owner_id`，不信任客户端传入所有者。服务层、Repository层和检索过滤都强制用户范围；PostgreSQL可在生产启用Row Level Security作为兜底。每个模块必须包含“用户A无法读取、修改、下载、搜索或让AI引用用户B数据”的测试。

Web使用HttpOnly、Secure和SameSite Cookie保存刷新会话；访问令牌短期化。Electron和移动端使用系统安全存储，渲染页不持有长期Secret。密码使用Argon2id。Electron关闭Node Integration、启用Context Isolation和白名单IPC。管理员会话独立且有效期更短。

模型Key、微信AppSecret、EncodingAESKey、短信密钥和乐享Secret只能以密钥引用保存。日志不得记录Cookie、Authorization、完整手机号、模型Key、用户文章全文和文件全文；OpenTelemetry采集Header时必须配置敏感字段脱敏。[15]

外部文件、网页和知识片段均视为不可信数据，不能改变系统提示词和工具权限。大模型提示注入防护遵循“数据与指令分离、工具最小权限、外部写操作二次确认和输出验证”原则。[29]

## 17. 管理端技术设计

管理端与用户端共用后端，但使用独立Vue项目和独立管理API。管理端只管理平台配置与运行状态，不代替用户写文章或发布内容。

| 模块 | 技术实现 | 用户端影响 |
|---|---|---|
| 管理首页 | 聚合用户、模型调用、文件、微信和任务指标 | 只展示平台状态，不修改用户内容 |
| AI配置 | 供应商、模型、能力、逻辑用途、主模型、有序备用链和连接测试 | 新AI任务读取最新发布路由 |
| 提示词 | Bundle、版本、变量Schema、测试案例、发布和回滚 | 新AI任务固化已发布版本 |
| 官方技能 | 草稿、测试、发布、排序、停用和恢复 | 已发布技能显示在用户技能库 |
| 用户管理 | 账号状态、额度、能力开关、用量和审计 | 下一次请求按新状态与额度校验 |
| 公众号管理 | 第三方平台参数、绑定状态、令牌、回调和失败任务 | 用户端只显示简化连接状态 |
| 任务管理 | AI、解析、Embedding、乐享、草稿和发布任务 | 安全重试或对账后更新用户状态 |
| 系统设置 | 文件限制、自动保存、功能开关、管理员账号 | 前后端按发布配置共同执行 |

管理员只能重试“明确失败”且输入已冻结的任务。`UNKNOWN`微信任务必须先对账。取消只允许未执行或安全检查点。管理员账号新增、停用、角色调整和审计查看归入系统设置；首个管理员由后端CLI在部署时初始化。

## 18. Docker、配置与环境

### 18.1 环境划分

开发、测试、预发布和生产使用不同数据库、对象存储桶、消息队列VHost、Redis前缀、微信平台配置和模型Key。禁止使用配置开关让测试环境访问生产数据。配置分为公开配置、普通环境变量和Secret三类；Secret只在运行时注入。

### 18.2 Compose职责

母仓库提供：

- `compose.dev.yml`：本地两个前端、后端热更新和全部基础设施；
- `compose.test.yml`：固定版本、隔离数据库和自动测试；
- `compose.demo.yml`：演示环境，使用构建镜像；
- `.env.example`：只包含变量名和安全占位，不放真实凭据。

后端镜像使用多阶段构建和非Root用户；用户端、管理端、Worker使用同一发布版本标签。数据库、RabbitMQ、Redis、对象存储和监控必须使用持久卷或托管服务。首期不强制Kubernetes，但API保持无状态、Worker独立队列、配置外置，为后续迁移保留边界。

## 19. CI/CD和跨仓发布

### 19.1 子仓库CI

| 子仓库 | 必须执行 |
|---|---|
| 用户端 | pnpm冻结安装、ESLint、Stylelint、TypeScript、Vitest、生产构建、Playwright关键流程、五档视口截图、依赖扫描 |
| 管理端 | 同用户端；增加管理权限、长表格、配置草稿/发布测试 |
| 后端 | uv锁文件同步、Ruff、mypy、pytest、Alembic空库升级、数据库/Redis/RabbitMQ集成测试、OpenAPI导出、镜像扫描 |

### 19.2 母仓库CI

母仓库检查Submodule是否指向可访问提交，启动完整Compose，比较OpenAPI快照，运行用户端与管理端跨仓E2E，执行登录、数据隔离、AI模拟、文章库、排版和微信Mock流程。三个子仓库全部通过后，才能更新母仓库发布标签。

### 19.3 发布顺序

兼容更新遵循“后端扩展 → 前端升级 → 数据回填 → 后端切换默认 → 后续清理”。数据库先加字段或表，不立即删除旧字段。Windows、Android和iOS构建使用同一用户端业务版本，但分别保存平台签名、商店元数据和发布记录。

## 20. 测试、质量门禁与性能目标

### 20.1 测试层级

| 层级 | 重点 |
|---|---|
| 单元测试 | 领域规则、状态机、StyleToken、提示词组装、额度结算、组件Props/Events |
| 组件测试 | 长文本、空/错/加载、暗色、键盘与响应式行为 |
| 数据库集成 | 唯一约束、RLS/用户隔离、软删除、事务、迁移和并发冲突 |
| Worker | 重试、幂等、检查点、取消、死信和资源回收 |
| 外部契约 | 模型、对象存储、乐享、短信和微信的成功与错误样本 |
| E2E | 登录、创作、上传、文章库、技能、模板、草稿和发布 |
| 性能 | 普通API、文章库列表、检索、SSE、上传、Worker和20—200路AI运行 |
| 安全 | 越权、Cookie/CSRF、文件、SSRF、XSS、提示注入、Secret和日志脱敏 |

### 20.2 必须通过的业务门禁

| 用例 | 通过标准 |
|---|---|
| 用户数据隔离 | 用户A不能查看、搜索、引用、修改或下载用户B的任何内容 |
| 无项目创作 | 不选项目即可发送消息并创建任务 |
| 上传形成文章库 | 上传完成立即显示处理中；解析成功后可预览和检索 |
| AI文章形成文章库 | 保存本地草稿、确认公众号草稿或确认发布后出现且不重复 |
| 响应式 | 375—1920宽度无非预期横向滚动、遮挡、按钮丢失和图片变形 |
| 深浅主题 | 关键页面在两种主题下颜色、对比、状态和图片正常 |
| AI断线 | 后台继续，重连补发事件，不重复扣额度 |
| 多模板 | 同一公众号可保存多个模板、启停、选择和预览 |
| 授权过期 | 模板仍能管理；只在草稿和发布时要求重新连接 |
| 微信草稿 | 显示同一Render最终预览，确认后才提交，不重复创建 |
| 正式发布 | 显示同一Render最终预览，确认后发布，结果不确定先对账 |
| 乐享故障 | 本地文章库、检索降级、创作、排版和微信不阻断 |

### 20.3 性能目标

首年按1,000—50,000注册用户、20—200路AI并发和1—20TB文件设计。普通读接口目标P95低于300毫秒；文章库列表目标P95低于300毫秒；本地全文+向量纯检索目标P95低于300毫秒；包含查询改写、Embedding和Rerank的完整检索目标约0.8—2秒。文件解析属于异步任务，可以数秒到数分钟。

并发承诺必须以真实服务器、模型配额和压测为准。建议初始上线先稳定支持50路AI同时生成，通过队列、模型RPM/TPM和成本观测逐步扩到200路。API、SSE和Worker分别压测，不能用普通HTTP并发替代AI供应商并发验证。

## 21. Codex渐进式开发规则

### 21.1 开发顺序

| 阶段 | 目标 | 完成门禁 |
|---:|---|---|
| -1 | 阅读文档并固化项目规则 | 只生成项目上下文和开发规范，不写业务代码 |
| 0 | 创建母仓库、三个子仓库、Docker、工具链、Token和基础组件 | 三个子仓可独立测试；母仓一键启动；两个PostgreSQL均健康 |
| 1 | 用户与管理员认证、Cookie、过期、刷新和数据隔离 | 越权、过期、重放和多端会话测试通过 |
| 2 | 用户、积分和通用配额 | 预占/结算/释放幂等，额度不能为负 |
| 3 | 可选项目和任务 | 无项目可创作，项目删除转未分类 |
| 4 | 管理端模型、路由和提示词 | 可测试、发布和回滚；前端不接真实Key |
| 5 | AI对话、SSE与上下文 | 流式、停止、断线恢复和备用模型通过 |
| 6 | 官方/个人技能 | 启停和版本固化正确 |
| 7 | 文章编辑、版本与本地草稿 | 乐观锁、自动保存和恢复通过 |
| 8 | 对象存储和文件上传 | 分片、哈希、扫描、权限和失败恢复通过 |
| 9 | 文件解析及上传来源文章库 | 上传后立即可见，解析状态与预览正确 |
| 10 | AI文章来源文章库 | 三种保存结果Upsert同一条目，不产生重复 |
| 11 | 全文、向量和RAG | 权限泄露0，引用可追溯，评测和延迟达标 |
| 12 | 乐享可选连接器 | 乐享故障不影响本地主链 |
| 13 | 会话摘要与长期偏好 | 来源可追溯，用户可修改删除 |
| 14 | 微信第三方平台与管理配置 | 授权、刷新、撤销、回调和简化状态通过 |
| 15 | 多模板提取与管理 | 多模板、启停、链接提取和多端编辑通过 |
| 16 | 微信兼容Render与最终预览 | 普通预览和最终预览职责分离 |
| 17 | 公众号草稿与正式发布 | 同一Render、幂等、对账和回调状态通过 |
| 18 | 管理任务、管理员CRUD与系统设置 | 审计、冻结重试和发布配置通过 |
| 19 | Windows、iOS、Android构建 | 真实设备、签名、回跳和安全存储通过 |
| 20 | 性能、安全、备份和上线 | 压测、越权、安全扫描和恢复演练通过 |

每次Codex任务只能执行`CURRENT_PHASE`指定的一个子任务。先计划，再编码；完成后必须运行测试、记录修改文件、数据库迁移、API变化、回滚方式和遗留问题，然后停止等待人工确认。

### 21.2 阶段0的修正范围

阶段0必须先创建三个独立Git仓库，再由母仓库作为Submodule引入。不得再创建单一`frontend/`。阶段0只建立项目骨架、Docker、OpenAPI生成链、SCSS Token、Base组件示例、测试和CI，不创建用户、文章、AI和微信业务表。

## 22. 外部服务与账号准备

| 类别 | 必须准备 | 时点 |
|---|---|---|
| 企业与域名 | 企业主体、Web/API/文件/微信回调域名、HTTPS证书、必要备案 | 微信联调和预发布前 |
| 模型 | 至少一个主模型和备用模型；API地址、Key、模型ID、能力、上下文、RPM/TPM和预算 | AI阶段前 |
| Embedding | Embedding模型和额度；Rerank可后加 | RAG阶段前 |
| 微信开放平台 | 公众号第三方平台、AppID、Secret、Token、EncodingAESKey、权限集和回调 | 微信授权阶段前 |
| 公众号 | 测试公众号、正式公众号和可扫码管理员 | 微信联调前 |
| 对象存储 | COS或兼容S3 Bucket、凭据、私有读、分片、跨域、生命周期和备份 | 文件上传阶段前 |
| 短信 | 服务账号、签名、验证码模板、Key、频率和额度 | 注册登录阶段前 |
| 腾讯乐享 | 如果启用：版本、AppKey/Secret、开放接口、知识范围、容量、限流和SLA | 乐享阶段前，不是首版阻断项 |
| OCR/ASR/内容安全 | 选择本地或腾讯云服务，准备账号和Key | 对应文件类型启用前 |
| 多端发布 | Windows签名、Apple Developer、Bundle ID、证书、App Store Connect；Android开发者账号与Keystore | 多端发布阶段前 |
| 合规 | 用户协议、隐私政策、AI说明、版权承诺、注销与数据保留规则 | 对外测试前 |

## 23. 最终实施结论

本项目不再存在“单一前端仓库”的歧义。**用户端和管理端是两个独立Git仓库，后端是第三个独立共享服务仓库**；母仓库只负责项目集说明、Git Submodule版本锁定、部署、契约和组合发布。两个前端共享统一API和设计语言，但不共享业务页面，避免管理端与多端用户应用互相牵制。

文章库必须显式实现两条形成路径：用户上传文件在上传登记完成后立即产生处理中条目；AI文章在用户保存本地草稿、确认公众号草稿或确认发布时产生或更新文章条目。`library_items`保证列表快速读取，事实表保证版本正确，独立检索库保证AI查询性能。

前端选择SCSS、语义Token和CSS运行时变量，为浅色、深色和后续主题留出稳定接口；Quasar只是底层组件来源，项目仍必须建设三层组件体系并把复用作为开发门禁。后端继续采用共享模块化单体与独立Worker，在不增加首版微服务复杂度的前提下保留模型、检索、知识源、团队、付费和高并发扩展能力。

---

## References

[1]: https://git-scm.com/docs/git-submodule "Git - git-submodule Documentation"
[2]: https://git-scm.com/book/en/v2/Git-Tools-Submodules "Pro Git - Submodules"
[3]: https://git-scm.com/docs/gitmodules "Git - gitmodules Documentation"
[4]: https://quasar.dev/style/sass-scss-variables/ "Quasar Sass/SCSS Variables"
[5]: https://quasar.dev/style/dark-mode/ "Quasar Dark Mode"
[6]: https://quasar.dev/options/screen-plugin/ "Quasar Screen Plugin"
[7]: https://sass-lang.com/documentation/at-rules/use/ "Sass @use Rule"
[8]: https://pnpm.io/motivation "pnpm Motivation"
[9]: https://docs.astral.sh/uv/ "uv Documentation"
[10]: https://vuejs.org/guide/scaling-up/testing.html "Vue Testing Guide"
[11]: https://docs.pytest.org/en/stable/ "pytest Documentation"
[12]: https://docs.celeryq.dev/en/stable/getting-started/introduction.html "Celery Introduction"
[13]: https://docs.celeryq.dev/en/main/getting-started/backends-and-brokers/rabbitmq.html "Celery with RabbitMQ"
[14]: https://opentelemetry.io/docs/ "OpenTelemetry Documentation"
[15]: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html "OpenTelemetry FastAPI Instrumentation"
[16]: https://quasar.dev/introduction-to-quasar/ "Quasar Framework Introduction"
[17]: https://quasar.dev/quasar-cli-vite/developing-electron-apps/introduction/ "Quasar Electron Mode"
[18]: https://quasar.dev/quasar-cli-vite/developing-capacitor-apps/introduction/ "Quasar Capacitor Mode"
[19]: https://tiptap.dev/docs/editor/getting-started/install/vue3 "Tiptap Vue 3"
[20]: https://github.com/pgvector/pgvector "pgvector"
[21]: https://lexiang.tencent.com/wiki/api/ "腾讯乐享开放接口"
[22]: https://lexiang.tencent.com/product-version "腾讯乐享版本与资源说明"
[23]: https://developers.weixin.qq.com/doc/oplatform/Third-party_Platforms/2.0/api/Before_Develop/Authorization_Process_Technical_Description.html "微信开放平台第三方授权流程"
[24]: https://developers.weixin.qq.com/doc/subscription/api/draftbox/draftmanage/api_draft_add.html "微信公众号新增草稿"
[25]: https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_submit.html "微信公众号发布草稿"
[26]: https://developers.weixin.qq.com/doc/service/api/notify/message/api_uploadimage.html "上传发表内容中的图片"
[27]: https://docs.litellm.ai/docs/ "LiteLLM Documentation"
[28]: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html "OWASP File Upload Cheat Sheet"
[29]: https://genai.owasp.org/llmrisk/llm01-prompt-injection/ "OWASP Prompt Injection"
