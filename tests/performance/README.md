# 性能测试

`k6-smoke.js` 通过 `PROFILE` 覆盖普通 API、文章库、SSE 断线续传、真实分片上传、Worker 状态和 AI 入队。默认只执行无副作用的 `smoke`；其余场景必须使用隔离的测试环境和预置测试数据。

```bash
k6 run tests/performance/k6-smoke.js
k6 run -e PROFILE=api -e BASE_URL=https://test.example.com tests/performance/k6-smoke.js
k6 run -e PROFILE=library -e ACCESS_TOKEN=... tests/performance/k6-smoke.js
k6 run -e PROFILE=sse -e ACCESS_TOKEN=... -e RUN_IDS=id1,id2 tests/performance/k6-smoke.js
k6 run -e PROFILE=upload -e ACCESS_TOKEN=... -e VUS=10 tests/performance/k6-smoke.js
k6 run -e PROFILE=worker -e ADMIN_ACCESS_TOKEN=... -e JOB_IDS=id1,id2 tests/performance/k6-smoke.js
k6 run -e PROFILE=ai -e ACCESS_TOKEN=... -e TASK_IDS=id1,id2 -e VUS=50 tests/performance/k6-smoke.js
```

AI 并发按 `VUS=20`、`50`、`100`、`200` 分级执行；每一级都必须同时观察 RabbitMQ 队列、模型 RPM/TPM、失败率、额度结算和成本。`TASK_IDS` 应包含足够多的预置任务，避免用单任务锁竞争冒充真实平台并发。

普通 API 和文章库阈值为 P95 小于 300ms。SSE、上传、Worker 和 AI 的耗时包含外部系统或异步处理，分别记录，不用普通 HTTP 阈值替代。完整检索需要在独立检索库中用真实 100-300 条问题集执行；本脚本的文章库 `query` 只验证列表搜索，不能作为全文+向量+Rerank 延迟证据。

真实检索验收使用后端基准程序。问题集为 JSONL，每行遵循 `retrieval-dataset.schema.json`，必须引用隔离压测库中真实存在的 owner、资料和人工标注的相关 chunk/document。程序先预计算查询向量并单独计时 PostgreSQL 全文 + pgvector + RRF，再计时包含 Embedding、Rerank 和检索审计写入的完整链路；任一阈值失败都会以非零状态退出。

```bash
uv run --project services/platform-backend \
  python services/platform-backend/scripts/retrieval_benchmark.py \
  --dataset /secure/evaluation/retrieval-questions.jsonl \
  --output /secure/evaluation/retrieval-report.json
```

运行环境必须提供 `RETRIEVAL_DATABASE_URL`、`EMBEDDING_API_BASE`、`EMBEDDING_API_KEY_REF`、`EMBEDDING_MODEL`、`RERANK_API_BASE`、`RERANK_API_KEY_REF` 和 `RERANK_MODEL`；密钥通过 `env:` 或 `file:` 引用解析。默认门禁与技术设计一致：100—300 题、权限泄露 0、纯检索 P95 < 300ms、完整检索 P95 ≤ 2000ms、两段 Recall@10 均不低于 90%。评测问题和逐题结果可能包含真实业务信息，不提交仓库；汇总报告也只能进入受控验收制品。

任何包含 Token 的命令输出和结果文件都不得提交；测试后撤销测试会话并清理性能数据。
