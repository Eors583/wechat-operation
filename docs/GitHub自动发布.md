# GitHub 自动发布入口

生产上线统一使用 **GitHub Actions 构建并推送 GHCR → GitHub 自动通过 SSH 部署 → 服务器拉取成品镜像并切换服务**，不依赖本机 Docker。

操作入口：[Production release](https://github.com/Eors583/wechat-operation/actions/workflows/production-release.yml) → **Run workflow** → 分支 `main` → 选择 `backend`、`user` 或 `admin`。手动启动后，其余发布步骤自动执行；普通 Git push 不触发生产上线。

完整流程以 [《运维与恢复手册》第 2 节](运维与恢复手册.md#2-部署与扩缩容) 为唯一维护入口，已替换旧的本机构建和手动传包流程：

- 2.1：发布入口、lint 与构建边界。
- 2.2–2.4：独立版本、凭据、Registry 拉取与 GitHub SSH 归档回退。
- 2.5：失败处理、回滚与用户验收。
- 2.6：后端日常上线步骤。
- 2.7：数据库迁移发布例外。
- 2.8：当前与上一版镜像保留及清理。

工作流成功不代表业务功能验收通过。文档修改无需发布应用；测试仅在用户明确要求后执行。
