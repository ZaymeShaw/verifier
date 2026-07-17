# Check 报告：impl/core 与 spec/adapter/trace.md 对齐情况

**检查日期**：2026-07-16
**检查范围**：impl/core/{live_protocol, trace, interaction_protocol, adapter_v2, pipeline}.py
**对照 spec**：spec/adapter/trace.md（最新版，已取代 multiturn.md 与 multiturn-bak*.md）
**结论**：🔴 重大偏离。trace.md 已宣告废弃 `deliver(case) 模板` / `deliver_multi_turn` / `LiveExecutionResult` / `get_last_execution_facts`，但代码层仍全面保留旧架构。

---

## 一、trace.md 协议契约（权威口径）

### 第二节 live 协议层
| 方法 | 签名 | 职责 |
|---|---|---|
| `execute_live` | `(intent: MockIntentOutput) → EXTRACT_OUTPUT_SCHEMA` | 完整调用入口，内部判断单轮/多轮，调用 mock + deliver_turn |
| `deliver_turn` | `(request: REQUEST_SCHEMA) → EXTRACT_OUTPUT_SCHEMA` | 单次投递，调 deliver_real → extract_output → 校验 EXTRACT_OUTPUT_SCHEMA |

- **行 11**：`execute_live：完整调用，输入 MockIntentOutput，内部判断单轮/多轮，和 mock 交互`
- **行 12**：`deliver_turn：单次投递，输入 REQUEST_SCHEMA，不碰 mock，纯投递`
- **行 13**：`只返回 EXTRACT_OUTPUT_SCHEMA，不背 trace 字段`

### 第十节 live 层职责边界
- **行 204**：`deliver_turn │ REQUEST_SCHEMA │ 单次投递业务 API │ 不区分`（单轮/多轮统一走 deliver_turn）
- **行 209-215**：deliver_turn 内部流程 = 校验 request → deliver_real → extract_output → 校验 output → 返回 EXTRACT_OUTPUT_SCHEMA

### 第十一节 核心原则（逐条）
1. mock 层权责清晰：build_live_request（单轮专用）+ build_next_request（多轮专用），不重叠
2. live 层两个函数：deliver_turn（单次投递）+ execute_live（完整调用，支持单轮/多轮）
3. execute_live 是统一入口：输入 intent，内部判断单轮/多轮
4. deliver_turn 不碰 mock：纯投递
5. execute_live 才和 mock 交互
6. case 不进 live 层：case 只在 pipeline 入口用，转成 intent 后传给 live
7. request 不被覆盖
8. 校验在协议层
9. 停止判断统一：只用 mock.should_stop，删协议层自己的停止判断
10. case 是跨层载体
11. **live 只返回 EXTRACT_OUTPUT_SCHEMA：不返回 LiveExecutionResult，不背任何 trace 字段**
12. trace 字段由 trace 层收集
13. 项目必须正确实现 extract_output
14. 协议层校验失败说明项目实现有问题

### 第十二节 影响范围
- **行 247**：`删 deliver(case) 模板，统一用 deliver_turn(request)`
- **行 248**：`删 LiveExecutionResult`
- **行 249-250**：删 deliver(case) 模板、删 LiveExecutionResult、execute_live 内部不重复调 build_live_request、删 deliver_multi_turn

---

## 二、当前代码实测结果

### 2.1 live_protocol.py 方法清单（实测）

`_LiveProtocol` 公开方法（共 20 个）：
- **trace.md 不再承认的**：`deliver`、`deliver_provided`、`deliver_stub`、`application_boundary`、`build_execution_trace`、`project_fields`、`normalize_result`、`get_last_execution_facts`、`build_request`
- **trace.md 保留的**：`execute_live`、`deliver_real`、`extract_output`、`_validate_request`、`_validate_output`

`MultiTurnInteractiveLive` 公开方法（共 12 个）：
- **trace.md 不再承认的**：`deliver_multi_turn`、`_assemble_multi_turn_result`、`_build_turn_request`、`_build_turn_trace`、`_collect_missing_fields`、`_extract_source_case`、`_extract_turn_output`、`_mock_for_multi_turn`、`_read_turn_expectations`、`_should_stop`、`_summarize_assistant`
- **trace.md 保留的**：`deliver_turn`（签名仍带 `accumulated_output`，spec 要返回 EXTRACT_OUTPUT_SCHEMA）

### 2.2 trace.md 第十一节逐条核对

| # | spec 要求 | 当前实现 | 偏离 |
|---|---|---|---|
| 1 | build_live_request（单轮）/ build_next_request（多轮）不重叠 | ✅ mock 协议层已分开 | OK |
| 2 | live 层两个函数：deliver_turn + execute_live | 实际有 deliver / deliver_multi_turn / deliver_turn / execute_live 共 4 个 | 🔴 多了 deliver / deliver_multi_turn |
| 3 | execute_live 输入 intent，内部判断单轮/多轮 | execute_live 输入是 `normalized_request`（不是 intent），intent 是第二可选参数 | 🔴 签名偏离 |
| 4 | deliver_turn 不碰 mock，输入 REQUEST_SCHEMA | deliver_turn 输入 `(request, accumulated_output)`，返回 `accumulated dict` | 🔴 签名偏离（多带 accumulated_output，返回值非 EXTRACT_OUTPUT_SCHEMA） |
| 5 | execute_live 才和 mock 交互 | execute_live 通过 `_execute_live_internal` 调 `deliver_multi_turn` 间接调 mock；单轮路径调 `_resolve_intent`（也调 mock） | 🟡 部分偏离 |
| 6 | case 不进 live 层 | execute_live 接受 `NormalizedCaseInteraction`，deliver_multi_turn 直接读 `case.scenario/case_id/reference/mode/policy`，仍是 case 形态 | 🔴 偏离（live 层吃 case） |
| 7 | request 不被覆盖 | deliver_multi_turn 内 `next_input = mock.build_next_request(...)` 直接构造，不重新调 build_live_request | ✅ OK |
| 8 | 校验在协议层 | _validate_request / _validate_output 在协议层 | ✅ OK |
| 9 | 停止判断统一：只用 mock.should_stop，删协议层自己的停止判断 | `_should_stop` + `mock.should_stop` 同时存在 | 🔴 偏离（_should_stop 应删） |
| 10 | case 是跨层载体 | 部分遵守，deliver_multi_turn 仍读 case | 🔴 偏离 |
| 11 | live 只返回 EXTRACT_OUTPUT_SCHEMA，不返回 LiveExecutionResult | execute_live 表面返回 extracted_output，但 `_execute_live_internal` 返回 LiveExecutionResult 并缓存到 `_last_execution_result`，trace.py 通过 `get_last_execution_facts()` 取回 | 🔴 偏离（LiveExecutionResult 仍是内部载体） |
| 12 | trace 字段由 trace 层收集 | trace_from_live_result 直接读 LiveExecutionResult 的 raw_response / execution_trace / fallbacks / multi_turn_state | 🔴 偏离（trace 层依赖 LiveExecutionResult） |
| 13 | 项目必须正确实现 extract_output | ✅ 项目层都实现了 | OK |
| 14 | 协议层校验失败说明项目实现有问题 | ✅ 协议层抛 ValueError | OK |

### 2.3 trace.md 第十二节影响范围逐条核对

| spec 要求 | 当前实现 | 偏离 |
|---|---|---|
| 删 deliver(case) 模板，统一用 deliver_turn(request) | `deliver(case, contract) → LiveExecutionResult` 仍在 `_LiveProtocol`，`@final` 装饰 | 🔴 |
| 删 LiveExecutionResult | `LiveExecutionResult` 仍在 schema/live.py；trace.py / live_protocol.py / pipeline.py / 项目 live.py 全部依赖 | 🔴 |
| deliver_turn 直接投递，不背 trace 字段 | deliver_turn 返回 `accumulated dict`，且内部构建 LiveExecutionResult | 🔴 |
| execute_live 内部不重复调 build_live_request | 单轮路径走 `_run_provided` / `deliver_real`，不重调 build_live_request；多轮路径调 `mock.build_next_request`（不重调 build_live_request） | ✅ |
| 删 deliver_multi_turn | `deliver_multi_turn @final` 仍在 `MultiTurnInteractiveLive` | 🔴 |
| 删 LiveExecutionResult | （同上） | 🔴 |

### 2.4 受影响的下游代码

**core 层**：
- `impl/core/trace.py`：`trace_from_live_result(result: LiveExecutionResult)`、`live_multi_turn_result(result: LiveExecutionResult)` 直接吃 LiveExecutionResult
- `impl/core/pipeline.py:337`：`_unsupported_interactive_run` 构造 `LiveExecutionResult`
- `impl/core/schema/trace.py:46`：`RunTrace.live_result: Optional[LiveExecutionResult]` 字段
- `impl/core/schema/occam.py:80`：occam 表注册 LiveExecutionResult
- `impl/core/mock_protocol.py:351,383,398`：docstring 引用 deliver_multi_turn

**项目层**（每个项目的 live.py）：
- `impl/projects/marketting-planning/live.py:10,621,646`：直接 import LiveExecutionResult，构造 LiveExecutionResult；多轮扩展点 `_should_stop`/`_build_turn_trace`/`_collect_missing_fields`/`_summarize_assistant`
- `impl/projects/deerflow/live.py:18,463,496`：同上
- `impl/projects/client_search/live.py:20,387`：单轮 LiveExecutionResult
- `impl/projects/QA/live.py:5`：import LiveExecutionResult
- `impl/projects/marketting-planning-intent/live.py:9,187`：同上

---

## 三、问题清单

### P1（协议级偏离，必须修）
- **P1-1**：`_LiveProtocol.deliver(case, contract)` 模板方法仍保留，trace.md 第十二节明确要求"删 deliver(case) 模板"
- **P1-2**：`MultiTurnInteractiveLive.deliver_multi_turn @final` 模板方法仍保留，trace.md 第十二节明确要求"删 deliver_multi_turn"
- **P1-3**：`LiveExecutionResult` dataclass 仍是协议层主载体，trace.md 第十二节明确要求"删 LiveExecutionResult"
- **P1-4**：`get_last_execution_facts()` 仍存在，这是 LiveExecutionResult 的伴随物，trace.md 行 13 "只返回 EXTRACT_OUTPUT_SCHEMA，不背 trace 字段"直接否定
- **P1-5**：`execute_live` 签名 `(normalized_request, intent=None)` 与 spec `(intent: MockIntentOutput) → EXTRACT_OUTPUT_SCHEMA` 偏离
- **P1-6**：`deliver_turn` 签名 `(request, accumulated_output) → accumulated dict` 与 spec `(request: REQUEST_SCHEMA) → EXTRACT_OUTPUT_SCHEMA` 偏离
- **P1-7**：`MultiTurnInteractiveLive._should_stop` + `mock.should_stop` 双重停止判断，违反核心原则 9 "只用 mock.should_stop，删协议层自己的停止判断"
- **P1-8**：case 进 live 层（`NormalizedCaseInteraction` 直接传给 execute_live），违反核心原则 6 "case 不进 live 层"
- **P1-9**：trace 层依赖 LiveExecutionResult（`trace_from_live_result` / `live_multi_turn_result` 签名直接吃 LiveExecutionResult），违反核心原则 11 / 12

### P2（冗余/过时代码）
- **P2-1**：`_LiveProtocol` 内部 `_run_provided / _run_real_or_fallback / _candidate_to_result / _result_from_raw / _failed_live_result / _make_live_error_fallback / _apply_interaction_state / _multi_turn_accumulated_fields / _live_multi_turn_result / _append_validation / _build_request` 等大量内部方法围绕 LiveExecutionResult 体系构建，trace.md 体系下应大幅瘦身
- **P2-2**：`MultiTurnInteractiveLive` 的 `_assemble_multi_turn_result / _build_turn_request / _build_turn_trace / _collect_missing_fields / _extract_source_case / _extract_turn_output / _read_turn_expectations / _should_stop / _summarize_assistant` 都围绕 deliver_multi_turn 主循环构建，trace.md 体系下应整体删除（或大幅合并到 trace 层）
- **P2-3**：项目层（marketting-planning/deerflow live.py）覆盖的多轮扩展点（`_should_stop`/`_build_turn_trace`/`_summarize_assistant`/`_collect_missing_fields`）将随 deliver_multi_turn 删除而失效

### P3（docstring 引用过时）
- `impl/core/mock_protocol.py:351,383,398`：docstring 仍引用 deliver_multi_turn
- `impl/projects/marketting-planning/live.py:621`、`impl/projects/deerflow/live.py:463`：docstring 仍引用 deliver_multi_turn

---

## 四、根因分析

trace.md 已经把协议从「Live 层产出 LiveExecutionResult，trace 层组装 RunTrace」改成「Live 层只产出 EXTRACT_OUTPUT_SCHEMA，trace 层在调用过程中收集过程事实」。但代码仍停留在旧架构：

1. **trace_from_live 的实现路径**（trace.py:92-173）仍是「调 execute_live → get_last_execution_facts() 拿 LiveExecutionResult → trace_from_live_result 组装 RunTrace」，依赖 LiveExecutionResult 作为 live 层到 trace 层的桥梁。
2. **多轮主循环位置**：trace.md 行 11 "execute_live：完整调用，内部判断单轮/多轮，和 mock 交互"，意味着多轮主循环应该在 execute_live 内部用 deliver_turn 串联，而不是抽出一个独立的 `deliver_multi_turn` 模板方法。
3. **过程事实收集位置**：trace.md 行 12 "trace 字段由 trace 层收集：trace 层作为 live 的调用方，在调用过程中记录过程事实"——即 trace 层应该在调用 deliver_turn 的过程中记录 raw_response / call_status / fallbacks 等，而不是等 live 层把所有东西打包成 LiveExecutionResult 后再取。

---

## 五、修复方案（向用户确认后再执行）

### 阶段 A：协议层重构（高风险，需用户确认）

**目标**：让 impl/core/live_protocol.py 与 trace.md 第十、十一、十二节对齐。

**改动**：
1. 删除 `_LiveProtocol.deliver(case, contract)` 模板方法和 `@typing_final` 装饰；删 `_FORBIDDEN_OVERRIDES` 中的 `deliver`
2. 删除 `MultiTurnInteractiveLive.deliver_multi_turn` 模板方法和 `@typing_final` 装饰；删 `_FORBIDDEN_OVERRIDES` 中的 `deliver_multi_turn`
3. 重构 `execute_live` 签名：`execute_live(intent: MockIntentOutput) → EXTRACT_OUTPUT_SCHEMA`
   - 内部判断单轮/多轮（通过 `isinstance(self, MultiTurnInteractiveLive)`）
   - 单轮：`mock.build_live_request(intent) → request → deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA`
   - 多轮：循环 `mock.build_next_request(intent, accumulated) → request → deliver_turn(request) → EXTRACT_OUTPUT_SCHEMA`，停止判断只用 `mock.should_stop`
4. 重构 `deliver_turn` 签名：`deliver_turn(request: REQUEST_SCHEMA) → EXTRACT_OUTPUT_SCHEMA`
   - 内部流程：校验 request → deliver_real → extract_output → 校验 output → 返回 EXTRACT_OUTPUT_SCHEMA
   - 不带 accumulated_output，不碰 mock
5. 删除 `LiveExecutionResult` dataclass（impl/core/schema/live.py:41-61）；trace 层不再依赖
6. 删除 `get_last_execution_facts()`；trace 层在调用 deliver_turn 的过程中直接收集过程事实
7. 删除 `_should_stop` 协议层默认实现；只保留 `mock.should_stop`
8. 删除 `_run_provided / _run_real_or_fallback / _candidate_to_result / _result_from_raw / _failed_live_result / _make_live_error_fallback / _apply_interaction_state / _multi_turn_accumulated_fields / _live_multi_turn_result / _append_validation / _build_request / _assemble_multi_turn_result / _build_turn_request / _build_turn_trace / _collect_missing_fields / _extract_source_case / _extract_turn_output / _read_turn_expectations / _summarize_assistant` 等 LiveExecutionResult 体系下的内部方法
9. 保留：`_validate_request / _validate_output / deliver_real / deliver_provided / deliver_stub / extract_output / application_boundary / project_fields / build_execution_trace / normalize_result`（但 normalize_result 等后处理扩展点是否保留需用户决定——trace.md 行 246 没有明确提及，看第十一节 11 也不背 trace 字段，建议把 project_fields / application_boundary / build_execution_trace 都迁到 trace 层）

### 阶段 B：trace 层重构（中风险）

**目标**：trace_from_live 在调用 live 的过程中收集过程事实，不依赖 LiveExecutionResult。

**改动**：
1. 重写 `trace_from_live(live, case)`：
   - 从 case 提取 intent（调 mock.build_user_intent 或从 case.user_intent 取）
   - 单轮：调 `live.execute_live(intent)`，过程中收集 raw_response / call_status / fallbacks
   - 多轮：trace 层在 execute_live 内部无法直接 hook deliver_turn，需要 live 层暴露一个 callback / 事件流，或在 trace 层重新接管多轮主循环（这违反 spec 行 11 "execute_live 内部判断单轮/多轮"——需用户确认）
2. 删除 `trace_from_live_result(result: LiveExecutionResult)` 入口
3. 删除 `live_multi_turn_result(result: LiveExecutionResult)` 辅助函数
4. RunTrace 字段调整：`live_result: Optional[LiveExecutionResult]` 字段删除或替换

**关键问题**：trace.md 行 11 + 行 12 同时要求 "execute_live 内部判断单轮/多轮" + "trace 层在调用过程中记录过程事实"——这两条隐含矛盾：如果 execute_live 是黑盒（trace 层不进入），trace 层怎么记录每轮的过程事实？需要用户确认：
- **方案 A**：execute_live 接受 trace 层注入的 callback / context，每轮通过 callback 上报过程事实
- **方案 B**：trace 层接管多轮主循环（违反 spec 行 11）
- **方案 C**：execute_live 内部记录过程事实到一个 trace 层可读的载体（仍是 LiveExecutionResult 的演化，违反 spec 行 13 "不背 trace 字段"）

### 阶段 C：项目层迁移（低风险，但工作量大）

**目标**：5 个项目的 live.py 去掉 LiveExecutionResult 依赖。

**改动**：
1. marketting-planning / deerflow：删除覆盖的 `_should_stop`/`_build_turn_trace`/`_summarize_assistant`/`_collect_missing_fields`（这些方法随 deliver_multi_turn 删除而失效），项目特化的停止判断迁移到 mock.should_stop，项目特化的 turn_trace 字段迁移到 trace 层
2. 5 个项目的 live.py：删除 `from impl.core.schema import LiveExecutionResult`，`deliver_real` / `deliver_provided` 直接返回 raw_response，由 extract_output 提取 EXTRACT_OUTPUT_SCHEMA
3. impl/core/pipeline.py:337 的 `_unsupported_interactive_run` 不再构造 LiveExecutionResult，改为直接构造 RunTrace

### 阶段 D：schema 清理（低风险）

1. impl/core/schema/live.py：删除 LiveExecutionResult dataclass，保留 LiveRequest / LiveMultiTurnState（如果 trace 层仍需多轮状态载体）
2. impl/core/schema/__init__.py / normalize.py / occam.py：删除 LiveExecutionResult 的导出和注册
3. impl/core/schema/trace.py:46：删除 RunTrace.live_result 字段或改为 `Any`

---

## 六、check list

- [ ] trace.md 行 247 "删 deliver(case) 模板" — 🔴 未执行
- [ ] trace.md 行 248 "删 LiveExecutionResult" — 🔴 未执行
- [ ] trace.md 行 247 "统一用 deliver_turn(request)" — 🔴 未执行
- [ ] trace.md 第二节 execute_live 签名 `(intent: MockIntentOutput) → EXTRACT_OUTPUT_SCHEMA` — 🔴 当前签名偏离
- [ ] trace.md 第二节 deliver_turn 签名 `(request: REQUEST_SCHEMA) → EXTRACT_OUTPUT_SCHEMA` — 🔴 当前签名偏离
- [ ] trace.md 第十一节 9 "只用 mock.should_stop，删协议层自己的停止判断" — 🔴 `_should_stop` 仍在
- [ ] trace.md 第十一节 11 "live 只返回 EXTRACT_OUTPUT_SCHEMA，不返回 LiveExecutionResult" — 🔴
- [ ] trace.md 第十一节 6 "case 不进 live 层" — 🔴 NormalizedCaseInteraction 仍传给 execute_live
- [ ] trace.md 第十二节 249-250 — 🔴 三项明确删除项未执行
- [ ] 项目层 5 个 live.py 去除 LiveExecutionResult 依赖 — 🔴 未执行
- [ ] pipeline.py `_unsupported_interactive_run` 不再构造 LiveExecutionResult — 🔴 未执行
- [ ] 协议/项目 docstring 中 deliver_multi_turn 引用清理 — 🔴 未执行

---

## 七、需要用户确认的决策点

1. **是否启动阶段 A 协议层重构？** — 这是高风险大改，影响 5 个项目和整个 core 层。建议先做更小的样例（比如先重构 marketting-planning-intent 单轮项目，跑通后再推广）。

2. **trace 层如何在 execute_live 黑盒下收集过程事实？**（阶段 B 的方案 A/B/C 选择）— 这是 spec 本身的潜在歧义，建议先和用户对齐口径再动代码。

3. **`_should_stop` / `_build_turn_trace` / `_summarize_assistant` / `_collect_missing_fields` 这些项目特化扩展点的归宿？** — trace.md 行 11 "execute_live 内部判断单轮/多轮" 暗示主循环在协议层，但 trace.md 行 12 "trace 层在调用过程中记录过程事实" 暗示主循环在 trace 层。项目特化字段（如 marketting-planning 的 stage、card_summary）应放在哪里？

4. **是否一次性删除 LiveExecutionResult？** — 这是 spec 明确要求，但影响 30+ 处代码。建议先保留 dataclass 但不再让协议层产出它，让 trace 层逐步迁移，最后再删 dataclass。
