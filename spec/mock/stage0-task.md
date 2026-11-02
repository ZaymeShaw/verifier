# 阶段 0 任务书：多轮交互 golden trace 基线

> 交给 codex 执行的任务说明。背景与决定见同目录 `protocol.md` 第 9 节"阶段 0"，以及 `discussion-20260907-rollout-pacing.md`。
> 本阶段目标：**立基线，不改现有逻辑**。让一次多轮运行可以离线、逐字节地重跑，作为阶段 1 重构"零行为变化"的判据。

---

## 0. 硬性边界（违反即任务失败）

1. **不得修改**以下文件的任何一行：`impl/core/llm_client.py`、`impl/core/live_transport.py`、`impl/core/live_protocol.py`、`impl/core/trace.py`、`impl/core/pipeline.py`、`impl/core/mock_agent.py`、`impl/core/mock_protocol.py`、`impl/core/context_store.py`、`impl/projects/**` 下所有文件。录制/回放通过在运行时替换方法（monkeypatch 风格）实现，不侵入被测代码。
2. 唯一允许修改的既有文件：`tests/test_core_live_protocol.py`，且**只允许追加**新测试函数，不改动已有内容。
3. 其余全部为**新增文件**。
4. **不得**执行 `git commit` / `git stash` / `git checkout` / `git reset` / `git add`。工作区已有与本任务无关的未提交改动，不要碰它们。
5. 不要新建 `.md` 文档（本任务书已存在）。代码里不写叙述性注释。
6. 运行 Python 一律用 `bash run.sh python ...`（它会选对解释器，pytest 已装）。测试命令：`bash run.sh python -m pytest tests/<file> -q`。
7. **代码质量**：正常 PEP 8 格式——4 空格缩进、一行一条语句、不用分号连写、函数有类型标注。这是会进 git 并被人审阅的基线代码，不是一次性脚本。
8. **包装不得改变被包装方法的行为**：替换 `LlmClient.complete_json` / `LiveTransport.request` 时必须用 `def wrapper(self, *args, **kwargs)` 原样透传，**不得**重新声明参数缺省值。`complete_json` 的 `reasoning_effort` / `tools_override` 缺省是哨兵 `_USE_CONFIG`，显式传 `None` 会改变语义（关闭深度推理）；`stage` / `_caller` 等录制需要的字段从 `kwargs` 与 `self` 上读取即可。
9. **关于仓库里已存在的草稿**：`impl/core/cassette.py`、`scripts/trace_canonicalize.py`、`scripts/record_golden.py`、`tests/test_golden_multiturn.py` 是此前一次被中断的执行留下的**未审阅草稿**，已知问题：违反第 7、8 条；`record_golden.py` 调用了未核实存在的 `run_chain`，且 `--live-base-url-override` 未实现；`test_golden_multiturn.py` 没有做回放比对。**请按本任务书重写这四个文件**，不要在草稿上修补。

---

## 1. 背景事实（已核实，直接用）

- 所有 LLM 调用的唯一收口点：`impl/core/llm_client.py` 中 `LlmClient.complete_json(self, system, user, trace_id=None, reasoning_effort=..., output_spec=None, stage="", tools_override=...) -> Dict`。`impl/core/mock_agent.py` 的 `MockAgent._complete_json` 是它的薄封装，每次调用带 `stage`（如 `infer_intent` / `continue_decision` / `next_turn` / `live_request` / `intent`）。client 上有 `_caller`（role，如 `mock` / `judge`）和 `_project_id` 属性。
- 所有 live HTTP 的唯一收口点：`impl/core/live_transport.py` 中 `LiveTransport.request(self, method, url, *, json_body=None, headers=None, timeout=30.0, carries_live_request=False, contributes_raw_response=False, forbid_content_types=None, sse_last_frame=False) -> LiveResponseView`。它内部调 `urllib.request.urlopen`，成功时返回 `LiveResponseView(exchange_id, status_code, payload, error)` 并把 `LiveExchange` 追加到 `self._exchanges`；失败时先追加 exchange 再抛 `LiveHTTPStatusError(status_code, payload)`（4xx/5xx）或 `urllib.error.URLError(error)`（不可达）。**回放时必须保持这个副作用与异常行为一致**，否则 trace 的 `live_exchanges` 和 `live_error` 分支会不同。
- 每次 LLM 调用会经 `impl/core/context_store.save_context` 落盘到 `data/` 下的 artifact 目录；回放模式下要避免写入仓库（重定向到临时目录或 no-op）。
- 多轮执行入口：`impl/core/pipeline.py` 的多轮 case 执行函数（约第 522 行，调 `trace_from_live`）；单轮入口 `live_run`。阅读 `pipeline.py` 找到多轮 case 的公开入口和它接受的 case 形态（`data/policy_search/mock_cases-multiturn-select.json` 是现成的多轮 case 样本）。
- 三个多轮项目：`policy_search`（live: `http://127.0.0.1:8050`，已在线）、`marketting-planning`（live: `http://127.0.0.1:9006`，已在线）、`deerflow`（live: `http://127.0.0.1:8001`，**当前未启动**；`project.yaml` 开了 `local_deployment`，pipeline 的 `ensure_project_service` 会自动拉起，也可手动 `bash impl/projects/deerflow/scripts/start.sh`）。
- 多轮 mock 的 `safety_max_turns`：`policy_search` 3，另两个 12。
- trace 里的天然不确定字段：`trace_id`（含 `time.time()`）、`created_at` / `started_at` / `finished_at`、`runtime_ms` / `elapsed_ms`、`exchange_id`、`record_id`；请求体里的随机值：`policy_search` 的 `session_id` / `trace_id`（uuid）、`marketting-planning` 的 `session_id` / `ts`（epoch）、`deerflow` 的 `thread_id`（来自 live 响应，回放时相同）。
- 现有测试 `tests/test_core_live_protocol.py` 已用 monkeypatch 替换 `urlopen` 和 `complete_json`，可参考其手法与 fake 项目的构造方式。

---

## 2. 交付物

### 2.1 `impl/core/cassette.py` —— 录制/回放层

- 由环境变量控制：`VERIFIER_CASSETTE=record|replay|off`（默认 `off`），`VERIFIER_CASSETTE_DIR=<目录>`。
- 提供 `install()` / `uninstall()`（或 context manager），在运行时替换 `LlmClient.complete_json` 与 `LiveTransport.request`。
- **record**：调用原方法，把每次调用按顺序追加到 `<dir>/llm.jsonl` 与 `<dir>/live.jsonl`。
  - LLM 记录字段：`seq`、`role`（`_caller`）、`stage`、`system`、`user`、`response`（返回的 dict）、`error`（若抛异常则记异常类型与消息，并重新抛出）。
  - live 记录字段：`seq`、`method`、`url_path`（去掉 scheme/host，保留 path，query 可保留）、`request`（json_body）、`status_code`、`response`、`error`、`raised`（`none` / `http_status` / `url_error` / `forbidden_content_type` / `sse_read_error`）。
- **replay**：不调原方法。
  - LLM：按 `(role, stage)` **顺序匹配**——本次运行中该 `(role, stage)` 的第 N 次调用返回录像带中同 key 的第 N 条 `response`；录了 `error` 则重新抛出同类型异常。
  - live：按 `(method, url_path)` 顺序匹配；重建 `LiveExchange` 追加到 `transport._exchanges`（字段尽量与真实路径一致，`exchange_id` 新生成即可），然后按 `raised` 决定返回 `LiveResponseView` 还是抛对应异常。
  - 任一 key 录像带耗尽、或运行结束时录像带有剩余条目，都要以明确错误报出（这是检测结构回归的手段）。提供 `assert_exhausted()`。
- **replay 模式下**把 `context_store.save_context` 替换为 no-op（或重定向到临时目录），避免污染 `data/`。
- 不改被测代码；所有替换在 `install()` 中完成，`uninstall()` 恢复。

### 2.2 `scripts/trace_canonicalize.py` —— trace 规范化

- 输入 `RunTrace`（对象或 `to_dict` 后的 dict），输出可 JSON 序列化、键排序的规范 dict。
- 规则一（按 key 剔除，任意深度）：`trace_id`、`created_at`、`started_at`、`finished_at`、`runtime_ms`、`elapsed_ms`、`exchange_id`、`record_id`。
- 规则二（对所有剩余字符串做正则遮罩）：uuid（含 32 位 hex 与带连字符形式）→ `<uuid>`；ISO 8601 时间 → `<iso_ts>`；13 位 epoch 毫秒与 10 位 epoch 秒（作为独立 token）→ `<epoch>`。
- 规则三（项目层易变字段）：在 `impl/core/cassette.py` 或独立模块里声明一个 `VOLATILE_FIELDS: Dict[project_id, List[str]]`（点路径），当前值：`policy_search: ["session_id", "trace_id"]`，`marketting-planning: ["session_id", "trace_id", "ts"]`，`deerflow: []`。规范化时按项目剔除。这份列表将来会被 `protocol.md` 6.2 的确定性检查复用，命名清楚即可。
- 提供 CLI：`bash run.sh python scripts/trace_canonicalize.py <trace.json> [--project X]` 输出规范 JSON；以及可 import 的函数 `canonicalize(trace_dict, project_id) -> dict`。

### 2.3 `scripts/record_golden.py` —— 一次性录制

- 用法：`bash run.sh python scripts/record_golden.py --project <id> --case-file <path> --case-id <id> --out tests/golden/<project>/<case_id>/`
- 流程：设 `VERIFIER_CASSETTE=record` + 目录 → `cassette.install()` → 调 pipeline 多轮入口跑该 case → 得到 `RunTrace` → 写 `case.json`（原始 case）、`llm.jsonl`、`live.jsonl`、`trace.canonical.json`（规范化后）、`trace.raw.json`（未规范化，便于人工排查）。
- 支持 `--live-base-url-override <url>`，用于录 `live_error` 场景（把该项目 live 指向不存在的端口，例如 `http://127.0.0.1:1`）。查阅 `impl/core/project_config.py` / `project_loader.py` 找运行时覆盖 `runtime.services.primary.base_url` 的方式；若确无覆盖机制，可在录制脚本内对加载后的 `spec` 对象做就地修改（这是脚本内的行为，不改被测代码）。

### 2.4 `tests/golden/<project>/<case_id>/` —— golden 数据

每个多轮项目录两条：
- `happy`：正常走到 `stop_reason=goal_satisfied`（或该项目 mock 在正常情况下实际产生的停止原因，以实际为准）。
- `live_error`：live 不可达，预期 `stop_reason=live_error`。

case 选择：`policy_search` 从 `data/policy_search/mock_cases-multiturn-select.json` 挑一条 `interactive` 场景；另两个项目查看各自 `project.yaml` 的 `mock_cases` 配置和 `data/` 下是否有 case 文件，没有则用项目 mock 的 `generate_mock_case` 生成一条并把生成结果存进 `case.json`（生成过程的 LLM 调用**不在**录像带范围内，录像带只录执行阶段）。

`deerflow` 需要先把服务起来（见第 1 节）。若某项目的 live 在录制时确实无法成功跑通（非本任务可解决的环境问题），跳过该项目的 `happy`，只录 `live_error`，并在最终报告中说明原因。

### 2.5 `tests/test_golden_multiturn.py` —— 回放比对测试

- 遍历 `tests/golden/*/*/`，对每个目录：设 `VERIFIER_CASSETTE=replay` → `install()` → 跑同一 pipeline 入口 → `canonicalize` → 与 `trace.canonical.json` **逐字节比对**（序列化后字符串相等；不等时输出 unified diff 便于定位）→ `assert_exhausted()` → `uninstall()`。
- 用 `pytest.mark.parametrize` 按目录参数化，目录不存在时 skip 而不是失败。
- 回放不得访问网络、不得依赖 live 服务在线。验证方法：在 `install()` 后额外 monkeypatch `urllib.request.urlopen` 为直接抛异常的函数，确保没有漏网的真实调用。

### 2.6 `tests/test_core_live_protocol.py` —— 追加断言缺口（只追加）

用该文件已有的 fake 项目/fake mock 手法，追加三条测试：
- `safety_max_turns`：mock 一直 `continue`，跑满 `safety_max_turns()` 轮 → `ctx.stop_reason == "safety_max_turns"`、`completion_status == "incomplete"`、`interaction_controller_status == "ok"`。
- 多轮中途 `live_error`：前 1 轮成功、第 2 轮 `deliver_turn` 抛 `URLError` → `stop_reason == "live_error"`、`completion_status == "incomplete"`、**`interaction_controller_status == "ok"`**（验证 live 故障不被记到 mock 头上）、`turn_count == 2`。
- `intent_unavailable`：`intent=None` 且 `infer_user_intent` 抛异常 → `stop_reason == "intent_unavailable"`、`completion_status == "incomplete"`、`interaction_controller_status == "error"`。

---

## 3. 执行顺序

1. 先做 2.1 + 2.2，然后**用 `tests/test_core_live_protocol.py` 里现有的 fake 项目**写一个自检：record 一次 → replay 一次 → canonicalize 两者 → 相等；并验证"录像带耗尽"和"录像带剩余"两种错误都能报出。这个自检可以放在 `tests/test_cassette.py`。
2. 做 2.6。
3. 做 2.3，先对 `policy_search` 录一条 `happy`，跑 2.5 通过后再录其余。
4. 全部录完后跑 `bash run.sh python -m pytest tests/test_cassette.py tests/test_golden_multiturn.py tests/test_core_live_protocol.py -q`，全绿。
5. 最后再跑一次完整 `bash run.sh python -m pytest tests -q -x --ignore=tests/test_golden_multiturn.py` 确认没有破坏既有测试（若既有测试在你动手前就有失败项，先记录下来，最终报告里区分"原本就失败"和"本任务导致"）。

---

## 3.5 完成记录（2026-09-08，事后追加）

执行方：codex（`gpt-6-astra` / medium），第 41 次尝试成功（前 40 次因模型容量受限被拒）。事后审阅与一处调整由助手完成。

**与任务书的偏差**：
- 录制/回放层最终位于 `tests/support/cassette.py` 而非 `impl/core/cassette.py`。原因：`impl/core/` 属产品代码域，`config_check` 对其中读取未注册环境变量（`VERIFIER_CASSETTE*`）和未走注册 writer 的 JSONL 写入报 3 处违规；`tests/` 属 `test_fixture` 域免检。它本质是测试设施，挪位置比给测试设施注册产品配置更合理。`VOLATILE_FIELDS` 随之移入 `scripts/trace_canonicalize.py`。
- golden 目录多一个 `execution.json`（记录录制时的 `live_base_url_override` 等参数，回放时复用）。

**结果**：
- 六条 golden 全部录齐并通过断网回放逐字节比对；`policy_search/happy` 0 次 LLM 调用（脚本式 mock）、`deerflow/happy` 实际停止原因为 `perceived_no_progress`（保留实况，未改写）。
- `test_cassette.py` 11 / `test_golden_multiturn.py` 6 / `test_core_live_protocol.py` 21，共 38 通过。
- 完整回归：唯一失败为 `test_config_contract.py::test_repository_public_config_contract_has_no_consumer_bypass`，其 5 处 issue 均为既有（`capability_store.py`、`llm_probe/`），与本阶段无关；本阶段文件贡献 0 处。

**阶段 1 通过门**：`bash run.sh python -m pytest tests/test_golden_multiturn.py -q` 六条全绿，即"零行为变化"成立。

## 4. 最终报告（写到 stdout 最后一条消息）

- 新增/修改文件清单。
- 每个 golden 目录：project、case_id、实际 `stop_reason`、`completion_status`、轮数、LLM 调用数、live 调用数。
- 跳过或降级的项目及原因。
- 测试结果：三个目标测试文件的通过数；完整测试集的结果与"原本就失败"清单。
- 实现中遇到的、需要人工决定的点（例如某项目的易变字段列表需要补充）。
