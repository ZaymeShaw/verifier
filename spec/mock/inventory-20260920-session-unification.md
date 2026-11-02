# 盘点 2026-09-20：多轮 / mock / harness 现状与统一方案

状态：盘点 + 方案草稿，待对齐。承接 `discussion-20260919-harness-mcp.md`（MCP 接口形态不变），把它的 C4 从"llm_probe 实现多轮 mixin"改为"删掉单轮/多轮类型区分，Session 成为唯一执行路径"。

## 1. 现状：一件事有四条路

评测系统里"把一条 case 打到 live 并记成 trace"现在有四条执行路径，入口选择靠类型和开关：

| # | 路径 | 谁在用 | 谁扮演用户 | 选路条件 |
|---|---|---|---|---|
| P1 | `_LiveProtocol._execute_single_turn` | client_search、llm_probe、marketting-planning-intent、QA | 无（一发一收） | live 没混入 `MultiTurnInteractiveLive` |
| P2 | `_execute_multi_turn` 旧循环 | policy_search、marketting-planning、deerflow 批量跑 | 评测进程内 `MultiTurnInteractiveMock` 四回调 → `MockAgent` LLM | 混入 `MultiTurnInteractiveLive` 且 `interaction.driver` 缺省 `legacy`（三个项目都没设 `session`） |
| P3 | `_execute_multi_turn_via_session` = `Session` + `LegacyMixinDriver` / `ReplayDriver` | 只有 harness 导出的 transcript seed 回放走到（`case.metadata.seed.level == transcript`） | 录音（ReplayDriver）| 同上且 seed 为 transcript 级；`driver: session` 没人开 |
| P4 | `session_store.STORE` = `Session` + 外部 agent | harness（policy_search 7 场，2026-09-10 后没再用） | 外部 agent | HTTP `/api/session/*` |

代码位置：`impl/core/live_protocol.py` 83–427，`impl/core/session.py`，`impl/core/session_store.py` 85–159。

四条路最终都经 `TraceContext.record_turn / finish_execution` → `trace_from_context`（`impl/core/trace.py` 404–532）组装同一形状的 `RunTrace`：`turn_records[]`、`conversation_transcript`、`session_id`、`stop_reason`、`completion_status`、`intent_history`、`diverged_at_turn`。**trace 层已经是"一份会话一份 trace"，不需要动。** judge（`pipeline.judge`）也已经拿整份 trace 判一次，不是逐轮判。

### 1.1 同一件事声明了三次

"这个项目是单轮还是多轮"在三处各说一遍，且必须一致：
- `project.yaml` `runtime.interaction.mode: single_turn | multi_turn`（`schema/project.py` 61–64）
- live 类混入 `SingleTurnLive` / `MultiTurnInteractiveLive`（`live_protocol.py` 813–869）
- mock 类混入 `SingleTurnMock` / `MultiTurnInteractiveMock`（`mock_protocol.py` 365–460）

`RunTrace.interaction_mode` 由 `isinstance(live, MultiTurnInteractiveLive)` 推出，不看实际轮数（`trace.py` 515）。`session_store.open` 同样按 isinstance 给 `max_turns`：单轮 live 一律 1（`session_store.py` 113–116）。这就是 llm_probe 开不了多轮对抗会话的直接原因。

### 1.2 llm_probe 的多轮是扁平化的（B 套）

`impl/data/llm_probe/mock_cases.json` 52 条里 8 条 `ctx-*-t1/t2` 是 4 组多轮对：同一 `body.session_id`，t2 依赖 Agno 服务端记的历史。`mock.md` 第 9/11 行要求"t1 跑完再跑 t2"，但代码里没有任何顺序约束，批量跑并行就错；t2 的 trace 与 judge 看不到 t1。协议 4.10 明文"不允许把多轮会话扁平化为单轮 case"，这 8 条正是反例。另外 fixture 里 `session_id` 写死，重跑会往同一 Agno 会话追加 run（`mock.md` 第 11 行自己也承认）。

### 1.3 协议第 9 节阶段 5 一直没做

阶段 0–4 都 ✅，阶段 5（删 `LegacyMixinDriver`、四回调、`_has_visible_goal_evidence`、`MockAgent` 扮演用户的 LLM 路径、`interaction_driver` 开关）的前置条件是"全部项目在新路径稳定运行"，但三个多轮项目没有一个把 `driver` 切到 `session`，于是新路径只被 harness 和回放走过，旧路径永远删不掉。

同时协议 1.2 非目标写着"单轮路径 `_execute_single_turn` 不做任何改动"——这条现在恰好是阻塞项：只要单轮是另一条路，llm_probe 这种项目就进不了 Session。

### 1.4 存量数据对删旧循环的影响：零

| 项目 | 用例池 | fixture | 说明 |
|---|---|---|---|
| policy_search | `harness-explore-20260910-01`(6)、`harness-gate3`(1) | 4 条 | 池里全是 transcript seed，本来就走 ReplayDriver，不经旧循环 |
| marketting-planning | 无 | 7 条 | 旧循环只在临时批量时生成后续轮 |
| deerflow | 无 | 6 条 | 同上 |

没有任何持久化数据依赖 P2。删掉 P2 后这三个项目 request 级 case 打 1 轮，多轮内容一律来自 harness 录制的 transcript seed——这正是协议第 0 节写的"评测系统不再扮演用户"。

### 1.5 harness 侧缺口（沿用 9/19 结论）

- `session_judge`（`service.py` 446）只跑 `pipeline.judge`，不跑 `eval_axes_report`；批量路径 `_run_payload`（`pipeline.py` 425–440）两者都跑。harness 会话在 llm_probe 上吃不到六轴。
- `harness_cli` 没有 `exploration save`；`explore.html` 有"保存方向"表单（第 37/85 行）。
- 探索数据：`impl/data/policy_search/sessions/` 7 场、`explorations.json` 1 个批次，都是 9/10；llm_probe 一场没有。

### 1.6 mock 子系统的三块东西

| 块 | 现在是什么 | 协议给它的定位 |
|---|---|---|
| 离线 case 池 | `MockCase{id, project_id, scenario, live_request, output, reference, intent?, seed?}`，`case_pools.json` + 各项目 `mock_cases.json`；生成靠 `ProjectMock.build_user_intent`（LLM）→ `build_initial_request` | 保留。`seed.level ∈ request | transcript` 已有字段，只是 llm_probe 没用 |
| 进程内扮演用户 | `MultiTurnInteractiveMock` 四回调 + `MockAgent.infer_user_intent / decide_next_action / next_turn`（LLM） | 阶段 5 删除对象 |
| 确定性翻译 | `SessionTranslator`（`request_from_user_message` / `user_message_from_request` / `supports_history_injection`），policy_search(True)、marketting-planning(False)、deerflow(False) 已实现 | 多轮项目**唯一**扩展点（6.1）。llm_probe / client_search / mpi / QA 没实现 |

## 2. 方案：Session 成为唯一执行单位

一句话：**评测单位 = 一次会话 = 一份 RunTrace = N ≥ 1 次接口调用。单轮是 N=1 的会话，不是另一种类型。**

### 2.1 删掉的

- `SingleTurnLive` / `MultiTurnInteractiveLive` / `SingleTurnMock` / `MultiTurnInteractiveMock` 四个 mixin；项目 live 只继承 `RealServiceLive` 或 `ProvidedOutputLive`，mock 只继承 `ProjectMock`。
- `project.yaml` 的 `runtime.interaction.mode` 与 `interaction.driver`；`ProjectSpec.interaction_mode / interaction_driver`；`project_config.py` 对它们的校验。
- `_execute_single_turn`、`_execute_multi_turn`、`_execute_multi_turn_via_session` 三个分支 → `execute_live` 只剩"建 Session，选 Driver，跑"。
- `LegacyMixinDriver`、四回调、`_has_visible_goal_evidence`、`MockAgent` 的 `infer_user_intent / decide_next_action / next_turn / _preserve_chat_user_query / _contains_internal_user_language`、`LEGACY_STOP_REASONS`（阶段 5 全部内容）。
- `safety_max_turns()` → 并入预算（见 2.3）。
- llm_probe 的 8 条 `ctx-*-t1/t2` 单轮 case。

### 2.2 留下的（不动）

`Session` / `SessionBudget` / `ReplayDriver` / `TraceContext` / `trace_from_context` / `RunTrace` 形状 / judge / 六轴 / `session_store` 的 open-send-intent-close-export / 台账 / 探索 store / 导出格式 / 前端多轮视图。

### 2.3 `execute_live` 之后长这样

```
execute_live(initial_request, ctx, intent):
    session = Session(self, ctx, session_id=..., budget=SessionBudget(max_turns=spec.session_max_turns), translator=mock if SessionTranslator else None)
    driver = ReplayDriver(ctx.seed) if ctx.seed else OneShotDriver()
    driver.run(session, initial_request, intent)
```

- `OneShotDriver`：`send_request(initial_request)` 一次，`close("single_turn_completed")`。provided 路径（QA）也走它：`Session.send_request` 内部按 `_has_provided_output()` 决定调 `deliver_turn` 还是 `_run_provided`——这是把 P1 的 provided 分支搬进 Session，不是新逻辑。
- `ReplayDriver`：现有实现不动。
- `max_turns`：`project.yaml` 新增 `runtime.session.max_turns`（缺省 8），`session_store.open` 的 `budget.max_turns` 可覆盖。policy_search 现在 3、另两个 12，迁过去即可。
- `RunTrace.interaction_mode`：由 `turn_count > 1` 推出，不再看类。
- `session_store.open`：去掉 isinstance 判断，任何项目都能开多轮会话；能开几轮只看预算；能不能说人话只看有没有 `SessionTranslator`（没有就只能 `protocol-fuzz` 发请求体，现有行为）。

### 2.4 llm_probe 接入（原 C4）

- `LlmProbeMock` 混入 `SessionTranslator`：`request_from_user_message` = 取 capability 的信封模板，`body.session_id = state.session_id`，`body.messages = [{"role":"user","content": text}]`；`user_message_from_request` 反向取 `messages[-1].content`。`supports_history_injection = False`（历史由 Agno 服务端记）。约十几行。
- 4 组 ctx 对改写成 4 条 transcript 级 seed case（`seed.level = transcript`，`turns` 各 2 轮，`message.type = text`），进 `mock_cases.json`。回放时 `session_id` 由 Session 分配，每次重跑都是干净会话，顺带修掉 `mock.md` 第 11 行的"重跑追加 run"问题。
- `service.session_judge` 补跑 `eval_axes_report`，结果写回导出（原 C5）。

### 2.5 判整体还是判每轮

judge 现状：整份 trace 一次判（不改）。协议 §10 "judge 结论对齐到轮"仍开放，本方案不碰；`diverged_at_turn` + harness 标注的失败轮次继续做过渡。`context_memory` 轴以后能在同一份 trace 里直接看到 t1，不用猜服务端记了什么。

### 2.6 实施顺序（每步都能独立跑通）

| 步 | 内容 | 验证 |
|---|---|---|
| S1 | 2.1 + 2.3：删 mixin/开关/三分支/legacy，`execute_live` 只走 Session，加 `OneShotDriver`，`session_store` 去 isinstance | 全部 tests 绿；`test_golden_multiturn.py` 里 legacy 相关 golden 删除，ReplayDriver golden 保留；4 个单轮项目 + QA provided 的 trace 与改前逐字段一致（新增 golden） |
| S2 | 2.4：llm_probe translator + 4 条 transcript seed + `session_judge` 六轴 | `scripts/check_adapter_compliance.py` 对 llm_probe 过 6.2 三道约束；用 `harness_cli` 对 insurance 开一场 2 轮会话，导出含六轴；批量重放 4 条 seed |
| S3 | 9/19 文档 C1–C3、C6：`harness_mcp.py`、删 `harness_cli.py`、`explore.html` 只读、skill 改写 | 在 Cursor 里一句话起一轮 insurance 探索 |

### 2.7 需要对齐的决定

1. **现在做阶段 5**（删进程内 LLM 扮演用户）。存量数据零依赖（1.4），协议本来就这么定；代价是 policy_search / marketting-planning / deerflow 的 request 级 case 从此只打 1 轮，要多轮就走 harness 录制。
2. `max_turns` 放 `project.yaml runtime.session.max_turns`，缺省 8。
3. llm_probe 4 组 ctx 对 → 4 条 2 轮 transcript seed，旧 8 条删。
4. 顺序 S1 → S2 → S3。
