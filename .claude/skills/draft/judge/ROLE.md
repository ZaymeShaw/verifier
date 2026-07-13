---
name: draft-judge
description: draft skill 的 judge 角色专属扩展。定位、状态档位、case 字段派生、tool 边界（默认屏蔽内部代码）、对比脚本入口。
---

# Draft · Judge 角色

本文件是 `/draft` skill 在 judge 角色下的专属扩展。通用 draft 机制见 `../SKILL.md` 与 `verifier/spec/draft/draft.md`，本文件只补充 judge 角色特有的部分。

## 角色定位

**Judge** = 业务角度评估系统输出是否满足意图（外部/业务视角）。**只看业务系统输入输出**，不看代码。区别于 attribute（attribute 看代码链路）。

draft judge 的典型场景：当前 production `judge.py` 的判定输出在某些 case 上覆盖不准、判定域字段混乱、把 not_evaluable 包装成 fulfilled、或业务期望提取与项目实际业务语义不对齐。draft 要在 `impl/projects/<project>/draft/judge.py` 下重写 `build_context` 等扩展点，引入项目特有业务期望提取逻辑、判定边界、fulfillment 评估策略，让判定输出更贴合项目业务语义。

## 协议自省

```bash
$(读取 impl/config.yaml 的 python.executable) .claude/skills/draft/scripts/introspect_protocol.py impl/core/judge_protocol.py
```

输出 judge 当前协议的方法表（实际以脚本输出为准，不预判）：

- 模板方法：`judge_trace`（不可覆盖）
- 内部方法：`_run_llm_judge` / `_validate_judge_output`（不可覆盖）
- 必须实现：`build_context(self, trace) -> Dict[str, Any]`
- 可选覆盖：`pre_judge` / `build_intent_frame` / `reconcile_result` / `normalize_result`

## 角色特异部分（draft 机制不预判，本文件填）

### case 字段（从当前 `ProjectJudge.judge_trace` 模板方法签名派生）

模板方法签名：`judge_trace(self, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult`

→ 每个 case 至少包含：

- `case_key`：case 标识。
- `trace: RunTrace`：判定输入。
- `expected_intent: Optional[str]`：项目侧声明的预期意图（若有）。
- `expected_check`：用户给出的"期望"——该 case 下 draft 应输出什么样的判定/期望提取才算合格。**期望由用户在 config 或 case 数据中给出，不由 skill 自动猜测**。

注意：judge case **不携带 judge_result**——judge 自己产 `JudgeResult`，不像 attribute case 携带上游 judge_result。

### `_run_judge` / `_result_summary` / `_case_status`

实现在 `scripts/compare_judge.py`：

- `_run_judge(impl, spec, adapter, case)`：从 case 取 `trace` + `expected_intent` 喂给 `impl.judge_trace(trace, expected_intent=expected_intent)`。
- `_result_summary(result)`：抽 `JudgeResult` 的 `overall_fulfillment` / `fulfillment_assessments` / `business_expectations` / `missing` / `wrong` / `extra` / `evidence` / `reasoning_summary` / `summary`。
- `_case_status(case)`：judge case 不自带 judge_result，从 `case.expected_check.expected_status` 取用户给的期望状态，没有则 `unknown`。

## 角色特异门禁

judge 角色特有的门禁（通用门禁见 `../SKILL.md`）：

- **业务期望提取**：draft 要从 trace 提取贴合项目业务语义的 `business_expectations`，不套用其他项目的字段模板（防止把别的项目的字段混进来）。
- **判定状态档位**：`overall_fulfillment.status` 取 `fulfilled` / `not_fulfilled` / `not_evaluable`（沿用通用层 judge.py 的 `_FULFILLMENT_STATUS_VOCAB`，不重建）。
- **不伪造判定**：不把 `not_evaluable` 包装成 `fulfilled` 或 `not_fulfilled`；expected/reference/actual 缺失时倾向 `not_evaluable`，不强行 `fulfilled` 或 `not_fulfilled`。
- **不伪造 confidence**：evidence 缺失或 tool/probe failed 时不伪造 high confidence。
- **fulfilled case 不强判失败**：draft 不能为了"显示找问题能力"而把 fulfilled case 改成 not_fulfilled——判定要基于业务输入输出证据。

## 判定状态档位

`JudgeResult.overall_fulfillment.status` 的档位见上方"角色特异门禁"。

## 对比脚本

`scripts/compare_judge.py` 的 `compare_judge_outputs(spec, adapter, cases, current_impl, draft_impl)`：

- 同一批冻结 case，current 和 draft 各跑一遍。
- 比"判定准确性 / 业务期望提取 / 不过拟合 / 不伪造"，不比刷分。
- **异常直接冒泡，不吞**——任一 case 抛异常即终止本次对比，不生成可用于 promotion 的报告。
- `decision_rule`：draft 在判定准确性/业务期望提取任一维度优于 current 且不弱于其他维度，且不伪造判定、不引入 overfit → 可考虑 promotion。Blocked case 不计入。

## tool 边界

judge 角色的 draft tool 默认**屏蔽内部代码信息**——judge 是外部业务视角，不应该看业务系统代码：

- **不允许**接入看业务系统代码的 tool（与 attribute 区分）。自检逐个审查 `build_context` 返回的 tools；任何读取项目源码、文件路径、符号表或代码搜索结果的能力都直接失败，不进入对比。
- **允许**接入调用业务系统接口做 probe 的 tool（如 semantic equivalence / output schema check / boundary check），但只做外部视角的输入输出验证。
- **允许**复用项目已有 adapter comparison / runtime check / production tool，但只取业务输入输出相关字段。
- 用户在 config 中显式声明允许 judge 接入看代码的 tool 时，才允许（用户有自己的使用期望）；默认屏蔽。

draft tool 必须用现有 `impl/tools/protocol.py` 的 `VerifiableTool` / `ToolResult` 协议，不另造。tool 经 `ToolRegistry` + `ToolOrchestrator` + `agno 桥接`调度，不绕过统一 orchestrator。draft tool 写在 `impl/projects/<project>/draft/tools/` 下，不被 production loader 自动加载。

## promotion 前置

按 spec 阶段 6：

- `draft/judge.py` 可 import，`__init_subclass__` 不报错。
- `judge_trace()` 返回最小 `JudgeResult`，`overall_fulfillment.status` 在 `{fulfilled, not_fulfilled, not_evaluable}` 内。
- 代表 case 的 targeted run 或局部函数验证通过。
- mock 对比报告显示 draft 在判定准确性/业务期望提取/泛化风险上优于或不弱于 current。
- 不伪造 not_evaluable → fulfilled。
- production loader 不加载 draft；judge draft 固定由对比脚本 direct import 离线运行，不新增 `judge_draft` loader 开关。人工确认后直接覆盖 production `judge.py`。
- 人工确认后直接覆盖 `draft/judge.py` → `judge.py`；judge 不配置 `judge_draft` loader 开关。

## 与现有 attribute skill 的关系

`/draft` skill 的 judge 子目录是新增——现有 `/attribute` skill 不覆盖 judge draft。当前阶段 `/draft` skill 同时提供 attribute 和 judge 两条 draft 路径，但 `attribute` 路径暂时与 `/attribute` skill 并存（互不修改）；judge 路径直接由 `/draft` skill 承担。
