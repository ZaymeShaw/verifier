# Verification Workflow

meta-verifier 每次执行的详细步骤。SKILL.md 是路由入口，这里是展开说明。

## Agent 1: 理解目标与系统

**触发**：每次 `/meta-verifier` 调用

**调用**：
```
Agent 工具
  subagent_type: general-purpose
  description: "Understand goal: <用户目标>"
  prompt: 按 agents/understand-goal.md 模板填充
```

**输入**：用户原始验证目标、项目根目录、入口 URL（如有）

**输出**：
- 用户意图文档（目标、成功标准、失败模式）
- 系统理解文档（入口、交互路径、需要的工具脚本）
- 参考 checklist

**质量要求**：
- 成功标准必须具体可验证（不能是"系统好用"）
- 交互路径必须包含具体操作步骤
- checklist 每项必须标注来源文件

## Agent 2: 挑剔用户驱动系统

**触发**：Agent 1 完成后

**调用**：
```
Agent 工具
  subagent_type: general-purpose
  description: "Demanding user: <用户目标>"
  prompt: 按 agents/demanding-user.md 模板填充，传入 Agent 1 的输出
```

**输入**：Agent 1 的意图文档 + 系统理解文档

**执行**：
1. 用 Bash + Selenium/curl/CLI 与系统交互
2. 记录每一步操作和系统反应（交互 trace）
3. 逐条判断成功标准是否满足
4. 记录发现的问题

**输出**：
- 交互 trace
- 预期分析（每条成功标准的判定 + 实际结果）
- 问题列表（FINDING ... END_FINDING 格式）

**质量要求**：
- 必须真的执行交互，不能用 WebFetch 读 HTML 代替
- 每条问题必须有具体证据（截图路径、日志、响应内容）

## Agent 3: 问题归因（按需）

**触发**：Agent 2 发现 confirmed/high-severity 问题时

**调用**：
```
Agent 工具
  subagent_type: general-purpose
  description: "Root cause: <问题简述>"
  prompt: 按 agents/root-cause.md 模板填充
```

**输入**：问题描述 + Agent 2 的交互 trace

**执行**：
1. 阅读相关项目代码
2. 编写局部链路测试脚本（import 项目代码，不是 mock）
3. 逐段验证链路，定位偏离点

**输出**：
- 归因结论（文件、函数、行号）
- 证据（链路测试输出、代码分析）
- 修复建议

**质量要求**：
- 不能使用"可能""也许""大概"
- 必须有可复现的链路测试证据

## 合成报告

1. Agent 2/3 的发现中，有独立证据的 → confirmed
2. 纯主观判断 → unverified_reviewer_critique
3. 用 `MetaVerifierReportBuilder` 合成
4. 用 `MetaVerifierDemandCoverageAuditor` 做安全检查
5. 按 `references/finding-format.md` 格式化
6. 按 `references/audit-gates.md` 检查 pass theater

## 铁律

- Agent 子进程是执行者，主 Claude 是编排者
- 没有 confirmed finding → 说明探了什么、为什么没确认、还有什么值得查。不写"通过"
- 不可见面必须体现在 confidence impact 中
