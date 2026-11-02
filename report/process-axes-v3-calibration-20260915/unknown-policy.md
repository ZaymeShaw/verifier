## unknown-policy（65s）

| 轴 | 预期(v3) | 实判 | 一致 | status | 汇总规则 / 一句话 |
|---|---|---|---|---|---|
| fulfillment | fulfilled_with_disclosed_gap | fulfilled_with_disclosed_gap | yes | succeeded |  fulfilled_with_disclosed_gap · Judge 判各 blocking 期望已兑现，但 F4 显示数据源有未命中/报错：policy_detail→对象/字段不存在或未命中 · fulfilled · 1 blocking expectations all met · 用户查询特定保单 P999999 的现金价值，底层数据源调用 policy_detail 返回未命中（对象/字段不存在或未命中，提示“未查询到该 |
| intent_understanding | sound | sound | yes | succeeded | all_applicable_pass 系统准确理解了用户问题，识别出保单号“P999999”与目标字段“现金价值”，并在 agent_input 与首批工具调用 policy_detail 参数中完全保留与准确表达，未发生篡改或信息遗漏，意图理解环节健全。（pass=2/not_applicable=3） |
| planning_routing | sound | sound | yes | succeeded | all_applicable_pass 编排设计与实际执行路径合理。Gate 阶段基于残文未归约准确命中规则 G-4a 并路由至 AGENT；工具调用序列首先通过 policy_detail 执行保单现金价值查询；在接口返回 EMPTY（未查询到该保单）后，系统有效执行失败后分支，调用 ask_clarify 向用户澄清保单号并合理收尾，未发生异常放弃或同名同参重复调用。（pass=4/not_applicable=1） |
| tool_execution | sound | sound | yes | succeeded | all_applicable_pass 本轮执行的全部 3 次工具调用（policy_detail、get_skill_instructions、ask_clarify）均成功执行完成，无报错、异常或超时现象；返回数据结构完整且与入参一致，非信封调用内容可用，各调用耗时均在合理范围内。（pass=4） |
| context_memory | sound | not_evaluable | **NO** | succeeded | critical_insufficient_evidence（Judge 原判 sound，被程序覆盖） 系统在本轮交互中的上下文与状态管理完整可靠：步骤输入与工具返回结果向模型输入的投影完整保留了 status（EMPTY）、提示信息与未完成项；两次模型调用的 verified 重建输入均忠实包含用户查询目标（保单 P999999 的现金价值）、系统红线约束以及前序工具调用结果，未出现截断丢失；会话状态与消息历史中仅包含当前用户与目标保单实体，未发生数据污染。（pass=2/not_applicable=2/insufficient_ev |
| knowledge_data | problematic | problematic | yes | succeeded | any_fail 下游数据源 policy_svc 在查询保单 P999999 的现金价值时未命中目标对象（status 为 EMPTY），未能提供用户子问题所需的数据，数据源未能撑住业务需求。（fail=1/not_applicable=2） |
| model_capability | sound | sound | yes | succeeded | all_applicable_pass 本轮全部 2 次模型调用的输入均经 token 校验并完成重建（reconstructed_input.status=verified），输入输出链路清晰可观测。模型在第 0 次调用中准确识别保单现金价值查询意图并提取保单号 P999999，发起对应的 policy_detail 与技能指南查询；在第 1 次调用中，面对 policy_detail 返回的 status=EMPTY（未查询到该保单），模型忠实整合了该事实，未编造任何数值 |

一致性：**consistent** — 结果 fulfilled_with_disclosed_gap，由 ['knowledge_data'] 解释

<details><summary>fulfillment 期望逐条</summary>

- fulfilled `保单未命中时诚实披露原因且不虚构数据` 用户准确得知保单未命中真实原因，避免了因虚构数据导致的业务误导
- fulfilled `提供可行动的后续排查指引` 为用户提供了清晰的排查方向，帮助用户定位问题

</details>

<details><summary>intent_understanding 检查项</summary>

- pass `objects_and_fields_match`  用户原文（/records/run/run_input）明确指定查询对象为保单“P999999”，目标字段为“现金价值”。在 agent_input 步骤输出（/records/run/step_results/2/steps/0/content）中完整保留为“请查保单 P999999 的现金价值。”，且模型在首个工具调用 policy_detail 参数（/records/run/step_executor_runs/0/tools/0/tool_args）中准确传入“保单 P999999 的现金价值”，对象与字段与用户原文完全一致，未被改写或替换。
- pass `subquestions_all_identified`  用户提出的单目标问题（查询保单 P999999 的现金价值）在 agent_input（/records/run/step_results/2/steps/0/content）中被完整保留，并在首个工具调用 policy_detail 的参数（/records/run/step_executor_runs/0/tools/0/tool_args）中明确表达，用户的查询目标被系统完整识别。
- not_applicable `constraints_kept`  用户原文“请查保单 P999999 的现金价值。”（/records/run/run_input）未包含时间、范围、比较关系、特定条件或显式输出格式等附加约束，根据规则本项不适用。
- not_applicable `reference_resolution`  本样本为单轮运行，没有同 session 的历史 run，且用户输入未包含跨轮代词指代，依据 precheck 本项不适用。
- not_applicable `ambiguity_handled`  用户输入“请查保单 P999999 的现金价值。”要素完整明确，不存在歧义或关键信息缺失；系统在首批工具执行前直接发起查询，未进行多余的意图澄清。根据规则，问题本身无歧义且未澄清时本项不适用。

</details>

<details><summary>planning_routing 检查项</summary>

- pass `route_choice_justified`  Gate 执行结果显示命中规则 G-4a，原因为“保单号已解析但残文未归约:'请'——完全解析或放弃,不放行”，路由动作明确决策为 AGENT；实际执行路径通过 to_agent 条件分支顺序执行 agent_input、agent、agent_bridge 与 finalize，实际路径与路由决策完全一致。
- pass `work_coverage`  针对用户查询保单 P999999 现金价值的需求，Agent 首先调用 policy_detail（query=“保单 P999999 的现金价值”）进行查询；在未查到有效保单的情况下，按先决条件依赖逻辑，转入调用 ask_clarify 请求用户核对保单号，调用覆盖了查询与前置实体消歧工作，执行顺序合理。
- pass `failure_branch_productive`  policy_detail 返回 status=EMPTY（hint=“未查询到该保单，请核对保单号”）后，系统未盲目重试，而是调取 policy-query 技能说明，并通过 ask_clarify 工具向用户明确指出“未查询到保单 P999999 的记录，无法提供其现金价值。请您核对保单号是否正确...”，将未命中结果转化为有效的澄清交互，分支动作具有实质产出。
- not_applicable `retry_policy`  本轮调用中各工具（policy_detail、get_skill_instructions、ask_clarify）均仅调用一次，没有发生同名同参的重复调用或缓存重放，不适用重试策略检查。
- pass `sensible_termination`  在工具查询未命中并执行 ask_clarify 明确挂起提请用户澄清后，工作流经 agent_bridge 正常流转至 finalize 步骤结束本轮交互，最终输出如实反馈查询未命中并指导用户核对，结束时机合理，未在还能做实质动作时提前放弃。

</details>

<details><summary>tool_execution 检查项</summary>

- pass `calls_executed_without_error`  所有工具调用均顺利执行完成：/records/run/step_executor_runs/0/tools/0/tool_call_error、/records/run/step_executor_runs/0/tools/1/tool_call_error 与 /records/run/step_executor_runs/0/tools/2/tool_call_error 均为 false。后端 policy_svc 返回 status=EMPTY，ask_clarify 返回 status=NEEDS_CLARIFICATION，error 字段均为 null，属于预期的业务状态而非系统
- pass `result_shape_complete`  信封调用返回结构完整且与参数完全对应：policy_detail（入参 query 为“保单 P999999 的现金价值”）返回了包含 ok, status, facts, evidence, gaps, hint, source, request_id, latency_ms, error 的完整信封字段，正确反映未查询到该保单；ask_clarify 传入的 question 在返回结果的 hint 中完整回显，信封字段齐全无截断缺失。
- pass `latency_acceptable`  各调用耗时正常：policy_detail 总耗时约为 1118.6ms（后端延迟 1086ms），get_skill_instructions 耗时约为 17.9ms，ask_clarify 耗时约为 112.4ms，均处于合理执行时间范围内，无接近超时或异常缓慢情况。
- pass `non_envelope_results_usable`  非信封调用 get_skill_instructions 正常返回了 policy-query 技能的说明文档，包含 skill_name、description 及 instructions 字段正文，内容非空且结构符合预期，不是错误页或残缺数据。

</details>

<details><summary>context_memory 检查项</summary>

- insufficient_evidence `projection_keeps_result_fields` [unread_evidence_refs] pass 引用了未读取正文的 ref: ['/records/run/step_executor_runs/0/tools/0']（Judge 原判 pass：在步骤 agent_input（/records/run/step_results/2/steps/0）将用户输入完整传递给 agent 后，agent 调用的 policy_detail 工具返回结果（/records/run/step_executor_runs/0/tools/0）被完整投影到第 2 次模型调用的输入消息（/records/run/step_executor_runs/0/messages/3），其 status=
- not_applicable `cache_reuse_valid`  本轮运行中未发生同名同参重复调用，cache.repeats 为空，不存在缓存复用或回放失败的情形。
- pass `per_call_context_has_goal`  本轮 2 次模型调用均为 verified 重建输入状态：第 1 次调用（/records/traces/0/tree/0/spans/3/spans/1）包含系统约束（/records/run/step_executor_runs/0/messages/0）与用户查询目标“请查保单 P999999 的现金价值。”（/records/run/step_executor_runs/0/messages/1）；第 2 次调用（/records/traces/0/tree/0/spans/3/spans/4）在此基础上完整携带了前序 assistant 发起的工具调用（/records/run/st
- not_applicable `history_injected_faithfully`  本样本为单轮交互，无同 session 的历史 run，未涉及多轮历史注入。
- pass `no_contamination`  审查可见输入消息（/records/run/step_executor_runs/0/messages/1）与 session_state 各字段（包括 /records/run/step_executor_runs/0/session_state/ledger/tasks、/records/run/step_executor_runs/0/session_state/entities/pending_clarify 以及 /records/run/step_executor_runs/0/session_state/route/decision），上下文中的保单实体仅涉及当前用户所查询的 P

</details>

<details><summary>knowledge_data 检查项</summary>

- fail `data_available_per_subquestion` [precheck] 模型调用 policy_detail 工具查询“保单 P999999 的现金价值”（入参见 /records/run/step_executor_runs/0/tools/0/tool_args），下游服务返回 ok: false、status: "EMPTY"、hint: "未查询到该保单，请核对保单号"（见 /records/run/step_executor_runs/0/tools/0/result），数据源未命中目标保单对象，未能提供现金价值数据。
- not_applicable `object_version_timepoint`  由于 policy_detail 调用返回结果为空（status: "EMPTY"，facts: []），下游数据源未返回任何保单实体、条款版本或数据时点，不存在需校验对象版本与时点的命中数据。
- not_applicable `answer_facts_traceable`  最终答案（见 /sample/extracted_output 及 /records/run/step_results/3）明确说明“未查询到保单 P999999 的记录，无法提供其现金价值”，并未陈述任何具体的保单数据事实（如现金价值数值、条款或状态），符合标准中“答案没有陈述任何数据事实时 not_applicable”的规则。

</details>

<details><summary>model_capability 检查项</summary>

- pass `output_faithful_to_input`  模型两次输出均忠实整合了对应输入的关键信息：在第 0 次模型调用中，模型根据用户提问“请查保单 P999999 的现金价值。”（/records/run/step_executor_runs/0/messages/1/content），忠实生成包含完整保单号与查询目标的工具参数 query=“保单 P999999 的现金价值”（/records/run/step_executor_runs/0/messages/2/tool_calls）；在第 1 次模型调用中，面对工具 policy_detail 返回的 status=EMPTY 及 hint=“未查询到该保单，请核对保单号”（/recor
- pass `tool_call_decisions_consistent`  模型发起与停止工具调用的决策与上下文信息缺口严格一致：在第 0 次调用（/records/traces/0/tree/0/spans/3/spans/1）中，因尚未获取保单数据存在信息缺口，模型发起 policy_detail（/records/run/step_executor_runs/0/tools/0）与 get_skill_instructions（/records/run/step_executor_runs/0/tools/1）；在第 1 次调用（/records/traces/0/tree/0/spans/3/spans/4）中，输入已明确包含 policy_detail 返回
- pass `output_contract_followed`  模型输出完全遵循系统提示与工具契约约束。系统提示（/records/run/step_executor_runs/0/messages/0/content）明确要求“仅当本轮尚无任何可答事实且缺少关键实体时,才调用ask_clarify 挂起等待用户”，且要求“answer_draft 与 gaps 只使用面向业务用户的自然语言,不得出现‘工具返回’、‘接口返回’或 EMPTY/BUDGET 等内部状态枚举”，技能 instructions（/records/run/step_executor_runs/0/messages/4）亦要求“失败形态按信封状态如实转述”。模型在第 1 次调用的输出

</details>
