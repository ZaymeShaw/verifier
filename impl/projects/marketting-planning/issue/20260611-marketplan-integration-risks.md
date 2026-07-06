# marketing-planning 接入当前评估系统的分歧点和坑点

记录时间：2026-06-11

范围：只读分析 `/Users/xiaozijian/WorkSpace/package/marketing-planning` 业务仓库，记录该项目接入当前 verifier/eval 系统前需要先明确的分歧点和风险点。本文件只记录分析结论，不代表已经实现接入。

## 一、业务项目事实

### 1. 项目定位

该项目是“平安寿险 NBEV 达成路径规划智能体”，面向代理人，通过对话式交互识别用户意图，在必要时澄清字段，并最终从队伍、客户、产品三个维度给出月度 NBEV 达成路径分析结果。

证据：

- `/Users/xiaozijian/WorkSpace/package/marketing-planning/README.md`
- `/Users/xiaozijian/WorkSpace/package/marketing-planning/app/main.py`
- `/Users/xiaozijian/WorkSpace/package/marketing-planning/app/workflow/nbev_workflow.py`

### 2. 服务和接口

服务基于 FastAPI，入口为 `app.main:app`，启动脚本通过 gunicorn 启动。

主要接口包括：

- `POST /api/v1/marketing-planning/stream`：全流程 SSE 流式接口。
- `POST /api/v1/nbev/achievement-path-planning/stream`：旧路由兼容。
- `POST /api/v1/marketing-planning/intent-recognition`：仅意图识别。
- `POST /api/v1/marketing-planning/execution/stream`：仅功能执行，跳过意图识别。
- `POST /api/v1/chat`：内部测试用非流式接口。

证据：

- `/Users/xiaozijian/WorkSpace/package/marketing-planning/README.md`
- `/Users/xiaozijian/WorkSpace/package/marketing-planning/docs/营销规划智能体接口文档【新版】.md`
- `/Users/xiaozijian/WorkSpace/package/marketing-planning/app/api/router.py`

### 3. 核心 workflow

当前 workflow 由四步组成：

1. 意图识别。
2. 字段澄清。
3. 并行路径规划。
4. 结果组装。

关键代码：

- `app/workflow/steps/intent_recognition.py`
- `app/workflow/steps/field_clarification.py`
- `app/workflow/steps/path_planning.py`
- `app/workflow/steps/result_assembly.py`

### 4. 外部依赖

项目至少依赖以下外部或半外部能力：

- DashScope / Qwen 模型，用于意图识别和字段抽取。
- Doris 或类似数据查询能力，用于真实队伍、客户、产品路径分析。
- SQLite session store，用于多轮字段累积。
- 本地 mock / fallback 数据和真实业务分析函数。

注意：业务仓库配置文件里存在硬编码模型 API key。接入 verifier 时不能把该值写入 RunTrace、frontend_view、报告或 case pool。

## 二、主要分歧点

### 分歧点 1：这是多轮状态型 agent，不是单轮无状态接口

当前 `client_search` 类项目更像 `query -> parse result -> judge`，而 marketing-planning 是：

```text
session -> intent -> clarification -> session state -> planning -> SSE cards
```

因此 case 不能只包含一个单轮 query。评估时必须知道当前轮属于：

- 首轮澄清；
- 字段补充；
- 字段完整后的规划执行；
- 目标值调整；
- 达成测算调整；
- 非本 agent 意图；
- fallback 场景。

如果直接按单轮 case 接入，会误判补充式输入。例如用户只说“300万”，单看这轮是不完整输入，但在已有 session 中可能是正确的目标值补充。

### 分歧点 2：主输出是 SSE 事件序列，不是单个 JSON 答案

业务主接口是 SSE 流式接口。评估不能只看最终文本或最终 JSON，需要至少检查：

1. 事件序列是否正确：`reasoning_message_content`、`card_start`、`card_message_content`、`run_finished` 等事件是否按预期出现。
2. 增量行为是否正确：每条路径完成后是否输出一帧，`card_list` 是否是累积全量。
3. 最终结果是否正确：最终帧是否包含完整 card list 和推荐追问卡片。

如果 adapter 只抽取最后一帧，会漏掉流式行为、事件顺序和中间路径增量输出错误。

### 分歧点 3：judge 必须按 workflow 阶段判断

该项目的正确性首先取决于当前阶段是否正确，而不是回答内容看起来是否合理。

例子：

- 用户只说“帮我做 NBEV 规划”，正确输出应是澄清卡片，不是规划结果。
- 用户只补充“目标值是 300 万”，如果还缺路径，正确输出应是路径澄清卡片。
- 只有目标值和路径类型都齐全时，才应执行规划。

因此 judge 需要按 scenario 拆分标准：

- intent recognition；
- clarification；
- multi-turn field accumulation；
- single-path planning；
- multi-path planning；
- adjustment；
- non-agent intent；
- fallback/data unavailable。

### 分歧点 4：reference 不能是唯一标准答案

NBEV 规划结果包含预测值、达成率、卡片结构、AI 分析文本和业务明细，不适合用固定答案 exact match。

更合理的 reference 应是条件式标准，例如：

```json
{
  "expected_stage": "clarification | planning | non_agent | adjustment",
  "expected_intent": "nbev_planning",
  "required_cards": [],
  "required_path_types": [],
  "required_fields": [],
  "forbidden_cards": [],
  "fallback_allowed": false,
  "semantic_requirements": []
}
```

否则容易出现两类误判：

- 对开放式 AI 文案过度严格，误判正确输出。
- 对结构性缺失过度宽松，放过真实错误。

### 分歧点 5：application boundary 需要比 client_search 更细

该项目不是一个单一下游可用性问题，至少有三类边界：

1. LLM 边界：DashScope 是否可用，规则路径是否能覆盖当前 case。
2. 数据边界：Doris/真实业务数据是否可用，mock/fallback 是否是当前允许边界。
3. Session 边界：SQLite session store 是否可用，session 是否被正确读写和清理。

因此不能只用类似 `result_set_verified` 的单一字段，需要项目级 application boundary 描述：

- `llm_available`
- `data_source_available`
- `session_store_available`
- `planning_functions_available`
- `fallback_allowed_by_scenario`
- `judge_scope`

### 分歧点 6：fallback 既可能是正确行为，也可能掩盖错误

业务代码中队伍、客户、产品三个 planning service 都会在真实函数异常或返回无效数据时返回 `SORRY_CARD`。

证据：

- `app/services/planning/team_planning.py`
- `app/services/planning/customer_planning.py`
- `app/services/planning/product_planning.py`
- `app/services/planning/normalization.py`

这对评估是高风险点：

- 如果 case 目标是验证数据不可用时能优雅兜底，`SORRY_CARD` 可能是 correct。
- 如果 case 目标是完成真实 NBEV 规划，`SORRY_CARD` 应是 incorrect 或 uncertain。
- 如果 trace 不记录真实函数失败原因，judge 只能看到正常响应，容易误判。

### 分歧点 7：path_types 是执行图选择，不是普通字段

`path_types` 决定实际执行哪些路径：队伍、客户、产品。

评估时必须检查：

- 用户选了几条路径；
- 是否只执行了被选路径；
- 是否额外执行未选路径；
- 是否漏执行已选路径；
- 多路径并发完成后是否正确组装；
- card sort/card code 是否和路径对应。

这和 QA/client_search 的单输出评估明显不同。

### 分歧点 8：卡片结构复杂，adapter 需要强归一化

最终输出卡片包含多层结构：

- `card_code`
- `card_style`
- `card_name`
- `card_desc`
- `card_data`
- `analysisType`
- `calculationSummary`
- `forecastValue`
- `achievementRate`
- `aiAnalysis`
- 各路径专属字段

如果 adapter 直接把完整 raw card JSON 交给 judge，会使 judge 被大对象干扰。接入时应抽取稳定摘要，例如：

```json
{
  "events": [],
  "final_intent": "",
  "final_stage": "",
  "card_summary": [
    {
      "path_type": "队伍",
      "card_code": "",
      "card_style": "",
      "is_fallback": false,
      "forecast_value": 0,
      "achievement_rate": 0
    }
  ],
  "missing_required_fields": [],
  "session_fields": {},
  "errors": []
}
```

### 分歧点 9：已有测试数据主要覆盖 intent，不足以覆盖全链路

仓库已有 `data/intent_recognition_eval_dataset.jsonl`，主要是 query 到 expected intent 的数据。

这适合 intent-recognition eval，但不足以覆盖：

- 字段澄清；
- session 累积；
- SSE 事件；
- 路径执行；
- fallback；
- 卡片结构；
- 多路径并行；
- next-step recommendation。

如果直接把它当完整 case pool，会导致评估范围过窄。

### 分歧点 10：全流程接口、拆分接口、内部接口容易形成 split-brain

项目同时存在：

- 全流程 `/stream`；
- 拆分接口 `/intent-recognition` + `/execution/stream`；
- 内部 `/chat`。

接入时必须明确主评估路径。建议以 `/api/v1/marketing-planning/stream` 为主，因为它是用户真实路径；`/chat` 和拆分接口只作为局部验证或辅助 probe。

否则可能出现：

- `/chat` 正确但 SSE 错误；
- 全流程正确但拆分接口错误；
- verifier 测了内部接口，但前端实际链路仍然失败。

## 三、主要坑点

### 坑点 1：真实依赖和 fallback 会掩盖错误

真实路径函数失败时可能被包装成 `SORRY_CARD` 正常返回。如果 trace 不记录真实函数是否调用、校验是否失败、fallback 原因是什么，judge/attribute 会误判。

接入时需要在 `RunTrace.extracted_output`、`RunTrace.fallbacks` 或 `RunTrace.execution_trace` 中记录：

- 哪条路径 fallback；
- fallback 原因；
- 真实函数是否调用；
- 数据校验是否失败；
- 异常类型摘要；
- 当前 scenario 是否允许 fallback。

### 坑点 2：多轮 session 会污染 batch

项目有 session store。如果 batch case 复用 session_id，case 之间会互相污染。

典型风险：

1. case A 写入 `target_value=300`。
2. case B 没给目标值但复用 session。
3. 系统误以为 case B 字段完整并进入规划。
4. judge 误判。

接入 batch 时，每个 case 必须生成独立 session_id，或者 adapter 必须提供 session reset/隔离机制。

### 坑点 3：SSE 和卡片大对象可能再次触发前端 storage quota

该项目的 raw SSE frames、card_data、AI 分析文本、矩阵/表格数据可能很大。如果未来把完整 raw response、trace、judge、attribute、frontend_view 写入浏览器 casePool，可能重现之前的 `sessionStorage quota exceeded` 问题。

接入时前端持久化应只保存轻量 case source，不保存完整 SSE/card payload。

### 坑点 4：LLM 产物不能再完全交给 LLM judge

业务本身用了 LLM 做意图识别和字段抽取。如果 verifier judge 也完全依赖 LLM，就会形成：

```text
LLM 产物 -> LLM judge -> LLM attribution
```

中间缺少可执行证据。

应优先用确定性检查：

- intent code 是否匹配；
- required fields 是否齐全；
- card code/card style 是否正确；
- path count 是否匹配；
- event sequence 是否正确；
- fallback 是否符合 boundary。

LLM judge 只适合做开放文本质量的补充判断。

### 坑点 5：目标值单位和数值转换高风险

`target_value` 业务单位是“万”。风险包括：

- “300万”是否变成 `300`；
- “3000000”是否被错误当成 `3000000 万`；
- 小数目标值如何处理；
- 新目标值是否覆盖旧 session 值；
- 调整目标值时是否保留 path_types。

这些应作为单独 scenario 测试。

### 坑点 6：路径顺序和 card_sort 存在潜在不一致

配置和文档显示路径顺序倾向于：

```text
队伍 -> 客户 -> 产品
```

但 `app/workflow/steps/result_assembly.py` 中 `CARD_CONFIG` 当前是：

```text
customer -> 1
product -> 2
team -> 3
```

这可能导致前端展示顺序、文档标准和实际实现不一致。接入前需要确认最终评估标准到底以哪个为准。

### 坑点 7：状态码口径可能不一致

文档中状态码说明包括：

- `200` 成功；
- `4001` 非本 agent 意图；
- `5001` 调用报错。

但代码中存在：

- `SUCCESS_CODE = 0`
- `ERROR_CODE = -1`
- `WorkflowResponse.code` 默认 `0`

此外 `_build_intent_response()` 对 `IntentType.other` 返回 `code=0`、`msg="非本agent意图"`、`nlu_code="other"`。

这说明文档和实现存在口径分歧。接入 verifier 前必须确认 judge 应以文档为准，还是以当前实现为准。

### 坑点 8：配置文件存在疑似敏感信息

业务仓库配置文件中存在硬编码模型 API key。接入 verifier 时必须避免：

- 把 secret 原值写入 RunTrace；
- 把 secret 原值暴露到 frontend；
- 把 secret 原值写入 issue/report；
- 把完整 config raw dump 存入 case pool。

需要 evidence 时只记录 key 是否存在、配置来源和脱敏状态。

### 坑点 9：当前业务函数可能处于半 mock / 半真实状态

部分代码注释显示当前使用本地 mock 数据，未来要替换成真实 Doris/sql 查询。

这意味着接入评估时必须明确：

- 当前本地评估是否允许 mock 数据；
- mock 数据是否属于 application boundary 内的预期行为；
- 真实 Doris 不可用时 fallback 应判 correct、incorrect 还是 uncertain；
- mock 下通过不能直接等价于生产正确。

### 坑点 10：attribute 如果没有细粒度 trace 会很容易空泛

如果只记录最终 card_list，attribute 很可能只能输出“模型理解错误”“规划失败”“数据不可用”等泛泛结论。

接入时需要在 trace 中保留关键链路节点：

1. request normalization；
2. intent recognition：规则命中还是 LLM；
3. field clarification：regex、LLM、session 分别贡献了什么；
4. session merge：旧值、新值、覆盖关系；
5. path dispatch：选择了哪些路径；
6. 每条 path 的真实函数调用、校验、fallback；
7. result assembly；
8. SSE frame generation；
9. adapter output extraction。

## 四、建议的评估 scenario 切分

### Scenario 1：intent_recognition

评估 query 到 intent 的识别是否正确。已有 `data/intent_recognition_eval_dataset.jsonl` 可作为初始数据来源。

重点判断：

- intent 是否正确；
- 非 NBEV 是否不进入规划；
- confidence 只作为辅助证据，不作为唯一正确性依据。

### Scenario 2：clarification

评估字段缺失时是否返回正确澄清卡片。

重点判断：

- 缺目标值时是否问目标值；
- 缺路径类型时是否问路径；
- 两者都缺时是否返回两张卡片；
- 不应提前进入规划。

### Scenario 3：multi_turn_field_accumulation

评估多轮 session 是否正确累积字段。

重点判断：

- session 是否隔离；
- 当前轮新值是否覆盖旧值；
- 字段齐全后是否进入规划；
- case 之间不能串状态。

### Scenario 4：execution_planning

评估字段完整后的路径执行和卡片结果。

重点判断：

- 执行路径数量是否等于用户选择；
- 是否漏执行或额外执行；
- card_code/card_style/card_sort 是否正确；
- fallback 是否符合当前 boundary。

### Scenario 5：streaming_protocol

评估 SSE 协议行为。

重点判断：

- 事件顺序；
- `card_message_content` 数量；
- `card_list` 是否累积；
- `run_finished` 是否含完整结果；
- `end_flag` 是否正确。

## 五、后续接入建议

1. 暂时不要改 generic protocol，优先通过 project adapter 承接该项目差异。
2. 主评估路径建议选择 `/api/v1/marketing-planning/stream`，因为这是用户真实链路。
3. `/api/v1/chat` 可作为局部 debug，不应作为唯一评估路径。
4. 必须先定义 project evaluation spec 和 application boundary，再写 judge/attribute。
5. adapter 的 `extract_output` 应输出轻量、稳定、可 judge 的结构摘要，不要直接把完整 SSE/card raw object 塞给 judge。
6. batch case 必须隔离 session_id，避免状态污染。
7. issue 中标记的文档/实现分歧，例如状态码、card_sort、非本 agent 意图 code，需要先确认标准后再实现。
