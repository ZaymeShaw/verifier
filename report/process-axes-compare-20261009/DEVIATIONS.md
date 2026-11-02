# 偏离与更正（跑模型过程中发生的、需要在 RESULT.md 里交代的事）

## 更正 1（派发方，2026-10-09）：现行臂缺输出结构注入与校验

冒烟（`runs/current/INVALID-pass1-no-output-spec/smoke-policy-detail-renyanlin/`）暴露两个管道缺陷：

1. `llm_transport.Transport.complete_json` 忽略了 `output_spec`：模型看不到输出结构，
   也不会被 `enforce_output` 强校验。六个轴因此全部因结构不合格失败（`units` 被写成对象、
   缺 `reason`/`scope_note`、单位里出现 `unit_id`/`verdict` 等）。**这是管道缺陷，不是现行方案的表现。**
   已修：system 末尾追加 `render_output_constraint(output_spec)`；解析改用仓库的
   `extract_json` + `_select_schema_matching_object`；解析后跑 `enforce_output`，不合规抛
   `ValueError` 交给六轴自己的纠错轮；请求层失败返回 `{"error": "llm_request_failed"}`，
   由 `raise_for_error_payload` 转成轴失败。这三件事与生产 `LlmClient.complete_json` 一致。
2. 整轴重跑复用了上一轮的 `AxisRuntime`（批次、selection、projection、process_issues 都是可变对象），
   于是 `*.rerun1.json` 全部报「发送前检查失败：材料批次与 pending 必须一一覆盖」。
   已修：每次运行（含整案重跑）都从冻结输入重建 `AxisRuntime`，整案重跑放 `pass<N>b/`，
   两份记录都留。

处置：原冒烟记录保留在 `runs/current/INVALID-pass1-no-output-spec/`，在 RESULT.md 里标为
**无效：现行臂缺输出结构注入与校验**，不计入任何指标。

## 更正 2（用户，2026-10-10）：请求不带 `response_format`

生产 `LlmClient` 从未启用 `response_format`（用户的明确决定）。两臂都不带，只靠提示词里的
输出结构 + 事后强校验 + 纠错轮。`Transport._one_request` 已去掉 `response_format`。

## 与生产通道的已知差异（不是缺陷，但要交代）

- 两臂都直连已验证可用的上游模型 `deepseek-flash`（provider `fallback2`，预检见
  `preflight/model_selection.json`），不走生产的 LiteLLM 中转与端点选择：仓库把 judge 角色
  固定成 `deepseek-v4-pro` 且无法从环境覆盖，与本任务「两臂同一个已验证模型」冲突。
- 请求体字段与生产一致：`messages`、`model`、`reasoning_effort`、`stream`、`stream_options`、`temperature`；
  不设 `max_tokens`（用模型默认上限），不带 `response_format`。
- 不启用工具（六轴调用本身不带工具），与生产一致。

## 更正 3（派发方，2026-10-09）：输出上限与 reasoning_effort 对齐生产

修好结构注入后的冒烟里，`context_memory`、`model_capability` 两轴各 6 次尝试全部
`llm_request_failed`：原始回复约 66KB、`completion_tokens` 正好 16000、`content_chars` 多次为 0——
回复全停在 `reasoning_content` 里、没写到 JSON，是 `MAX_TOKENS = 16000` 截断，不是方案或模型的问题。
生产侧证据：183 次真实六轴请求不设 `max_tokens`、带 `reasoning_effort`，单次最多约 52,000 token。

已修：`Transport` 不再发 `max_tokens`（用模型默认上限；若中转要求必填则降级到 64000 并在 RESULT.md 写明），
把六轴传入的 `reasoning_effort` 原样转发（新方案臂用同样设置）。
这一版冒烟记录保留在 `runs/current/INVALID-pass1-truncated-max-tokens/`，标为
**无效：输出上限低于生产**，不计入任何指标。

## 更正 4（本机，2026-10-10）：六轴调用被并发抢走，落到另一个模型

发现：`smoke-policy-list-fuyunping/context_memory`（第一次 pass1）有 `results 14` 与一段模型写出的
`reason`，但 `prompts 0` / `http_attempts 0`，且 `runs/current/raw/` 里没有该轴任何 batch 的原始应答文件。
逐案核对：`smoke-policy-list-fuyunping` 的 10 个 batch 里，`context_memory` 的 2 个 batch 完全没有原始文件。

原因：`current_arm.py` 原来在 `call_axis` 里临时改写模块全局 `process_common.axis_llm`，跑完再还原。
3 个 case 线程并发时互相抢这个全局：A 线程读到的是 B 线程装的 sink，更糟的是某个线程的还原会把
全局还原成**真实 `LlmClient`**（`impl/config.yaml` 固定 `llm.model=deepseek-v4-pro`），
于是那一轴的部分调用真的走了另一个模型，且记录不落到本实验的 transport 里。

处置：
1. 改成本进程只在主线程装一次补丁：`axis_llm` 变成按线程分发的转发器，线程没注册 sink 就直接
   `RuntimeError`——绝不允许回落到真实 `LlmClient`；每个轴在自己的线程里注册/注销 sink。
2. 轴记录新增 `bookkeeping_ok`（`len(prompts) == len(http_attempts)`）；不成立的轴按失败处理，
   触发整案重跑（`pass<N>b/`）。
3. 这一轮全部记录（`pass1/`、`raw/`、`prompt/`）移入 `runs/current/INVALID-real-client-race/`，
   标为**无效：跨线程抢模型客户端，部分调用未用同一模型**，不计入任何指标。
4. 之后一次 429 是同期跑了两个臂进程（冒烟未结束就起了全量）造成的，不是通道限制；
   已把 429 的退避放宽（`min(90, 8*attempt)`），并约定同一时刻只跑一个臂进程。

## 更正 5（本机，2026-10-10）：新方案臂的输入视图与程序判定条目

草稿 §3/§5 要求「第一次调用只看输入」和「程序逐字核对传递」。实现时发现记录材料的两个性质，
按下面的方式落地，均不改冻结输入（`TASK.md`/`known_issues.md`/`triage_rules.md`/`frozen/`）。

1. **输入视图改成构造性保证**。原实现是把每条 link 的 `output` 清空后重跑 `material_view`，
   但 `material_view` 会顺着嵌套引用（run 的 input 里嵌着整棵树）把输出侧记录一并展开，
   于是 `tools/N.result`、`spans/*.output` 这些东西仍可能在第一次调用里出现。现改为：
   用**完整** links 生成材料，再按 (记录 id, 字段) 把本轴所有 link 的输出端字段**逐个摘掉**，
   然后交给 `model_material`。这样「第一次调用看不到输出端」是构造成立，不靠事后扫描。
   核验：8 个 case × 6 轴 × 全部批次，`real_leak` 全为 0。
   另有 `byte_hits`（同一段正文既在输入端又在输出端出现，例如请求投影里嵌着模型发出的工具调用）
   记为提示信息，人工抽查过 renyanlin planning_routing 的一处：命中的是
   `traces/0/tree/0/spans/3/spans/3.exact_request`（请求侧字段），不是输出端。
2. **程序判定条目「工具返回是否原样进入下一次模型输入」限定在调用之后**。原来拿全材料的请求侧正文比，
   会把「更早的记录里有这段文字」也算通过。现按 `record_order` 只取该工具调用**之后**的记录。
   记录里的请求侧正文本身是投影（会压缩），逐字未命中但结果的取值出现在后续输入里时记「无法核」，
   只有返回正文与该返回里的取值都找不到才记「没达到」。
3. **草稿 §5 的「参数是否原样执行」未实现**。该核对需要模型发出的工具调用正文，
   而 §3 规定工具执行轴的第一次调用只看这一次调用的参数（没有发出侧正文），材料不支持；
   在能看到请求投影的轴上（如 renyanlin planning_routing），`tools/0.arguments` 与
   `spans/3/spans/3.exact_request` 里的调用正文逐字一致。这条记为「本轮未核对」，写进 RESULT.md 的覆盖范围。
4. **同一包装行为的同一事实只算一条**。缺口说明、执行余量提示、工具返回在多个轴/批次里会各报一次，
   现在按「缺口原文 / 余量提示 / 工具返回」归并成一条（保留合并后的轴与引用）。
5. **原始应答与 system 提示词落盘加了 pass 前缀**（`runs/<arm>/{raw,prompt}/pass<N>/…`），
   保证两遍、两臂的原始材料不会互相覆盖。pass1 之前的文件仍是旧命名（无子目录）。

## 更正 6（本机，2026-10-10 02:15 起）：fallback2 余额耗尽，全量运行中断

- 02:15 起，fallback2 的每次请求返回 `402 {"error":"Insufficient balance"}`（直接抓应答体确认，不是限流）。
  不是 429、不是并发问题：并发已降到 2，仍 402；重试 6 次全 402（记录在 `runs/current/**/http_attempts`，
  `raw_text` 为空，`status_code=402`）。
- 同时探测三条线路（2026-10-10T09:2x UTC，`preflight2/` 留有请求与应答）：
  - primary `gemini-3.8-flash-medium` / `deepseek-chat`：`503 Token acquisition timeout`；
  - fallback2 `deepseek-flash`：`402 Insufficient balance`；
  - fallback1 `qwen3.8-flash`：`200`，`reasoning_effort` 生效（应答含 `reasoning_tokens`），
    `max_tokens` 未设置，流式 usage 正常。即：任务书 §0.5 指定的两条线路都已不可用。
- 因此全量运行在中途停止：现行臂 pass1 48 个轴里 31 个合格、8 个被 402 挡住、9 个模型侧失败；
  pass1b 48 个轴里 24 个合格、12 个被 402 挡住、6 个失败。**两臂都没跑完，被挡住的轴不是结果。**
- 已完成的合格记录用的是任务书指定的 `deepseek-flash`（每轴 `http_attempts[].response_models` 可核），
  未做模型替换。是否改用它线（fallback1 `qwen3.8-flash`）跑完，记在 RESULT.md 的「待决」，不自行改设计。

## 更正 7（本机，2026-10-10 00:55）：原始应答落盘加 pass 前缀

`runs/<arm>/{raw,prompt}/` 下改成 `pass<N>/<tag>__<stage>__…`，避免两遍互相覆盖。
00:55 之前（含被 402 挡住的一批）的旧命名文件留在
`runs/current/INVALID-429-collision/raw-attempt-429/`，不计入任何指标。
