# 讨论 2026-09-19：harness 从 CLI 改成 MCP，让任何 agent 宿主都能直接起探索

状态：方案草稿，待对齐。不动协议（`protocol.md` 第 4/5/7 节）、不动存储、不动 judge 与台账；只改接口形态，并补两处让 insurance 场景能走通的缺口。

## 0. 起因

9/8 的讨论把"用户长什么样、说什么、什么时候放弃"从评测系统剔出去交给外部 harness agent，评测系统只管开会话、转消息、记 trace、预算、导出、judge。这一层 9/13 落地（`cde26b13`），9/10 在 policy_search 上跑过一批（7 场，1 个真缺陷 + 2 个 judge 口径问题），之后没再用。

今天的疑问：探索页会不会是限制？应该能在 Codex / Claude Code / Cursor 里直接起，再关联 verifier 的 live 与 trace。

结论：**探索页从来不是运行时**，它只存方向、看台账。真正的限制是三处：

| # | 现状 | 后果 |
|---|---|---|
| L1 | 唯一入口是 `python -m impl.harness_cli`，十几个子命令、几十个参数，输出靠 `jq` 解析 | agent 要先读 SKILL.md 学命令；每句话拼一次 shell；换宿主要再教一遍 |
| L2 | 探索方向只能在 explore.html 上保存（CLI 没有 `exploration save`） | 在 Codex 里想"来一轮"必须先开浏览器——这是"局促感"的真实来源 |
| L3 | `llm_probe` 的 live 是 `SingleTurnLive`；Session 对它 `max_turns=1`。`session judge` 只走 `pipeline.judge`，不跑 `eval_axes` | insurance-agno-e2e 开不了多轮对抗会话；即便开了，过程六轴也吃不到 |

## 1. 目标

1. 在 Codex / Claude Code / Cursor 任一宿主里，一句"探索 insurance-agno-e2e，重点打多轮上下文"就能起一轮，全程不开浏览器。
2. 宿主 agent 拿到的是**工具**不是命令：工具名就是协议动词，参数就是协议字段，返回就是协议对象。
3. insurance 的对抗会话能走完整评测：fulfillment + 一致性 + trace_analysis + 过程六轴。
4. 探索页退化为纯看板；`harness_cli` 删除（MCP 是它的替代，不留两套）。

非目标：不做 agent 调度/一键起 agent（那才是把自己关进页面）；不做批量灌会话；不改 Session 协议语义。

## 2. 整体结构

```
┌───────────────────────────┐   stdio MCP   ┌──────────────────────────┐   HTTP   ┌────────────────────┐
│ 宿主 agent                 │◄────────────►│ impl/harness_mcp.py       │◄────────►│ verifier server     │
│ Codex / Claude Code /      │  tools        │ (fastmcp, ~150 行,        │ /api/... │ session_store       │
│ Cursor + harness skill     │               │  只做协议动词→HTTP 转发)   │          │ findings_ledger      │
└───────────────────────────┘               └──────────────────────────┘          │ exploration_store    │
                                                                                   │ pipeline.judge+axes  │
                                                                                   └─────────┬──────────┘
                                                                                             │ live / business_trace
                                                                                   ┌─────────▼──────────┐
                                                                                   │ 被测 live           │
                                                                                   │ (policy_search /    │
                                                                                   │  insurance-qa-agent)│
                                                                                   └────────────────────┘
        看板：impl/frontend/explore.html（只读）· live.html / summary.html（单场会话细看）
```

三条边界不变：宿主 agent 只经 MCP 碰评测系统；MCP 无状态，所有状态在服务端；评测系统不知道也不关心 agent 跑在哪。

## 3. MCP 工具面（= 协议动词）

一个 server，名字 `verifier-harness`。工具与 `protocol.md` 5.1 的动词一一对应，参数沿用现有 `/api/*` 请求体字段，返回原样透传服务端 JSON。

| 工具 | 对应 API | 参数要点 |
|---|---|---|
| `exploration_list(project)` | `/api/exploration/list` | |
| `exploration_get(project, run_id)` | `/api/exploration/get` | 返回 direction + report + sessions + ledger |
| `exploration_save(project, run_id, direction)` | `/api/exploration/save` | **新增到 agent 侧**（服务端已有）。direction = {coverage_targets, focus, strategy_hints, budget} |
| `exploration_report(project, run_id, report)` | `/api/exploration/report` | report = {sessions, findings, coverage, budget_usage, notes} |
| `session_open(project, run_id, scenario, mode="text", budget=None, seed_prefix=None, seed_mode=None, pool="")` | `/api/session/open` | 返回 session_id、budget、allowed_actions |
| `declare_intent(session_id, user_intent, source, user_context=None)` | `/api/session/intent` | source ∈ seeded / adopted_from_inference / drifted |
| `send_text(session_id, text, tokens=0)` | `/api/session/send` | 默认路径，返回 extracted_output / assistant / turn 状态 |
| `send_action(session_id, name, params)` | `/api/session/send` | 协议 B 动作 |
| `send_request(session_id, payload)` | `/api/session/send` | 仅 protocol-fuzz 会话；服务端已校验 mode |
| `session_close(session_id, stop_reason)` | `/api/session/close` | goal_satisfied / user_abandons / perceived_no_progress |
| `session_get(project, session_id)` / `session_list(project, run_id="")` | `/api/session/get|list` | |
| `judge(project, session_id)` | `/api/session/judge` | 同步，数分钟；宿主自己决定是否并行 |
| `ledger_add(...)` / `ledger_query(...)` | `/api/ledger/add|query` | 字段同现有 CLI |

约束不进 MCP，进 skill：MCP 只保证"能做"，"该不该做"（说人话、一场一个假设、签名怎么命名、什么时候停）仍是 harness skill 的职责。服务端已有的硬约束（`--request` 必须 fuzz 模式、session_id 只从 open 得到、turn_wait_timeout）不变。

实现：`impl/harness_mcp.py`，fastmcp（stdio），复用 `harness_cli._post` 的转发逻辑；`--server` 用环境变量 `VERIFIER_SERVER` 或默认读 `impl/config.yaml`。依赖：`fastmcp` 加进 requirements。

## 4. 完整使用流程

### 4.1 一次性接入（每个宿主一次）

```jsonc
// Cursor: ~/.cursor/mcp.json   Claude Code: claude mcp add …   Codex: ~/.codex/config.toml [mcp_servers.verifier-harness]
{ "verifier-harness": {
    "command": "/Users/xiaozijian/miniconda3/envs/agno/bin/python",
    "args": ["-m", "impl.harness_mcp"],
    "cwd": "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier",
    "env": { "VERIFIER_SERVER": "http://127.0.0.1:8022" } } }
```

harness skill 同时放到三处宿主的 skills 目录（Cursor `.claude/skills/harness` 已有；Codex `~/.codex/skills`、Claude Code `~/.claude/skills` 各放一份同文件，或软链）。

前置：verifier server 在跑；被测 live 在跑（insurance 用 `scripts/insurance_backend.sh`）。

### 4.2 一轮探索（宿主里的对话）

```
用户：探索 llm_probe 的 insurance-agno-e2e，run_id 用 explore-insurance-01，
     重点打多轮上下文（指代、省略、缓存复用、澄清后补槽），身份用 EMP000006 / 皮奕辰 / P260000000000079，6 场。

agent（harness skill 生效）：
  1. exploration_list / exploration_get(run_id)      → 不存在 → exploration_save(direction=用户口述整理成 JSON)
     读 impl/projects/llm_probe/ 材料 + 已有台账（只读，用宿主自带的文件工具）
  2. 计划 6 场：persona×2 / drift×2 / boundary×1 / adaptive-replay×1，每场一个假设
  3. 每场：session_open → declare_intent → send_text ×N（看上一轮回复再想下一句）→ session_close
     close 后服务端自动导出 impl/data/llm_probe/sessions/<sid>.json，seed 进用例池 harness-explore-insurance-01
  4. judge(sid) 可以在开下一场时并行发
  5. 每场 harness_verdict 自评 → ledger_query 看已有签名 → ledger_add
  6. 连续 3 场无新签名 / 预算用完 → exploration_report
用户：在探索页选 explore-insurance-01 看批次；点单场进 live.html 看多轮 trace 与六轴
```

宿主之间没有差别：Codex 里说同一句话走同一条路。

### 4.3 复现 / 回归

- 单场复现：`session_get` 拿导出的 transcript seed → `session_open(seed_prefix=..., seed_mode="replay")` 重放前 N 轮，从分叉点接着打（adaptive-replay 策略卡）。
- 回归：用例池 `harness-<run_id>` 已在 case pool 里，走现有批量评测入口即可，不需要 harness 在场。

## 5. 展示

不新做页面。

| 层 | 在哪看 | 内容 |
|---|---|---|
| 批次 | explore.html（改成只读：去掉"保存方向"表单，保留 run 列表、方向、报告、台账三类筛选、会话表） | 方向、覆盖、预算用量、findings by_category、每场 harness/judge 结论 |
| 单场 | live.html / summary.html（现有） | 多轮 transcript、RunTrace、business_trace、judge、eval_axes（六轴 + trace_analysis findings） |
| 过程 | 宿主自己的对话流 | agent 每场说了什么、为什么这么说、自评理由——这部分本来就不该进评测系统 |

如果需要"agent 正在打第几场"这种实时进度：`session_list(run_id)` 已经能给出 open/closed 状态，探索页轮询它即可；不做推送。

## 6. 控制

| 想控什么 | 手段 | 状态 |
|---|---|---|
| 预算 | direction.budget（会话数 / tokens / 墙钟）+ session_open 的 budget（max_turns / turn_wait_timeout_ms / session_timeout_ms / token_limit） | 已有 |
| 停一场 | agent 调 `session_close`；或 300 s 不发下一句服务端以 `driver_timeout` 关掉 | 已有 |
| 停整轮 | 宿主里直接停 agent；已开会话由 driver_timeout 收尾，不会悬挂 | 已有 |
| 只读探索 | mode=text 默认；改请求体必须 protocol-fuzz 开场，且发现固定归 protocol_fuzz | 已有 |
| 并行 | 多个宿主各领不同 run_id；同 run_id 多 agent 也行，台账按签名去重 | 已有 |
| 不许碰评测系统 | MCP 面上没有写文件、改配置的工具；skill 第 0 节重申 | 设计即约束 |

## 7. 需要改的地方

| # | 改动 | 量 | 说明 |
|---|---|---|---|
| C1 | 新增 `impl/harness_mcp.py`（fastmcp） | ~150 行 | 3 节工具面；`_post` 从 harness_cli 搬过来 |
| C2 | 删除 `impl/harness_cli.py`；SKILL.md 改写：去掉命令拼法，保留约束、策略卡、台账规范，示例改为工具调用 | 净减 | 不留两套入口 |
| C3 | explore.html 去掉方向表单，改只读 | 小 | 方向由 agent `exploration_save` |
| C4 | `llm_probe` live 支持多轮 Session：`LlmProbeLive` 实现 `MultiTurnInteractiveLive`，把 Session 的 session_id 与轮次消息映射进请求体 `body.session_id` / `body.messages`；`mock.py` 提供 `safety_max_turns` 与 `SessionTranslator`（text → 请求体） | 中 | L3 的前半。insurance 后端本身多轮靠 `session_id` 续，映射是直的 |
| C5 | `service.session_judge` 改走 `_run_payload` 同款路径：judge 后跑 `eval_axes_report`，把 `eval_axes` 一起写回导出 | 小 | L3 的后半。business_trace 已由 `project_fields` 每轮采集，不用另加 |
| C6 | requirements 加 `fastmcp`；宿主 MCP 配置各加一条 | 配置 | |

不改：Session 协议、session_store、findings_ledger、exploration_store、judge、六轴、台账分类规则、导出格式。

## 8. 风险与取舍

- **fastmcp 是新依赖**。选它是因为三个宿主都只认 MCP，且它是 MCP 官方 Python SDK 的高层封装；不用自己写 stdio 协议。
- **C4 是唯一有业务判断的改动**：insurance 多轮到底是"同一个 session_id 连续 POST"（现在 14+8 个手写 case 就是这么跑的）还是别的形态，要按 `docs/接口文档` 确认一次。做错会让多轮对抗会话的 history 注入与真实用户不一致。
- **judge 同步阻塞**：一场六轴 20 分钟级（今天实测 axes 1300 s）。MCP 工具超时按 30 分钟设；宿主并行发 judge 不等它。若嫌久，先只跑 fulfillment 再按需补六轴——这是控制项，不是架构问题。
- **删 CLI 的代价**：脚本化场景（比如 tests 里如果有用 CLI 的）要改成直接打 HTTP。目前 tests 没有依赖 harness_cli。

## 9. 待对齐的问题

1. 工具粒度：`send_text / send_action / send_request` 拆三个（agent 不会用错）还是一个 `send(message)`（贴协议）？我倾向拆三个。
2. C4 的多轮映射形态，需要你确认 insurance 后端的会话续接方式。
3. 首轮探索目标：直接用今天 live-report 的 A1–A5 当 focus（投影丢字段、JSON 泄漏、多余调用超时、禁用措辞、跨工号），还是重新指方向？
4. 探索页是否连"保存方向"都不留（纯看板），还是留一个手动兜底？我倾向不留。
