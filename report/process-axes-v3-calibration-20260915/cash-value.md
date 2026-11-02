## cash-value（1011s）

| 轴 | 预期(v3) | 实判 | 一致 | status | 汇总规则 / 一句话 |
|---|---|---|---|---|---|
| fulfillment | not_fulfilled | not_fulfilled | yes | succeeded |  not_fulfilled · blocking=[保单未命中真实原因与核对提示传达] · 用户查询保单 P002 的现金价值。数据源真实调用结果显示 policy_svc 返回 EMPTY，truth 为对象/字段不存在或未命中，且附带明确 hint：“未查询到该保单，请核对保单号”。模型输出虽未编造具体金额（保单现金价值未捏造数值判 fulfilled），但对未能给出数据的原因解释与真实状态严重不符：把“未查询到该保单（整单未命中） |
| intent_understanding | sound | sound | yes | succeeded | all_applicable_pass 系统在路由决策（gate）、首个直连工具调用（direct tool）以及 agent_input 中均准确识别并保留了用户问询的保单号“P002”与“现金价值（cash_value）”字段，内部表达与用户原文完全一致；问题单一无复合子问题，亦无特殊时间条件约束或歧义，意图理解环节健全正确。（pass=2/not_applicable=3） |
| planning_routing | problematic | problematic | yes | succeeded | any_fail gate 根据用户问题解析显式保单号和字段词典并选择 DIRECT_TOOL 路径合理，且直连查询覆盖了问题的取数需求；但是在 Direct 查询未命中保单（EMPTY）后，工作流设计升级至 Agent 分支，Agent 阶段仅读取了技能说明，未执行任何新的取数、参数修正或澄清动作，导致失败升级分支完全空转、缺乏业务产出。（pass=3/fail=1/not_applicable=1） |
| tool_execution | sound | sound | yes | succeeded | all_applicable_pass 本轮评测范围内包含 1 次工作流直连后端调用 direct:policy_svc/policy/full 与 2 次 Agent 工具调用 get_skill_instructions。全部调用均正常执行完成，未发生异常、超时或接口报错；信封数据结构完整，EMPTY 返回属于业务未命中而非系统故障；非信封技能指令返回内容详实可用；各调用耗时均在合理正常范围内。（pass=4） |
| context_memory | problematic | problematic | yes | succeeded | any_fail 在结果投影链路上存在信息丢失与语义反向问题：Direct 调用 policy_svc/policy/full 返回的提示信息（hint=“未查询到该保单，请核对保单号”）在投影至 agent_input 时被丢弃，且未完成项被反向表述为未完成项=[]，导致传递给后续模型调用的上下文失真；其余模型调用上下文及会话状态未发生跨样本污染。（pass=2/fail=1/not_applicable=2） |
| knowledge_data | problematic | problematic | yes | succeeded | any_fail 数据源 direct:policy_svc/policy/full 查询保单 P002 的 cash_value 字段返回 EMPTY（未查询到该保单），数据源未能提供用户子问题所需的保单现金价值数据；最终回复未捏造数据事实并如实说明未能确认。因核心取数数据源未命中且无有效数据返回，汇总判定为 problematic。（fail=1/not_applicable=2） |
| model_capability | sound | sound | yes | succeeded | all_applicable_pass 在 2 次输入经验证（reconstructed_input: verified）的模型调用中，模型忠实地整合了上下文信息。面对上游在 agent_input 阶段已丢失详细 hint 且将未完成项置空的缺陷输入（inputs_already_defective），模型未编造任何保单金额数据，没有违规重复发起已确认结果的后端请求，而是规范调用 get_skill_instructions 工具加载所需技能，并在最终输出中严格遵循系统提示 |

一致性：**consistent** — 结果 not_fulfilled，由 ['planning_routing', 'context_memory', 'knowledge_data'] 解释

<details><summary>fulfillment 期望逐条</summary>

- fulfilled `保单现金价值未捏造数值` 守住了保险金融数据的真实性底线，未向用户传递虚假金额信息。
- not_fulfilled `保单未命中真实原因与核对提示传达` 用户被误导认为保单存在仅是缺少现金价值数据，且遗漏了核对保单号的关键提示，会导致用户无效前往 App 查找不存在的保单，严重影响业务办理与用户体验。

</details>

<details><summary>intent_understanding 检查项</summary>

- pass `objects_and_fields_match`  用户原问题中的目标对象“保单 P002”和查询字段“现金价值”（见 /records/run/run_input）在 gate 决策中被准确解析为 resolved_args={"fields":["cash_value"],"policy_no":"P002"}（见 /records/run/step_results/1/content 与 /records/run/step_executor_runs/0/session_state/route/decision），并在直连工具调用（/records/run/step_executor_runs/0/session_state/budget
- pass `subquestions_all_identified`  用户提出的单一查询目标“保单 P002 的现金价值是多少”（见 /records/run/run_input）被系统完整识别，gate 记录明确标注 reason 为“显式保单号 P002 × 字段词典 ['cash_value'] × 完全解析”（见 /records/run/step_results/1/content），且在 agent_input（/records/run/step_results/3/steps/0/content）中完整保留了原问题与已解析参数，无子问题遗漏。
- not_applicable `constraints_kept`  用户输入仅为简单的单保单字段查询“保单 P002 的现金价值是多少？”，未给出时间、范围、条件、比较关系或特定格式约束，因此不适用。
- not_applicable `reference_resolution`  本样本为单轮问询（同 session 无历史 run），且用户输入直接给出了具体保单号 P002，不存在代词指代需要跨轮解析的情形。
- not_applicable `ambiguity_handled`  用户提问已完整包含具体保单号 P002 与明确查询字段现金价值，问题本身无歧义且不缺关键实体；系统亦未触发多余的澄清提问，符合无歧义且未澄清的判定标准，故不适用。

</details>

<details><summary>planning_routing 检查项</summary>

- pass `route_choice_justified`  用户提问“保单 P002 的现金价值是多少？”，包含明确保单号与单一字段需求。在 /records/run/step_results/1/content 及 /records/run/step_executor_runs/0/session_state/route/decision 中，gate 命中规则 G-4a，决策为 DIRECT_TOOL，解析参数为 policy_no=P002, fields=['cash_value']，理由为“显式保单号 P002 × 字段词典 ['cash_value'] × 完全解析”，且实际执行流顺利走向 /records/run/step_results
- pass `work_coverage`  针对用户查询保单 P002 现金价值的唯一子问题，系统在 direct 阶段发起了 /records/run/step_executor_runs/0/session_state/budget/direct_tool_results/{"fields":["cash_value"],"policy_no":"P002"} 调用，向 policy_svc 发送了包含对应保单号与 cash_value 字段的查询请求，覆盖了该问题所需的取数工作，不存在前置依赖缺失或顺序颠倒问题。
- fail `failure_branch_productive` [precheck] 在 direct 调用 /records/run/step_executor_runs/0/session_state/budget/direct_tool_results/{"fields":["cash_value"],"policy_no":"P002"} 返回 status=EMPTY（提示未查询到该保单）后，工作流升级到 Agent（/records/run/step_results/3）。但在 Agent 阶段，系统仅调用了两次 get_skill_instructions 获取 policy-query 与 compose 技能说明（/records/run/step_execu
- not_applicable `retry_policy`  本轮中 direct 工具仅调用一次，Agent 阶段调用的两次技能查询参数各不相同，全流程没有同名同参的重复调用，不涉及重试策略与缓存规避检查。
- pass `sensible_termination`  在 direct 取数未命中且 Agent 阶段确认无可用数据后，工作流在 finalize 步骤（/records/run/step_results/4）正常结束。finalize 结果中 gaps 明确如实记录了“保单 P002 的现金价值未能确认：本次未取得该字段数据，无法提供金额及数据时点”，并给出了相应的用户指引，收尾时机合理且如实标记缺口。

</details>

<details><summary>tool_execution 检查项</summary>

- pass `calls_executed_without_error`  direct:policy_svc/policy/full 返回的 error 字段为 null，status 为 EMPTY，属于合法的业务未命中结果，非系统执行错误；Agent 调用的两次 get_skill_instructions 对应的 tool_call_error 均为 false，所有调用均正常执行完毕，无异常或超时报错。
- pass `result_shape_complete`  读取 direct:policy_svc/policy/full 的返回正文，包含 ok、status、facts、evidence、gaps、hint、source、request_id、latency_ms、error 等完整信封结构字段，且针对请求参数中的保单号 P002 返回明确的 hint“未查询到该保单，请核对保单号”，数据结构完整，无残缺截断或返回对象错乱。
- pass `latency_acceptable`  Direct 调用的 duration_ms 为 1127 毫秒（信封内 latency_ms 为 1124 毫秒），处于正常远程接口响应区间；两次 get_skill_instructions 的 duration 分别为 0.0112 秒（约 11.2 毫秒）与 0.0097 秒（约 9.7 毫秒），耗时正常且无延迟激增或接近超时现象。
- pass `non_envelope_results_usable`  两次 get_skill_instructions 非信封调用分别获取了 policy-query 和 compose 技能的说明文档。返回正文均包含完整的 skill_name、description 与 instructions 规范文本，内容非空且结构可读，能够正常指导后续执行。

</details>

<details><summary>context_memory 检查项</summary>

- fail `projection_keeps_result_fields` [precheck] Direct 工具调用 direct:policy_svc/policy/full 返回的原始结果包含 hint=“未查询到该保单，请核对保单号”且 status=EMPTY（存在 open_item）。但在投影到步骤 direct（/records/run/step_results/2/steps/0）及后续步骤 agent_input（/records/run/step_results/3/steps/0）时，hint 被完全丢弃，且未完成项被反向表述为“未完成项=[]”，导致进入模型前关键提示信息丢失且未完成状态失真。
- not_applicable `cache_reuse_valid`  本轮执行中没有发生同名同参的重复调用，cache.repeats 与 failure_replays 均为空，未触发缓存或状态复用逻辑。
- pass `per_call_context_has_goal`  本轮共发生 2 次模型调用（/records/traces/0/tree/0/spans/4/spans/1 与 /records/traces/0/tree/0/spans/4/spans/4），reconstructed_input 校验均为 verified。第 1 次调用的输入消息完整包含了用户针对保单 P002 查询现金价值的目标与 Direct 执行约束；第 2 次调用在此基础上完整保留了前序工具调用与返回结果（messages/2、messages/3、messages/4），未出现用户目标、关键实体或工具结果截断丢失的情况。
- not_applicable `history_injected_faithfully`  本样本为单轮交互，快照中没有同 session 的历史 run 记录（history_runs=0），不涉及跨轮历史注入。
- pass `no_contamination`  检查 session_state 中的 direct_tool_results、route/decision 以及输入模型的消息上下文，所有涉及的对象均严格限定于当前用户的查询目标保单 P002 及现金价值字段，未混入其他用户、样本或无关保单的数据。

</details>

<details><summary>knowledge_data 检查项</summary>

- fail `data_available_per_subquestion` [precheck] 工作流直连调用 direct:policy_svc/policy/full 查询保单 P002 的 cash_value 字段，记录 /records/run/step_executor_runs/0/session_state/budget/direct_tool_results/{"fields":["cash_value"],"policy_no":"P002"} 显示返回 ok=false，status=“EMPTY”，hint=“未查询到该保单，请核对保单号”，facts 数组为空。数据源未能命中目标保单对象，未能提供子问题所需的现金价值数据。
- not_applicable `object_version_timepoint`  数据源调用直连返回状态为 EMPTY 且 facts 为空（见 /records/run/step_executor_runs/0/session_state/budget/direct_tool_results/{"fields":["cash_value"],"policy_no":"P002"}），没有返回任何命中的业务数据对象、版本标识或数据时点字段，本样本未触发命中数据对象版本与时点的核对情形。
- not_applicable `answer_facts_traceable`  在最终步骤结果 /records/run/step_results/4 中，fact_refs 为空，答案陈述为“很抱歉，保单 P002 的现金价值当前未能确认——本次查询未取得该字段的数据（未能确认其具体金额及对应数据时点）。建议您通过平安金管家 App 的保单详情页查看，或联系人工客服协助核实该保单的现金价值。”，未陈述任何保单金额、状态或条款等特定数据事实，符合答案未陈述数据事实时不适用的判定标准。

</details>

<details><summary>model_capability 检查项</summary>

- pass `output_faithful_to_input`  模型两次调用的输出均忠实于输入。在第二次调用（/records/traces/0/tree/0/spans/4/spans/4）中，输入（/records/run/step_results/3/steps/0 及 /records/run/step_executor_runs/0/messages/1/content）由于上游转换缺陷，丢失了原始提示并呈现‘状态=EMPTY;未完成项=[]’。模型在输出（/records/run/step_executor_runs/0/messages/5/content）中忠实遵循该输入，未编造任何虚假现金价值数值或事实，如实披露保单 P002 现金价值未
- pass `tool_call_decisions_consistent`  工具调用决策与输入要求一致。第一次调用（/records/traces/0/tree/0/spans/4/spans/1）面对输入中‘不要再次请求后端；可使用其他能力补充’的约束，模型未重复调用 policy_detail，而是根据系统技能框架在 /records/run/step_executor_runs/0/messages/2/tool_calls 中调用 get_skill_instructions 分别获取 policy-query 与 compose 规范；在第二次调用获得技能指令（/records/run/step_executor_runs/0/messages/3/cont
- pass `output_contract_followed`  最终模型输出（/records/run/step_executor_runs/0/messages/5/content）严格遵循了系统提示（/records/run/step_executor_runs/0/messages/0/content）的契约：以合法 JSON 格式输出且首个字段为 answer_draft；包含规范定义的 fact_refs、gaps、needs_user_input、task_updates 等字段；文案不含任何内部状态码（如 EMPTY/BUDGET），严格按规范使用‘未能确认’表述缺口，并遵照 L7 及工作纪律引导至 App 保单详情页与人工客服。

</details>
