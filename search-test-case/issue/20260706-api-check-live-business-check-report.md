# Business/Check 报告：最新 api-check.xlsx 与 spec/live.md 完成度审查

**日期:** 2026-07-06  
**报告文件:** `report/api-check/20260706-180246/api-check.xlsx`  
**审查角度:** 仅从业务期望出发，按最小单元格逐项排查；同时追溯产生机制，不只看展示结果。  
**补充范围:** 评估 `spec/live.md` 的实现完成情况。

---

## 一、总览结论

最新 API 检查报告不是全量通过：

| 指标 | 数量 |
|---|---:|
| 总行数 | 56 |
| `schema_check=pass` | 45 |
| `schema_check=fail` | 1 |
| `schema_check=setup_error` | 10 |
| `http_status=200` | 46 |
| `http_status=0` | 10 |

核心业务结论：

1. **QA / client_search / marketting-planning-intent 基本通过本次 API schema 检查。**
2. **marketting-planning 是本次报告的主要失败项目。** 失败不是单个接口偶发，而是从 `run_chain` 开始向 `judge / attribute / cluster / check / frontend_view / batch_run / trace / table` 级联扩散。
3. **`spec/live.md` 的 live 模块重构只完成了“通用投递层落地”和“live_run 基础路径”，但未完成多轮协议在 judge/reference/下游链路中的闭环对齐。**
4. **最严重的业务问题不是 Excel 展示，而是源头链路口径不统一：** `marketting-planning` 的 actual 已经是 `{"turns": [...]}` 多轮输出，但 judge 自生成 expected 仍是单轮裸响应 dict，导致 EXTRACT_OUTPUT_SHAPE 校验失败。

---

## 二、最小单元格级别问题清单

### P0-1：`marketting-planning / run_chain` 单元格失败，是后续失败的根源

| Excel 行 | project | case | api | http_status | schema_check | 问题单元格 |
|---:|---|---|---|---:|---|---|
| 20 | marketting-planning | run_chain | `POST /api/run_chain` | 200 | fail | `schema_error` |

`schema_error` 内容显示：

```text
run_chain.judge.expected 不符合 marketting-planning EXTRACT_OUTPUT_SHAPE: {'code': 0, 'msg': 'success', ...}
```

业务判断：

- 当前项目 `marketting-planning/live_schema.py` 定义的 `EXTRACT_OUTPUT_SHAPE` 是：

```python
{"turns": "list"}
```

- `run_chain` 的 actual 是：

```json
{
  "turns": [
    {
      "code": 0,
      "msg": "success",
      "robot_text": "卡片生成完成",
      "end_flag": 1,
      "extra_output_params": {...},
      "turn_index": 0
    }
  ]
}
```

- 但 judge.expected 是裸 dict：

```json
{
  "code": 0,
  "msg": "success",
  "robot_text": "根据您的需求，正在为您制定NBEV目标达成规划，请提供具体的缺口金额以便精准计算。",
  "end_flag": 0,
  "extra_output_params": {...}
}
```

**这不是业务内容判断错误，而是协议形状错误。** 多轮项目的 expected/reference 也必须与 `EXTRACT_OUTPUT_SHAPE` 同形，即至少应是：

```json
{"turns": [{...}]}
```

否则 judge 无法在统一契约下比较 expected vs actual。

---

### P0-2：10 个 `setup_error` 都是同一协议不对齐问题的级联结果

| Excel 行 | project | case | api | http_status | schema_check | 失败原因 |
|---:|---|---|---|---:|---|---|
| 22 | QA | judge | `POST /api/judge` | 0 | setup_error | 依赖预置 `run_chain` 构造失败/超时 |
| 24 | marketting-planning | judge | `POST /api/judge` | 0 | setup_error | `run_chain.judge.expected` 不符合 `EXTRACT_OUTPUT_SHAPE` |
| 28 | marketting-planning | attribute | `POST /api/attribute` | 0 | setup_error | 同上 |
| 32 | marketting-planning | cluster | `POST /api/cluster` | 0 | setup_error | 同上 |
| 36 | marketting-planning | check | `POST /api/check` | 0 | setup_error | 调 `/api/run_chain` 超时 600s |
| 40 | marketting-planning | frontend_view | `POST /api/frontend_view` | 0 | setup_error | `run_chain.judge.expected` 不符合 `EXTRACT_OUTPUT_SHAPE` |
| 44 | marketting-planning | batch_run | `POST /api/batch_run` | 0 | setup_error | 调 `/api/batch_run` 超时 600s |
| 48 | marketting-planning | trace | `POST /api/trace` | 0 | setup_error | `run_chain.judge.expected` 不符合 `EXTRACT_OUTPUT_SHAPE` |
| 52 | marketting-planning | table_row | `POST /api/table` | 0 | setup_error | `run_chain.judge.expected` 不符合 `EXTRACT_OUTPUT_SHAPE` |
| 56 | marketting-planning | table_pool | `POST /api/table` | 0 | setup_error | `run_chain.judge.expected` 不符合 `EXTRACT_OUTPUT_SHAPE` |

业务判断：

- 这些不应被当成 10 个独立问题分别修。
- 根因是 `marketting-planning` 多轮输出契约没有贯穿到 judge expected/reference 生成和 API check 预置链路。
- `check / batch_run` 的 600s 超时是症状：上游 `run_chain` 不稳定或阻断后，后续检查仍继续调完整链路，导致测试报告被超时污染。

---

### P0-3：`marketting-planning / live_run` 表面通过，但输入归一化已经偏离业务意图

| Excel 行 | project | case | api | http_status | schema_check |
|---:|---|---|---|---:|---|
| 16 | marketting-planning | live_run | `POST /api/live_run` | 200 | pass |

这一行 `schema_check=pass`，但业务上并不健康。报告中的请求输入包含：

```json
{
  "user_text": "我们团队今年的NBEV目标还差不少，能帮我看看怎么通过增加理财师或者优化产品方案来补上吗？",
  "extra_input_params": {...}
}
```

而 `live_result.normalized_request` 变成：

```json
{
  "user_intent": "intent_recognition",
  "query": "",
  "scenario": "intent_recognition",
  "reference": {"scenario": "intent_recognition"}
}
```

业务问题：

- 用户真实问题 `user_text` 没有进入 `query`。
- `user_intent` 被填成了场景名 `intent_recognition`，不是用户意图文本。
- 业务系统收到的关键文本为空，实际返回“其他意图”并不意外。

源头机制位置：

- `impl/projects/marketting-planning/adapter.py:65-96` 的 `build_request` 主要读取 `query / user_query / user_intent / nested_input.query`，没有把 mock case 中的 `user_text` 映射到 `query`。
- `report/api-check/20260706-180246/rows/007-marketting-planning-mock_cases.response.json` 生成的 mock case input 使用的是 API 请求风格字段 `user_text / extra_input_params`，而不是 `marketting-planning/live_schema.py:30-43` 描述的 `CASE_INPUT_SHAPE`（`query / user_intent / turns / expected_stage...`）。

所以 `live_run pass` 只是 schema 外层通过，不代表业务输入被正确投递。

---

### P1-1：`mock_cases` 行通过，但 mock 数据源口径已经与项目 live_schema 脱节

| Excel 行 | project | case | api | http_status | schema_check |
|---:|---|---|---|---:|---|
| 8 | marketting-planning | mock_cases | `POST /api/mock_cases` | 200 | pass |

业务问题：

- `mock_cases` 返回的 `marketting-planning` case 使用 `user_text`，更像真实 API body。
- 但 `live_schema.py` 中明确写了 mock_agent 产出的 `CASE_INPUT_SHAPE` 应含 `query / user_intent / turns / expected_stage / expected_path_types`。
- metadata 里出现 `schema_ok: true`，但从业务含义看并不可信：它没有发现 `query` 丢失和 `turns` 缺失。

这说明当前 schema 检查更像“响应模型检查”，没有真正覆盖“mock case 是否符合项目业务输入契约”。

---

### P1-2：报告中 `checked_response_path=[]` 对业务审查不够

大部分通过行的 `checked_response_path` 都是：

```text
[]
```

业务问题：

- 对 `analysis/mock_cases/live_run/run_chain/frontend_view/table` 这种复杂响应，仅验证顶层 Pydantic/schema 通过，不足以说明业务关键字段正确。
- 例如 `live_run` 行通过，但 `normalized_request.query` 为空；如果报告没有业务字段断言，这类问题会漏掉。

建议把 api-check 的最小业务断言扩展为：

- `marketting-planning live_run`: `normalized_request.query` 必须非空，且等于/包含输入 `user_text`。
- 多轮项目: `extracted_output.turns` 必须存在，且 `len(turns)` 与 `normalized_request.turns` 或当前执行轮次语义一致。
- `run_chain`: `judge.expected` 与 `judge.actual` 必须同形。

---

## 三、`spec/live.md` 完成情况评估

### 已完成部分

| spec/live.md 期望 | 当前完成情况 |
|---|---|
| 实现 `impl/core/live.py` 作为通用层 | 已实现，且基础测试通过 |
| 实现 `impl/projects/<project>/live.py` 作为项目自定义投递层 | QA / client_search / marketting-planning / marketting-planning-intent 均已有 |
| live_run 入口签名不变 | 已保持 |
| schema 校验失败进入诊断，不直接触发 fallback | `impl/core/live.py` 已有对应机制 |
| 项目投递动作下沉 | 基本完成，真实调用逻辑已从 adapter 迁到项目 live.py |

已实测：

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python -m pytest tests/test_core_live_protocol.py tests/test_project_live_smoke.py -q
```

结果：

```text
8 passed
```

### 未完成 / 不达业务预期部分

| 缺口 | 证据 | 业务影响 |
|---|---|---|
| 多轮 `EXTRACT_OUTPUT_SHAPE={turns}` 未贯穿到 judge expected/reference | api-check 行 20/24/28/32/40/48/52/56 均报 `judge.expected` 不符合 shape | run_chain 后续链路无法稳定运行 |
| mock case 输入形状与 `CASE_INPUT_SHAPE` 脱节 | mock case 使用 `user_text`，adapter 归一后 `query=""` | 业务系统收到空查询，意图识别失真 |
| `live_run` pass 不能代表业务投递正确 | 行 16 pass，但 normalized_request 丢失用户真实文本 | 报告存在“形式通过、业务失败”的误导 |
| 多轮执行未充分体现“按 turns 顺序执行每轮” | `marketting-planning/live.py` 当前 `_multi_turn_output` 只把最后一次调用包装进 `turns[0]`；报告样例 normalized_request 甚至没有 turns | 多轮契约仅被包装，未形成完整逐轮执行语义 |
| `stub` 方案未看到完整闭环验证 | spec 明确 stub 是系统侧 output 构造器，但报告未覆盖 stub 分支 | 业务系统不可用时的兜底质量不可知 |

完成度判断：**约 60%-70%。** 结构性代码已落地，但从最新 api-check 的业务结果看，多轮协议仍未完成端到端闭环。

---

## 四、根因机制分析

### 根因 A：`marketting-planning` 的输入层存在两套口径

当前至少有两套输入形状：

1. `live_schema.py` 注释/契约中的项目语义输入：`query / user_intent / turns / expected_stage...`
2. mock_cases 实际生成的 API 风格输入：`user_text / extra_input_params / session_id / trace_id...`

adapter 只部分支持第一套，导致第二套进入时丢失业务文本。

**这属于协议-项目实现-数据不一致，不是单个 case 错误。**

### 根因 B：judge expected 生成没有严格跟随当前 live_schema

`pipeline.py` 中 `_enforce_judge_live_schema` 会检查：

```python
checker.reference(result.expected)
```

这一步是正确的，**不应该绕过、降级或自动吞掉错误**。这里没有“多轮 expected 的特殊 schema 逻辑”：expected/reference 的唯一契约就是当前项目 `live_schema.EXTRACT_OUTPUT_SHAPE`。如果当前 `EXTRACT_OUTPUT_SHAPE` 是 `{"turns": "list"}`，那么 expected/reference 就必须天然生成这个形状；如果业务真实契约不是这个形状，就应该更新 live_schema，并同步所有关联方。

当前失败说明两类问题至少有一个存在：

- `marketting-planning` 的旧 schema 没有更新到真实业务输出口径；或
- 新 schema 已更新为 `{"turns": "list"}`，但 judge/reference/mock/api-check 等关联生产方没有跟上。

所以修复目标不是“包装一下以避免报错”，而是让所有生产 expected/reference/actual 的链路都回到同一个 live_schema 口径；报错要保留，用来暴露未对齐的生产源头。

### 根因 C：报告 schema pass 与业务 pass 混在一起

当前 `api-check.xlsx` 的 `schema_check=pass` 主要表示响应模型能解析，不代表：

- 输入是否保留了用户业务意图；
- actual/expected 是否同形；
- 多轮 turns 是否按顺序对应；
- 前端展示是否没有过时字段。

所以当前报告需要增加业务断言列，否则会继续出现“通过行里藏核心业务问题”。

---

## 五、建议修复方案（先确认后执行）

### 修复 1：统一 `marketting-planning` mock case 输入口径（P0）

建议选择一个标准，不要两套并存：

- 标准输入仍用 `CASE_INPUT_SHAPE`：`query / user_intent / turns / expected_stage...`
- 如果需要支持真实 API body，则在项目 `live.py` 的投递层做 API body 翻译，不要让 mock case 直接长成 API body。

最小修法：

1. 在 `marketting-planning` mock 生成源头中产出 `query` 和 `turns`。
2. `adapter.build_request` 可以兼容读取 `user_text`，但只能作为过渡兜底。
3. api-check 增加断言：输入 `user_text`/`query` 不能在 normalized_request 中丢失。

### 修复 2：按当前 live_schema 修正 expected/reference 生产源头（P0）

不要增加“多轮 expected 特殊包装逻辑”，也不要在校验失败时规避错误。修复原则是：

1. 先确认 `marketting-planning/live_schema.py` 的 `EXTRACT_OUTPUT_SHAPE` 是否就是业务真实输出契约。
2. 如果 `EXTRACT_OUTPUT_SHAPE={"turns": "list"}` 是正确的新契约，则修改 judge/reference/mock/api-check 相关生产方，让它们直接产出同形 expected/reference。
3. 如果业务真实 expected/reference 不应有 `turns`，则说明 live_schema 更新错了，应修正 live_schema，并同步 live actual、frontend/table、api-check 断言。
4. 保留 `checker.reference(result.expected)` 的强校验；它的作用就是发现旧 schema 或关联方未跟上的问题。

验收标准：

- `judge.expected`、`judge.actual`、`trace.extracted_output` 都通过同一个 `live_schema.check.reference/output` 口径。
- api-check 不再出现 `run_chain.judge.expected 不符合 EXTRACT_OUTPUT_SHAPE`。
- 修复不能只改报告 JSON 或前端展示，必须改生产 expected/reference 的源头。

### 修复 3：api-check 增加业务断言列（P1）

新增列建议：

| 列名 | 含义 |
|---|---|
| `business_check` | pass/fail |
| `business_error` | 业务断言失败原因 |
| `critical_paths_checked` | 实际检查的关键字段路径 |

`marketting-planning` 至少检查：

- `live_result.normalized_request.query` 非空；
- `live_result.extracted_output.turns` 存在；
- `judge.actual` 与 `judge.expected` 同形；
- `table_row.output_summary` 不应只是截断 JSON，而应显示业务 stage/path/card 摘要。

### 修复 4：把超时类 setup_error 与 schema mismatch 分离（P1）

当前 `check / batch_run` 超时 600s 会掩盖根因。建议：

- 如果预置 `run_chain` 已经失败，不继续调完整 `/api/check` 或 `/api/batch_run`，直接标记 `blocked_by=run_chain_schema_mismatch`。
- 报告中区分：
  - upstream_blocked
  - timeout
  - schema_mismatch
  - business_assertion_failed

---

## 六、checklist

| 检查项 | 结果 | 证据 |
|---|---|---|
| 找到最新 api-check.xlsx | 通过 | `report/api-check/20260706-180246/api-check.xlsx` |
| 按最小单元格统计 http/schema 状态 | 通过 | 56 行，45 pass，1 fail，10 setup_error |
| 定位主要失败项目 | 通过 | `marketting-planning` |
| 追溯到源头机制 | 通过 | mock input `user_text` → adapter normalized `query=""`；judge expected 单轮裸 dict |
| 评估 `spec/live.md` 完成度 | 通过 | 结构落地，但多轮端到端未闭环 |
| 是否建议直接修改代码 | 暂不执行 | 修复涉及协议/项目/报告生成三层，需要用户确认 |

---

## 七、最终业务判断

`spec/live.md` 的方向是对的，且基础代码已经落地；但最新 `api-check.xlsx` 证明它尚未完成业务闭环。当前最大问题是：

> 多轮 live 的 `turns` 契约只在 live actual 输出侧局部生效，没有贯穿 mock 输入、judge expected/reference、run_chain、frontend/table 和 api-check 业务断言。

建议优先修 P0：

1. 修 `marketting-planning` 输入口径，保证真实用户文本不丢失；
2. 按当前 live_schema 修正 judge expected/reference 生产源头；不要通过特殊包装或规避错误来掩盖不一致；
3. 再重跑 api-check，确认 `marketting-planning` 的 1 个 fail 和 10 个 setup_error 是否消失。
