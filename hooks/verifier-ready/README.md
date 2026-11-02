# 独立 verifier-ready 验证命令

这版包含独立命令及 pi hook 适配器，不接业务主流程、不注册自动 hook、不改根目录 run.sh、AGENTS、.pi 扩展或全局模型配置。

## 先看帮助

```bash
bash hooks/verifier-ready/run.sh --help
```

没有参数只显示帮助，不启动服务、不调用模型。

## 独立验证 hook

适配器在 adapters/pi_before_settle.ts，尚未放入 `.pi/extensions`。可在未注册到正常会话的情况下验证：

```bash
bash run.sh python -m pytest -q hooks/verifier-ready/tests/test_hook_status.py \
  hooks/verifier-ready/tests/test_pi_adapter.py

# 查看 hook 所读的状态；这条命令只读，不启动业务或模型。
bash hooks/verifier-ready/run.sh --hook-status

# 完整 pi CLI 会话：临时仓库 + 内置 write + 原样 hook/门 + 本机模拟模型服务。
bash run.sh python hooks/verifier-ready/tests/pi_cli_harness.py \
  --out report/verifier-ready-validation/my-hook-cli-check
```

验证包含实际安装的 pi TypeScript loader、事件运行器和消息投影：在最终 assistant 消息后注入 custom_message，让 pi 确认具有可继续的上下文。各失败状态、正常 PASS、人工例外放行、未知/损坏状态、拦截上限和会话恢复均用离线输入覆盖，不发送 provider 请求。Python 桥接测试实际重算 verdict，检查原文/代码变化后的 stale，以及全过程不写报告。

完整 CLI harness 向 127.0.0.1 模拟端点发送合成请求，用真实 write 工具写临时仓库，以真实 Python 门状态驱动 hook。12 个场景包括 6 次继续及上限通知、进程退出后磁盘恢复不重置次数、纯文档不激活、相同内容的 `@impl` 写入仍激活、正常/人工例外放行及各类失败。每个场景保存 stdout、磁盘会话和模拟端点收到的请求；不访问外部模型，不注册项目扩展。PASS 等报告是明确标注的合成测试输入，不能当作真实审阅结果。

hook 只调用 `--hook-status`，不调用采集、审阅或人工裁决。成功的 write/edit 按 pi 的路径归一化及真实路径标记本会话改过代码，支持 `@`、`~/`、file URL 和目录别名；bash/custom tool 的变化通过前后代码内容指纹识别。仅有文档或排除文件改动时不激活。内容指纹反映观测到的变化，不能归属并发外部写入，也不能发现单次 bash 内写入后完全还原的操作。状态保存错误会显示失败并受拦截上限约束；磁盘无法保存记录时，不保证重启后的计数完整。

默认同一会话最多强制继续 6 次（profile.hook.max_blocks）。计数保存在 pi 会话 custom entry，reload/resume 不重置；新会话重置。达到上限会显示“门未通过，已达拦截上限”，不再由本 hook 强制继续；不会覆盖其他扩展已提出的 continuation。人工待裁决状态同样受上限约束，取消或错误结束的运行不会被 hook 重新启动。

## 单独验证真实流程

```bash
# 只运行专用 8029 实例并采集，先检查材料，不调用审阅模型。
bash hooks/verifier-ready/run.sh --live --out report/verifier-ready/my-live-run

# 对这一份采集结果启动 pi + DashScope Qwen 审阅。
bash hooks/verifier-ready/run.sh --review --out report/verifier-ready/my-live-run

# 或一次执行采集、审阅、判定。
bash hooks/verifier-ready/run.sh --all --out report/verifier-ready/my-complete-run

# 只重新计算状态，不启动业务或模型。
bash hooks/verifier-ready/run.sh --status --out report/verifier-ready/my-complete-run --json

# 重审一个 case，其他有效分片复用，共同规则重新聚合。
bash hooks/verifier-ready/run.sh --review --out report/verifier-ready/my-complete-run \
  --case llm-probe-insurance-real-smoke-customer-profile-fuyunping
```

新采集目录必须不存在；失败记录不会被静默覆盖。新运行默认携带最近审阅报告中未闭环的关键发现；也可用 `--previous <旧报告目录>` 明确指定。代码或审阅配置变动后要新采集，不能把旧调用当成新代码运行的证明。

真实运行会访问现有保险业务、模型网关，使用独立端口及实例数据。它仍是手动验证命令，不影响正常会话的结束或业务调用。长任务应在后台启动，通过 progress/status 查看进度；进度位于 `report/verifier-ready/current/progress.json`。

## 指定存档的采集

```bash
bash hooks/verifier-ready/run.sh --collect --out report/verifier-ready/archive-check \
  --instance inst-16fa340ac786414f \
  --execution-id '<从原 API 身份记录取到的 execution_id>' \
  --batch-status '<原 batch-status-at-export.json 路径>' \
  --wall-clock-s '<原运行实测整体秒数>'
```

多个 execution 重复传 `--execution-id`；原 batch status 的 identities 必须包含这些 ID。门只调用 llmtrace query calls/show/HTML，不解析日志或 pairs；原始导出不改写。存档批次可以包含其他 execution，指标只评估选中的范围。缺少实测墙钟或身份记录不能编造数值。

## 审查与判定

- 所有选中调用按 UTF-8 无损分块，带源文件、字节范围和 payload 哈希；每块连同头部不超过 40 KB/1700 行。
- pi 工具日志必须证明整个 chunk 原文实际返回，截断、只读开头、缺块、工具失败均不能计全文读取。
- 每次调用检查七类关系；共同规则使用固定标识及运行 role/stage 范围，必须明确存在、不适用或未知。跨分片差异触发聚合审阅，允许确认、解释或未决。
- 全局内容快照包围全部审阅，协调器在 spawn/ 缓冲完成后才发布结果，避免并行分片互相误伤。
- U1/L1/L2/W 是硬性检查；V1–V4 只报告，已有人工 promote 基线时 V5 检查体量回退。usage 缺失明确披露，不当零使用量。
- 上轮关键发现必须在新调用中证明 resolved；persists 或 unverifiable 继续阻断，不能靠改名或删除 case 隐去。
- 实际一致性与人工放行分开：`PASS` 表示已通过；`PASS_WITH_EXCEPTION` 表示人工允许带问题放行，真实不一致仍保留。

读取完毕不证明理解准确，一致性也不证明业务正确。审阅原文、工具返回、结构化发现、裁决和旧报告均保留供核对。

## 实施者回应与人工裁决

`response.json` 使用分片与 finding 的复合身份，禁止只写 F-01：

```json
{"responses":[{"finding":"<case_id>::F-01","status":"refuted","note":"原文已经包含该规则",
"counter_evidence":[{"call_id":"<真实 call_id>","quote":"原文摘引"}]}]}
```

允许 `fixed`、`refuted`。fixed 只是修复声明，必须新运行闭环；实施 agent 没有自我豁免通道。以下命令由人显式在终端执行，agent 不执行：

```bash
bash hooks/verifier-ready/run.sh adjudicate <报告目录> '<case_id>::F-01' \
  --rule withdrawn --note '审阅误判，原文反证明确'

bash hooks/verifier-ready/run.sh adjudicate <报告目录> '<case_id>::F-01' \
  --rule waived-by-human --note '问题成立，本轮接受风险'

bash hooks/verifier-ready/run.sh promote-baseline <报告目录>
```

人工确认用 `--rule confirmed`，整个报告例外放行用 `--override-release`。TTY 检查只拦非交互调用，不宣称区分人和伪造终端。豁免不改写审阅，不将不一致数清零；带例外的运行不能 promote 基线。报告与 meta 同目录的哈希只做一致性校验，不提供防篡改保证。

## 模型与验证边界

主要执行路径为 pi + DashScope `qwen3.8-flash`。沿用本机 DashScope provider 的端点及凭据，在临时私有 pi 配置中注册 Flash，权限 0600，结束即清理；不换 OpenRouter，不修改全局配置。JSONC 配置使用本机已有 strip-json-comments 解析；缺依赖、凭据或 provider 就明确失败。也可传 `--agent-dir <已配置有效 JSON 的私有 pi 配置目录>`，同一报告后续命令应使用相同参数。

Claude/Codex 的最终 stdout 格式提取已有离线测试；当前没有对应工具返回证据采集，不能证明全文读取，所以不能声称这两种 harness 已支持完整放行。

本次开发验证的是确定性机制和模拟审阅进程，尚未验证新门的真实业务运行、全量真实 Qwen 审阅和修复后 live 闭环。旧报告里的 Qwen 试验不是新门已通过的证据。

```bash
bash run.sh python -m pytest -q hooks/verifier-ready/tests
```

冻结的 12 个微型校准样本及 gold 在 tests/calibration/，与原报告一致。它们用于后续语义校准，不是生产金标；其中重复样本存在任务目的歧义，不能按预设 finding 强度机械判分。

历史指标 fixture 位于 tests/fixtures/20261006-metadata/：calls.json 原样保留，batch 仅投影指标所需字段，provenance.json 标明来源与哈希。它用于离线复算 111 次请求、24 次同名额外调用等机械指标，不能用于证明全文读取或语义审阅通过。
