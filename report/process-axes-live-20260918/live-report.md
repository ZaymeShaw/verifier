# insurance-agno-e2e 真实身份 live 评测：过程八轴校准（2026-09-18）

被测：insurance-qa-agent 七工具全 real（`scripts/insurance_backend.sh start`，127.0.0.1:18062，Agno SQLite `~/.insurance-qa-agent-real/runtime-real.db`）。评测机不在内网：保单解析（43.139.190.73）与 Java 保单查询/明细（211.161.232.13）可达，产品知识/FAQ/权益/客户解析（192.168.1.x）不可达，因此产品类请求是真实的"下游不可用"样本。
身份：`EMP000006 / 皮奕辰 / P260000000000079`（user_id、empno、agentno 三处同填，见 mock.md）。评测 LLM：qwen3.8-flash（judge / 勘察均无 mock）。
样本：22 条新 case（14 单轮 + 4 组多轮对，已入 `impl/data/llm_probe/mock_cases.json`）+ 首条探路 + 5 条修复后重跑，共 27 次八轴链路；原始压缩结果见同目录 `results.json`。

## 1. 被测 agent 的真实缺陷（评测抓到的）

| # | 缺陷 | 复现 case | 抓到它的轴 | 备注 |
|---|---|---|---|---|
| A1 | **policy_detail/policy_search 的"保守投影"把下游已返回的字段丢了**：Java `/policy-search/detail` 实际返回 `pol_status_desc=交费有效`、`is_valid_pol=有效`、`plan_full_name=平安鑫祥两全保险（分红型，2017）`、`year_pay_prem=5,200.00`、`sum_ins=120,000.00` 等，agent 的 `policy_detail_projection.py` 只透出 insured_name/applicant_name，并在 hint 里写死"接口未明确提供产品名称、保单状态、当前保费…" | data-status-field-missing、routing-name-then-status、routing-name-search、scenario-policy-plus-product、model-pressure-confirm | knowledge_data（fail：字段未返回） | **归因偏差**：轴只能看到 agent 归一化后的信封，看不到 Java 原始响应，因此把 agent 适配层的问题记成了"数据源缺数据"。这是可见性上限，不是判错；要分清需要 agent 落原始下游响应或评测侧自己探下游（见 §4） |
| A2 | **内部 JSON 泄漏给用户**：模型同一轮既输出 ```json 围栏正文又发 ask_clarify 工具调用，agent_bridge 把两段拼进最终 answer | data-cross-identity（首轮）、data-unknown-policy（重跑） | 首轮：只有 trace_analysis 的 finding 指出，model_capability 仍判 pass（→ 修 B3 后重跑抓到）；重跑：model_capability.output_contract_followed fail，理由精确 | 复现率约 2/20，与"查无此单→澄清"路径相关 |
| A3 | **失败结果被缓存并在重试时回放**：product_knowledge 超时（TIMEOUT），模型按 hint 重试同参，`budget.tool_result_cache` 直接回放超时结果（9.9ms，同 request_id） | scenario-product-waiting-period | context_memory.cache_reuse_valid fail + planning_routing.retry_policy fail | 与 v3 case08 同类，真实复现 |
| A4 | **拿到结果后多余调用 workflow 工具并超时 75s**：policy_detail 已 SUCCESS 返回被保人，模型又调 run_policy_field_lookup / run_policy_snapshot（参数里无保单号），75s 超时，整轮 90–125s | ctx-clarify-t2、scenario-policy-plus-product（重跑） | planning_routing.path_choice_justified fail、model_capability.tool_call_decisions_consistent fail、tool_execution 三项 fail | 两次独立复现 |
| A5 | 答案/gaps 里出现"接口未返回"等被系统提示明令禁止的内部措辞 | baseline、routing-name-search、ctx-clarify-t2 | model_capability.output_contract_followed fail | 轻微但真实的契约违反；因 any_fail→problematic，会让"结果对、过程 problematic"频繁出现 |
| A6 | 内部记账不一致：`budget.llm_calls/llm_tokens=0` 与实际 2–3 次模型调用不符；`tool_metrics` 记 get_skill_instructions ok=false 而调用实际成功；子 Agent run 末态 CANCELLED 而外层 COMPLETED | 几乎每条 | 仅 trace_analysis finding，六轴按"不影响业务结果"未记账 | 可作为 agent 观测层的 bug 反馈 |
| A7 | 越权/不存在的保单一律回"未查询到"，不区分"无权限"与"不存在" | data-cross-identity | 按用户口径记 knowledge_data 问题 | 产品层面可讨论是否要区分 |

## 2. 各维度难 case 表现（修复后口径）

- **intent_understanding**：复合子问题+条件（"分别是谁，同一个人请说明"）、否定纠错（"不是 P…001"）、格式约束、尾号定位、跨轮指代（"这张保单"）、省略主语（"那投保人呢"）、澄清后仅补一个保单号——全部正确判 pass，`constraints_kept` / `reference_resolution` / `ambiguity_handled` 在该触发时触发、不该触发时 not_applicable。未见误判。
- **planning_routing**：direct→EMPTY→escalate 到 Agent 判合理；姓名搜单、尾号定位链判合理；多余的 workflow 工具调用（A4）判 path_choice fail；缓存吞掉重试（A3）判 retry_policy fail。未见误判。
- **tool_execution**：正常调用 sound；TIMEOUT 时 calls_executed_without_error / latency / results_usable 三项同时 fail，理由指向具体 tools/N/result。未见误判。
- **knowledge_data**：查无此单、字段未透出、服务超时都判 fail（符合用户口径"查无此单算数据问题"）。发现两类过严：① 用户没问的字段缺失也扣分（routing-name-search）；② 子问题数据已齐、多余调用失败也扣分（ctx-clarify-t2）。已改 pass_requires 按子问题判（B4）。`object_version_timepoint` 几乎每条 insufficient_evidence：真实信封 `as_of=null`，属实，非关键项不影响 verdict。
- **context_memory**：kept_ratio、跨轮 history 注入、无污染判断稳定；A3 的缓存回放抓准。多轮 t2 `history_injected_faithfully` 正确 pass。
- **model_capability**：诱导"不用查了直接确认"→模型仍查并如实说未获取，判 pass 正确；A2/A5 契约违反抓到；A4 重复调用抓到。首轮一处漏判（A2 首次）和一处误判（工具调用轮无正文被判违约）已由 B2/B3 修正并重跑验证。
- **fulfillment**：3 值 verdict 与业务直觉一致：被保人类正向 fulfilled；状态/现金价值类 not_fulfilled（数据没给）；澄清轮 fulfilled（系统正确要求补信息）。一致性检查全部 consistent，not_fulfilled 都有 problematic 轴解释。
- **trace_analysis**：27 次全部 complete，每次 5–11 条 finding，refs 全部经校验（unverified 为空）。质量高：A2 的拼接链、A3 的回放、A4 的多余调用、A6 的记账不一致都是它先指出来的；`downstream_focus` 按启用轴给方向后，finding 的 topic 与六轴对齐。弱点：偶有中性描述（"模型并行调用了两个工具"）当 finding，六轴需要花一次 review 处置。

## 3. 本轮对评测系统的修改（process_common / model_capability / knowledge_data）

| # | 问题（live 暴露） | 修改 | 验证 |
|---|---|---|---|
| B1 | judge 引用 observations 里给出的 ref（model_io 的模型调用 span、handoffs 的 hop、calls 的 call_ref/tool_args）被判"未读正文"降级，多条 pass 被误降为 insufficient_evidence | `catalog_refs` 纳入 model_io/handoffs 全部 ref、calls 的 `call_ref` 及其 `/tool_args`、`/tool_name`；`result_ref`/tool_message 仍必须读过 | 新测试 `test_observation_refs_count_as_seen_but_call_results_must_be_read`；重跑 policy-plus-product 不再降级 |
| B2 | 只发 tool_calls 无正文的中间轮被判"违反 JSON 输出契约"（假阳性） | `output_contract_followed.pass_requires` 明确：中间轮不算；同轮正文+tool_calls、围栏、内部枚举、正文进最终交付物算违约 | 重跑 cross-identity：judge 依此驳回该线索 |
| B3 | 六轴 judge 忽略 trace_analysis 指向本轴的 finding（A2 首轮 model_capability 判 pass） | 输出新增 `findings_review`（每条 topic=本轴的 finding 必须 adopted/rejected/out_of_scope）；漏处置时 sound→not_evaluable（rule `unaddressed_findings`），并写进 missing_evidence | 新测试 2 条；重跑 unknown-policy：A2 被采信并落到 fail |
| B4 | knowledge_data 按"每条调用"而非"每个子问题"判，扣用户没问的字段、扣多余调用的失败 | pass_requires 改为逐子问题判；多余/重复调用失败归 planning/tool；未问字段只提不扣 | 重跑 routing-name-search（`-rerun1`）：knowledge_data 由 problematic 转 sound，`data_available_per_subquestion` pass 且理由写明"用户只问有哪些保单，产品名/状态未单独要求"；fulfillment fulfilled，一致性 consistent |

测试：llm_probe 相关 208 条全绿。

## 4. 可见性上限与建议

1. **A1 类问题评测看不穿**：trace 里只有 agent 归一化信封，没有下游 HTTP 原始响应，也没落日志。要把"数据源没给"和"agent 适配层丢了"分开，两条路：agent 侧把下游原始响应写进 tool result 的 evidence 或审计日志；或评测侧按能力边界里的下游契约自己探一次（本轮是手工 curl 发现的）。前者更干净，建议反馈给 agent 团队。
2. **时间成本**：一条八轴链 6–14 分钟（trace_analysis 勘察 + 六轴各一次 judge，含读正文工具调用），live 本身 8–125 秒。并发 4 时 14 条约 34 分钟。多轮对必须串行。
3. **重跑同 session 会追加 history**：需要干净对照时换 session_id（本轮 rerun 用 `-rerun1` 后缀），已写进 mock.md。
4. **内网不可达**时产品/FAQ/权益/客户类 case 只能测"下游不可用"分支；接入内网后应再跑一遍 `scenario-*` 与既有 SYNTHETIC 产品 case。
