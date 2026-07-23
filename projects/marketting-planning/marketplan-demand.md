---
doc_type: requirements
schema_version: 1
---

# 营销规划测评需求

- 业务目标：评估多轮、阶段化、SSE 输出的营销规划智能体能否正确识别目标、澄清信息并形成规划结果。
- 范围：意图、澄清、会话字段累积、规划执行、fallback、非智能体意图和流式协议。
- 非目标：不评估部署机器差异，不在本文保存本地绝对路径，也不替业务仓库执行代码同步或发布。
- 核心场景：意图识别、澄清、多轮字段累积、执行规划、数据不可用兜底和 SSE 完整性。

本项目仓库位于 https://github.com/PA-ALG/marketing-planning，本地源码通过 `${MARKETTING_PLANNING_REPO}` 路由。

# 初始化

当本地仓库不存在时，进行初始化
1. 从远程仓库初始化项目到 `${MARKETTING_PLANNING_REPO}`
    + 不要重新拉取新代码或推送代码到该仓库，除非用户显式要求
2. 按项目流程进行初始化，启动服务

# 分歧点

1. 分析该业务项目如果接入当前评估系统，主要的分歧点和坑点是什么地方（分歧点分析记录在impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md）



分歧点处理方案请参考：reviews-of-propose/20260611-marketplan-integration-risks.md
