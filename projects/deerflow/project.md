---
doc_type: requirements
schema_version: 1
---

# DeerFlow 测评需求

- 业务目标：评估基于 DeerFlow Gateway 的多轮营销规划智能体能否持续理解用户目标并形成可执行规划。
- 范围：thread 创建、逐轮消息、澄清、规划、多维度累积、tool calls、回复提取和外部依赖失败。
- 非目标：不测评网页登录 UI，不把某台机器的仓库路径或账号凭据作为项目要求。
- 核心场景：单轮规划、多轮维度累积、澄清、权限边界、非智能体意图和服务不可用。

业务源码由 `${DEERFLOW_REPO}` 路由；参考远程仓库为 `https://github.com/PA-ALG/deer-flow/tree/feat/marketing-planning-agent`，目标分支为 `feat/marketing-planning-agent`。
