# verifier 完工门（verifier-ready gate）方案

> 一句话：harness（pi / Claude Code / Codex）里的实施 agent 改完 verifier、准备停下时，hook 自动触发这道门。程序起一个独立实例跑 4 条真实 case，用 **llmtracing 自带的 `llmtrace` 工具**把每一次模型请求与响应导出来，做账本、判少数硬性项；然后 **harness 按 case spawn 独立的只读审阅子代理**，对导出的全部调用做**一致性审阅**：整个 llmtrace 上下文及其跨调用流转能不能自圆其说。实施 agent 逐条回应；有争议的交人裁决；覆盖无遗漏、已确认不一致为零、硬性全过，hook 才放行。
>
> 流程：用户在 harness 里提要求 → harness 改 → harness 认为改完 → hook 触发门 → 程序采集 + 硬性检查 → 子代理按 case 并行审阅 + 聚合分片裁共同规则 → 程序汇总覆盖与裁决 → 实施 agent 回应（修 / 反驳）→ 反驳交人裁决（确认 / 撤销 / 豁免）→ 放行或继续修。
>
> 适用范围：llm_probe 项目（真实保险 Agno 业务）。项目专属，不做通用化。代码放 `hooks/verifier-ready/`，报告放 `report/verifier-ready/`。v1 只做 live；冻结样本重判（frozen）不在本版范围。
>
> 本文档交给另一位实施者执行。§11 是实施前必读的坑。§5 的一致性要求合并自 `report/verifier-ready-validation/20261007/context-consistency-requirements.md`，机制问题的复现证据在同目录。

## 0. 为什么要这道门，门判什么

每次优化 verifier 之后，三类问题都是事后人工翻 llmtrace 才发现的：模型收到的上下文不正常、模型产出不可用或不对、单条请求耗时暴涨。现有 406 个单测全部 mock 掉模型，验的是接线，验不了这三件事。

门的定位：**把"接线对了"和"真的能用"分开**。接线交给单测；能不能用交给这道门。

门的首要目标是**一致性**：仅凭 llmtrace 实际导出的记录，能否解释清楚每一次调用要求什么、依据什么、允许得出什么，以及它与前后调用为什么相容。不能靠模型猜符号、补规则、补材料、自行决定冲突优先级才能让任务成立。这是语义判断，程序判不了，由 harness spawn 的独立审阅子代理来判；程序只保证它看到的材料真实、完整、可定位，并把它的结论整理成可核对的覆盖与计数。

耗时和轴状态是**独立的硬性项**，各自给结论，不和一致性互相抵扣。业务准确性不判：一套错误规则也可能内部自洽，这道门不替代业务金标。verifier 运行时不新增任何 LLM 角色。

## 1. 门的层次

```
① 采集      起独立实例（自带端口 + llmtracing 中转），跑 4 条真实 case；
            拉 batch_status；用 llmtrace 导出调用清单、每次调用全文、HTML，落 raw/
② 账本      程序整理：每次模型调用一行（只用 llmtrace 给的字段）；每条轴输出的证据解引用；阅读顺序
③ 硬性检查  程序判 FAIL：全部轴 succeeded；单例评测墙钟；单请求耗时；整体墙钟；体积相对基线不回退（V5）
④ 一致性审阅 harness 按 case spawn 4 个独立只读子代理并行，每个覆盖本 case 全部调用，
            出覆盖记录、六类关系记录、共同规则登记、finding（已确认 / 已解释 / 未决 × blocking / high / diagnostic）；
            程序对四份共同规则做跨 case diff，有差异再 spawn 第 5 个聚合分片裁决
⑤ 程序汇总  校验 call_id 与覆盖、从结构化结果算计数、对照 chunk 清单与工具调用日志核对"全文读取"、
            共同规则跨分片 diff、合并结果
⑥ agent 回应 实施 agent 对每条 blocking / high 写 fixed / refuted；想豁免也只能写 refuted 交人裁
⑦ 人工裁决  有 refuted 就交人：confirmed（必须修）/ withdrawn（撤销）/ waived-by-human（豁免但披露）；留完整记录
⑧ hook 放行  指纹 = 当前代码 ∧ 硬性全过 ∧ 审阅有效 ∧ 覆盖无遗漏 ∧ 已确认不一致 = 0 ∧ 关键未决 = 0
            ∧ 全部 blocking / high 已回应 ∧ 无待裁决 → 放行；否则拦
```

①–⑤ 由 `bash run.sh gate` 一条命令完成（后台运行，写进度；④ 是 gate.py 以子进程方式 spawn 的 harness 子代理）；⑥ 由实施 agent 在 hook 提示下完成；⑦ 由人在终端执行 `gate adjudicate`；⑧ 由 hook 适配器执行。

## 2. 上下文就是 llmtracing 采到的东西

这是整个门的前提：**审阅者审的"上下文"，定义为 llmtracing 中转记录下来的、真正发到模型网关的请求正文；"模型输出"定义为同一条记录里的响应正文。** 包括实际请求中的 system / messages、任务和判准、业务材料、历史、前序结果、工具定义、输出结构约束、错误反馈。verifier 内部的 compiled snapshot、context_store、治理扫描结论、`impl.context audit`、源码里的 prompt 和预期配置，一律不进门，也不能用来证明"模型已经收到"。llmtracing 看不到的东西记为不可核验，审阅者不猜。

响应本身不是先前请求的上下文；只有在后续调用里实际交付了，才能说它进入了后续上下文。

第二个前提：**门只通过 llmtracing 自带的 `llmtrace` 命令读采集数据，不自己解析任何日志、pairs 或记录结构。** llmtracing 的身份字段正在往标准协议迁（envelope 里已有 `trace_id`，`--execution-id` 同时匹配 W3C trace_id）；门把 ID 当不透明字符串从 verifier 接口拿到、原样传给 `llmtrace`，字段含义只认 `llmtrace` 的输出契约。

### 2.1 链路

| 环节 | 机制 | 代码位置 |
|---|---|---|
| 实例 | 一个服务端口对应一个实例 ID、一个数据目录 `.runtime/instances/<id>/data/`、三个中转端口；再次启动同一端口复用同一实例 | `impl/core/instances.py`，`.runtime/instances.json` |
| 中转 | `tracing run server --port P` 为 primary / fallback1 / fallback2 各起一个 LiteLLM 中转，服务子进程的 `LLM_BASE_URL`、`LLM_FALLBACK_n_BASE_URL` 被覆盖指到中转；根目录 `.env` 不改 | `scripts/tracing.py:86-140` |
| 身份 | verifier 给每条提交一个 execution 身份，连同 run / case / role / stage 写进请求头；一次提交内部的重试、降级、失败都在同一 execution 下。**门从 `batch_start` 返回的 `requests[].execution_id` 拿这个值，不自己拼** | `impl/core/llm_tracing.py:47-55`，`impl/core/run_store.py:179-184` |
| 日志 | 中转写到 `.runtime/instances/<id>/tracing/logs/`，批次结束后服务自动 rotate 并按 execution 归档。门不读这些文件 | `impl/core/tracing_retention.py` |
| 工具 | `<llmtracing_root>/llm_gateway/.venv/bin/python <llmtracing_root>/llmtrace …`；`llmtracing_root` 读 `tracing/config.yaml` | 调用方式同 `scripts/tracing.py:143-145`（门里复制这几行，不 import） |

### 2.2 门用到的 `llmtrace` 命令

统一前缀 `llmtrace query calls --log <instance>/tracing/logs --include-rotated`；执行 ID 来自 `requests.json`，原样传。

| 用途 | 命令 | 产物 |
|---|---|---|
| 调用清单（账本、硬性检查、覆盖校验的唯一数据源） | `… --execution-id <id,…> --format json --settle 30` | `raw/calls.json`：`llmtrace.calls/v1` envelope。顶层 `status / counts / pending_call_ids / conflicts`，`calls[]` 每条有 `call_id, execution_id, trace_id, run_id, case_id, gateway, role, stage, model, state, status_code, latency_ms, first_frame_ms, ts, ended_at, usage{prompt_tokens, completion_tokens}, error, warnings` |
| 每次调用全文（审阅者读的东西） | `llmtrace query show <call_id> --full --log … --include-rotated` | `raw/calls/<call_id>.txt`：system、messages、thinking、assistant 原文，llmtrace 自己的可读排版 |
| 人看的 HTML | `… --execution-id <id,…> --html raw/html` | `raw/html/llm_trace.html` |

`stage` 是 verifier 自己打的阶段名（如 `llm_probe_expectations`、`llm_probe_judge`，ToolLoop 带 `:s<n>`）；`gateway ≠ verifier_primary` 即发生了降级；`state ∈ {succeeded, failed, pending}`。门校验 envelope 的 `schema == "llmtrace.calls/v1"` 且 `status == "complete"`，否则采集记 FAIL(reason=trace_export)，不猜。

### 2.3 门怎么落盘

```
report/verifier-ready/<ts>/raw/
  batch-status.json          完成后的 /api/batch_status 原样
  requests.json              batch_start 返回的 requests[]（含 execution_id）
  calls.json                 llmtrace --format json 原样
  calls/<call_id>.txt        llmtrace query show --full 原样，每次调用一个文件
  calls/<call_id>.chunks/    门把 txt 无损切成 ≤40 KB 的 chunk-NN.txt（头部：源文件、byte 区间、sha256）；审阅者只读这里
  calls/chunks-manifest.json 全部 chunk 的清单，覆盖校验的基准（§5.6 检查 6、§11-21）
  html/                      llmtrace --html 原样
  export-manifest.json       每条导出命令的 argv、exit_code、时刻
```

账本（§4.1）里每一行都指向 `raw/calls/<call_id>.txt`。审阅范围 = `calls.json` 里属于这 4 个 execution 的全部 call，一个不少。

## 3. 样本与执行

### 3.1 4 条真实 smoke case

来自 `impl/data/llm_probe/mock_cases.json`：

| case_id | 覆盖 |
|---|---|
| `llm-probe-insurance-real-smoke-policy-list-fuyunping` | 单客户保单列表 |
| `llm-probe-insurance-real-smoke-customer-profile-fuyunping` | 客户画像（曾出现 μ 非 JSON、birthday 口径问题） |
| `llm-probe-insurance-real-smoke-neg-unknown-policy` | 负例：不存在的保单 |
| `llm-probe-insurance-real-smoke-multi-policy-anjinning` | 多保单 |

### 3.2 执行顺序（`live.py`）

1. **解析实例**：`resolve_instance(profile.live.port)`（默认 8029），得到实例 ID 与数据目录。门自带端口，不借用开发中的 8021（中转与实例锁按端口独占）。
2. **种数据**：若 `<instance>/data/llm_probe/materials` 不存在，复制 `impl/data/llm_probe/{materials, capability_map.json, mock_cases.json}`（git 跟踪）过去。不种会被 `require_materials` 拒跑（§11-1）。
3. **起服务**：`bash run.sh tracing run server --port <port>` 作子进程；轮询 `GET /health`。
4. **提交**：`POST /api/batch_start {"project": "llm_probe", "cases": [4 条 mock_cases 原条目], "concurrency": profile.live.concurrency}` → `job_id`、`requests[]`（每条含 `execution_id`）。并发数固定写在 profile，耗时阈值和基线都对应这个并发（§11-3）。
5. **轮询**：`POST /api/batch_status {"project": "llm_probe", "job_id": …}` 到 `status == completed`；整体墙钟上限 `profile.live.wall_clock_s`（默认 5400 s）。
6. **导出**：取 `requests[].execution_id`，按 §2.2 三条命令依次导出 `calls.json`、每个 call 的 `show --full`、HTML（持 `impl.core.tracing_retention.log_lock` 共享锁，和服务的自动 cleanup 不打架）；随后把每个 `calls/<id>.txt` 无损切成 chunk 并写 `chunks-manifest.json`（§11-21）；写 manifest。
7. **停**：终止服务子进程；`bash run.sh tracing down --port <port>`（§11-8）。
8. **业务不可达**：任一 case `run.error` 指向 live 阶段（业务系统未响应、trace 为空）→ 该例记 `FAIL(reason=business_unreachable)`，不混入其他结论，不参与 U1 / L1，也不进审阅。

## 4. 账本与硬性检查（程序）

### 4.1 调用账本（每 case 一份，每次网关请求一行，全部取自 `raw/calls.json` 的字段，不读正文）

| 列 | 内容 |
|---|---|
| call | `raw/calls/<call_id>.txt` 路径；`stage`、`role`、`gateway`、`model`；按 `ts` 排序的序号 |
| 状态 | `state`、`status_code`、`error`、`warnings`；同一 stage 在本 case 里是第几次出现（>1 即整批重判或重试） |
| 耗时与规模 | `latency_ms`、`first_frame_ms`、`prompt_tokens`、`completion_tokens`；`prompt_tokens` 相对同 stage 上一次的增量 |

账本是索引，不是分析。请求里装了什么、输出是不是合法 JSON、前后调用是否相容，由审阅者读 `calls/<call_id>.txt` 判；程序不解析 messages 正文。

### 4.2 证据解引用

对 `batch_status.events[].run.eval_axes.results[]` 每条轴输出：`results[].evidence.{input,output}`、`problems[].{input_refs,output_refs,source_refs,expectation_ids}` 逐个解析到案卷 record 原文片段（`trace_analysis` 输出的 dossier）、E 原文、obligation 原文，附在输出旁；解析不到的单独列出。这是程序能判的事实，不是审阅意见。

### 4.3 阅读顺序（不是覆盖依据）

任务文件给每 case 一个建议顺序：每个轴的第一批、`state ≠ succeeded` 的调用及其后的重试、需求轴调用、主判调用、`gateway ≠ verifier_primary` 的调用排前面，其余按时间序。这只是顺序。**覆盖要求是本 case 全部调用都全文审查**（§5.5），"其他调用按需打开"不构成"整个 trace 一致"的依据。

### 4.4 硬性检查（程序判 FAIL）

**状态与耗时**

| 项 | 定义 | 阈值 |
|---|---|---|
| U1 | 启用的每个轴 `status == succeeded`，主判存在且无 error | 必须 |
| L1 | 每例评测墙钟 `stage_timings.eval_axes_ms + judge_ms`（`live_ms` 单独报告不计入） | ≤ 15 min |
| L2 | `calls.json` 里 `latency_ms` 的 p95 / max | p95 ≤ 180 s，max ≤ 400 s |
| W | 整体墙钟 | ≤ `live.wall_clock_s` |

**体积不回退（硬）**

| 项 | 定义 | 阈值 |
|---|---|---|
| V5 | 有基线时，每例 V1 / V3 / V4（定义见 §4.5）任一项相对基线 | ≤ 基线 × 1.1 |

V1–V4 降为**参考指标**（§4.5），不设硬阈值：合理阈值要等至少一轮正常流程（不是 10-06 这种异常批次）验证后由人定标。在那之前门对体量只做两件事：报告数值与趋势、用 V5 卡回涨。基线只在 PASS 后由人 promote（§8.2）。

按 10-06 批次实测，当前代码会在 U1、L1、L2 上 FAIL，V1–V4 显示超参考值，这是预期。硬性 FAIL 不免除审阅：轴 failed 的那次调用、体量最大的那次调用，审阅者更要看。

### 4.5 参考数（只报告，不 FAIL；给审阅者和基线用）

**体量参考（V1–V4）**：审阅时长、审阅 token、人工翻 trace 的成本，都正比于 verifier 每例的调用数 × 单次体量 × 重复度。四项全部从 `calls.json` 字段算，进 verdict 与基线：

| 项 | 定义 | 参考值 | 10-06 实测 |
|---|---|---|---|
| V1 | 每例网关请求数 | 14 | 18–26 |
| V2 | 每例同名非 ToolLoop stage 的额外出现次数（整批重判 / 重试） | 0 | 2–9 |
| V3 | 每例单次请求 `prompt_tokens` 最大值 | 80k | 81k–254k |
| V4 | 每例 `prompt_tokens` 合计 | 500k | 0.72M–1.41M |

参考值来源：V1 = 六个过程轴 + 需求轴 + 投影 + 主判 + 分析轴 3 步各调一次再留 2 次余量；V3 = `demand/context.md` 的 attribute 预算；V4 = 14 次 × 35k 取整。**参考值不是阈值**：超出不 FAIL，但审阅者对超 V3 参考值的调用要给体量建议（§5.4 末段），V5 拿它们卡回退。

每例：`state ≠ succeeded` 数；`gateway ≠ verifier_primary` 数；`completion_tokens` 合计；按 stage 分列的调用数与 `prompt_tokens`（看哪个轴在膨胀）。另记**审阅成本**：每个分片的墙钟、工具调用次数、模型请求次数、usage 合计（从 `spawn/<case_id>/meta.json` 与 `tool_calls.jsonl` 取），并排给出上次 PASS 基线。审阅成本是 verifier 体量的派生量，不单独 FAIL，但要让人看到它随 V1–V4 一起降。

不算"重复正文占比"这类要读正文才能算的数。重复是否成问题由审阅者判（§5.4 第 7 条）；哪些块可以不发，由审阅者在超 V3 的调用上给出建议（§5.4 末段）。

## 5. 一致性审阅（harness 子代理）

### 5.1 审阅者是谁

harness spawn 的**无头只读子进程 agent**（`claude -p` / `codex exec` / `pi -p`），不是 verifier 里的 LLM 客户端。新进程、干净上下文，看不到实施 agent 的对话。

**按 case 分片，4 个并行；共同规则由第 5 个聚合分片收口。** 一个审阅者只负责一个 case：拿本 case 的账本、全部调用全文、轴输出与解引用、业务 trace。不同 case 不共享业务事实身份，六类关系都在 case 内部，按 case 分片不丢关系覆盖；换来的是时长按单 case 算。但角色词、版本词、prompt 结构条款、引用格式这类**共同规则**在每个 case 里都出现，分片各看各的，漏得掉"同一条规则在四个 case 里长得不一样"。所以每个分片必须把它实际读到的共同规则逐条登记进 `common_rules`（§5.6），程序跨分片 diff，差异项交聚合分片裁决（§5.6 末）。实测（`report/verifier-ready-validation/20261007/technical-report.md`）：5 次调用、764 KB 原文，qwen3.8-flash 用了 19 分钟、67 次工具调用、累计 447 万 token（多为缓存读）。按当前 verifier 一个 case 18–26 次调用、单次最大 25 万 token 外推，是 1–1.5 小时、千万级 token。

这个时长不是门的目标，是被测对象的体量。门不靠缩审阅范围省时间；体量靠 V5 卡住回退（§4.4）、靠 V1–V4 的趋势与审阅者的体量建议往下压（§4.5、§5.4 末段），verifier 把调用数、单次体量、重复降下来，审阅时长自然掉到 20 分钟量级。审阅成本按分片记进 verdict，和 V1–V4 一起看趋势。

### 5.2 怎么起（`spawn_reviewer.py`）

思路取自 council 的 spawn-peer（随机 spawn_id、系统提示由角色卡拼接、工作区前后快照做范围审计、meta.json 落盘），**代码复制进本目录并按本门改写，不 import、不调用 `~/.claude/skills/` 下任何文件**。

- 每个分片生成独立 `spawn_id`（随机，只写进该分片任务文件）。
- 系统提示 = `roles/gate-reviewer.md` + `checklists/consistency.md` + `checklists/output.md` 拼接。角色卡第一段：你是审阅者，不是实施者；仓库 AGENTS.md 里"完工门"条款对你不适用；只读；最后在 stdout 输出一个 JSON（§5.6），不写文件。
- 审阅模型钉死在 profile 并记进 verdict（实测默认模型停供时进程仍 exit 0、无输出，§11-16）。命令模板（2026-10 核过的参数，变了只改这里）：
  ```yaml
  reviewer:
    spawn: pi                       # claude | codex | pi
    model: dashscope/qwen3.8-flash  # 记进 verdict.fingerprint.models.reviewer
    parallel: 4
    timeout_s: 7200
    commands:
      claude: ["claude", "-p", "--output-format", "json", "--no-session-persistence", "--model", "{model}",
               "--append-system-prompt", "{system_prompt}", "--add-dir", "{repo}",
               "--allowedTools", "Read,Grep,Glob,Bash(rg:*),Bash(python3:*),Bash(cat:*),Bash(ls:*)", "{task}"]
      codex:  ["codex", "exec", "-s", "read-only", "-C", "{repo}", "--skip-git-repo-check", "-m", "{model}",
               "-o", "{stdout_file}", "{task_with_system_prompt}"]
      pi:     ["pi", "-p", "--mode", "json", "--no-session", "--model", "{model}", "--tools", "read,bash,grep,find,ls",
               "--append-system-prompt", "{system_prompt_file}", "{task}"]
  ```
- `cwd = 仓库根`。**内容哈希快照只做全局两次，不做逐分片**：gate.py 在 spawn 第一个分片前取一次，4 个分片与聚合分片全部结束后再取一次；范围 = 指纹范围 + `hooks/verifier-ready/**` + `spec/**` + `AGENTS.md` + 本次报告目录（除 `spawn/`——门自己往里写缓冲与日志；`report/verifier-ready/current/progress.json` 在 `<ts>/` 之外、由门持续重写，本就不在范围内）。分片结果先留在 `spawn/<case_id>/result.json` 缓冲；第二次快照一致，gate.py 才把它落盘为 `review/<case_id>.json`、把 sha256 写回各 meta；不一致则本次审阅作废：结果不采用、全部 meta 记 `scope_valid = false`，重跑或转 `needs_human`。两次快照与比对结果写 `review/snapshot.json`。`git status --porcelain` 不够：已是 M 的文件再改，porcelain 不变（`mechanics-results.json`）。
- **结论从 stdout 回收**：取子进程输出里最后一个能解析为 §5.6 结构的 JSON，先写 `spawn/<case_id>/result.json` 缓冲（在快照排除区内），第二次全局快照一致后才由 gate.py 复制为 `review/<case_id>.json`，`sha256` 记进 `spawn/<case_id>/meta.json`；原始事件流 `stdout.txt` 和工具调用记录完整保留。这个哈希是**一致性检测，不是防篡改**：同目录可写，改结论再改 meta 就能对上；防篡改需要独立可信边界（CI、他人机器），v1 不做。实施 agent 不碰这些文件靠 AGENTS 条款，人抽查靠 `stdout.txt`。
- `spawn/<case_id>/meta.json`：`{spawn_id, case_id, model, command, started_at, ended_at, exit_code, has_result, scope_valid, review_sha256, stdout, stderr, tool_calls}`。`exit_code == 0` 但没有有效 JSON 记 `has_result = false`，视为失败。

### 5.3 它拿到什么（`review-task/<case_id>.md`，gate.py 生成）

```
spawn_id: …
case_id: …
报告目录: report/verifier-ready/<ts>/
硬性结论（本 case）: U1 … / L1 … / L2 …（含 FAIL 原因与出错的 call_id）
审阅范围: raw/calls.json 中 case_id == … 的全部 call_id（逐一列出，共 n 条）；全部要全文审查
建议阅读顺序: §4.3
账本: ledger/<case_id>.json
调用全文: raw/calls/<call_id>.chunks/（逐 chunk 读，全清单见 raw/calls/chunks-manifest.json；原始 txt 已切片，不要直接读，更不许 cat 整个目录）
轴输出 + 解引用: ledger/<case_id>.deref.json
业务 trace: raw/batch-status.json → events[i].run.trace
上一轮待闭环 finding: carry-over.json（若有；见 §6.3）
输出要求: §5.6 的 JSON，只输出到 stdout
```

### 5.4 审什么：六类关系

对每一次调用，仅凭实际记录回答六类问题；跨调用关系在"流转"一类里逐条登记上下游 call_id。不同调用可以承担不同任务、不同范围、不同判准，不要求字面相同；要解释的是**差异有没有任务、对象、阶段、条件、时点、版本或来源上的依据**。

| 类别 | 核验内容 |
|---|---|
| 1 概念与指代 | 同一名称、对象、ID、符号是否保持含义；必须使用的术语是否已有解释；不同 ID 之间的映射是否明确（如轴标识希腊字母与英文 ID 的对应是否在实际请求里讲清） |
| 2 任务与指令 | 全部适用要求能否同时满足；不同段落是否互相禁止；范围或优先级是否在实际上下文中讲清 |
| 3 任务与材料 | 要求的判断是否有材料、可用的取证路径和表达位置；只有材料目录或编号时不能当成已有正文；审阅者没找到不等于没交付，要按引用层级查到底（实测 F-08：工具定义在顶层 `captured_tool_definitions`，不在 `fields` 里） |
| 4 结构与语义 | 字段、枚举、空值、覆盖、分组、引用与条件规则是否一致；完成语义要求是否会违反结构限制（如要求空串但 `minLength: 1`） |
| 5 来源与事实 | 对象、单位、时点、版本、否定与不确定性是否保留；来源之间的差异是否如实呈现；业务材料本身矛盾不等于必须删掉矛盾 |
| 6 跨调用流转 | 上游材料、结果、规则被下游使用时是否变义、丢条件、换对象；推测是否变成事实；采集时的定义是否变成当次已收到的规则；重试是否改变任务或悄悄增加门槛；错误反馈是否可操作 |
| 7 重复与裁剪 | 重复材料本身不是不一致：独立调用重供必要证据可以成立。只有重复造成冲突、混淆、淹没必要信息，或裁剪掉了规则的适用条件、把两个版本拼成一个事实，才是问题；说不出目的的重复最多 diagnostic |

**共同规则登记（跨 case）**：每个分片把它实际读到的共同规则逐条写进输出的 `common_rules`：角色词及其解释、版本词、prompt 结构条款（输出结构、枚举、引用格式）、反复出现的任务规则。每条带 `key / call_id / where / quote`。程序按 `key` 跨四个分片聚类，规范化比对 `quote`；不一致项交聚合分片裁 `real`（规则本体在 case 间确实不同，登记为 finding，走同一回应 / 裁决流程）或 `cosmetic`（描述差异，规则本体一致，记 explained）。不要求分片互相读对方的 case。

**体量建议（对 `prompt_tokens` 超 80k 参考值的调用）**：审阅者在该调用的 relations 第 7 类里列出哪些块与本次任务无关、哪些块在同一 case 更早调用里已交付且本次没有独立取证需要、各约多大。这是 `remediation`，不是 finding；它告诉实施者往哪里砍体量，而不是审阅者替它决定。

**输出审查（每个轴）**保留：verdict / reason / 计数自洽；每条 problem 的 observed 能否在解引用原文里找到；漏判（对照业务 trace 与 E）；误判（正常样本被硬判、input_invalid 是否指向真实上游问题）；E 是否忠实原文、条件是否保留、有无虚构歧义组、承诺是否漏掉工具能力；与上次基线 verdict 变化有无依据。

### 5.5 证据与裁决

每个候选问题必须记录具体关系，然后**核对邻近说明、来源差异和反证**，再定裁决：

- **冲突类**（类别 1、2、4、6）：两端的 call_id、请求或响应、消息 / 块位置、原文摘引；为什么两端适用于同一范围；为什么不能同时成立。
- **缺口类**（类别 3、5）：要求端的位置与原文；实际交付的范围（查过哪些层级）；缺的是什么。
- 不能因为关键词不同直接判冲突；不能因为某次输出被拒绝就断言"任何合法输出都不可能"；不能因为没找到材料就断言"材料未交付"。实测两条 blocking 都栽在这里（F-01：说没有英文轴标识，请求里明明有 `dimension: tool_execution`；F-08：说没有合法引用材料，案卷交付了 3 条 model_calls 与 12 项工具 schema）。

裁决三分：

| verdict | 含义 |
|---|---|
| `confirmed` 已确认不一致 | 两端确实适用于同一范围，没有已交付的解释，存在具体冲突、变义或无法同时满足的要求 |
| `explained` 已解释差异 | 范围、版本、来源或任务变化能解释；记录解释与依据。不计入问题，但保留 |
| `open` 未决 | 材料不完整或含义无法确认；写出还缺什么。不能计为通过，也不能断言任务必然无解 |

严重度仍为 `blocking / high / diagnostic`，只对 `confirmed` 和 `open` 有意义：`blocking` = 凭所给上下文无法完成任务、输出结论与证据相反、E 虚构；`high` = 漏判疑似、误判疑似、无关大块、错误反馈不可操作、重复造成混淆；`diagnostic` = 趋势与建议。**关键未决** = `open ∧ severity ∈ {blocking, high}`。

覆盖按调用记录：`full`（全文读完；判定依据 = 该调用的 chunk 全部被读且返回无截断标志，§5.6 检查 6）/ `partial`（读了一部分，写明哪部分）/ `unverifiable`（llmtrace 没采到或导出缺失）。只打开文件或读摘要不算 `full`。

### 5.6 它输出什么（`review/<case_id>.json`）

```json
{"spawn_id": "…", "case_id": "…",
 "coverage": [{"call_id": "…", "depth": "full | partial | unverifiable", "note": "partial 时写读了哪部分"}],
 "relations": [{"call_id": "…", "category": 1, "result": "ok | finding | n/a", "finding_ids": [], "note": "n/a 必须给理由；类别 6 写上下游 call_id"}],
 "common_rules": [{"key": "规则名（角色词 / 版本词 / prompt 结构条款 / 引用格式）", "call_id": "…", "where": "…", "quote": "≤ 300 字"}],
 "findings": [
   {"id": "F-01", "verdict": "confirmed | explained | open", "severity": "blocking | high | diagnostic", "category": 2,
    "ends": [{"call_id": "…", "side": "request | response", "where": "消息序号 / 块名 / 行", "quote": "≤ 300 字"},
             {"call_id": "…", "side": "…", "where": "…", "quote": "…"}],
    "scope": "为什么两端适用于同一范围（缺口类写要求端与交付范围）",
    "exclusive": "为什么不能同时成立 / 缺口是什么",
    "counter_evidence": "核对了哪些邻近说明、来源差异、反证，结果如何",
    "impact": "…", "remediation": "…"}],
 "carry_over": [{"finding": "上轮 F-03", "ruling": "resolved | persists | unverifiable", "ends": [...], "note": "…"}],
 "output_checks": [{"axis": "…", "items": ["逐条作答"]}],
 "summary": "三五句话。不写计数，计数由程序算"}
```

**程序校验（确定性的，不替 LLM 判语义）**：

1. 能解析；`spawn_id` 与 meta 一致；`case_id` 正确。
2. 每个 `call_id`（coverage、relations、ends、common_rules）都在 `calls.json` 本 case 的 ID 集合里；不在的记 `invalid_ref`，该 finding 降为 `open` 并标记（实测抓到过带 `.txt` 后缀的 call_id）。
3. `coverage` 覆盖本 case 全部 call；缺的补 `unverifiable(reason=not_reported)`。
4. `relations` 对每个 call 六类都有记录；缺的记 `missing_relation`。
5. 冲突类 finding `ends` 至少两条且 `quote` 非空；缺口类至少一条；`verdict == confirmed` 的必须有 `counter_evidence`。
6. 对照 `raw/calls/chunks-manifest.json` 与 `spawn/<case_id>/tool_calls.jsonl` 核对：声称 `full` 的调用，其全部 chunk 文件都出现在读取记录里，且这些读取的返回没有 `truncated` / `firstLineExceedsLimit` 标志；缺 chunk 或有截断标志的降为 `partial(reason=chunk_missing | truncated)`。不做 offset/limit 行区间算术：pi 的 read 上限 50 KB / 2000 行，超长单行直接返回空（§11-21）。程序只能核对读没读、读全没读全，不能核对读懂没读懂。
7. 所有计数由程序从结构化字段生成：`calls_total / full / partial / unverifiable / relations_recorded / confirmed / explained / open_key / open_other`，按严重度分列。审阅者 `summary` 原样保留，不采信其中的数字（实测一次摘要把 5 / 7 写反）。
8. `common_rules` 非空（至少登记本分片实际看到的角色词与输出结构条款；一条没有记 `missing_common_rules`）。程序按 `key` 跨分片聚类比对，差异项写 `review/common-rules-diff.json`。

**聚合分片（第 5 个子代理）**：仅当 `common-rules-diff.json` 非空时 spawn，角色卡与分片同源（`roles/gate-reviewer.md` + 聚合段），输入是四份 `common_rules`、diff 清单和它需要核对的 chunk——输入只有摘引，不是全文，所以它很小。对每个 diff 项裁 `real`（登记为 finding，两端给 call_id 与原文，走同一回应 / 裁决流程）或 `cosmetic`（记 explained）。输出用同一 JSON 结构，程序对它跳过检查 3、4（它不做全量覆盖），其余照查；其 finding 与四个分片同口径合并计数。

### 5.7 审阅有效性与一致性通过（程序判）

**审阅有效**：4 个分片（及聚合分片，若触发了）都满足 `meta.has_result ∧ exit_code == 0 ∧ scope_valid ∧ sha256 匹配 ∧ spawn_id 匹配`，且 `review/snapshot.json` 里两次全局快照一致。任一分片无效 → 该 case 审阅无效，hook 不放行，`gate --review --case <id>` 只重跑该分片（重跑会重取两次快照）。

**一致性通过**：导出完整（§2.2 校验）∧ 4 个 case 全部 call `depth == full` ∧ 六类关系无 `missing_relation` ∧ 共同规则无 `missing_common_rules`、diff 全部经聚合分片裁决 ∧ `confirmed == 0` ∧ `open_key == 0`（计数均已扣除人工裁决的 `withdrawn / waived-by-human`，§6.2）。非关键未决（`open ∧ diagnostic`）保留披露，不拦。

覆盖不完整时，报告写"本次范围审阅不完整"，不得写"整个 llmtrace 上下文一致"。通过结论是本次范围内有证据的验收，不是不存在任何语义矛盾的证明。

## 6. 回应、裁决、闭环

### 6.1 实施 agent 回应（`response.json`）

对每条 `verdict ∈ {confirmed, open} ∧ severity ∈ {blocking, high}` 的 finding 写一条：

| status | 允许范围 | 要求 |
|---|---|---|
| `fixed` | 全部 | 写改了什么；**只有下一轮审阅在新 llmtrace 里裁 `resolved` 才算数**（§6.3） |
| `refuted` | 全部 | 不接受这条结论，两种情形都走这里：审阅判错了——必须给反证（`call_id` + 原文摘引 + 为什么断言不成立）；问题存在但认为不该修 / 不值得修——写理由。两者都进入人工裁决 |

**实施 agent 没有豁免通道**：`waived` 不作为回应类型存在，任何豁免只能由人在 `gate adjudicate` 里裁 `waived-by-human`（§6.2）。程序校验回应覆盖全部应答项；`refuted` 的反证 `call_id` 必须在 `calls.json` 里。

### 6.2 人工裁决（`gate adjudicate`）

任何 `refuted` 都让门进入 `needs_human`，hook 一直拦，直到人在终端执行：

```
bash run.sh gate adjudicate <ts> F-01 --rule confirmed|withdrawn|waived-by-human --note "…"
```

- `withdrawn`：审阅误判成立，该 finding 不再计入 `confirmed / open_key`；原 finding、反证、裁决全部保留在 `adjudication.json` 与 `summary.md`。
- `confirmed`：反证不成立，实施 agent 必须 `fixed`。
- `waived-by-human`：问题成立，但人决定本轮不修。该条不再计入阻断计数，连同理由写进 `summary.md` 顶部披露；下一轮若同类问题再被报出，人可引用上次裁决编号快速裁。

全部裁决累积在各轮 `adjudication.json`；gate 生成新一轮任务文件时把历史裁决清单附上，供审阅者参考。
- 命令要求 stdin 是 TTY（`isatty`），非交互环境直接拒绝；记录 `$USER`、时刻、note。这能挡住 harness 里 bash 工具的非交互调用，挡不住刻意伪造终端；后者由 AGENTS 条款禁止，transcript 可查（§11-24）。
- 人也可以 `gate adjudicate <ts> --override-release --note "…"` 强行放行，verdict 与 summary 顶部写明"人工 override"。

### 6.3 修复闭环必须落到新 llmtrace

"改了 prompt""删了符号""单测过了"都不能关闭 finding。流程：

1. 实施 agent 标 `fixed` → 重跑 `bash run.sh gate`（新运行、新 llmtrace，旧报告保留）。
2. gate.py 把上一轮全部 `fixed` 和未闭环的 `confirmed / open_key` 写进 `carry-over.json`，随任务文件交给对应 case 的审阅者。
3. 审阅者对每条裁 `resolved`（在新记录里定位对应两端，说明原不一致怎样消除；缺口类证明所需内容已实际交付）/ `persists`（仍在，作为新 finding 登记）/ `unverifiable`（新记录里没有对应调用，写明为什么）。
4. 审阅者同时检查受影响的后续调用：有没有靠删掉任务或材料掩盖，有没有把不一致转移到下一阶段（类别 6）。同一轮另外三个 case 就是"邻近正常场景"：它们的范围差异和必要材料应保持。
5. `persists` 自动进入新一轮 `confirmed`；`unverifiable`（severity ∈ {blocking, high}）视为未闭环，不放行——finding 不许靠"消失"过关：要么在新记录里被裁 `resolved`，要么有人工裁决记录。

"在冻结材料中制造冲突证明检查能抓住"不按修复逐项做，而是门级校准（§12 任务 2、任务 8）：角色卡、清单或审阅模型任一变化，必须重跑校准集。

## 7. hook

### 7.1 放行条件与流程

实施 agent 准备停下 → hook 调 `python3 hooks/verifier-ready/gate.py --status --json` → 读最近一份 `report/verifier-ready/<ts>/verdict.json`，满足全部条件才放行：

`fingerprint.code` = 当前代码指纹 ∧ 硬性全过 ∧ 审阅有效 ∧ 一致性通过（§5.7）∧ 全部应答项有回应 ∧ 无 `refuted` 待裁决 ∧ 上轮 carry-over 的 blocking / high 全部 `resolved` 或已有裁决记录（无未裁决的 `persists` / `unverifiable`）。

| status | 注入指令 |
|---|---|
| `no_report` / `stale` | 先后台运行 `bash run.sh gate`，进度见 `report/verifier-ready/current/progress.json`；按 AGENTS 规则每轮等待 ≥ 300 s |
| `running` | 门正在运行（进度 …），等待完成后再结束 |
| `review_invalid` | 分片 `<case_id>` 审阅未成功（meta …），重跑 `bash run.sh gate --review --case <case_id>` |
| `coverage_incomplete` | 列出 `partial / unverifiable / missing_relation`；重跑该分片 |
| `hard_fail` / `inconsistent` | 列出 failures（V5 附基线对比；体量超参考值的 call_id 与审阅者的体量建议一并附上）与 `confirmed / open_key` finding（两端原文）；修复后重跑门，或在 `response.json` 写 `refuted` + 反证 |
| `unanswered` | 列出未回应的 finding；在 `response.json` 逐条回应 |
| `needs_human` | 有 `refuted` 待人工裁决：`<finding 列表>`。等待人执行 `gate adjudicate`，不要自行处理 |

hook 不跑门、不跑 LLM，只读结论。只在本轮会话写过 `impl/` 或 `projects/llm_probe/` 下的文件时生效（与指纹范围一致），纯文档改动不拦。同一会话最多拦 `profile.hook.max_blocks` 次（默认 6），超过后放行并在消息里写明"门未通过，已达拦截上限"。

实施 agent 在整个流程里只做三件事：跑门、修、回应。它不写 `review/*`、不执行 `gate adjudicate`、不改阈值、清单、角色卡、审阅模型。

### 7.2 适配器

v1 只实现 pi（实施者当前运行时）：`adapters/pi_before_settle.ts`，监听 `agent_before_settle`，不满足放行条件时追加消息并返回 `continue: true`。pi 的项目级扩展从 `.pi/extensions/` 加载，所以在 `.pi/extensions/verifier-ready.ts` 放一个单行 re-export 指向适配器；首次加载需要项目信任与 `/reload`（§11-25）。

Claude Code（`Stop` hook，输出 `decision=block`）与 Droid（同）适配器同一契约，后续补；代码各自独立放在 `adapters/`，不 import `hooks/review` 或 `hooks/issue-solved`。

### 7.3 AGENTS.md 条款（拟加入）

> **verifier 完工门。** 声称 verifier 可用、优化完成、或请求人工验收之前，必须运行 `bash run.sh gate`，等待完成（含按 case 并行的审阅子代理），对每条 blocking / high finding 在 `response.json` 回应：修了写 `fixed` 并重跑门让新 llmtrace 证明；不接受结论写 `refuted`（审阅错了附 call_id 与原文反证；认为不该修写理由），然后等人裁决（confirmed / withdrawn / waived-by-human）。你没有豁免通道。结论中给出 verdict 路径、硬性结论、覆盖与一致性计数、回应摘要。报告指纹必须与当前代码一致。不得撰写或修改 `review/`、`spawn/`、`adjudication.json`，不得执行 `gate adjudicate`，不得修改 `profile.yaml`、`baseline/`、`roles/`、`checklists/` 来让门通过。

## 8. verdict 与基线

### 8.1 verdict.json

```json
{"gate": "PASS | FAIL | NEEDS_HUMAN", "generated_at": "…",
 "fingerprint": {"code": "<sha256>", "profile": "<sha256>", "role_card": "<sha256>",
                 "models": {"judge": ["calls.json 里出现过的 model"], "reviewer": "dashscope/qwen3.8-flash"}},
 "hard_checks": [{"id": "U1", "pass": true, "value": "…", "threshold": "…"},
                 {"id": "V5", "case": "policy-list", "pass": false, "value": "V3 254035", "threshold": "baseline 138000 × 1.1"}, …],
 "reference": [{"id": "V3", "case": "policy-list", "value": 254035, "reference": 80000, "baseline": 138000},
               {"id": "completion_tokens_total", "case": "…", "value": 72735, "baseline": 61000},
               {"id": "review_cost", "case": "…", "wall_s": 4120, "tool_calls": 231, "tokens": 15400000, "baseline": {…}}, …],
 "review": {"valid": true, "shards": {"<case_id>": {"path": "review/<case_id>.json", "meta": "spawn/<case_id>/meta.json", "valid": true}}},
 "consistency": {"pass": false, "calls_total": 93, "full": 91, "partial": 2, "unverifiable": 0, "missing_relation": 0,
                 "confirmed": {"blocking": 0, "high": 1, "diagnostic": 0},
                 "explained": 6, "open_key": 1, "open_other": 3, "invalid_ref": 1},
 "response": {"path": "response.json", "unanswered": 0, "refuted_pending": 1},
 "adjudication": {"path": "adjudication.json", "withdrawn": 0, "confirmed": 0, "waived_by_human": 1, "override": false},
 "carry_over": {"resolved": 2, "persists": 0, "unverifiable": 0},
 "live": {"job_id": "…", "port": 8029, "instance": "inst-…", "cases": […], "degraded_calls": 0},
 "failures": ["L1: customer-profile 评测 41 min（阈值 15）", "consistency: 2 calls partial", "F-04 confirmed high 未回应", "…"]}
```

`gate = PASS` 当且仅当 §7.1 全部条件成立；有 `refuted` 待裁决为 `NEEDS_HUMAN`；其余 `FAIL`。

`fingerprint.code` = `impl/**` 与 `projects/llm_probe/**` 全部文件（排除 `__pycache__`、`.pyc`）的 (相对路径, sha256) 排序后再哈希，**读工作区文件而不是 git 树**（实施 agent 的改动都未提交）。

### 8.2 基线

`hooks/verifier-ready/baseline/metrics.json`（上次 PASS 的 V1–V4 每例值、参考数、审阅成本）与 `baseline/review-summary.md`（上次四份 review 的 summary、`explained` 列表与 finding 列表），纳入 git。首次运行没有基线：V5 不生效，参考数只报当前值。PASS 后由人执行 `bash run.sh gate --promote-baseline report/verifier-ready/<ts>`；门自己永远不改基线。judge 或 reviewer 模型与基线不一致时标 `baseline_stale`，V5 照样生效（模型换了也不许体量回涨）。

## 9. 目录与命令

```
hooks/verifier-ready/
  README.md            用法
  profile.yaml         live.{port,cases,concurrency,wall_clock_s} / hard_checks / reviewer.{spawn,model,parallel,timeout_s,commands} / hook.max_blocks
  run.sh               run.sh gate 转发
  gate.py              --all(默认) --live --review [--case <id>] --status [--json] adjudicate <ts> <F-id> --rule … | --override-release
                       --promote-baseline <dir> --out <dir>
  live.py              种数据、起服务、batch_start、轮询、导出、停服务
  collect.py           组装并执行 llmtrace 命令（calls.json / show --full / html）、校验 envelope、无损切 chunk 与 chunks-manifest、manifest；不解析日志
  ledger.py            调用账本（只读 calls.json 字段）、证据解引用、阅读顺序
  metrics.py           硬性判定与参考数（纯函数）
  review.py            生成分片任务文件与 carry-over、并行调用 spawn_reviewer、§5.6 程序校验、共同规则 diff 与聚合分片、计数、合并
  spawn_reviewer.py    子代理启动器（spawn_id、系统提示拼接、全局两次内容哈希快照、stdout 回收缓冲、tool_calls 记录、meta.json）
  adjudicate.py        人工裁决命令（TTY 检查、adjudication.json）
  roles/gate-reviewer.md
  checklists/consistency.md  checklists/output.md
  adapters/pi_before_settle.ts
  baseline/
  tests/
    fixtures/20261006/           任务 1 的 llmtrace 导出与 batch-status
    calibration/                 审阅者校准集：12 个构造样本 + 冻结 gold（复制自 report/verifier-ready-validation/20261007/corpus/controlled 与 private-gold.json）
.pi/extensions/verifier-ready.ts     单行 re-export 适配器

report/verifier-ready/
  current/progress.json
  <ts>/ verdict.json metrics.json summary.md response.json adjudication.json carry-over.json
        review-task/<case_id>.md  review/<case_id>.json
        review/_aggregate.json  review/common-rules-diff.json  review/snapshot.json
        ledger/<case_id>.json ledger/<case_id>.deref.json
        spawn/<case_id>/ (meta.json, result.json, stdout.txt, stderr.txt, tool_calls.jsonl)
        raw/ (batch-status.json, requests.json, calls.json, calls/<call_id>.txt,
              calls/<call_id>.chunks/, calls/chunks-manifest.json, html/, export-manifest.json)
```

`run.sh` 新增 `gate) exec bash hooks/verifier-ready/run.sh "$@" ;;`。

依赖边界：本目录只 import 两类东西，verifier 运行时（`impl.*`，被测对象；具体用到 `impl.core.instances.{resolve_instance, instance_root}`、`impl.core.tracing_retention.log_lock`）和标准库 / 已有第三方包；**不 import `scripts/`、`hooks/review`、`hooks/issue-solved`，不引用 `~/.claude/skills/` 或任何 skill**。需要的机制一律复制进来。

## 10. 不做的事

- 不改评测器代码、协议文档、模型配置；门只读。
- 不替代单测；不通用化；v1 不做 frozen；不判业务准确性。
- 不自动调阈值、不自动 promote 基线、不自动 waive、不自动裁决 `refuted`。
- 审阅子代理只读、只输出 stdout；不修代码、不改写评测结论。
- 不在 verifier 运行时新增 LLM 角色或客户端；审阅完全在 harness 层。
- 不依赖 `context-governance`、`council` 或其他 skill；不采信 verifier 内部治理扫描的结论。上下文只以 llmtracing 导出的原始请求为准。
- 不自己解析 llmtracing 的日志、pairs、事件记录；不自己拼 execution_id；不读 messages 正文算指标。采集数据只经 `llmtrace` 命令进出。
- 不用单个加权总分；不用大量正常项抵消一个确认冲突；不把"没发现"直接算通过。
- 不宣称防篡改。

## 11. 坑（实施前必读，每条都核过代码或有复现产物）

**采集**

1. **新实例数据目录是空的。** `batch_start` 先过 `require_materials`（`impl/server/batch_jobs.py:54-56`，`impl/core/materials_store.py:330`），缺材料直接 422。`impl/core/instances.py` 没有任何自动种子逻辑。live.py 第 2 步的复制不能省；来源用 `impl/data/llm_probe/`（git 跟踪，与 8021 实例的副本一致），不要从别的实例拷。
2. **`batch_start` 的 cases 要给 mock_cases 原条目**，服务端用 `parse_mock_case` 解析（`batch_jobs.py:53`）；不传 `pool_indexes` 时会整体替换该实例的候选区（`run_store.py:170-172`），这正是我们要的。`batch_status` 的 `job_id` 不是当前批次时返回 404（`batch_jobs.py:75`），所以门必须用自己的端口，不能和别人共用实例。
3. **并发影响耗时。** `batch_concurrency_default: 4`（`impl/config.yaml:47`），4 条 case 同时打同一网关，p95 比单跑高。并发数钉死在 profile，阈值和基线只在同一并发下有意义。
4. **业务不可达要先分出来。** live 阶段失败时 `run.error` 有值、trace 为空；不分出来会被算成 U1 FAIL，把业务问题记到 verifier 头上。
5. **服务异常退出不会卡死下一次。** `current_batches` 的 `owner_pid` 不在了会在下次读取时自动标 failed（`run_store.py:122-126`），但上一轮没跑完的 case 结果就没了；gate 被杀后重跑即可，不必手工清库。

**llmtracing**

6. **只用 `llmtrace`，别碰日志。** llmtracing 的身份字段在往标准协议迁（envelope 已有 `trace_id`），日志行结构和 pairs 格式都可能变。门只调 `llmtrace query calls --format json`、`query show --full`、`--html` 三条命令，只认 `llmtrace.calls/v1` envelope 里的字段；`schema` 不是这个值就 FAIL(reason=trace_export)，让人来升级，不要在门里兼容。execution_id 从 `batch_start` 的 `requests[]` 拿、原样传，不要按 `job_id:index` 自己拼。
7. **批次结束后服务自动 cleanup。** `_run_batch_job` 的 `finally` 调 `scripts/tracing.py cleanup`（`batch_jobs.py:37-44`），只保留当前用例行的 execution、会 rotate 日志。门的 4 条就是当前行，所以不会被删；但查询必须 `--include-rotated`，并且导出要持 `log_lock` 共享锁，否则可能读到一半被 rotate。
8. **中转进程要显式停。** 服务子进程结束后 3 个 LiteLLM 中转还活着；门结束必须 `tracing down --port`。
9. **别用 `tracing report --project`。** 那是按实例当前用例行取范围（`tracing_retention.workspace_trace_selection`），门直接按 `requests[].execution_id` 列表查。
10. **迟到的 callback。** 响应结束后中转才写完整记录；导出加 `--settle 30`，并在 batch 完成后再等几秒。envelope 的 `status ≠ complete` 或 `pending_call_ids` 非空说明还没写完，重试导出而不是带着残缺数据往下走。
11. **单次调用全文很大。** 一次 `show --full` 可达几百 KB（dossier_view 块单块就上百 KB），一个 case 二十多次调用，单行最大实测 146,853 字节。所以门导出后先无损切 chunk（§2.3），审阅子代理逐 chunk 读；角色卡要提醒它按 chunk 读、不许一次 cat 整个目录，漏读的 chunk 会被程序判成 `partial`（§5.6 检查 6）。
12. **降级会换模型。** primary 600 s 超时（`impl/config.yaml:24`）后走 fallback 中转，`calls.json` 的 `gateway`、`model` 会变。账本标出来，`fingerprint.models.judge` 记出现过的全部 model，基线比较时模型不一致标 `baseline_stale`。
13. **零调用的 execution 是正常现象。** 10-06 fixture 里 `:4`（`agg-paid-prem-fuyunping`）not_evaluable、0 次网关调用。覆盖按 `calls.json` 实际有的 call 算，不按 case 数推。
14. **体量项是"参考 + 回退卡"，两个方向都别作弊。** V1–V4 只报告不判 FAIL，V5 卡相对基线 ×1.1。错误反应一：看到 V1–V4 超参考值就去"调阈值"——profile 里没有它们的阈值可调。错误反应二：为了让 V 数字好看把必要材料裁掉——一致性审阅会把它抓成缺口类 finding，比 V 超参考值严重得多。体量的正确降法是修整批重判（`process_common.py:516-517`、`runner.py:341-348` 事后门槛清空成功结果）和每批重发 dossier_view / expectation_sources 的 compiler。

**审阅子代理**

15. **CLI 参数以 2026-10 本机版本为准**：claude `-p --output-format json --model --append-system-prompt --add-dir --allowedTools --no-session-persistence`；codex `exec -s read-only -C --skip-git-repo-check -m -o`；pi `-p --mode json --no-session --model --tools read,bash,grep,find,ls --append-system-prompt <file>`。参数漂移只改 `profile.yaml`。pi 的 `bash` 不能按命令白名单限制，内容哈希快照是唯一护栏；codex 的 `read-only` 沙箱和 claude 的 `allowedTools` 是真限制。
16. **`exit 0` 不代表审阅成功。** 默认模型（anyrouter / claude-opus）HTTP 400 停供时，pi 进程照样 exit 0、无工具调用、无 JSON（`technical-report.md` 已复现）。有效性看 `has_result`，不看退出码。审阅模型在 profile 钉死并记进 verdict；本次校准用的是 pi + DashScope qwen3.8-flash。
17. **子代理会读到仓库的 AGENTS.md / CLAUDE.md。** 里面的"完工门"条款、编码规范对它不适用，角色卡第一段就要说明身份，否则它可能去跑门或改代码。
18. **stdout 里不止一个 JSON。** claude `--output-format json` 是一个带 `result` 字段的信封；pi `--mode json` 是事件流；codex `-o` 只写最后一条消息。`spawn_reviewer.py` 对三种各写一个很小的提取函数，取"最后一个能解析为 §5.6 结构的 JSON 对象"。
19. **审阅时长与 token。** 实测 5 次调用 19 分钟、447 万累计 token（多为缓存读）；一个 case 预计 1–1.5 小时、千万级 token，4 个并行。`reviewer.timeout_s` 默认 7200，超时杀进程记 `exit_code = -1`。Token Plan 实际账单未知，不能按 registry 的 cost=0 当免费。
20. **程序校验不是语义校验。** `call_id ∈ calls.json`、覆盖齐全、两端非空、tool_calls 核对读过没读过，这些都能挡住格式错和明显偷懒，挡不住读错了。审阅质量靠角色卡、六类关系清单和校准集回归；审阅误判靠 `refuted` + 人工裁决纠正。
21. **"全文审查"靠 chunk 集合核对，不靠 offset 算术。** pi 的 read 工具上限 50 KB / 2000 行（`truncate.js`），且单行超 50 KB 时首行直接返回空、`firstLineExceedsLimit: true`——历史语料里最大单行 146,853 字节，这条路在真实数据上必然失灵。所以门在导出后把每次调用全文无损切成 ≤40 KB 的 `calls/<call_id>.chunks/chunk-NN.txt`（头部带源文件、byte 区间、sha256），审阅者只读 chunk；程序对照 `chunks-manifest.json` 与 `tool_calls.jsonl` 核对每个 chunk 都被读且返回无截断标志。读过不等于读懂：文档和报告只说"全文读取已核对"，不说"逐字审查已证明"。

**裁决与完整性**

22. **git porcelain 不能做内容审计。** 已是 M 的文件再次修改，前后 porcelain 相同（`mechanics-results.json`）。scope 审计用内容哈希快照。
23. **同目录哈希只证一致性。** 仅改 review 会失配；同时改 meta 的 hash 就匹配。文档、README、verdict 都写"一致性检测"，不写"不可篡改"。
24. **`gate adjudicate` 的 TTY 检查挡的是非交互调用。** harness 的 bash 工具没有 TTY，直接被拒；用 `script` 等伪造终端属于刻意绕过，由 AGENTS 条款禁止，transcript 里能看见。程序不宣称能区分人和 agent。

**hook**

25. **pi 项目级扩展要项目信任。** `.pi/extensions/` 下的文件首次加载会弹信任确认，改完要 `/reload`；适配器本体在 `hooks/verifier-ready/adapters/`，`.pi/extensions/verifier-ready.ts` 只 re-export。
26. **hook 绝不能同步跑门。** 门一次 2 小时上下（采集 1 小时 + 审阅 1–1.5 小时并行），hook 只读 `--status`。实施 agent 后台起门后要按 AGENTS 规则 ≥ 300 s 一轮地等，而不是反复试图结束。
27. **死循环保险。** 门持续 FAIL 时 `agent_before_settle` 会一直 `continue: true`；按 `hook.max_blocks` 封顶。`needs_human` 状态下每次拦截消息相同，不消耗上限之外的东西，但实施 agent 应停下等人而不是反复触发。
28. **`.claude/settings.json` 里现存的 Stop hook 指向另一个分支的路径。** 装 Claude 适配器时是替换那条，不是追加。

**指纹**

29. **指纹哈希工作区文件**，不是 git 树；实施 agent 的改动全是未提交的。`impl/config.yaml` 在 `impl/**` 里已覆盖。
30. **门自己的文件不进指纹。** `hooks/verifier-ready/**` 改动不会让报告过期，这是故意的（否则改一下 README 就要重跑 2 小时）；但 `profile.yaml`、角色卡、清单、审阅模型的 sha 单独记在 `fingerprint.profile / role_card`，hook 只看 `fingerprint.code`，人看报告时能发现阈值或审阅配置被改。这几样一变必须重跑校准集（任务 2）。

## 12. 实施任务与验收

| # | 任务 | 验收 |
|---|---|---|
| 1 | `collect.py` + `ledger.py` + `metrics.py`。fixture：对 8021 实例（`inst-16fa340ac786414f`）里 10-06 批次 `b9712b378fba4f1cbb08e4ca22d94293` 的 6 个 execution（`:0,:1,:2,:3,:4,:6`）跑一遍 §2.2 三条命令，产物连同 `batch-status-at-export.json` 存进 `tests/fixtures/20261006/` | 复算出 **111 次网关请求（110 succeeded / 1 failed）、24 次同名非 ToolLoop 额外 wire 调用**（2026-10-07 用 `llmtrace --format json` 复核，与 `fixture-reconciliation.json` 一致；旧统计的 19 次"逻辑纠错"口径不同，不混用）；`:4` 零调用被正确处理；账本能标出 `llm_probe_expectations` 等 stage 的多次出现与 prompt_tokens 跳变；U1 / L1 / L2 判 FAIL；V1–V4 每例**报告**数值且与上表一致（如 `:0` V3 = 254035、`:3` V2 = 9），不判 FAIL；无基线时 V5 不生效，写入构造基线后 V5 对超限项判 FAIL；envelope `schema` 被改时 FAIL(reason=trace_export) |
| 2 | `spawn_reviewer.py` + `roles/gate-reviewer.md` + `checklists/{consistency,output}.md` + `review.py` + 校准集 `tests/calibration/`（复制 `report/verifier-ready-validation/20261007/corpus/controlled` 与 `private-gold.json`） | 校准集：5 类构造问题全部命中并给出两端原文，6 个正常 / 修复后对照无无依据的 high / blocking，重复样本至多 diagnostic；对任务 1 fixture 的两个 case 各 spawn 一个分片，`coverage` 全部 `full` 且 chunk 核对通过（含 >50KB 单行的调用被切成多个 chunk、manifest 完整），`relations` 六类无缺、`common_rules` 非空；漏读一个 chunk 时程序判 `partial(reason=chunk_missing)`；构造两个分片 `common_rules` 同 key 不同 quote，程序产出 diff 并触发聚合分片，聚合裁 `cosmetic` 不计 confirmed、裁 `real` 计入 finding；构造一份带 `.txt` 后缀 call_id 和写反计数的 review，程序标 `invalid_ref`、计数以程序为准；手改 `review/*.json` 后 sha 不符判无效；分片运行期间改了工作区文件时两次全局快照不一致、结果不落盘且 `scope_valid = false`；`exit 0` 无 JSON 判 `has_result = false`；三种 CLI 各跑通一次 stdout 提取 |
| 3 | `live.py`：种数据、独立端口、batch_start、导出、停服务 | 对当前代码跑一次，产出 verdict（预期 FAIL 于 U1 / L1 / L2），failures 与 10-06 现象一致；`tracing status --port 8029` 显示中转已停 |
| 4 | `gate.py` 子命令、verdict / fingerprint / baseline / status / progress；`adjudicate.py` | `--status` 能报 §7.1 全部状态；非 TTY 下 `adjudicate` 被拒；`withdrawn` 后 `confirmed` 计数减一且记录完整；`waived-by-human` 后该条不再阻断、连同理由进 `summary.md` 披露；`response.json` 里写 `waived` 被程序判为非法回应 |
| 5 | pi 适配器 + `.pi/extensions` re-export + 拦截上限 | 模拟各状态各拦一次、满足条件放行一次、超上限放行并提示、`needs_human` 时消息正确 |
| 6 | `run.sh gate`、README、AGENTS.md 条款 | 一条命令跑完；条款入库 |
| 7 | **修复闭环**：从任务 3 的首轮结果里取一条 `confirmed` 不一致，实施者修复、标 `fixed`、重跑门 | 新一轮审阅在新 llmtrace 里对该条裁 `resolved` 并给出新两端；受影响的后续调用无新 `confirmed`；另外三个 case 的 `explained` 项与上一轮一致；旧报告完整保留 |
| 8 | 首轮 PASS 后 promote 基线；门级劣化校准：在一次门运行前临时让 compiler 把 `expectation_sources` 重复装入并裁掉其中一条规则的适用条件（跑完立即还原，不入库） | 对应 case 的审阅者给出 `confirmed`，两端定位到重复块与丢失条件；hook 拦住；还原后重跑 PASS |
