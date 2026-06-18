## Why

新版 `demand.md` 明确要求 verifier 不只是能跑 mock/live/judge/attribute，而是要用协议把 analysis、application、build、mock、judge、attribute、check 等 agent 的职责、产物和项目实现边界串起来。当前项目虽然已有 `impl/core`、`impl/protocols`、`impl/projects`、前端和批量链路，但按 `check.md` 审核后仍存在职责边界不够可执行、项目实现产物不够标准化、前端/live/summary 与 agent 协议缺少统一校验、judge/attribute 边界落地依赖项目自由实现等问题。

## What Changes

- 建立面向新版 `demand.md` 的 agent 职责协议，明确 analysis、application、build、mock、judge、attribute、check 分别对哪类产物和代码负责，而不是按“是否写代码”粗暴划分。
- 为 `impl/projects/<project>` 增加可检查的项目实现清单，要求每个项目显式声明 API、应用运行方式、mock 输入、output/reference 处理、judge 边界、attribute trace、frontend 展示和批量持久化策略。
- 补齐 build agent / 前端实现规范，使 live 请求页和归因总结页不依赖项目临时拼接，而是按前端协议消费项目级展示配置。
- 强化 judge boundary 协议落地：边界应由项目资料和用户填写模板确定，并通过流程化 gate/配置进入项目 judge，而不是每次由 judge prompt 临时判断。
- 强化 attribute trace 协议落地：归因必须基于当前 case 的 trace、代码链路、局部验证或项目文档证据，不能只给模块级模糊原因。
- 增加 check agent 审核能力：按 `check.md` 对协议一致性、过拟合风险、死旧路径、批量/持久化、前端/API 一致性输出中文 issue 报告，并把发现的问题转成后续修复任务。
- 增加针对现有 QA、client_search、marketting-planning、marketting-planning-intent 的兼容性检查，避免协议收敛破坏已有项目。

## Capabilities

### New Capabilities
- `agent-role-protocol`: 定义各 agent 的职责边界、触发时机、输入输出产物、可写代码范围和交接关系。
- `project-implementation-standard`: 定义每个 `impl/projects/<project>` 必须具备的项目级标准、配置、实现清单和自检要求。
- `project-frontend-standard`: 定义项目 live 请求页、归因总结页、output/reference 展示、上传/保存/批量归因的协议式接入要求。
- `judge-boundary-implementation`: 定义责任边界模板如何转成项目 judge 的流程化 gate，而不是 prompt 临时判断。
- `attribute-trace-implementation`: 定义项目 trace、局部链路验证、归因证据链和修复建议的结构化实现要求。
- `check-driven-gap-reporting`: 定义 check agent 如何按新版 demand/check 审计当前项目缺口，并产出可执行 issue/check 报告。

### Modified Capabilities
<!-- No existing archived OpenSpec capability is modified; this change derives new executable standards from the updated demand document. -->

## Impact

- Affected implementation areas: `impl/protocols`, `impl/projects/*`, `impl/core/judge.py`, `impl/core/attribute.py`, `impl/core/frontend_view.py`, `impl/frontend/live.html`, `impl/frontend/summary.html`, `impl/core/pipeline.py`, project adapters and project docs.
- Affected docs/check reports: `search-test-case/issue`, project-level checklist/evaluation/attribution/application/mock docs, and demand-derived templates such as `impl/judge_boundary-template.md`.
- Affected tests: project loader, protocol alignment, frontend summary/live behavior, judge boundary gates, attribution evidence grounding, batch resilience, and cross-project compatibility tests.
- No external business repositories should be modified as part of this change.
