---
name: draft-attribute
description: draft skill 的 attribute 角色专属扩展。定位、强度档位、case 字段派生、tool 边界、对比脚本入口。
---

# Draft · Attribute 角色

本文件是 `/draft` skill 在 attribute 角色下的专属扩展。通用 draft 机制见 `../SKILL.md` 与 `verifier/spec/draft/draft.md`，本文件只补充 attribute 角色特有的部分。

## 角色定位

**Attribute** = 系统不及预期时，从**代码链路**做内部归因审视（内部/技术视角）。会看业务系统代码、运行时 trace、tool/probe 输出，定位根因到**可修改点**。区别于 judge（judge 只看业务系统输入输出，不看代码）。

draft attribute 的典型场景：当前 production `attribute.py` 的归因输出停在模块名（"intent_recognition" / "intent_contract_gate"），没下沉到具体 tool / 具体代码路径 / 具体配置项。draft 要在 `impl/projects/<project>/draft/attribute.py` 下重写 `build_context` 等扩展点，引入项目特有 probe / runtime check / draft tool，把链路定位下沉到可修改点。

## 协议自省

```bash
$(读取 impl/config.yaml 的 python.executable) .claude/skills/draft/scripts/introspect_protocol.py impl/core/attribute_protocol.py
```

输出 attribute 当前协议的方法表（实际以脚本输出为准，不预判）：

- 模板方法：`attribute_failure`（不可覆盖）
- 内部方法：`_run_probes` / `_run_llm_attribute` / `_validate_attribute_output`（不可覆盖）
- 必须实现：`build_context(self, trace, judge_result) -> Dict[str, Any]`
- 可选覆盖：`probes()` / `normalize_result(trace, judge_result, result)`

## 角色特异部分（draft 机制不预判，本文件填）

### case 字段（从当前 `ProjectAttribute.attribute_failure` 模板方法签名派生）

模板方法签名：`attribute_failure(self, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult`

→ 每个 case 至少包含：

- `case_key`：case 标识。
- `trace: RunTrace`：归因输入。
- `judge_result: JudgeResult`：归因输入。
- `expected_check`：用户给出的"期望"——该 case 下 draft 应输出什么样的证据/链路定位才算合格。**期望由用户在 config 或 case 数据中给出，不由 skill 自动猜测**。

### `_run_attribute` / `_result_summary` / `_case_status`

实现在 `scripts/compare_attribute.py`：

- `_run_attribute(impl, spec, adapter, case)`：从 case 取 `trace` + `judge_result` 喂给 `impl.attribute_failure(trace, judge_result)`。
- `_result_summary(result)`：抽 `AttributeResult` 的 `expectation_attributions` / `suspected_locations` / `root_cause_hypothesis` / `evidence` / `evidence_strength`。
- `_case_status(case)`：从 `case.judge_result.overall_fulfillment.status` 取（attribute case 携带 judge_result）。

## 角色特异门禁

attribute 角色特有的门禁（通用门禁见 `../SKILL.md`）：

- **链路定位**：draft 归因输出要说明问题发生在哪个可观察阶段（具体 tool / 具体代码路径 / 具体配置项），不停在模块名。证据不足写缺口，不编造根因。
- **强度档位**：`evidence_strength` 取 `none` / `weak` / `medium` / `strong`（沿用现有 attribute skill，不重建）：
  - `strong`：当前 tool/probe/runtime check 明确显示 gap，且 expected/reference 与 actual 都存在。
  - `medium`：有当前证据，但缺关键链路验证。
  - `weak`：只有 judge 文本、部分 trace 或间接配置证据。
  - `none`：expected/reference、actual 或 judge 缺失。
- **不伪造强度**：tool/probe/runtime check failed 不产生 strong；expected/reference/actual 缺失不产生 strong。
- **fulfilled case 不归因失败**：judge status = fulfilled 的 case 不被强行归因失败——draft 不能为了"找问题"而造问题。

## 强度档位

`AttributeResult.evidence_strength` 的档位见上方"角色特异门禁"。

## 对比脚本

`scripts/compare_attribute.py` 的 `compare_attribute_outputs(spec, adapter, cases, current_impl, draft_impl)`：

- 同一批冻结 case，current 和 draft 各跑一遍。
- 比"证据质量 / 链路定位 / 不过拟合 / 不伪造"，不比刷分。
- **异常冒泡，不吞**——某 case 抛异常时该 case 标 blocked，不计入"draft 更优"。
- `decision_rule`：draft 在证据质量/链路定位任一维度优于 current 且不弱于其他维度，且不伪造强度、不引入 overfit → 可考虑 promotion。Blocked case 不计入。

## tool 边界

attribute 角色的 draft tool 可以接入：

- 看**业务系统代码**的 tool（attribute 是内部技术视角，允许看代码）。
- 调用**业务系统接口**做 probe 的 tool（runtime check / semantic equivalence / comparator）。
- 复用项目已有 adapter comparison / runtime check / production tool。

draft tool 必须用现有 `impl/tools/protocol.py` 的 `VerifiableTool` / `ToolResult` 协议，不另造。tool 经 `ToolRegistry` + `ToolOrchestrator` + `agno 桥接`调度，不绕过统一 orchestrator。draft tool 写在 `impl/projects/<project>/draft/tools/` 下，不被 production loader 自动加载。

## promotion 前置

按 spec 阶段 6：

- `draft/attribute.py` 可 import，`__init_subclass__` 不报错。
- `attribute_failure()` 返回最小 `AttributeResult`。
- 代表 case 的 targeted run 或局部函数验证通过。
- mock 对比报告显示 draft 在证据质量/链路定位/泛化风险上优于或不弱于 current。
- tool/probe failed 不会伪造 strong。
- production loader（`load_project_attribute`）在 `attribute_draft.enabled=false` 时不加载 draft。
- 人工确认后才 promotion：搬移 `draft/attribute.py` → `attribute.py`，`draft/tools/` → `tools/`，`project.yaml` 中 `attribute_draft.enabled` 设为 `false`。

## 与现有 attribute skill 的关系

当前阶段 `/draft` skill **不动**现有 `/attribute` skill。`/attribute` skill 继续作为归因审查门禁独立运作。`/draft` skill 的 attribute 子目录提供 draft 优化路径，目标是最终把 `/attribute` skill 的 draft 部分融合进来，但当前阶段两者并存，互不修改。
