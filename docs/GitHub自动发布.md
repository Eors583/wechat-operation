# GitHub 构建与生产发布

入口：仓库 Actions → **Production release** → **Run workflow**，分支选择 `main`，
服务选择 `backend`、`user` 或 `admin`。每次仅构建和切换选中的服务。

该工作流独立于 `suite-ci`，只运行对应项目 lint 和生产镜像构建，不运行测试。
手动选择服务启动后，构建、推送、源码交付、拉取及切换均自动执行。
`[skip ci]` 不影响手动触发此工作流；不要直接启动包含测试的 `suite-ci` 代替发布。

## 镜像和凭据

- GitHub 托管的 Ubuntu runner 构建 `linux/amd64`，版本固定为 `git-<7位Git SHA>`。
- 镜像：`ghcr.io/eors583/wechat-ai-backend`、`wechat-ai-user`、`wechat-ai-admin`。
- 构建 job 的 `GITHUB_TOKEN` 只有代码读取及包写入权限。
- 部署 job 使用独立的临时 `GITHUB_TOKEN`，只有代码读取及包读取权限。
- 服务器通过 SSH 标准输入接收临时令牌，执行 `docker login --password-stdin`；
  Docker 登录配置放在临时目录，退出时删除。令牌不写入 `.env.server` 或源码。
- 镜像按构建返回的 SHA-256 digest 拉取，再检查平台与完整 Git revision 标签。
- 服务器拉取超过 3 分钟或仓库不可达时，自动回退到 GitHub runner 下载同一 digest，
  压缩后经 SSH 交付；校验归档 SHA-256、镜像配置摘要、文件层、平台和 Git revision 后才切换。
  发布摘要和回滚记录明确标记交付方式；回退同样不使用本机或服务器构建。
- production 环境只允许 `main` 分支，存放 `PRODUCTION_SSH_KEY`、
  `PRODUCTION_KNOWN_HOSTS` 两个 Secret，以及 `PRODUCTION_HOST` 变量。
- 部署密钥为专用 Ed25519 密钥。服务器授权采用 `restrict` 与 forced command，
  仅允许上传本仓库 Git bundle 和执行指定服务发布，不提供交互 shell、端口或 agent 转发。

## 服务器部署入口

一次性由管理员安装：

```bash
install -d -m 700 /usr/local/lib/wechat-ci
install -m 700 scripts/ci-ssh-entry.sh /usr/local/sbin/wechat-ci-entry
install -m 700 scripts/deploy-ci-release.sh /usr/local/lib/wechat-ci/deploy-ci-release.sh
```

将专用公钥添加到 root 的 `authorized_keys`，前缀为：

```text
restrict,command="/usr/local/sbin/wechat-ci-entry" ssh-ed25519 <专用公钥>
```

以上两个入口固定安装在仓库外；修改它们后须由管理员重新安装，不通过更新仓库隐式改变
SSH 授权入口。不要将个人日常 SSH 私钥上传到 GitHub。

服务器运行目录为 `/opt/wechat-operation`。Git bundle 让源码交付不依赖服务器访问 GitHub；
生产 checkout 必须干净，且只允许快进到构建所用提交。旧版本或分叉提交会被拒绝。

## 服务切换与回滚

遵循《运维与恢复手册》的生产运行边界：服务器不安装依赖、不构建应用镜像。

| 服务 | 仓库变量 | 版本变量 | 切换容器 |
| --- | --- | --- | --- |
| backend | BACKEND_IMAGE_REPOSITORY | BACKEND_VERSION | backend-api、worker、scheduler |
| user | USER_WEB_IMAGE_REPOSITORY | USER_WEB_VERSION | user-web |
| admin | ADMIN_WEB_IMAGE_REPOSITORY | ADMIN_WEB_VERSION | admin-web |

发布会先记录旧仓库、版本和镜像 ID 到 `.deploy-images/ci-*-rollback.txt`，拉取成功后
原子更新 `.env.server`，以 `--no-build --no-deps` 切换选中服务并重启网关。
切换命令失败时，仅恢复选中服务的旧仓库和版本。功能验收失败时，管理员按回滚记录恢复。
首次切换 GHCR 时，保留旧仓库镜像，并为它建立新仓库的本地别名供清理脚本保留。
成功切换后执行 `prune-release-images.sh`，保留当前和上一版。

数据库 migration 文件与上一后端版本不同时，本工作流会在切换前停止，提示按运维手册
完成备份与显式单次迁移流程；不会在 API 启动或普通发布中自动执行迁移。

工作流成功代表 lint、镜像构建、交付和服务切换完成，不代表功能测试通过。
生产功能由用户手动验收，只有明确要求测试后才执行自动化或冒烟测试。
