# 统一模型文件入口交付记录

## 范围

复用原有附件上传、所有权校验、安全扫描状态、原文件存储、SHA256 校验及任务附件继承。
`app/model_files.py` 根据服务商协议选择文件传递方式，不按显示模型名称复制上传模块。
本次没有数据库迁移、HTTP DTO 或前端改动；运行数据库仍是 Docker PostgreSQL。

## 已实现通道

- Kimi/Moonshot 官方 Chat Completions：原文件上传至官方 Files API，官方提取完整文本后进入模型上下文。不是本地解析，不承诺原生 PDF 页面视觉理解。
- Manus 官方 v2：原文件经官方预签名 S3 URL 上传，确认 uploaded 后，将 file_id 作为 task.create 的 file 内容块发送。
- 切换上述服务商：根据同一任务的附件 ID 读取保留的原文件，再上传到新服务商；不复用其他服务商文件 ID。
- Kimi 缓存限定同所有者、任务、服务商、端点、凭据引用指纹及文件哈希。Manus 每个新运行重新上传，避免复用 48 小时后过期的 ID；超过 47 小时的冻结引用在调用前明确拒绝。
- 上传失败、安全检查未通过、缺少原文件、未知协议和不支持的格式均明确失败，不用文件名或本地占位正文替代。

## 限制

- 当前统一入口最多 20 个文件，每个不超过 100 MiB，支持代码白名单中的 PDF、Office、文本格式。图片、音视频不在本次范围。
- Qwen3.7 Flash 和未适配渠道仍明确拒绝文件输入；Qwen-Long 官方文件引用协议不能直接套到其他千问模型。此次未添加 Qwen-Long 部署，也不更改用户模型配置。
- Manus 原文件副本按服务商 48 小时过期机制清理，失败上传也可能留下待过期记录。没有新增清理调度器。
- 旧版内存存储已丢失的附件需重新上传；新增持久化原文件不受影响。
- 不支持的渠道可以扩展 `file_input_route` 及其协议实现，公共文件流程无需重写。不声称任意 OpenAI 兼容地址均支持文件。

## 验证

- Ruff、mypy（44 个源文件）通过。
- model_files、model_gateway、production_providers、retrieval：53 项测试通过。
- 覆盖原文件字节上传、真实附件消息块、跨服务商重传、任务附件继承、越权拒绝、缓存范围、外部上传 URL 限制、官方正文为空及长度预算。
- 真实 Manus TXT 联调：随机校验码仅在文件中出现；官方上传确认后，模型返回同一校验码。使用合成测试资料，没有修改业务文章。
- 可选真实联调脚本：`services/platform-backend/scripts/check_manus_file_delivery.py`。会上传合成 TXT 并创建一次 Manus 任务，可能产生费用；不自动在测试套件中执行。

## 官方依据

- https://open.manus.im/docs/v2/file.upload
- https://open.manus.im/docs/v2/task.create
- https://help.aliyun.com/en/model-studio/long-context-qwen-long

## 回退

恢复此次修改前的 model_files.py、production_providers.py 后，在无活跃任务时重启 API 和 AI Worker。
无需回滚数据库；保留原文件存储，不删除用户附件或历史文章。
