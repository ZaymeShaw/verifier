## multi-turn（0s）

| 轴 | 预期(v3) | 实判 | 一致 | status | 汇总规则 / 一句话 |
|---|---|---|---|---|---|
| fulfillment | fulfilled_with_disclosed_gap | fulfilled_with_disclosed_gap | yes | succeeded |  fulfilled_with_disclosed_gap · Judge 判各 blocking 期望已兑现，但 F4 显示数据源有未命中/报错：policy_detail→对象/字段不存在或未命中 · fulfilled · 1 blocking expectations all met · 本次请求为多轮对话，用户询问“那它的缴费方式呢”，模型正确结合上下文指代保单 P260000000000001。底层数据源 policy_det |
| intent_understanding | sound | sound | yes | succeeded | all_applicable_pass 系统在多轮对话中对用户的查询意图理解准确完整：通过上下文成功将代词“它”消解为历史保单 P260000000000001，并将目标字段“缴费方式”准确转化为工具调用参数，未发生关键对象或字段的遗漏与篡改。（pass=3/not_applicable=2） |
| planning_routing | sound | sound | yes | succeeded | all_applicable_pass 本轮针对代词指代的多轮追问准确路由至 Agent，并结合上一轮对话上下文消歧出保单号发起 policy_detail 全量查询；在接口返回 PARTIAL 且未包含缴费方式字段后，系统合规完成技能组织并如实将该缺失字段作为 gap 记录披露后收尾，编排设计与实际执行路径合理且产出有效。（pass=4/not_applicable=1） |
| tool_execution | sound | sound | yes | succeeded | all_applicable_pass 本轮涉及的 1 次后端保单接口调用（policy_detail）与 2 次技能读取调用（get_skill_instructions）均正常执行完成，无系统异常或报错；返回的信封与非信封数据结构完整、字段齐全，返回对象与请求参数一致，且调用耗时均处于合理可接受范围。（pass=4） |
| context_memory | sound | sound | yes | succeeded | all_applicable_pass 上下文与状态管理全流程表现正常：工具 policy_detail 返回的 PARTIAL 状态、未完成项及提示完整投影至后续模型输入；前轮历史记录真实内联且本轮针对新问题重新发起工具调用核实；3 次模型调用经 token 校验均为 verified 重建输入，各调用均完整包含用户目标、关键对象及前序工具交互结果，无截断或目标丢失；session_state 与上下文无跨用户或跨保单的数据污染。（pass=4/not_applicable |
| knowledge_data | problematic | problematic | yes | succeeded | any_fail 业务数据源未能支撑用户子问题所需的核心数据：针对用户询问的保单 P260000000000001 缴费方式，policy_detail 调用返回状态为 PARTIAL，且缺失缴费方式字段；返回数据中也未提供业务时点（as_of 均为 null）。虽然最终答案忠实回溯了已有的险种与投保人事实并如实披露了字段缺失，但由于外部数据源本身未提供所需核心业务数据，导致本轮业务无法完成实质解答，按规则判定为 problematic。（pass=1/ |
| model_capability | sound | sound | yes | succeeded | all_applicable_pass 模型在全部可观测的模型调用与工具调用决策环节中表现符合标准：在多轮指代下准确提取保单号并针对信息缺口发起工具查询；工具返回未包含目标字段后未进行无意义重复调用；最终输出忠实整合已有险种事实并如实披露缴费方式未确认的缺口，严格遵守系统提示的 JSON 契约、首字段顺序及业务自然语言约束。各项检查均通过正面证据验证通过。（pass=3） |

一致性：**consistent** — 结果 fulfilled_with_disclosed_gap，由 ['knowledge_data'] 解释

<details><summary>fulfillment 期望逐条</summary>

- fulfilled `保单缴费方式如实披露与下一步指引` 终端用户清晰了解该保单由于资料缺失暂无法确认缴费方式的事实，未受虚构信息误导，并获得了明确的下一步处理途径。
- fulfilled `结构化数据缺口与追溯凭证交付` 下游质检与审计系统能够准确解析数据缺口事实和凭证链，便于自动化跟踪与处理。

</details>

<details><summary>intent_understanding 检查项</summary>

- pass `objects_and_fields_match`  用户原文为“那它的缴费方式呢”（/records/run/run_input），查询对象为承接历史的保单，目标字段为“缴费方式”。在首个业务工具调用的参数记录 /records/run/step_executor_runs/0/tools/1/tool_args 中，query 参数为“保单 P260000000000001 的缴费方式”，对象与字段与用户意图完全一致，未被改写或替换。
- pass `subquestions_all_identified`  用户本轮仅提出单一问题，即查询保单的“缴费方式”。该问题在 /records/run/step_results/2/steps/0/content 的任务输入中被完整保留，并在工具调用 /records/run/step_executor_runs/0/tools/1/tool_args 的参数中体现为具体查询意图，问题已被完整识别。
- not_applicable `constraints_kept`  用户问题“那它的缴费方式呢”未设定时间、条件、比较关系、范围或特定输出格式等限制条件，因此该检查项不适用。
- pass `reference_resolution`  用户在提问中使用代词“它”。上一轮会话历史 /records/history_runs/0/step_executor_runs/0/messages/5/content 中讨论的对象为保单 P260000000000001。模型在 /records/run/step_executor_runs/0/messages/2/tool_calls 及 /records/run/step_executor_runs/0/tools/1/tool_args 中将“它”准确解析为“保单 P260000000000001”，指代消解正确。
- not_applicable `ambiguity_handled`  结合对话历史，用户的指代对象及查询字段清晰明确，不存在歧义或信息缺失，系统也未发起多余澄清，因此该检查项不适用。

</details>

<details><summary>planning_routing 检查项</summary>

- pass `route_choice_justified`  用户问题为带代词指代的追问“那它的缴费方式呢”（见 /records/run/step_results/2/steps/0/content），gate 执行检查时规则 G-2、G-3、G-4a 均未命中，决策动作判定为 AGENT（见 /records/run/step_results/1/content 与 /records/run/step_executor_runs/0/session_state/route/decision）。实际执行路径严格走 assemble -> gate -> agent_input -> agent -> agent_bridge -> finalize（见
- pass `work_coverage`  结合 agent_input 中组装的历史上下文（/records/run/step_results/2/steps/0/content），模型准确识别出目标保单 P260000000000001 并调用 policy_detail 查询其缴费方式（参数为“保单 P260000000000001 的缴费方式”，见 /records/run/step_executor_runs/0/tools/1/tool_args），取数调用与消歧依赖先决条件对应且全面覆盖用户查询需求。
- pass `failure_branch_productive`  policy_detail 调用返回 status=PARTIAL 且明确提示接口未返回缴费方式等字段（见 /records/run/step_executor_runs/0/tools/1/result），模型在接收到该未命中结果后，调用 compose 技能并生成结构化回答，保留已确认事实并将缺失的缴费方式如实登记至 gaps，最终顺利 finalize 收尾（见 /records/run/step_executor_runs/0/messages/7 与 /records/run/step_results/3），未命中分支产出实质有效且符合规范。
- not_applicable `retry_policy`  precheck 表明本轮没有同名同参的重复调用，且实际 trace 中仅发起了一次 policy_detail 和两次入参不同的 get_skill_instructions，未触发重试机制。
- pass `sensible_termination`  在执行 finalize 步骤（见 /records/run/step_results/3）前，系统已完成针对用户问题的保单全量查询（/records/run/step_executor_runs/0/tools/1）；在下游服务未提供缴费方式字段时，finalize 如实将该未完成项记录为缺口（gaps=[“缴费方式：系统资料未返回该字段，未能确认；需通过人工渠道核实。”]），并给出了基于已确认险种与投保人事实的客观答复，结束时机合理，无未尽工作被提前放弃。

</details>

<details><summary>tool_execution 检查项</summary>

- pass `calls_executed_without_error`  所有工具调用均顺利执行完成，无异常报错。policy_detail 返回 ok 为 true 且 error 为 null，status 为 PARTIAL 属于业务上缺少缴费方式字段的正常返回，并非执行故障；两次 get_skill_instructions 的 tool_call_error 均为 false。
- pass `result_shape_complete`  policy_detail 的返回信封字段（ok、status、facts、evidence、gaps、hint、source、request_id、latency_ms）齐全；返回的 facts 列表对象 subject_id 均为 P260000000000001，与输入参数 query 中的保单号完全吻合，无截断或与请求无关的内容。
- pass `latency_acceptable`  policy_detail 调用耗时为 1293.4ms（接口内部 latency_ms 为 1271ms），两次 get_skill_instructions 调用耗时分别为 16.2ms 和 10.9ms，所有调用耗时指标均有完整记录且处于正常响应范围内，无超时或异常缓慢情况。
- pass `non_envelope_results_usable`  本轮进行了两次非信封形态的 get_skill_instructions 调用，返回正文均为非空且结构完整的技能指令 JSON 文本（分别对应 policy-query 与 compose 技能说明），内容可读可用，并非错误页面或异常数据。

</details>

<details><summary>context_memory 检查项</summary>

- pass `projection_keeps_result_fields`  工具调用 policy_detail 返回的 PARTIAL 状态、gaps 未完成项及 hint 提示信息在投影到模型输入消息时被完整保留，无字段丢失、篡改或反向表述。
- not_applicable `cache_reuse_valid`  本轮运行中无同名同参重复调用，去重调用计数为 0（deduplicated_tool_calls=0），未触发缓存复用机制。
- pass `per_call_context_has_goal`  本轮 3 次模型调用的 reconstructed_input 均为 verified 状态且 token 数与 span 完全一致；每次调用的输入均包含系统红线规则、当前用户目标（缴费方式）及保单对象 P260000000000001，后续调用完整携带了前序工具执行返回的事实与缺口，未发生目标丢失或上下文截断。
- pass `history_injected_faithfully`  输入消息中的历史对话文本与上一轮历史运行的真实输出完全一致，并明确标注历史仅用于指代理解而非本轮事实依据；Agent 随后针对缴费方式发起新的 policy_detail 查询重新取数，未将旧答案作为新数据替代。
- pass `no_contamination`  session_state 中的 entities、evidence 和 route.policy_search_contexts，以及本轮输入和工具返回内容均严格绑定当前用户 EMP000000 与目标保单 P260000000000001，未混入其他用户、样本或无关保单的数据。

</details>

<details><summary>knowledge_data 检查项</summary>

- fail `data_available_per_subquestion` [precheck] 根据 /records/run/step_executor_runs/0/tools/1/result 与 /records/run/step_executor_runs/0/tools/1，用户子问题询问保单 P260000000000001 的缴费方式，但 policy_detail 返回状态为 PARTIAL；返回结果中虽有投保人及 3 条险种记录，但完全缺失缴费方式相关字段，且 hint 明确披露未明确提供产品名称、保单状态、当前保费、现金价值、币种和业务时点等，属于字段缺失/未命中，未能支撑该子问题的数据需求。
- insufficient_evidence `object_version_timepoint`  在 /records/run/step_executor_runs/0/tools/1/result 中，返回的保单标识 subject_id 为 P260000000000001，与用户询问的目标保单一致；但所有 fact 的 as_of 字段均为 null，且 hint 和 gaps 明确说明接口未提供业务时点与版本字段，依照规则缺乏时点字段不得推断为最新，属于证据不足。
- pass `answer_facts_traceable`  对照最终输出 /sample/extracted_output 与 /records/run/step_results/3，答案中陈述的各项保单数据事实（保单 P260000000000001 下包含 3 条险种记录、险种代码分别为 1689、1731、1730，投保日期均为 2023-07-29，投保人为赵子谦，险种 1689 被保人为钱清禾且其余两条被保人为赵子谦本人）均在数据源返回结果 /records/run/step_executor_runs/0/tools/1/result 的 facts（F-CALL-TR-b4ac3e77263748be94f8c723a256b305-01

</details>

<details><summary>model_capability 检查项</summary>

- pass `output_faithful_to_input`  模型在首跳工具调用（/records/run/step_executor_runs/0/messages/2/tool_calls）中准确解析用户输入（/records/run/step_executor_runs/0/messages/1/content）对上一轮保单 P260000000000001 的指代与缴费方式意图，未篡改关键实体；在最终生成内容（/records/run/step_executor_runs/0/content）中，模型忠实陈述了接口返回的 3 条险种记录（险种代码 1689、1731、1730）、投保日期（2023-07-29）、投保人与被保人对应关系，精准绑定 
- pass `tool_call_decisions_consistent`  在模型输入（/records/run/step_executor_runs/0/messages/1/content）中，上下文明确提示历史答案不可作为本轮事实依据且当前问题存在缴费方式信息缺口，模型在 /records/run/step_executor_runs/0/messages/2/tool_calls 中及时发起针对保单 P260000000000001 缴费方式的 policy_detail 调用以及读取技能指令的 get_skill_instructions 调用（span 见 /records/traces/0/tree/0/spans/3/spans/1）；在工具返回确认无
- pass `output_contract_followed`  系统提示（/records/run/step_executor_runs/0/messages/0/content）明确要求以 JSON 格式输出且 answer_draft 必须是首个字段，需包含 fact_refs、gaps、needs_user_input、task_updates，且禁用“工具返回”等技术内部枚举。核对 /records/run/step_executor_runs/0/content 与 /sample/extracted_output，模型输出结构严格为合法 JSON，首字段为 answer_draft，完整包含所有必须字段，gaps 准确披露了“缴费方式：系统资料

</details>
