---
doc_type: startup
schema_version: 1
---

# DeerFlow Gateway 启动说明

- 前置条件：`${DEERFLOW_REPO}` 指向 deer-flow 仓库，依赖和 Gateway 运行环境已安装。
- 启动方式：verifier 在需要时执行 `impl/projects/deerflow/scripts/start.sh`，该脚本从 `${DEERFLOW_REPO}` 启动业务服务。
- 健康检查：轮询 `GET http://127.0.0.1:8001/health`；地址可由已登记的 `DEERFLOW_BASE_URL` 覆盖。
- 成功信号：健康接口返回 2xx/3xx 后开始测评，测评结束不主动停止服务。
- 常见失败：仓库变量缺失、启动脚本不可执行、8001 端口冲突、依赖未安装或健康检查超时。
