---
name: meta-verifier
description: Use when verifying a project, testing a product surface, reproducing a reported issue, or judging whether a system satisfies a demand-side goal
---

# Meta-verifier

当用户 `/meta-verifier <目标/问题>` 时，不要问用户选模式，按以下路由执行。

## 路由

用 `scripts/meta_verifier.py` 的 `MetaVerifierIntentRouter` 判断方向。

## 执行流程

### Agent 1: 理解目标与系统

用 Agent 工具启动 `agents/understand-goal.md`，传入用户的验证目标。

该 agent 输出：
- 用户意图文档（目标、成功标准、失败模式）
- 系统理解文档（入口、交互路径、需要的工具脚本）
- 参考 checklist

### Agent 2: 挑剔用户驱动系统

用 Agent 工具启动 `agents/demanding-user.md`，传入 Agent 1 的意图文档和系统理解文档。

该 agent 用 Bash + Selenium/curl/CLI 与系统交互，输出：
- 交互 trace
- 预期分析（每条成功标准是否满足）
- 发现的问题列表

### Agent 3: 问题归因（按需）

仅当 Agent 2 发现了问题且用户需要深入分析时，对每个问题启动 `agents/root-cause.md`。

该 agent ：
- 阅读项目代码找到根因
- 编写局部链路测试脚本验证
- 给出确定性的归因结论（文件、函数、行号、证据）

### 合成报告

- 有独立证据的 → confirmed
- 子进程主观判断 → unverified_reviewer_critique
- 用 `scripts/meta_verifier.py` 的 `MetaVerifierReportBuilder` 和 `MetaVerifierDemandCoverageAuditor` 做合成与安全检查

→ 证据规则：`references/evidence-standards.md`
→ finding 格式：`references/finding-format.md`
→ 审计门：`references/audit-gates.md`

## 铁律

- Agent 子进程是核心执行者，主 Claude 是编排者
- 没有 confirmed finding 时说明探了什么、为什么没确认、还有什么值得查。不要写"通过"
- 不可见面必须体现在 confidence impact 中

## 文件索引

| 文件 | 用途 |
|---|---|
| `agents/understand-goal.md` | 用户意图 + 系统理解 |
| `agents/demanding-user.md` | 执行交互 + 预期判断 |
| `agents/root-cause.md` | 问题归因 + 证据 |
| `references/workflow.md` | 详细流程 |
| `references/evidence-standards.md` | 证据规则 |
| `references/finding-format.md` | finding 格式 |
| `references/audit-gates.md` | 安全检查 |
| `protocols/meta_verifier_protocol.md` | 对象语义 |
| `scripts/meta_verifier.py` | 共享库：路由/schema/discovery/checklist/审计/报告 |
| `scripts/scan_surfaces.py` | CLI：扫描项目可验证面，输出 JSON |
| `scripts/validate_evidence.py` | CLI：验证 finding 证据引用完整性 |
| `scripts/render_report.py` | CLI：将 findings 渲染为 markdown 报告 |
