# 20260714 api-check 业务审查报告

## 审查范围
report/api-check/20260714-012858/api-check.xlsx（56 case，4 项目 × 14 端点）。
角度：仅从业务期望出发，将响应内容以最小单元格逐项排查。

## 表层结论（schema 层）
- HTTP 200：56/56 ✅
- schema_check=pass：56/56 ✅
- 4 个项目（QA / client_search / marketting-planning / marketting-planning-intent）每个跑满 14 端点 ✅

但 schema pass 只能说明"返回结构对得上"，不能说明"业务被真正跑到了"。逐项排查响应内容后发现 2 个核心业务问题。

---

## 🔴 问题1（核心）：多轮 fixture 完全没被 api-check 跑到

### 现象
- marketting-planning batch_run 的响应里，`trace.execution_mode=live`、`output_source=live_service`、`trace.live_result.multi_turn_state` 全空（session_id="", turn_index=0, transcript=[]）。
- 即 B1 加的 `interactive_intent` fixture（mock_cases.json index 7, id=mock-agent-...-mt-039dd423）从头到尾没出现在 batch_run 的输入里。

### 根因（最小单元格定位）
1. `impl/server/service.py:163` `mock_cases(data)` 不传 count，调 `pipeline.mock_cases(project)` 默认 count=3。
2. `impl/core/pipeline.py:663-665` `mock_cases` 调 `_fixture_mock_cases` 拿全部 8 条 fixture，然后 `fixtures[:count]` 切前 3 条返回。
3. 多轮 fixture 排在 index 7，永远进不了前 3。
4. `hooks/api-check/api_check_registry.py:264` `real_project_case` 又固定 `_MOCK_CASE_CACHE[project_id] = cases[0]`，所以 batch_run 永远只用第 1 条单轮 case（mock-agent-...-d1642b58）。

### 业务影响
- 多轮协议改造做完后，api-check 验收完全没覆盖多轮路径。
- B1 加的多轮 fixture 形同摆设——存在文件里但接口不暴露、链路不消费。
- 后续每次跑 api-check 都是"56 case 全 pass"的假象，但多轮代码如果有回归根本测不出来。
- 违反 check.md 原则 d（数据更新不同步不一致：代码改了、fixture 加了、但 api-check 取数路径没改，前后不一致）。

### 修复建议（最小化、不破坏现有单轮验收）
两条路径，二选一（建议方案 A）：

**方案 A — 让多轮 fixture 进入 mock_cases 默认返回**
- `_fixture_mock_cases` 返回时把 `interaction.mode=interactive_intent` 的 fixture 排到前面（或保证至少 1 条多轮 fixture 进前 count 条）
- 改动点：`impl/core/pipeline.py:_fixture_mock_cases` 或 `mock_cases` 的切片逻辑，增加"确保多轮 fixture 优先"的策略
- 影响面：mock_cases 接口返回顺序变了，所有依赖 cases[0] 的下游（real_project_case / batch_run / live_run / run_chain）会切换到多轮 case
- 风险：单轮形态的 case 会被挤掉，需要同时调高 count 或者按"单轮 N 条 + 多轮 M 条"组合返回

**方案 B — api-check 显式挑多轮 case**
- `hooks/api-check/api_check_registry.py:real_project_case` 改为"优先挑 interaction.mode=interactive_intent 的 case"，找不到再退回 cases[0]
- 改动面更小，只动 api-check 这一层
- 缺点：只解决验收覆盖，没解决"mock_cases 接口默认不返回多轮 case"这个产品层问题

---

## 🟡 问题2：`[live_schema] request check failed` 重复出现 7+ 次

### 现象
日志中 `[live_schema] request check failed for marketting-planning: request 不符合 live_schema` 出现 7 次以上，发生在 live_run / run_chain / batch_run 等多个端点调用时。

### 业务影响
- 这说明 marketting-planning 的 mock case 输入本身不符合 live_schema 的 REQUEST_SCHEMA。
- 但 case 还是 schema=pass 跑完了，说明这个 check fail 是"警告/降级"而非"阻断"。
- 业务期望上，mock_cases 接口产出的 case 应该天然符合 live_schema（同源），不应该每次都 warn。如果是已知的"fixture 与 schema 漂移"，需要修 fixture；如果是 check 太严，需要调 check。

### 修复建议
- 排查是哪些字段不符合（缺字段？类型错？多字段？）
- 如果是 fixture 漂移：补 fixture 字段
- 如果是 check 误报：放宽 check
- 当前状态是"一边报错一边通过"，属于原则 c（只优化展示结果不优化源头逻辑）的灰色地带

---

## 🟡 问题3：judge enforce 阻断 + reprompt 触发 3 次（功能正确但需确认）

### 现象
日志中 `[judge] enforce 阻断，触发 reprompt` 出现 3 次，分别是：
- marketting-planning run_chain：`business_expectations.[*].boundary` 期望 object 实际 list
- marketting-planning batch_run：`fulfillment_assessments.[*].expected_evidence / actual_evidence` 期望 array 实际 str
- marketting-planning judge（独立调用）：同上

### 业务评价
- ✅ enforce 阻断机制工作正常（不放行假货，触发 reprompt 重试），这是 check.md 期望的行为。
- ⚠️ 但每次都阻断说明 judge LLM 输出形状稳定地错（boundary 出成 list、evidence 出成 str），可能是 judge prompt 或 schema 描述不够清晰，导致 LLM 反复出错。
- 业务期望：enforce 阻断应该是"偶发兜底"，而不是"每次必触发"。如果每次都触发，要么 prompt 要修，要么 schema 描述要修。

### 修复建议
- 看 judge prompt 里 boundary / expected_evidence / actual_evidence 的字段说明是否清晰
- 如果 prompt 没问题，看 schema 里这两个字段是不是定义成了 union（导致 LLM 困惑）
- 不属于紧急问题，但建议跟进

---

## 综合判断

| 项 | 状态 |
|---|---|
| 4 项目 14 端点 HTTP/schema 全 pass | ✅ |
| 多轮路径验收覆盖 | 🔴 完全没覆盖 |
| mock_cases 接口暴露多轮 fixture | 🔴 没暴露 |
| live_schema check fail 重复出现 | 🟡 待排查 |
| judge enforce 阻断机制 | ✅ 工作正常 |
| judge LLM 输出形状稳定性 | 🟡 待优化 |

## 建议优先级
1. **P0 问题1**：先确认走方案 A 还是方案 B。这关系到多轮改造是否能算"验收通过"。
2. **P1 问题2**：排查 live_schema check fail 的根因。
3. **P2 问题3**：judge LLM 输出形状优化（非阻断类问题）。

## 备注
- 问题1 是这次 api-check 审查最重要的发现：表面 56 case 全 pass，实际多轮代码完全没被验收覆盖。
- 之前 20260714 多轮协议改造 check 报告里写的"marketting-planning + deerflow 多轮实测通过"，是单条手动跑 `_batch_case` 的结果，不等于 api-check 自动验收覆盖了多轮路径。
