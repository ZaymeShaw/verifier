# 无 trace 场景主结论切到扩展轴的主轴（2026-10-18，待确认）

依据：用户 2026-10-18 决定——前后端整体切到扩展轴里的主轴（`eval_axes/adapters/fulfillment.py`，前端名"能力兑现"）；轴1 代码先保留不删；有业务 trace 的场景保持原样；新建预设默认带上主轴。不改主轴的结构（不往六轴"本应 / 实际"靠）。

## 1. 现状

- 每条 case 的链路：轴1 主判 → 归因（读主判结论）→ 聚类 → 校验 → 汇总表行 → 前端；扩展轴是之后的"判后 pass"，失败只记在 `run["eval_axes"]`，不碰主判结论（`impl/core/eval_axes.py` 隔离合同、`pipeline.py:461`）。
- 扩展轴的主轴与轴1 在无 trace 场景下是同一套判定（提示词逐字复制自 `LlmProbeJudge.build_context`，同走通用 `judge_trace`，输出字段同名）。差三处：能力描述取场景框描述而非 `capability_ref` 解析；可选吃真实性结果（D18）；模型输出不合规时轴记 failed（轴1 记 not_evaluable + 标记）。
- 有 trace 的场景：轴1 走 `ProcessJudgeExecution` → 六轴 → 冻结 E → `need_judge`，扩展轴报告挂在 `trace._pending_process_report`，判后 pass 直接拿来用（`eval_axes/__init__.py:62`）。本方案照这个已有模式做无 trace 场景。

## 2. 切换规则

`llm_probe` 项目内，按预设：

| 预设 | 主结论来源 |
|---|---|
| 有业务 trace | 不变（`need_judge`） |
| 无 trace，扩展轴里有**启用**的 fulfillment 框 | **扩展轴的主轴** |
| 无 trace，没有启用的 fulfillment 框 | 轴1（沿用，作为兜底） |

注意：按此规则，**已有预设里已经启用了 fulfillment 框的会立即切过去**（配置不改，行为变）：当前 8031 实例里是 `client_search`（fulfillment + carryability）、`hr-handbook-qa`、`policy-clause-qa`、`verify-insurance-mcp`（后三个带知识查证 + 真实性）。`dashscope-qa`、`marketting-planning-intent`、`policy_search` 没有框，仍走轴1。

## 3. 怎么改

### 3.1 后端（只改 llm_probe 项目内 + core 一处注释）

1. `impl/projects/llm_probe/judge.py`：`LlmProbeJudge.judge_execution()` 加一个分支——无 trace 且预设有启用的 fulfillment 框时，返回新的 `ExtendedAxesJudgeExecution`；否则照旧 `SinglePassJudgeExecution`（轴1 代码不删）。
2. `ExtendedAxesJudgeExecution.run`：`build_report(spec, trace)` 跑该预设全部启用的框（知识查证、真实性、主轴、承载性……按依赖顺序，与现在判后 pass 完全相同）→ 取 fulfillment 结果：
   - succeeded：其 output（字段与 `JudgeResult` 同名）构造 `JudgeResult` 返回；
   - failed / blocked：返回带 `evaluation_execution_failed` 标记的 `JudgeResult`（终态失败），链路照现在轴1 失败的处理走（整条 run 记 error，前端"补跑执行失败"可挑出）。
   - 报告挂到 `trace._pending_process_report`，判后 pass（`run_for_trace`）直接拿走，**不重跑**，不多花调用。
3. 下游（归因、聚类、校验、汇总表、导出）读的都是 `JudgeResult`，不改。
4. `impl/core/eval_axes.py` 顶部"扩展轴失败不碰 JudgeResult"的隔离合同改一句：对 llm_probe 无 trace 且启用主轴框的预设，主轴就是主结论来源，它失败即主判失败；其余扩展框仍守隔离合同。

### 3.2 前端

1. 汇总页、Live 页的主结论处标来源："主轴（扩展）"或"轴1"（读 run 里新增的一个来源字段，如 `judge.evidence` 里的 `{"kind": "main_axis_source", "value": "eval_axes.fulfillment" | "axis1"}`，不改 JudgeResult 结构）。
2. 扩展轴面板里主轴那一格不再标"试验"、不再与主结论重复展示判定，只给"即主结论"的指引。
3. 资料页：
   - 新建预设时，扩展评估轴默认带一个**已启用**的"能力兑现"框，描述预填能力描述（沿用现有"新建框预填旧字段"的逻辑，`materials.html:702`）；
   - "能力描述（轴1：……）"一栏改注为"未启用主轴框时轴1 使用"；扩展轴区去掉"（试验）""不影响上面"等字样中关于主轴的部分。
4. 轴1 的前端代码不删，只是不再作为默认入口（"软去掉"）。

## 4. 不做

- 不删轴1、轴2 的前后端代码。
- 不动有 trace 场景的主判。
- 不改主轴结构（不引入六轴"本应 / 实际"、不加 `claim_refs`）。
- 不改已有预设的配置数据。
- 扩展轴2（承载性框）是否同样替换生产轴2，本次不定（只切主结论）。

## 5. 已知风险 / 待定

- 已定（2026-10-18 用户）：主轴依赖知识查证 / 真实性。预设里启用了的上游框（主轴的依赖链：真实性 ← 知识查证）只要没成功（failed / blocked），整条 case 判执行失败，不降级照判。
- 耗时：带知识查证的预设，主结论要等知识查证 + 真实性跑完（MCP 场景单条 3–10 分钟），批量会明显变慢；不多花调用（原来判后 pass 也要跑），只是从"后台附加"变成"主路径"。
- `client_search` 预设的主轴框描述与它的能力描述是否一致，切换前要核一次，否则这个预设的结论会因描述不同而变。

## 6. 验证

1. 单测：判定执行分支选择（三种预设）、报告复用不重跑、主轴失败 → 终态失败、来源标记。
2. 实跑（8031）：`verify-insurance-mcp` 10 条、`policy-clause-qa`、`hr-handbook-qa`、`client_search` 各几条、一条 trace 预设、一条无框预设，经 `/api/run_chain` 与批量各跑一遍：主结论 = 主轴输出；归因 / 聚类 / 汇总表拿到同一结论；判后 pass 未重跑（看调用数）；前端来源标记正确。
3. 全量测试对比基线，不新增失败。

## 7. 反悔

一个 commit（后端）+ 一个 commit（前端），`git revert` 即回到轴1；单个预设可通过关闭主轴框回到轴1。
