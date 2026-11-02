# 方案 2026-09-21：Session 统一修复收口、多轮 transcript seed 落盘、过程评测轴失败根因与修法

状态：方案，待对齐后实施。承接 `inventory-20260920-session-unification.md`（antigravity 会话 a046c980 的 Session 统一）。本文是对该实施的验证结论 + 遗留问题的修法，**未改代码**，只新增了一个候选数据文件（§3.2）。

基线：git `cde26b13`（antigravity 改前）；antigravity 改后快照 `../backup-20260921-session-unify/`；本次覆盖前的 9 个文件 `../backup-20260921-session-unify/pre-devin/`。

---

## 0. 结论一页

| 问题 | 结论 | 需要动代码？ |
|---|---|---|
| Session 统一后多轮项目退化成单轮 | 已修（`PersonaDriver`），真实 LLM + 真实后端跑 policy_search 两轮 case，live trace 与基线逐字段一致 | 已完成 |
| judge 侧 intent 怎么办 | 不加"声明 intent"通道；judge 自推断，落 `BusinessExpectation.user_intent`（schema 已有） | 删 1 个悬空调用点 |
| policy_search judge 全部 `not_evaluable` | antigravity 删了 `_intent_from_trace` 却漏了 `judge.py:112` 的调用 → `NameError` | 是（1 行） |
| transcript seed 落盘格式 / 能否当 mock case 导入 | 就是 `MockCase.seed`，与普通 case 同构、同 list 可混放；`batch-run --inputs` 直接跑；已做 3 条样本实跑通过 | 否 |
| harness 导出去哪 | 现在自动 append 到 `impl/data/case_pools.json` 的 `harness-<run_id>` 池；改为写 `impl/data/<project>/mock_cases-<run_id>.json` 候选文件 | 是 |
| 过程评测轴大量 `not_evaluable` | **不是格式约束、不是上下文**。9 个全挂样本全部是 `model_policy=same_model` 且 `llm_attempts=0`：选不到同名模型端点 → RuntimeError 被 `complete_json` 吞成 `{"error": ...}` → adapter 当模型输出去校验 → 报"结构不合规" → salvage 成空 → 六轴 not_evaluable。`any` 策略的 21 个样本 100% 成功 0 修复 | 是（2 处） |

---

## 1. 执行层：Session + 三个 Driver（已完成，不再动）

```
execute_live(case)
  ├─ ctx.seed 是 dict            → ReplayDriver(seed)     逐字重放，比较录制响应，记 diverged_at_turn
  ├─ max_turns>1 且 mock 实现
  │   MultiTurnInteractiveMock   → PersonaDriver(mock)    进程内扮演用户：infer_user_intent / decide_next_action / build_next_request
  └─ 其他                        → OneShotDriver          一发一收
```

- `max_turns` 来自 `project.yaml` `runtime.session.max_turns`；无 seed 时取配置值，有 seed 时取 `len(seed.turns)`。
- `RunTrace.interaction_mode / execution_mode` 按配置（`session_max_turns > 1`）而不是实际轮数判定（golden 元数据回归的原因，已修）。
- 项目映射：QA / client_search / mpi / llm_probe 无 seed → OneShot；deerflow / marketting-planning / policy_search 无 seed → Persona；任何项目带 transcript seed → Replay。
- harness（外部 agent 打会话）走 `session_store.STORE`，同一个 `Session`，Driver 就是外部 agent 本身。

### 1.1 验证记录

| 验证 | 环境 | 结果 |
|---|---|---|
| 6 个 golden（3 项目 happy + live_error） | agno env | trace 逐字段一致 |
| 定向测试 core_live_protocol / golden / protocols / llm_probe / session_budget | agno env | 174 passed |
| 全量测试 vs HEAD 基线 | agno env | 无新增失败 |
| policy_search 库内 case（rich-0003 等）基线 vs 当前 | 真实后端 8050 + 真实 LLM | 首轮后端返回 SUCCESS，persona 不追问，两边都 1 轮，一致 |
| 手造 `保额 → UNSUPPORTED → 50万以上 → SUCCESS` | 同上 | 两边 2 轮、`session_id=interactive-clarification_reply`、transcript / stop_reason / final_output_turn 全同；仅 exchange_id / 时间戳 / config_fingerprint 不同 |

### 1.2 遗留 bug（antigravity）

`impl/projects/policy_search/judge.py` `build_intent_frame()`：

```python
"user_goal": _intent_from_trace(trace) or query,   # _intent_from_trace 已被删除 → NameError
```

后果：policy_search 的 judge / attribute / check / table_row 整段失效，全部 `not_evaluable`，`reasoning_summary = "name '_intent_from_trace' is not defined"`。测试没覆盖 `build_intent_frame` 所以没拦住。

---

## 2. intent：只由 judge 推断

用户结论："没有所谓声明的 intent，mock 用户一般不会说自己在想什么的，intent 这种只能是 judge 自己推断。"

两个"intent"要分开：

| | 是什么 | 谁用 | 去向 |
|---|---|---|---|
| mock 侧 persona intent（`MockIntentOutput`：`scenario` / `user_context.next_query` …） | 扮演用户的执行参数：决定要不要追问、追问什么 | `PersonaDriver` → `decide_next_action` / `build_next_request` | 留在 `MockCase.intent` / `trace.mock_intent` 作为执行元数据；**不送 judge** |
| judge 侧 user intent | judge 从 request / transcript / scenario / business objective 推断出的用户目标 | judge 主轴 | 落在每条 `BusinessExpectation.user_intent`（schema 已有字段） |

现状已经是这样：`pipeline.judge()` 不传 `user_intent`，`build_judge_evidence_view` 不含 `mock_intent`，judge 只看原始 request 与 trace，等于永远自己推断。

### 2.1 修法

- `policy_search/judge.py`：`"user_goal": query`（删掉 `_intent_from_trace` 调用；不恢复该函数）。
- 不新增 `declared_intent`，不改 evidence view。
- 补一个测试覆盖 `PolicySearchJudge.build_intent_frame()`，防止再次悬空。

---

## 3. 多轮 mock case：transcript seed 落盘与导入

### 3.1 格式

一条多轮 case 就是普通 `MockCase` 加 `seed` 字段（`parse_mock_case` 必填 `id / project_id / scenario / live_request / output / reference`，可选 `intent / seed`，其余字段拒绝）：

```json
{
  "id": "policy-search-transcript-0001",
  "project_id": "policy_search",
  "scenario": "clarification_reply",
  "intent": null,
  "live_request": { "...首轮 REQUEST_SCHEMA 请求体..." },
  "output": null,
  "reference": null,
  "seed": {
    "level": "transcript",
    "mode": "replay",
    "session_mode": "text",
    "protocol_fuzz": false,
    "stop_reason": "goal_satisfied",
    "prefix": [],
    "prefix_mode": null,
    "turns": [
      {
        "turn_index": 1,
        "message": {"type": "text", "text": "保额"},
        "request": { "...首轮请求体（message 缺省时才用）..." },
        "extracted_output": {"status": "UNSUPPORTED", "message": "“保额”缺少必要的条件，请补充后重试", "stage": null},
        "assistant": "“保额”缺少必要的条件，请补充后重试"
      },
      {
        "turn_index": 2,
        "message": {"type": "text", "text": "50万以上"},
        "request": {},
        "extracted_output": {"status": "SUCCESS", "message": "解析成功", "stage": null},
        "assistant": "解析成功"
      }
    ],
    "intent_history": []
  }
}
```

`ReplayDriver` 契约（`impl/core/session.py`）：

- `turns[].message` 存在 → `UserMessage.from_dict` 后 `session.send(...)`，text/action 经项目 `SessionTranslator` 重新翻译成请求（policy_search 的 `request_from_user_message` 会沿用 `state.last_request` 只替换 query）；`message` 缺省 → 用 `request` 原样透传。
- `turns[].extracted_output` 为 dict → 与本次响应按 `output_signature`（= `_summarize_assistant(output)` + `stage`）比较，第一处不一致记 `diverged_at_turn`；为 `null` → 不比较。所以录制值只需 `message`/`status`/`stage`，不必存整份输出。
- 结束用 seed 的 `stop_reason`（缺省 `user_abandons`）。
- `level`：`turns>1` 为 `transcript`，否则 `request`。

### 3.2 已做样本与实跑结果

文件：`impl/data/policy_search/mock_cases-transcript.json`（3 条，默认加载器只认 `mock_cases.json`，不会自动扫到）。

| id | 轮次 | 真实后端响应 | 用途 |
|---|---|---|---|
| policy-search-transcript-0001 | `保额` → `50万以上` | UNSUPPORTED → SUCCESS | 澄清后补全 |
| policy-search-transcript-0002 | `那种比较贵的` → `保费一年超过1万的` | UNSUPPORTED → UNSUPPORTED | 两轮都不支持 |
| policy-search-transcript-0003 | `保单` → `被保人叫张三的` → `而且是今年生效的` | UNSUPPORTED → SUCCESS → UNSUPPORTED | 第三轮后端未携带上下文，天然的多轮缺陷样本 |

命令：

```bash
PYTHONPATH=. python -m impl.cli batch-run --project policy_search \
  --inputs impl/data/policy_search/mock_cases-transcript.json --concurrency 1
```

结果（真实后端跑两遍）：全部走 `ReplayDriver`（`session_id=replay-<case_id>-<hex>`），轮数 2/2/3 与 seed 一致，`conversation_transcript` 四/六条完整，`stop_reason=goal_satisfied`、`completion_status=completed`，第二遍带录制 `extracted_output` 后 `diverged_at_turn=None`。judge 三条都因 §1.2 的 NameError 失败，与 trace 层无关。

### 3.3 三个入口最终形态一致

| 入口 | 谁扮演用户 | 落盘 |
|---|---|---|
| (a) 外部 agent（Codex 等）经 harness 打会话 | 外部 agent | `session_close` 自动导出 transcript seed |
| (b) 手写 transcript seed | 作者 | 直接写 §3.1 格式 |
| (c) request 级 case，`PersonaDriver` 现场生成后续轮 | 进程内 mock | 跑完可用 `Session.transcript_seed()` 固化为 (b) |

三者最终都是带 `seed.level=transcript` 的 `MockCase`，走同一条 `batch-run` 评测，重放不需要 agent 在场。

### 3.4 修法：harness 导出改写候选文件

现状：`session_store.py:311` `case_pool.append_cases(project_id, "harness-<run_id>", [seed_case])` → `impl/data/case_pools.json`。

改为：`session_close` 把 seed case 追加写入 `impl/data/<project_id>/mock_cases-<run_id>.json`（同 id 覆盖，文件不存在则新建，格式即 §3.1 的 list）。响应里的 `pool / pool_id` 换成 `candidate_file`。人工审阅后把条目拷进 `mock_cases.json` 收编。`case_pool.append_cases` 若无其他调用方则删除（不留兼容层）。

---

## 4. 过程评测轴：失败根因与修法

### 4.1 直接复现

在用户本机对最差样本 `clean-traces/llm-probe-insurance-real-ctx-ellipsis.json` 单跑 `trace_analysis` 轴（`.env`：`LLM_MODEL=gemini-3.8-flash-medium`，`eval_axes.model_policy=any`）：

```
STATUS succeeded  chunks 17  repaired_chunks None  elapsed 499s
USAGE  llm_calls 17  llm_attempts 17  llm_failed_attempts 0  dossier_chars 575879  overview_chars 38931
SELECTIONS intent_understanding 42 / planning_routing 54 / tool_execution 34 / context_memory 45 / knowledge_data 24 / model_capability 46
```

17 片全部一次通过结构校验。**格式约束（`StructuredOutputSpec` → `complete_json` 注入 + 后校验）是接上的，57 万字 dossier 分片后也不是问题。**

### 4.2 报告 30 个样本对照（`report/process-dossier-20260920/results/`）

| model_policy | 样本数 | llm_model | llm_attempts | 每片耗时 | repaired_chunks | 结果 |
|---|---|---|---|---|---|---|
| `any` | 21 | qwen3.8-flash | = chunks | 50–90s | 0 | 全部成功 |
| `same_model` | 9 | `""` | **0** | **< 1s** | = chunks（全片） | 六轴全 not_evaluable |

9 个全挂样本：ctx-ellipsis、ctx-ref、intent-negation、model-pressure-confirm、routing-name-search、routing-name-then-status、scenario-benefit-health、scenario-faq-policy-loan（+1）。`llm_calls = 2 × chunks`（每片重试一次），总耗时几秒——模型根本没被调到。

### 4.3 失败链路

```
eval_axes/llm.py  _RouterView.select()
   same_model 下过滤掉所有 model != 角色模型 的端点 → 空 → raise RuntimeError("no endpoint serving model ...")
        ↓
llm_client.py  complete_json()
   except → return {"error": "llm_request_failed", "raw_text": "<RuntimeError 文本>"}      # 不抛，返回 dict
        ↓
adapters/trace_analysis.py  run()
   raw = client.complete_json(...)        # 拿到上面的 error dict
   _validate(raw, ...)                    # set(payload) != {"route",...} → ValueError("结构输出必须含 route/...")
   attempt 0 → 追加"结构或引用格式错误，请重新输出" 再调一次 → 同样的 error dict
   attempt 1 → _salvage() → 空 selections；repaired 记 "片段 N 输出不可用：结构输出必须含 route/..."
        ↓
六个下游轴拿到空视图 → "xxx 未回答 → insufficient_evidence" → not_evaluable
```

真实错误文本（`raw_text`）在这条链上被丢掉，报告里只剩"格式不合规"。

### 4.4 修法（两处，都在 llm_probe 扩展轴内，不动 `LlmClient` / `LlmRouter`）

1. `adapters/trace_analysis.py`（以及其它调 `complete_json` 的过程轴 adapter，若有同样写法）：

   ```python
   raw = client.complete_json(...)
   if isinstance(raw, Mapping) and "error" in raw:
       raise AxisRequestFailed(raw["error"], raw.get("raw_text"))   # 非 ValueError，不走格式重试 / salvage
   ```
   `runner._run_one` 把它记为轴 `failed`，`usage` 带 `llm_error / llm_error_text`。请求失败与模型格式错误从此是两种状态。

2. `eval_axes/llm.py` `AxisLlm.__init__`：`same_model` 且 `_RouterView.endpoints` 为空时**当场**抛 `RuntimeError("eval_axes model_policy=same_model: no endpoint serving model ...")`，让 `build_report` 直接失败并带出模型名与可用端点列表，而不是每片各失败两次。

3. 修完用现 `.env`（`any` + gemini）重跑那 9 个样本，与 21 个成功样本一起出一版新的 `process-dossier` 对照；同时记录一次 `same_model` 的预期失败样例，确认错误文本可见。

### 4.5 不做的事

- 不改 `VIEW_BUDGET_CHARS` / 分片策略：成功样本里 16 片、86 万 ms 的也全过，"排除材料 N"是预算截断的正常提示，不是失败原因。
- 不改 `StructuredOutputSpec` / `_validate` 规则。

---

## 5. 实施顺序与范围

| 步 | 改动 | 文件 | 验证 |
|---|---|---|---|
| 1 | §4.4 ①② 请求失败分流 + same_model 早失败 | `impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py`、`eval_axes/llm.py`、`eval_axes/runner.py` | 单测：error dict → 轴 failed 且 usage 带错误文本；重跑 9 个样本 |
| 2 | §2.1 judge `user_goal=query`，删悬空调用 | `impl/projects/policy_search/judge.py` + 新测试 | `batch-run` 三条 transcript 样本 judge 出 verdict；基线 rich case 对比 |
| 3 | §3.4 harness 导出写候选文件 | `impl/core/session_store.py`、`impl/core/case_pool.py`（视调用方决定删否） | harness_cli 打一场会话，检查 `mock_cases-<run_id>.json` 可被 `batch-run --inputs` 直接跑 |
| 4 | 清理 unused import（lint） | `impl/core/live_protocol.py` 等 | ruff |

不在范围：`impl/harness_mcp.py`（9/19 方案 C1–C3）、`session_judge` 接六轴（C5）、llm_probe 之外项目的过程轴。

## 6. 环境备注

- 项目 Python：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`（默认 `python3` 是 miniconda 3.9，agno 版本不匹配）。
- 跑 policy_search 需 `source .env`（`POLICY_SEARCH_REPO` 等），否则 judge 报 `PATH_ROOT_UNBOUND business_source`。
- 过程轴当前 `.env`：`LLM_MODEL=gemini-3.8-flash-medium`，fallback 两个 `qwen3.8-flash`，`eval_axes.model_policy=any`。

