# 方案 2026-09-21 v2（已对齐）：Session 收口、多轮 case 落盘、过程轴错误分流

状态：已与用户对齐，待实施。取代 `plan-20260921-session-repair-and-process-axes.md`（v1，保留作验证记录）。

对齐结论：
- 执行层不再区分单轮/多轮，Session 是唯一路径；多轮 case 的正常形态是**提前准备好的 transcript seed**，批量时逐字重放给 judge。
- intent 只由 judge 推断，没有"用户声明的 intent"。
- 过程轴失败根因是一次临时 `same_model` 补跑留下的历史结果，配置本身（默认 `any`）不用调；`same_model` 相关代码**不动**。
- 进程内扮演用户（PersonaDriver）保留现状，后续再优化。

---

## 1. 现状（已完成，不再动）

```
execute_live(case)
  ├─ case 带 seed                      → ReplayDriver   逐字重放录制的用户轮次，比较响应，记 diverged_at_turn
  ├─ 无 seed，max_turns>1 且 mock 实现
  │   MultiTurnInteractiveMock         → PersonaDriver  进程内扮演用户（policy_search / deerflow / marketting-planning 老路）
  └─ 其他                              → OneShotDriver  一发一收
```

- 轮数只看 `project.yaml` `runtime.session.max_turns`（有 seed 时取 seed 轮数）和预算，没有单轮/多轮类型。
- trace / live.html / summary.html 多轮展示统一；harness 的 HTTP 会话接口（`session_store` open/send/close）任何项目可开多轮，MCP 只是包一层（`impl/harness_mcp.py` 未写，不在本方案范围）。
- 已验证：6 golden 逐字段一致；agno 环境 174 定向测试通过、全量无新增失败；真实后端 + 真实 LLM 跑 policy_search 两轮 case，live trace 与基线 `cde26b13` 逐字段一致。

---

## 2. 多轮 mock case = transcript seed

### 2.1 格式

普通 `MockCase` + `seed` 字段，同一 list 可与单轮 case 混放，`parse_mock_case` 直接解析：

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
      {"turn_index": 1, "message": {"type": "text", "text": "保额"},     "request": {"...首轮请求体..."},
       "extracted_output": {"status": "UNSUPPORTED", "message": "“保额”缺少必要的条件，请补充后重试", "stage": null},
       "assistant": "“保额”缺少必要的条件，请补充后重试"},
      {"turn_index": 2, "message": {"type": "text", "text": "50万以上"}, "request": {},
       "extracted_output": {"status": "SUCCESS", "message": "解析成功", "stage": null},
       "assistant": "解析成功"}
    ],
    "intent_history": []
  }
}
```

重放规则（`ReplayDriver`）：
- `turns[].message` 存在 → 经项目 `SessionTranslator` 重译成请求（policy_search 沿用上一轮请求只换 query）；缺省 → `request` 原样透传。
- `extracted_output` 为 dict → 按 `output_signature`（`_summarize_assistant` 文本 + `stage`）比较，首个不一致记 `diverged_at_turn`；为 `null` → 不比较。只需存 `message/status/stage`。
- 结束用 seed 的 `stop_reason`。

### 2.2 三个来源，一个形态

| 来源 | 谁产生轮次 | 落盘 |
|---|---|---|
| 外部 agent（Codex 等）经 harness 打会话 | 外部 agent | `session_close` 自动导出 seed → 候选文件（§4） |
| 手写 | 作者 | 直接写 §2.1 格式 |
| PersonaDriver 现场跑出的多轮 | 进程内 mock | 跑完 `Session.transcript_seed()` 固化为 seed |

批量评测统一 `batch-run --inputs <文件>`，重放不需要 agent 在场，judge 拿整份 trace 判一次。

### 2.3 已落地样本

`impl/data/policy_search/mock_cases-transcript.json`（3 条，默认加载器只认 `mock_cases.json`，不会自动扫到；用户审后自行拷入默认池）：

| id | 轮次 | 真实后端响应 |
|---|---|---|
| policy-search-transcript-0001 | 保额 → 50万以上 | UNSUPPORTED → SUCCESS |
| policy-search-transcript-0002 | 那种比较贵的 → 保费一年超过1万的 | UNSUPPORTED → UNSUPPORTED |
| policy-search-transcript-0003 | 保单 → 被保人叫张三的 → 而且是今年生效的 | UNSUPPORTED → SUCCESS → UNSUPPORTED（第三轮后端未带上下文） |

```bash
PYTHONPATH=. python -m impl.cli batch-run --project policy_search \
  --inputs impl/data/policy_search/mock_cases-transcript.json --concurrency 1
```

真实后端跑两遍：全走 `ReplayDriver`，轮数 2/2/3 与 seed 一致，transcript / stop_reason / completion 齐全，带录制输出后 `diverged_at_turn=None`。judge 因 §3 的 NameError 未出结果。

---

## 3. intent：judge 自推断

- judge 输入 = 原始 request + 整份 transcript + scenario / business objective，自己推断用户目标，写进每条 `BusinessExpectation.user_intent`。现状已如此（`pipeline.judge()` 不传 `user_intent`，evidence view 不含 `mock_intent`），不改。
- mock 侧 `infer_user_intent` 产出的 `scenario / next_query` 只是 PersonaDriver 的执行参数，留在 case 元数据，不送 judge。
- **要改**：`impl/projects/policy_search/judge.py` `build_intent_frame()` 里悬空的 `_intent_from_trace(trace)` 调用（函数已被删，现 policy_search 全部 judge `not_evaluable`）→ `"user_goal": query`；补测试覆盖 `build_intent_frame`。

---

## 4. harness 导出改写候选文件

现状：`session_store.py` `session_close` → `case_pool.append_cases(project_id, "harness-<run_id>", [seed_case])` → `impl/data/case_pools.json`。

改为：追加写 `impl/data/<project_id>/mock_cases-<run_id>.json`（list of MockCase，同 id 覆盖，不存在则新建），close 响应里 `pool / pool_id` 换成 `candidate_file`。用户审后手动拷入 `mock_cases.json`。`case_pool.append_cases` 若无其他调用方则删（不留兼容层）。

---

## 5. 过程评测轴：只做错误分流

### 5.1 事实

- 直接跑最差样本 ctx-ellipsis（57 万字、17 片，现配置 `any` + gemini）：17/17 结构校验通过，0 修复，六视图 24–54 条 refs。格式约束、上下文都没问题。
- 报告 30 样本：21 个 `any` 全成功 0 修复；9 个全挂的都是 `same_model`、`llm_attempts=0`、每片 <1s，文件时间 20:12–20:18 晚于其他（18:01–19:52），是一次临时设 `EVAL_AXES_MODEL_POLICY=same_model` 的续跑补出来的历史结果。代码默认 / config / .env 都是 `any`，配置不用动。
- 错误被伪装：`complete_json` 请求层失败返回 `{"error": "llm_request_failed", "raw_text": ...}`（不抛），`trace_analysis.py` 把它当模型输出过 `_validate` → 报"结构输出必须含 route/..." → 重试 → salvage 成空 → 六轴 not_evaluable，真实错误文本丢失。

### 5.2 修法

`impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py`（及其它调 `complete_json` 的过程轴 adapter 若有同样写法）：

```python
raw = client.complete_json(...)
if isinstance(raw, Mapping) and "error" in raw:
    raise AxisRequestFailed(str(raw["error"]), str(raw.get("raw_text") or ""))   # 不是 ValueError，不进格式重试 / salvage
```

`runner._run_one` 将其记为轴 `failed`，`usage` 带 `llm_error / llm_error_text`。请求失败与模型格式错误分成两种状态。

不做：不改 `same_model` / `_RouterView` / `AxisLlm`；不改分片、`VIEW_BUDGET_CHARS`、`StructuredOutputSpec`、`_validate`。

### 5.3 收尾

用现配置重跑那 9 个样本（`_replay_process_dossier_tmp.py --force` 或删旧结果续跑），刷掉报告里的历史失败，出一版新的 oracle 对照。

---

## 6. 实施清单

| 步 | 改动 | 文件 | 验证 |
|---|---|---|---|
| 1 | §5.2 请求失败分流 | `eval_axes/adapters/trace_analysis.py`、`eval_axes/runner.py` | 单测：error dict → 轴 failed 且 usage 带错误文本；重跑 9 样本 |
| 2 | §3 judge 删悬空调用，`user_goal=query` | `impl/projects/policy_search/judge.py` + 测试 | 3 条 transcript 样本 judge 出 verdict；库内 case 与基线对比 |
| 3 | §4 harness 导出写候选文件 | `impl/core/session_store.py`、`impl/core/case_pool.py` | harness_cli 打一场，`mock_cases-<run_id>.json` 可被 `batch-run --inputs` 直接跑 |
| 4 | lint：清 unused import | `impl/core/live_protocol.py` 等 | ruff |

不在范围：`same_model`；`impl/harness_mcp.py`（9/19 C1–C3）；`session_judge` 接六轴（C5）；llm_probe 进程内扮演用户；llm_probe 之外项目的过程轴。

## 7. 环境

- Python：`/Users/xiaozijian/miniconda3/envs/agno/bin/python`（默认 `python3` 是 3.9，agno 版本不匹配）。
- policy_search 需 `source .env`（`POLICY_SEARCH_REPO`），否则 judge 报 `PATH_ROOT_UNBOUND business_source`。
- 备份：基线 git `cde26b13`；antigravity 改后 `../backup-20260921-session-unify/`；本次覆盖前 9 文件 `../backup-20260921-session-unify/pre-devin/`。

---

## 8. 实施记录（2026-09-21）

### 步 1 · §5.2 请求失败与格式错误分流（已完成）

- `eval_axes/types.py`：新增 `AxisRequestFailed(RuntimeError)`（字段 `error` / `raw_text`）与 `raise_for_error_payload(raw)`（`Mapping` 含 `"error"` 即抛）。
- `adapters/trace_analysis.py`、`adapters/process_common.py`（`ask()`）：`complete_json` 之后立即 `raise_for_error_payload`，不再让 error dict 当模型输出进 `_validate` → 重试 → salvage。
- `runner.py::_run_one`：新增 `except AxisRequestFailed` 分支（位于 `AxisTimeout` 之后、通用 `Exception` 之前），记 `failed`，`usage = {elapsed_ms, llm_error, llm_error_text}`，`error = "AxisRequestFailed: <err>"`。
- 测试：`tests/test_llm_probe_eval_axes.py` +2（helper 层、runner 层）；`tests/test_llm_probe_business_trace.py` +1 接线测试（真 adapter + agno 快照 + 桩 LLM 返回 error dict → 轴 `failed`、usage 带 `401` 原文）。
- 重跑（`scripts/_replay_process_dossier_tmp.py --kind clean --force --workers 3`）：报告里历史「全挂」样本实测为 **8 个**（§5.1 写的 9 个；判据 `llm_attempts=0`，全库零调用样本就是这 8 个）。重跑后 **30/30 样本全部有真实 LLM 调用、0 个 failed 轴、0 个 `llm_error`**。8 个样本 verdict：`trace_analysis` complete ×8、`intent_understanding` sound ×8、`planning_routing` sound ×8；`context_memory` not_evaluable ×6 / problematic ×2；`knowledge_data` sound ×6 / problematic ×1 / not_evaluable ×1；`model_capability` not_evaluable ×4 / problematic ×3 / sound ×1；`tool_execution` sound ×6 / not_evaluable ×2。历史失败确系临时 `same_model` 续跑所致。

### 步 2 · §3 judge 自推断（代码已完成，真实样本待跑）

- `impl/projects/policy_search/judge.py`：`user_goal` 改为直接取首轮 `query`，删掉悬空的 `_intent_from_trace` 调用。（注：HEAD `cde26b13` 里这个函数**有定义**，读 `trace.mock_intent`；当前树定义已随 judge 不再吃 `mock_intent` 一并删除，所以调用才悬空。）
- 测试：新增 `tests/test_policy_search_judge.py` 2 条（单轮 user_goal=首轮 query；多轮逐轮列出 request_candidates）。
- 真实样本验证：`python -m impl.cli batch-run --project policy_search --inputs impl/data/policy_search/mock_cases-transcript.json --concurrency 1` → 3 条全部跑完（2/2/3 轮多轮重放），judge 各出一条 verdict：`0001` fulfilled；`0002` not_fulfilled（missing 1 / wrong 1，保费短答未承接）；`0003` not_fulfilled（missing 1 / wrong 1，“而且”追加条件未继承）。`check_passed=true`、无 fallback。修前这一路径全部报 `not_evaluable`。

### 步 3 · §4 导出改候选文件（已完成，live 已验）

- `impl/core/session_store.py`：新增 `_append_candidate_case`：写 `impl/data/<project>/mock_cases-<run_id>.json`（同 id 覆盖，无 run_id 则 `adhoc`）；`_export` / `_closed_event` / `list_exports` 的 `pool` / `pool_id` 全部改为 `candidate_file`。
- `impl/core/case_pool.py`：删 `append_cases`（唯一调用方是 session_store）；pool 的 open/close 能力本身保留。
- 前端与文档同步：`impl/frontend/explore.html` 显示 `candidate_file`；`spec/mock/protocol.md`（能力表、4.10、5.1 CLI 注释、5.2）同步。
- 测试：`tests/test_session_store.py` 改为校验候选文件落盘路径 / 内容 / `parse_mock_case` 回放可用（3 passed）。「可直接跑」离线依据：写入为 JSON list，而 `impl/cli.py:220` 的 `--inputs` 与 `impl/core/pipeline.py::batch_run` 正好吃 list，逐条经 `parse_mock_case`（批处理唯一解析入口）。
- live 验证（做完才发现一个真 bug，已修）：旧 server 进程（9/19 20:18 启动）已陈旧，另起 `--port 8123` 后跑真会话。**修前 close 必 500**：套件把 `candidate_file` 也写进了**导出文件** payload，而 `portable_artifact` 路径契约禁止 `*_file` 字段放裸路径（`PATH_SCHEMA_BYPASS: active artifact path fields must use LogicalPathRef`）——候选文件已写出、导出文件未写。修法：落盘 payload 不放该字段（plan §4 只要求“close 响应”换字段）；`export_of()` 在**响应**层按 `_candidate_file_path` 补上（单一命名来源，不落盘、不踩契约）；`_candidate_file_path` / `_repository_relative` 抽为模块级函数供两边共用。
- 同时补上测试漏洞：fixture 原来自带 `_write_json` 替身，只跑了 family 形状校验、绕过了真实 writer 的 payload 归一化，所以这个 bug 离线全绿。现补 `PortableArtifactWriter().validate(payload)`（已反向验证：带裸路径会被拦）。
- live 验收链路：`session open → intent → send×2 → close` → 导出文件 + `mock_cases-verify-v2-step3.json`（1 条、`level=transcript`、2 轮）→ `batch-run --inputs` 直接跑（2 轮重放、0 fallback、judge fulfilled）；`session get` 也能拿到 `candidate_file`。验证用产物已删（未污染 `impl/data`）。

### 步 4 · lint（已完成）

- `ruff check --select F401 --fix` 清 31 处（S1/v2 触及的 29 个文件）；仓内本方案外仍有 85 处 F401，未动。
- 副作用修复：ruff 曾误删 `tests/test_cassette.py` 里 `_fake_live_http` 的导入（`tests.test_core_live_protocol` 的 autouse fixture，隐式使用），已用 `# noqa: F401` 恢复。

### 计划外发现（未改，仅上报）

- **8022 上的 server 是 9/19 20:18 启动的旧进程**（S1 改名前的代码）：`session open` 会报 `cannot import name 'MultiTurnInteractiveLive'`（当前树已无此名字）。验证时没动它，另起了 `--port 8123`。**用户侧需重启 8022**。
- `impl/cli.py::_cli_check_request` 把**整条 case 字典**拿去做 `live_schema.check.request`，而应校的是 `case["live_request"]`：所以 `batch-run --inputs` 对 policy_search 每条都打一条假 `WARNING: CLI input does not match REQUEST_SCHEMA`（常规 `mock_cases.json` 同样中招）。非阻断，未改。

### 回归

全量 `pytest tests/ -q`（含 live 验证后的修复，最终树）：**9 failed / 1349 passed / 4 skipped**（637s），9 个失败与 HEAD 基线完全一致、均属计划外历史问题：`test_config_contract` ×1、`test_deerflow_attribute_evidence` ×6（fixture 目录从未入 git）、`test_schema_validator` ×2（py3.11 PEP604 `types.UnionType`）。本方案未引入新失败。

