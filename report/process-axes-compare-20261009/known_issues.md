# 已知缺陷清单（跑模型之前冻结）

判定对象：记录运行 `fb5fda5628174ef6967116bd4ecca493` 的 8 个 case。

判定只依据：案卷记录（`frozen/case_<tag>.json` 里的 `records` / `trace_analysis.collect` / `axes[].body.dossier_view`）、
交付 payload（`turn1.delivered_output`）、工具返回里的字段描述与 `execution.status/notes`、期望 E（`expectations`）。
**不依据任何一方模型给出的答案**。

分级：
- `hard`：由记录可直接证实（下一节逐条给出记录路径）。
- `soft`：事实清楚，但要按 `demand/rule.md` 的责任边界做口径判断。

证据路径都相对 case 的 `turn1`，例如 `records/run/step_executor_runs/0/tools/1` 即
`turn1/records/run/step_executor_runs/0/tools/1`。

---

## smoke-policy-detail-renyanlin

期望：告知 P260922000005855 的投保人、被保人、当前状态。

- **REN-1 [hard] 模型最终输出不是约定 JSON**
  最终模型调用是 `content: "…正文…\n\n{\"answer_draft\":…}"`：正文与裸 JSON 拼在一段文本里，
  不是纯 JSON；正文里陈述了“两张险种状态均为交费有效/有效”等结论，`answer_draft` 却只覆盖
  投保人/被保人/状态三句。
  证据：`records/traces/0/tree/0/spans/3/spans/3` 的 `output.messages[0].content`。
- **REN-2 [hard] 交付新增模型没有提出的缺口，并据此把完整度标成 partial**
  模型输出 `gaps: []`；交付 `gaps`/`limitations` = `["部分内容未能在本轮证据中对应，请结合原始资料核实。"]`，
  `completeness = "partial"`。
  证据：`delivered_output.output.output_text` 与 `spans/3/spans/3` 对照。
- **REN-3 [hard] 执行余量提示在同一轮内不更新**
  同一次运行里两次模型调用的 system/user 首段逐字相同：`剩余 10 次模型调用（含 2 次收尾预留）、12 次工具调用，约 598 秒`，
  中间已经真实消耗了 1 次模型调用和 1 次工具调用。
  证据：`spans/3/spans/1` 与 `spans/3/spans/3` 的 `last_user` 首段。
- **REN-4 [soft] 状态类事实的时点未声明**
  案卷里该保单的 fact（`applicant_name` 等）`as_of: null`，模型与交付都直接断言“当前状态为交费有效”，
  没有说明该状态没有时点锚。工具字段描述本身写的是“保单当前所处的…状态”，故这项依赖口径。
  证据：`records/run/step_executor_runs/0/tools/0` 的 `result.result.data.records[*]`；`spans/3/spans/3`。

## smoke-customer-profile-fuyunping

期望：告知伏云平的出生年月、性别。

- **CP-1 [hard] 工具参数非法 + 用同参数重复调用已失败工具**
  `customer_detail` 两次调用都同时传 `customer_id` 与非空语义上冲突的 `customer_ids: []`，两次都返回失败；
  第二次只在 `fields` 里多加一个 `clientbirthday`，`customer_id`/`customer_ids` 完全一致。失败返回里明确写着
  “本轮不要以相同参数重试同一工具”。
  证据：`records/run/step_executor_runs/0/tools/1`、`.../tools/2`（`args` 与 `result`）。
- **CP-2 [hard] 模型最终输出违反输出契约，且用占位符当引用**
  最终模型输出是“说明文字 + ```json 代码块”，且代码块里 `"fact_refs": ["...fact_id..."]` 是占位符文本。
  证据：`records/traces/0/tree/0/spans/3/spans/7` 的 `output.messages[0].content`。
- **CP-3 [hard] 交付新增模型没有提出的缺口并标 partial**
  模型 `gaps` 只有“客户的出生年月未确认，customer_detail 查询失败”；交付额外加入“部分内容未能在本轮证据中对应”。
  证据：`delivered_output.output.output_text` 与 `spans/3/spans/7` 对照。
- **CP-4 [soft] 交付同一段内自相矛盾**
  `answer` 写“出生年月未能在本轮确认”，同一段又附“客户 伏云平: · 客户摘要:伏云平·女·33岁·手机19909224628”。
  该摘要来自会话态 fact `customer_brief`（`as_of: null`），不是本轮工具返回的内容，交付没有标注来源差异。
  证据：`delivered_output.output.output_text`；`records/session` 的 `session_data.session_state.evidence`。

## smoke-policy-list-fuyunping

期望：查询并告知伏云平名下的保单。

- **PL-1 [hard] 本轮没有产出作答的模型调用，交付由非模型环节拼装**
  最后一次模型调用 `spans/3/spans/8` 仍是工具调用（`run_policy_field_lookup`），其后没有任何模型作答；
  交付答案是对两张保单的全字段倾倒（几十行字段），不是“有哪些保单”的清单回答。
  证据：`records/traces/0/tree/0` 下最后一次 span；`delivered_output.output.output_text`。
- **PL-2 [hard] 已有完整证据仍调用查询工具，并拿到与证据冲突的结论**
  前 3 次工具已返回两张保单的完整明细；模型仍调用 `run_policy_field_lookup`，返回
  `execution.status = NEEDS_CLARIFICATION`（“该客户名下有多张保单，请选择要查询的保单”），
  与“清单已在手”的现状冲突。
  证据：`records/run/step_executor_runs/0/tools/4`（`result.err = true`）对照 `tools/1..3`。
- **PL-3 [soft] 交付把敏感/无关字段直接写进面向用户的答案**
  交付里出现 `投保人证件号码明文:110101199308222741`、`投保人手机号明文:19909224628`、`被保人证件号码明文` 等。
  `demand/` 与工具契约都没有禁止明文输出的显式规则（工具本来就把这些字段作为“明文”返回），故属口径问题。
  证据：`delivered_output.output.output_text`。

## smoke-agg-paid-prem-fuyunping

期望：分别告知每张保单的累计已交保费；不给合计数。

- **AP-1 [hard] 交付的金额与案卷矛盾（1320 → 0.00）**
  工具 `policy_detail`（`tools/2`）返回 `agg_paid_prem = 1320.0`；模型草稿（`spans/3/spans/8`）也写
  “累计已交保费 1320”；交付答案却写 `保单 P260922000011415: · 保费:0.00`（取了同记录里的 `premium/保费`
  字段）。第二张保单 6300 三处一致，说明是取字段取错，不是数据缺失。
  证据：`tools/2` result、`spans/3/spans/8`、`delivered_output.output.output_text`。
- **AP-2 [hard] 模型最终输出违反输出契约**
  最终输出是“正文 + ```json 代码块”。
  证据：`records/traces/0/tree/0/spans/3/spans/8`。
- **AP-3 [hard] 交付新增假缺口并标 partial**
  交付 `gaps` 首条为“部分内容未能在本轮证据中对应，请结合原始资料核实。”，模型 `gaps` 只提了币种/业务时点。
  证据：`delivered_output.output.output_text` 与 `spans/3/spans/8` 对照。

## main-A01-fuyunping-list-aggprem

期望：告知保单清单；分别告知各保单累计已交保费；不给合计数。

- **A01-1 [hard] 交付的金额与案卷矛盾（1320 → 0.00）**
  与 AP-1 同一缺陷在本 case 复现：`tools/1` 返回 `agg_paid_prem = 1320.0`，交付写 `保费:0.00`。
  证据：`records/run/step_executor_runs/0/tools/1`、`delivered_output.output.output_text`。
- **A01-2 [hard] 模型最终输出违反输出契约**
  最终输出是“正文 + ```json 代码块”。
  证据：`records/traces/0/tree/0/spans/3/spans/6`。
- **A01-3 [hard] 交付新增假缺口并标 partial**
  交付 `gaps` 首条为“部分内容未能在本轮证据中对应…”，模型只提了币种/时点与附加险行未确认。
  证据：`delivered_output.output.output_text` 与 `spans/3/spans/6` 对照。

## main-B01-meeting-prep-fuyunping

期望：展示伏云平的资料；展示已有保单；基于资料和保单准备三个开场问题。

- **B01-1 [hard] 交付丢失了三个开场问题（三条期望中的一条完全没交付）**
  模型草稿（`spans/3/spans/12`）写了三个开场问题；交付答案里没有任何开场问题，只有客户字段与保单摘要。
  证据：`spans/3/spans/12` 与 `delivered_output.output.output_text` 对照。
- **B01-2 [hard] 交付把模型明确否定的证据拼进答案**
  模型在 `spans/3/spans/12` 明确写“这次 product_knowledge 返回的是‘平安爱满分（2026）两全保险’的内容，
  明显不是‘平安安佑福重大疾病保险’的产品，正文与所查产品不对应，不能作为安佑福的证据”；
  交付仍在末尾附了大段“参考原文（未确认，仅供参考）：医疗险-平安e生保（悦享版）…”。
  证据：`spans/3/spans/12`、`delivered_output.output.output_text`。
- **B01-3 [hard] 知识检索返回的对象与查询对象不符**
  `product_knowledge` 的参数是“平安安佑福重大疾病保险的保险责任是什么？”，返回的 `typed_value` 是
  “寿险-平安爱满分（2026）两全保险-OCR原文”等与查询产品无关的内容。
  证据：`records/run/step_executor_runs/0/tools/5` 的 `result.result.facts[*]`。
- **B01-4 [hard] 同一工具对同一客户重复调用**
  `customer_detail` 以同一 `customer_id` 调用两次（`tools/1` 取 姓名/性别/生日/VIP/客户等级/会员，
  `tools/4` 只为取 `clientNo`），第二次是同一实体同一来源的重复取数。
  证据：`records/run/step_executor_runs/0/tools/1`、`.../tools/4`。
- **B01-5 [soft] 交付把字段倾倒成无语义标签的行**
  交付里出现 `· 查询信息:大学专科`、`· 查询信息:已婚`、`· 查询信息:B`、`· 查询信息:6300.0` 等，字段名丢失。
  证据：`delivered_output.output.output_text`。

## main-D01-same-surname-clarify

期望：按客户号升序列出“我名下”姓平、12 月生日的女性客户供选择；确定选中后再查详情与保单状态。

- **D01-1 [hard] 用户给出的定位约束在查询里丢失且无人说明**
  4 次 `customer_search` 的 `query` 依次为“姓平、12月份生日、女性的客户”“姓名姓平开头的女性客户且生日在12月”
  “平姓女性客户，生日12月”“筛选客户：性别为女，生日月份为12月，姓平”。用户的“我名下”4 次全部缺失，
  “按客户号升序”4 次全部缺失；澄清与交付都没有说明这两条被丢弃。
  证据：`records/run/step_executor_runs/0/tools/0..3` 的 `args.query`；`tools/4` 与 `delivered_output`。
- **D01-2 [hard] 对同一失败来源换措辞连续重试**
  同一工具连续 4 次调用，前 3 次都返回 `execution.status = AMBIGUOUS`，第 4 次触发
  `execution.status = ERROR, code = BUDGET, control.reason = no_progress`，返回文本明确写
  “不再换措辞或换工具重复查询”。
  证据：`records/run/step_executor_runs/0/tools/0..3`。
- **D01-3 [hard] 交付把澄清态丢掉**
  `ask_clarify` 返回 `result.status = NEEDS_CLARIFICATION`；交付 `status = null`。
  证据：`records/run/step_executor_runs/0/tools/4` 与 `delivered_output.output.output_text`。
- **D01-4 [soft] 澄清问题没有说明真实卡点**
  澄清文本只说“当前筛选条件未能执行查询”，没有指出姓氏筛选无法被解析（工具返回的 message 里给了可用条件清单），
  也没有指出“我名下”归属未确定。
  证据：`tools/4` 的 `args.question` 与 `result.result.message`。
- **D01-5 [soft] 两段式意图没有进入结构化状态**
  用户要求“先列清单 → 确定选中后再查详情和保单状态”。会话账本 `session_state.ledger.tasks` 为空、
  `focus_task_id` 为 null，没有任何地方记录“选中后还要做两件事”。
  证据：`records/session` 的 `session_data.session_state.ledger`；`tools/4`。

## smoke-multi-policy-anjinning

期望：列出安锦宁名下的保单清单。

- **AN-1 [hard] 交付漏掉一张保单**
  `policy_search` 返回 8 行（唯一保单 6 张）；模型草稿 `spans/3/spans/3` 的表格列了 6 张（含
  `P260922000007861`，状态“到期终止”）；交付只列了 5 张，序号 `1.`–`5.`，`P260922000007861` 消失。
  证据：`records/run/step_executor_runs/0/tools/0`、`spans/3/spans/3`、`delivered_output.output.output_text`。
- **AN-2 [soft] 保单条数三个环节三种口径且无人说明**
  工具返回 8 行（`P...7858`、`P...7859` 各重复 2 行），模型按 6 张去重，交付 5 张。
  证据：`tools/0` result、`spans/3/spans/3`、`delivered_output`。

---

## 汇总

| case | hard | soft |
|---|---|---|
| smoke-policy-detail-renyanlin | 3 | 1 |
| smoke-customer-profile-fuyunping | 3 | 1 |
| smoke-policy-list-fuyunping | 2 | 1 |
| smoke-agg-paid-prem-fuyunping | 3 | 0 |
| main-A01-fuyunping-list-aggprem | 3 | 0 |
| main-B01-meeting-prep-fuyunping | 4 | 1 |
| main-D01-same-surname-clarify | 3 | 2 |
| smoke-multi-policy-anjinning | 1 | 1 |
| **合计** | **22** | **7** |

## 检查过但本批未复现的候选缺陷

- 「customer_detail 传空 id」在本批只出现在 `smoke-customer-profile-fuyunping`（CP-1）；
  `smoke-policy-list-fuyunping` 本轮没有 `customer_detail` 调用。
- 「金额未标时点/币种」本批只有 `agg-paid-prem` 与 `A01` 提到币种/时点缺失，且交付自己写了说明，
  不构成“未声明”。
- 「上游 HTTP/provider 失败后反复取数」：本批 8 个 case 的工具返回里没有 HTTP/上游失败，
  失败只有参数错误（CP-1）、`AMBIGUOUS`（D01-2）、`BUDGET no_progress`（D01-2）。
- 「历史轮次丢失」：4 个 `gap.history` 都是 `count = 0`（本批没有历史轮），未复现。
- 「会话末态被当成逐次状态快照」：属 provider 已声明的 `gap.state_transitions`，按责任边界不算被测缺陷。
