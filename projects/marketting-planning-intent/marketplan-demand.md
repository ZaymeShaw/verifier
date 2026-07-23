---
doc_type: requirements
schema_version: 1
---

# 营销规划意图识别测评需求

- 业务目标：单独评估营销规划服务是否把用户表达识别为正确的 NBEV 业务意图。
- 范围：单轮意图标签、置信度、必要槽位以及 unknown/fallback 行为。
- 非目标：不评估完整多轮规划结果，不在本文保存本地绝对路径，也不负责业务仓库发布。
- 核心场景：客户画像、队伍画像、NBEV 规划、规划兜底、达成测算调整、目标值调整和其他意图。

本项目仓库位于 https://github.com/PA-ALG/marketing-planning，本地源码通过 `${MARKETTING_PLANNING_INTENT_REPO}` 路由。

# 初始化

当本地仓库不存在时，进行初始化
1. 从远程仓库初始化项目到 `${MARKETTING_PLANNING_INTENT_REPO}`
    + 不要重新拉取新代码或推送代码到该仓库，除非用户显式要求
2. 按项目流程进行初始化，启动服务

1. 核心处理接口是/api/v1/marketing-planning/intent-recognition，这个接口是单轮的，所以你不用处理多轮了暂时

# 分歧点

1. 分析该业务项目如果接入当前评估系统，主要的分歧点和坑点是什么地方（分歧点分析记录在impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md）



分歧点处理方案请参考：reviews-of-propose/20260611-marketplan-integration-risks.md
