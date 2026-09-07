# 聊天重复消息与生成失败修复

## 修改

- CreatePage 在首次显示临时消息前生成 clientMessageId，API 使用同一 ID。服务端接受请求时回传原待处理命令的 ID，以兼容断线恢复；正式消息加载后临时消息被去重，而非按文本去重。
- Kimi 官方 K2.5/K2.6 的意图、规划、正文、检查、摘要与格式修复使用非思考模式和受限输出预算；文章输出启用 JSON object 模式。正文沿用独立规划阶段结果，不再反复进行长时间内部推理。未知服务商不附加这些专用参数。
- 文章输出提示从编辑器真实节点、属性、子节点及标记白名单生成。格式修复也使用同一规则，并获得具体校验错误，不放宽安全校验、不把损坏 JSON 保存成正文。
- 模型返回 finish_reason=length 时明确报 MODEL_OUTPUT_TRUNCATED，不把未完成输出当成成功文章。
- 超时保留 ProviderTimeoutError，错误提示指出失败阶段；只有实际调用过其他部署才说尝试过备用模型。
- OpenAI 兼容调用除了 HTTP 空闲超时，还使用 asyncio.timeout 限制整次请求总时长，避免持续收到零碎数据导致等待时间超过阶段上限。
- 带文件的 Chat Completions 请求允许一次同模型暂时失败重试；Manus 创建远程任务，不在结果不明时自动创建第二个任务。此项不代表跨服务商自动故障切换已完成。
- 结构修复通过统一模型调用入口记录尝试，修复失败不再丢失此前各阶段调用信息。

## 验证

- 用户端 TypeScript、lint、67 项 Vitest 与生产构建通过。
- 后端 Ruff、mypy、70 项相关 pytest 通过。OpenAPI 没有变化，无数据库迁移。
- 浏览器验证 1440×900、1280×720、1024×768、390×844，浅色/深色：新聊天临时消息与正式消息只出现一次；主动重复发送相同文字保留两条；失败重试、刷新恢复保留历史消息和附件。所有根节点 scrollWidth 等于 clientWidth。
- 脚本：用户端 scripts/check-message-dedup.mjs、check-immediate-chat.mjs、check-pending-message.mjs。
- 可选付费真实联调：后端 scripts/check_kimi_article_generation.py RUN_ID，复用指定运行的文件上下文测试规划与含表格正文，不保存或覆盖用户文章。
- 最终真实 Kimi 联调通过：规划 15.2 秒，正文生成及校验 63.9 秒；返回 3108 字符且含真实表格节点，首次结构校验通过，未调用修复，未保存用户文章。此前保留默认正文思考的试验等待过长，已中止；最终验证使用非思考模式和总时长上限。

## 边界与回退

旧运行不会因为新代码自动重放，也不修改旧错误记录或用户文章。供应商超时仍可能发生，不能保证外部服务永不失败。
运行数据库保持 Docker PostgreSQL。恢复对应前后端代码并在没有活跃任务时重启 AI Worker 即可回退，无数据回滚。

## 官方参数依据

https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart

https://platform.kimi.com/docs/api/chat
