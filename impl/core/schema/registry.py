from __future__ import annotations

# 当前 schema 分层登记表：用于 check/listing 快速判断用户提到的核心概念是否已有归属。
SCHEMA_LAYERS = {
    "base": "基础执行记录、质量门、状态迁移和通用序列化工具",
    "project": "项目配置与 analysis agent 交接结果",
    "mock": "测试输入、mock case、mock 数据集",
    "live": "业务系统实时请求、响应和多轮 live 状态",
    "trace": "业务执行链路和多轮 trace 聚合",
    "judge": "业务期望、满足度评估和最终裁决",
    "attribute": "归因证据链、根因和修复方向",
    "frontend": "前端通用 ViewModel",
    "table": "summary/case-pool 表格 View",
    "cluster": "归因聚类摘要",
    "check": "标准化审查报告",
    "batch": "批量运行聚合结果",
    "config": "schema 分层和项目配置声明",
    "fallback": "兜底/降级决策、原因、缺失证据和质量状态",
    "evidence": "执行链路事件、证据引用和探针结果",
}
