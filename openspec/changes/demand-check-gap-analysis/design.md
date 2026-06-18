## Context

新版 `demand.md` 把 verifier 的目标从“能运行一条评估链路”提升为“用协议约束各 agent 的产物、实现和检查闭环”。当前项目已有 `impl/protocols`、`impl/core`、`impl/projects/*`、live/summary 前端、批量运行、judge、attribute、cluster、check 等能力，但这些能力主要是通过已有工程结构和项目 adapter 组合起来，缺少面向 agent 责任边界的可执行标准。

按 `check.md` 审核，当前主要缺口不是单个功能不可用，而是机制层面不够清晰：analysis、application、build、mock、judge、attribute、check 都会产出代码或项目文件，但没有协议明确它们分别对哪类代码和结果负责；trace 运行时、trace 运行后、预构建批量数据这些触发边界还没有沉淀成可执行协议；`impl/projects/<project>` 的项目级文档和实现清单不统一；前端 live/summary 和 output/reference 展示缺少项目级标准输入；judge boundary 与 attribute trace 的要求仍容易落成 prompt 临时判断或模糊归因；check report 也需要能把这些机制缺口转成可执行的变更任务。

## Goals / Non-Goals

**Goals:**

- 将新版 `demand.md` 中的 agent 角色、协议、模板、前端、judge boundary、attribute trace 和 check 要求转成可测试的 OpenSpec 需求。
- 明确 agent 边界按“对哪类能力结果负责”划分，而不是按“是否写代码”划分。
- 为 `impl/projects/<project>` 建立统一项目实现标准，使项目级 API、application、mock、judge、attribute、frontend、batch/persistence 都可检查。
- 建立 build/frontend 协议，让 live 请求页和归因总结页按项目标准展示 output/reference、judge、attribute、cluster/check 信息。
- 让 judge boundary 通过模板/项目标准转成流程化 gate 或结构化配置，而不是每个 judge 运行时临时判断边界。
- 让 attribute trace 基于当前 case、业务链路、局部验证或项目文档证据输出可修复归因。
- 让 check agent 产出中文、可执行、带证据的缺口报告，并覆盖协议一致性、过拟合、死旧路径、批量/持久化和跨项目兼容。

**Non-Goals:**

- 不在本变更中重写所有已有项目 adapter 或替换统一 pipeline。
- 不修改任何外部业务仓库。
- 不把 check agent 变成默认主实现者；check 仍是审核和纠偏角色。
- 不把所有代码统一归给 application 或 analysis；judge、attribute、mock、application、build 都保留各自能力实现责任。
- 不新增与现有 `/api/run_chain`、`/api/batch_start`、`/api/batch_status` 并行的项目私有主链路。

## Decisions

### Decision 1: Agent 边界按能力 ownership 划分

每个 agent 可以写自己能力范围内的代码或项目文件：analysis 负责项目理解与标准提取，application 负责业务服务运行和 output 获取，build 负责项目前端实现，mock 负责输入/意图生成，judge 负责正确性判断，attribute 负责错误归因，check 负责审核与纠偏。边界不再用“谁写代码”划分，而是用“谁对哪类能力结果负责”划分。

Alternative considered: 设置一个统一 implementation agent 写所有代码。这个方案能减少角色交叉，但会削弱 judge/attribute/mock/application 对自身能力质量的 ownership，也不符合 `demand.md` 中这些 agent 需要在 `impl/project` 构建强能力的要求。

### Decision 2: 增加 project implementation standard 作为交接面

`impl/projects/<project>` 必须有可检查的项目实现清单，声明 API、application、mock、output/reference、judge boundary、attribute trace、frontend、batch/persistence、check 证据。这样各 agent 的产物能落到同一个项目标准，而不是各写各的孤立文档或代码。

Alternative considered: 继续靠 `project.yaml` + adapter 约定。这个方案工程成本低，但无法承载新版 `demand.md` 对模板、边界、前端、归因证据、check 闭环的要求。

### Decision 3: Frontend 由 build agent 标准化，但消费项目协议

build agent 负责项目前端实现和展示标准，但不直接硬编码业务逻辑。live 请求页和 summary 页应从项目级标准/前端视图协议获取 output/reference 字段选择、格式化、截断、judge/attribute 展示和持久化策略。

Alternative considered: 每个项目独立写专属前端。这个方案短期直观，但会造成 API、case-pool、batch、持久化、展示字段分裂，违反 check.md 的 split-brain 风险要求。

### Decision 4: Judge boundary 必须流程化落地

责任边界应由 `impl/judge_boundary-template.md`、用户项目资料和 analysis/application 输出确定，再由 judge agent 转成项目 judge 的流程化 gate 或结构化配置。LLM judge 可以解释语义，但不能每次运行时重新发明责任边界。

Alternative considered: 让 judge prompt 自行判断边界。这个方案灵活，但不可复现、不可检查，容易同一项目不同 case 标准漂移。

### Decision 5: Attribute trace 必须可追溯到当前 case 证据

attribute agent 的输出必须引用当前 query、output、reference、judge 结果、trace 节点、项目代码/配置/文档或局部链路验证。若无法定位根因，应明确归因不足并给出下一步验证，而不是输出模块级模糊原因。

Alternative considered: 允许 attribute 只给高层模块猜测。这个方案生成快，但不满足 `demand.md` 中“开发看了知道怎么修”的要求。

### Decision 6: Check report 是机制审计结果，不是手工验收摘要

check agent 需要按 `check.md` 审核产生机制，包括协议源头、项目标准、前后端一致性、batch/persistence、judge/attribute 证据、过拟合和死旧路径。报告应记录 evidence、root cause、fix、verification，并能转成后续任务。

Alternative considered: 只在功能跑通后写 checklist。这个方案会漏掉 display-only fix、本地 sample patch、stale mapping 和 split-brain implementation。

## Risks / Trade-offs

- 协议过重导致简单项目接入成本上升 → 项目实现清单只要求最小必填项，复杂字段可选，但必须能检查缺失项。
- 收敛协议时破坏现有 QA/client_search/marketting-planning 行为 → 每个阶段增加跨项目兼容测试和 representative run/batch smoke。
- Judge boundary 配置过度规则化导致过拟合 → boundary 只表达责任边界和评估范围，不写历史 case 特例；check agent 审核硬编码风险。
- Attribute trace 难以对所有外部系统做局部验证 → 允许记录“证据不足/需验证”的未完成归因，但不允许伪造 root cause。
- Frontend 标准化可能隐藏项目关键字段 → 项目级 frontend view 显式声明字段选择、截断和格式转换策略，保留详情展开能力。
