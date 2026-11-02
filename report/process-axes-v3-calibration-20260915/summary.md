# process-axes-v3 校准（真实 Judge）

场景 insurance-agno-e2e；快照 report/business-trace-agno-20260913/snapshots

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

## and-procedure（1501s）

| 轴 | 预期(v3) | 实判 | 一致 | status | 汇总规则 / 一句话 |
|---|---|---|---|---|---|
| fulfillment | fulfilled_with_disclosed_gap | fulfilled_with_disclosed_gap | yes | succeeded |  fulfilled_with_disclosed_gap · Judge 判各 blocking 期望已兑现，但 F4 显示数据源有未命中/报错：policy_detail→对象/字段不存在或未命中；general_qa→服务不可用 · fulfilled · 6 blocking expectations all met · 本次输出对复合问题逐项回应。保单P002现金价值查询在数据源中为未命中，输出如实说明系统未查询到保单、提示核对 |
| intent_understanding | sound | sound | yes | succeeded | all_applicable_pass 本轮用户原文“请查询保单 P002 的现金价值，并告诉我犹豫期内退保怎么办理。”在内部表达中被完整保留：gate 步骤输出记录了对象“保单号已解析”并把残文“犹豫期内退保怎么办理”原样带出（/records/run/step_results/1/content），agent_input 步骤输出与 run_input 逐字一致（/records/run/step_results/2/steps/0/content），首批工具参数 pol |
| planning_routing | problematic | problematic | yes | succeeded | any_fail 编排路线本身站得住：gate 因用户问句含两个未归约子任务（保单金额 + 办理流程）判 AGENT（G-4a，不放行 Direct），实际路径 assemble→gate→to_agent(if 分支)→agent_input→agent(lifeqa-unified)→agent_bridge→finalize 与决策一致；Agent 在一批内并行发起 policy_detail（P002 现金价值）与 general_qa（犹豫期退 |
| tool_execution | problematic | problematic | yes | succeeded | any_fail 本轮 5 次工具调用中，qa_svc 的 general_qa 两次返回执行级错误信封（status=ERROR、error.code=UPSTREAM、hint=“后端服务暂时不可用”），后端 qa_svc 属本轮全程报错系统，故 calls_executed_without_error 判 fail。其余各项本身符合标准：三次带信封调用的信封字段齐全且返回对象与参数一致（policy_detail 对 P002 的未命中是业务结果  |
| context_memory | problematic | problematic | yes | succeeded | any_fail 本轴两项定位到问题。其一，结果投影链在模型侧是完整的（三次工具信封在 tool 消息里逐字保留 status/hint/error/open_item，见 messages/3、messages/4、messages/8），但向步骤 content 投影时被改写并在末跳丢失：agent_bridge 把 policy_detail 的 EMPTY 与 general_qa 的 ERROR 统一改成 status=PARTIAL（fact |
| knowledge_data | problematic | problematic | yes | succeeded | any_fail 两个子问题的数据源都没撑住：保单侧 policy_detail 对“保单 P002 的现金价值”返回 status=EMPTY、facts=[]、evidence=[]、hint=“未查询到该保单，请核对保单号”（policy_svc /policy/full），即目标保单对象未命中，现金价值字段无从取得；知识侧 general_qa 对“犹豫期内退保怎么办理”两次均返回 status=ERROR、error.code=UPSTREAM |
| model_capability | sound | problematic | **NO** | succeeded | any_fail 本轮 3 次模型调用的输入均为 verified 重建（model_calls_with_verified_input:3/3），逐次对照后：调用决策与最终答案都忠实整合了输入里的工具信封与技能纪律（EMPTY/ERROR 均如实转述、缺口写入 gaps、未编造数值），同参重试也发生在 retryable=true 的错误上，属合理；但最终 assistant 消息的 task_updates 自述“未重试”，而同一模型自己前一次输出（ |
| evaluation_standard | - | sound | yes | succeeded | all_applicable_pass 本轴审的是 /scenario/capability、/scenario/boundary 与七个轴的标准本身。逐条对照已读到的轴 description 与 type_contract：各轴要求的证据都在本 Trace 实际覆盖范围内（gate 决策、agent_input 原文、工具信封正文、持久化消息与逐调用 token 指标均可读），且每个过程轴的 verdict_enum 都含 not_evaluable 并在 descrip |

一致性：**consistent** — 结果 fulfilled_with_disclosed_gap，由 ['planning_routing', 'tool_execution', 'context_memory', 'knowledge_data', 'model_capability'] 解释

<details><summary>fulfillment 期望逐条</summary>

- fulfilled `保单P002现金价值未命中时如实说明查询未命中` 用户能够知道现金价值未返回的真实原因是保单未命中，并获得核对或客服核实方向
- fulfilled `保单P002现金价值不编造数值或猜测保单` 避免用户把虚构数值当作保单事实使用
- fulfilled `犹豫期内退保办理查询服务不可用时如实说明原因` 用户能够理解退保流程未返回是由于服务暂不可用，而不是系统不支持该问题
- fulfilled `犹豫期内退保办理不声称已完成查询或确认具体流程` 避免用户误以为退保办理流程已被权威确认
- fulfilled `不将退保办理咨询写成已实际办理退保` 避免用户误认为退保申请已经实际提交
- fulfilled `复合问题两个子问题均得到回应` 用户无需追问即可知道两个子问题均未取得确认结果
- fulfilled `未命中或服务不可用时提供可行动下一步` 用户获得在结果缺失时继续推进的明确路径

</details>

<details><summary>intent_understanding 检查项</summary>

- pass `objects_and_fields_match`  对象与字段逐字保留：run_input 与 agent_input 步骤输出均为“请查询保单 P002 的现金价值，并告诉我犹豫期内退保怎么办理。”（/records/run/step_results/2/steps/0/content 与 /records/run/run_input 一致，32 字符）；首批工具参数把对象与字段原样落地——policy_detail 的 arguments 为{“query”: “保单 P002 的现金价值”}（/records/run/step_executor_runs/0/tools/0/tool_args），general_qa 的 argument
- pass `subquestions_all_identified`  复合问题的两个子目标均被识别并分别表达：子问题一“查询保单 P002 的现金价值”在首轮 assistant 工具调用意图中以 policy_detail{“query”:“保单 P002 的现金价值”} 出现（/records/run/step_executor_runs/0/messages/2/tool_calls 第 1 项，与 /records/run/step_executor_runs/0/tools/0/tool_args 一致）；子问题二“犹豫期内退保怎么办理”在同一批调用中以 general_qa{“query”:“犹豫期内退保怎么办理”} 出现（/records/run/
- pass `constraints_kept`  用户给出的限定条件“犹豫期内”未被换成默认口径：general_qa 参数原样为“犹豫期内退保怎么办理”（/records/run/step_executor_runs/0/tools/1/tool_args），重试调用亦未改词（/records/run/step_executor_runs/0/tools/4 的 arguments 同名同参，facts 判定为同参重复）；保单对象限定 P002 与目标字段“现金价值”在 policy_detail 参数中保留（/records/run/step_executor_runs/0/tools/0/tool_args）。“并告诉我”这一双目标要求
- not_applicable `reference_resolution`  本样本为单轮，不存在需要解析的跨轮指代：用户消息 messages/1 的 from_history 为 false（/records/run/step_executor_runs/0/messages/1/from_history），且本轮 agent 执行的消息序列中无历史轮消息（system 提示中的“当前任务台账摘要:[]”“当前会话实体上下文:{}”为空，/records/run/step_executor_runs/0/messages/0/content）。用户原文已显式给出保单号 P002，agent_input 与工具参数直接沿用该显式对象，无需回溯历史 run 解析指代。
- not_applicable `ambiguity_handled`  问题本身无缺参歧义：用户显式给出保单号 P002、目标字段“现金价值”与流程知识点“犹豫期内退保”，gate 理由亦确认“保单号已解析”（/records/run/step_results/1/content），未标记缺参；系统也未做多余澄清——调用清单中无 ask_clarify（calls 仅含 policy_detail、general_qa、get_skill_instructions，见 /records/run/step_executor_runs/0/tools/0 与 /records/run/step_executor_runs/0/tools/1），agent 末态 nee

</details>

<details><summary>planning_routing 检查项</summary>

- pass `route_choice_justified`  用户原文是复合问题：「请查询保单 P002 的现金价值，并告诉我犹豫期内退保怎么办理。」gate 输出 action=AGENT、matched_check=G-4a、resolved_args=null、reason=「保单号已解析但残文未归约:'请 并 犹豫期内退保怎么办理'——完全解析或放弃,不放行」，即因残文（第二个办理流程子问题）无法归约到单一 Direct 能力而不放行直连，与问题类型相称；因未走 Direct，resolved_args/capability_id 为 null 也与该决策自洽。实际路径与之匹配：/records/run/step_results/2/conten
- pass `work_coverage`  两个子问题各有对应调用且顺序无先决违反：子问题一（P002 现金价值）由 tools/0 policy_detail 承接，参数 {"query": "保单 P002 的现金价值"} 带显式完整保单号，符合 policy-query 纪律「显式保单号(含尾号)直接调 policy_detail」，无需先做客户→保单定位（无号才走 run_policy_field_lookup），故不存在在未消歧对象前执行依赖查询的问题；子问题二（犹豫期内退保怎么办）由 tools/1 general_qa 承接，参数 {"query": "犹豫期内退保怎么办理"} 已是自足问句，命中 general-qa 纪
- pass `failure_branch_productive`  两次失败后都有实质动作且收尾与问题状态相称：policy_detail 返回 EMPTY（hint「未查询到该保单，请核对保单号」）后，轨迹没有对同一意图猜别名重查，而是转入 general_qa 取办理流程并按纪律如实转述未命中（tools/0 的 failure_followups 记录 switched_tool:general_qa、read_skill×2、ended_with=finalized）；general_qa 返回 ERROR/UPSTREAM(retryable=true) 后，先读取 general-qa 与 policy-query 两份纪律（tools/3、too
- fail `retry_policy` [precheck] 对可重试失败没有可用的重试策略：tools/1 general_qa 于 05:51:01.95 返回 status=ERROR、error={code:UPSTREAM,retryable:true}、request_id=CALL-TR-b9316cf638074072a84fa27abfecd75b-02、耗时 113.7ms；11.09 秒后 tools/4 以完全相同参数 {"query": "犹豫期内退保怎么办理"} 再次调用，结果逐字相同（同一 request_id -02、latency_ms 仍为 105、status=ERROR），耗时骤降到 9.1ms，派生事实判定 ve
- pass `sensible_termination`  结束时机合理：finalize 之前已对两个子问题各发起过取数调用（tools/0 policy_detail、tools/1 general_qa 及一次重试 tools/4），并读取了两份领域纪律（tools/2、tools/3），没有尚未尝试的必要动作；finalize 的 gaps 如实列出两项未完成（现金价值未命中需核对保单号、办理流程因知识库服务不可用未确认），与调用记录中的 EMPTY 与 UPSTREAM ERROR 一一对应，answer_draft 也写明「以上两点均未能取得确认结果,未作任何推测」，属于把无法完成的工作标记为缺口后收尾，而非还能做事时提前放弃。needs_

</details>

<details><summary>tool_execution 检查项</summary>

- fail `calls_executed_without_error` [precheck] health.calls 中两次 general_qa 的 outcome=error：/records/run/step_executor_runs/0/tools/1/result 正文为 {ok:false, status:“ERROR”, error:{code:“UPSTREAM”, retryable:true}, hint:“后端服务暂时不可用”, source:{system:“qa_svc”, endpoint:“/qa/recall”}, request_id:“CALL-TR-b9316cf638074072a84fa27abfecd75b-02”}，/records/r
- pass `result_shape_complete`  三个信封调用的返回结构完整且对象与参数一致：/records/run/step_executor_runs/0/tools/0/result 含 ok/status/facts/evidence/gaps/hint/source/request_id/latency_ms/error 全字段，source.system=policy_svc、endpoint=/policy/full，hint“未查询到该保单，请核对保单号”正对应 /records/run/step_executor_runs/0/tools/0/tool_args 中请求的“保单 P002 的现金价值”，未返回别的保单、无截
- pass `latency_acceptable`  逐调用耗时均有记录且量级正常：/records/run/step_executor_runs/0/tools/0/metrics duration=1.006s（信封 latency_ms=991，policy_svc 单次查询约 1 秒）、/records/run/step_executor_runs/0/tools/1/metrics duration=0.114s（信封 latency_ms=105）、/records/run/step_executor_runs/0/tools/3 与 /records/run/step_executor_runs/0/tools/2 各约 6ms、/
- pass `non_envelope_results_usable`  本轮存在两次非信封返回，均为可用内容而非错误页：/records/run/step_executor_runs/0/tools/3/result 返回 general-qa skill 的 description、完整 instructions（含“工具白名单：general_qa”“召回不足(EMPTY/低置信)时明确告知未能确认”等正文）及 available_scripts/available_references 字段，共 4867 字符、无报错标记；/records/run/step_executor_runs/0/tools/2/result 返回 policy-query ski

</details>

<details><summary>context_memory 检查项</summary>

- fail `projection_keeps_result_fields`  模型输入侧保留完好：tools/0 的 EMPTY 信封在 messages/3/content 逐字为 {"ok":false,"status":"EMPTY",…"hint":"未查询到该保单，请核对保单号"}，tools/1 与 tools/4 的 ERROR 信封在 messages/4/content、messages/8/content 逐字含 status=ERROR、hint=“后端服务暂时不可用”、error.code=UPSTREAM、retryable=true。但向步骤 content 投影时发生改义与丢失：step_results/2/steps/2（agent_br
- fail `cache_reuse_valid` [precheck] cache.repeats 判定 verdict=replayed、failure_replayed=true：tools/4（general_qa，同参 query=“犹豫期内退保怎么办理”）与 tools/1 返回完全相同的结果体——request_id 同为 CALL-TR-b9316cf638074072a84fa27abfecd75b-02、latency_ms 同为 105、error.code=UPSTREAM(retryable=true)，而 tools/4 自身 duration 仅 9.07ms 对 tools/1 的 113.69ms，间隔 11.09s；session
- pass `per_call_context_has_goal`  三次模型调用的 reconstructed_input 均为 verified 且 token_check=match（call_ordinal 0：message_input_tokens 4548=span 4548、output 470=470；call_ordinal 1/2 对应 spans/6 input 11391、spans/8 input 11547，均标 token_check=match）。逐次核对 message_refs：call 0 含 messages/0（system：七条红线+输出契约，尾部可见“当前任务台账摘要:[]”“当前会话实体上下文:{}”）与 mes
- not_applicable `history_injected_faithfully`  本样本为单轮，不存在多轮历史内联：scope.turn.history_runs=0、multi_turn=false，采集侧 history.status=empty、count=0；已读的 messages/0/from_history 与 messages/1/from_history 均为 false，messages/7 的 from_history 亦为 false，说明本轮输入里没有来自前轮 run 的历史文本。session_state/route/last_result 与 last_result_run_id 指向的正是本轮自身 run（441773b9-ae7c-4366
- pass `no_contamination`  上下文中的业务对象与本轮问题一致、无串入：用户目标 messages/1/content 只涉及保单 P002 现金价值与犹豫期退保流程；两次数据调用的参数分别为 tools/0 的 {"query":"保单 P002 的现金价值"} 与 tools/1、tools/4 的 {"query":"犹豫期内退保怎么办理"}，未出现其他保单号或客户；session_state/entities 与 ledger 均为 {}、evidence 为 {}、route/policy_search_contexts 为 []，没有残留其他样本的实体或台账。route/decision 与 trace_id（

</details>

<details><summary>knowledge_data 检查项</summary>

- fail `data_available_per_subquestion` [precheck] 两个子问题的数据源均未提供所需数据，且失败类型不同：①“保单 P002 的现金价值”——tools/0/result 信封为 {"ok":false,"status":"EMPTY","facts":[],"evidence":[],"hint":"未查询到该保单，请核对保单号","source":{"system":"policy_svc","endpoint":"/policy/full"},"request_id":"CALL-TR-...-01","error":null}，即对象未命中（保单不存在/保单号无法定位），目标保单的现金价值字段没有任何值返回；②“犹豫期内退保怎么办理”——
- not_applicable `object_version_timepoint`  本项检查的情形未发生：本轮没有任何一条命中数据可供核对对象/版本/数据时点。tools/0/result 与 tools/1/result、tools/4/result 的 facts、evidence、gaps 全部为空数组，既没有保单标识、也没有 as_of 时点或产品版本字段；最终 finalize（step_results/3）与 route.last_result 中 facts=[]、evidence=[]，答案也未给出任何保单金额或条款数值，因此不存在“拿别的保单/旧版本/过期时点数据冒充目标数据”的事实。需要说明的是，policy-query 技能纪律第 4 条要求“金额类答案
- fail `answer_facts_traceable`  答案中“未查询到保单 P002、需核对保单号”这一条可正面对应 tools/0/result 的 hint=“未查询到该保单，请核对保单号”，gaps 也如实记录了 EMPTY 与 UPSTREAM 两种未确认原因；但另有两类事实没有任何数据源返回可回溯：①流程知识断言——step_results/3 的答案写“犹豫期退保属于保全办理类操作，需经官方渠道申请(如金管家 App 或客服热线)，具体规则以保险公司现行规定为准”，而唯一被期望提供该知识的 qa_svc 两次返回 facts=[]、evidence=[]（tools/1/result、tools/4/result），这些内容实际只能追

</details>

<details><summary>model_capability 检查项</summary>

- pass `output_faithful_to_input`  Call0 输入为红线提示＋用户原句“请查询保单 P002 的现金价值，并告诉我犹豫期内退保怎么办理。”，输出 tool_calls 把两个子问题原义映射为 policy_detail{query:"保单 P002 的现金价值"} 与 general_qa{query:"犹豫期内退保怎么办理"}，实体号 P002 与字段“现金价值”未改义、未丢子问题。Call2 输入含 policy_detail 信封 status=EMPTY、hint=“未查询到该保单，请核对保单号”与 general_qa 信封 status=ERROR、hint=“后端服务暂时不可用”，输出 answer_draft 
- pass `tool_call_decisions_consistent`  Call0 时输入只有用户两问、无任何后端结果，模型同时发起 policy_detail 与 general_qa 两个数据调用，并按系统提示的 Progressive Discovery（“When a task matches a skill, call get_skill_instructions(skill_name) first”）加载 policy-query 与 general-qa 两份技能说明，属“有信息缺口时调用”，不存在已有结果仍重复或无缺口直接作答。Call1 的输入里 policy_detail 已返回 EMPTY（hint 要求核对保单号），模型未再为同一意图改写法
- fail `output_contract_followed`  结构面符合契约：messages/9 为 JSON，answer_draft 是第一个字段，含 fact_refs/gaps/needs_user_input/task_updates；复合问题按“能答多少先答多少”处理，needs_user_input=false 且未调 ask_clarify（保单号已给出，不满足“尚无可答事实且缺关键实体”的澄清条件）；answer_draft 与 gaps 未出现“工具返回/接口返回”或 EMPTY/BUDGET 等内部枚举，缺口按 L6 以“未能确认”披露。但 task_updates 第二条自述“犹豫期退保问答服务不可用(UPSTREAM ERRO

</details>

<details><summary>evaluation_standard 检查项</summary>

- pass `observable_with_available_evidence`  逐轴核对可得性：intent_understanding 要求“检查 gate、agent_input、可见任务或工具参数是否保留用户的对象、目标”，并写明“只有最终答案而无理解过程证据时 not_evaluable”——本 Trace 确有 gate 决策正文与 agent_input 原文（/records/run/step_results/1/content 记录 action=AGENT、matched_check=G-4a、reason“保单号已解析但残文未归约”），属可观察范围。tool_execution 写明“span OK 不代表工具返回成功或参数正确”“参数或结果脱敏无法判
- pass `no_hardcoded_truth_or_route`  路线未被硬编码：planning_routing 明确“简单保单查询允许 Direct；复合问题允许 Agent、并行调用或其他等价路线，不强制固定 Skill 数量与唯一执行顺序”，并把 problematic 限定在“遗漏必要子任务、在未消歧对象前执行依赖查询、反复无效调用”且“必须定位实际步骤”，未把某条具体路线设为唯一标准；本样本 gate 实际选择 AGENT 路线（/records/run/step_results/1/content）落在其允许集合内。数值/真值未被硬编码：knowledge_data 明确“业务数据按本次真实工具证据评，不把任一测试保单金额或产品等待期硬编码为通
- pass `clear_responsibility`  各轴检查对象有显式分工且互不反向：fulfillment 只看“输入和输出能证明的能力兑现”，并把“数值的外部真实性和内部过程另由有证据的过程轴核验”明确让出；tool_execution 的 summary 限定为“每次调用（含 Direct）自身是否正常执行、返回是否完整”；knowledge_data 限定为“数据源对每个子问题给了数据没有；对象/版本/时点对不对；答案事实可否回溯”；context_memory 限定为“结果投影、缓存复用、逐次模型输入与历史注入是否丢失或改义信息”；intent_understanding 管理解是否保留约束，model_capability 管“输入
- pass `gap_handling`  缺口与缺证被分开处理，且合理披露不被判失败：fulfillment 的 verdict_enum 单列“fulfilled_with_disclosed_gap：数据源未命中/报错，回答没拿到数据但如实说明了真实原因与下一步”，与 not_fulfilled 并列，说明“如实说明缺口”是合格出口；capability 写“条件不足应具体说明缺口或澄清，不得猜保单或编造数值”，boundary 写“信息缺失、真实下游不可用或对象不唯一时应如实说明缺口或澄清”，两处都把披露/澄清当作正当行为。缺证不被当作业务失败：六个过程轴的 verdict_enum 均含 not_evaluable，plann
- pass `coverage_of_scenario_goal`  对照 capability 与 boundary 逐项映射到轴：复合问题“不能漏答”由 fulfillment（逐条判 output_text 兑现）与 intent_understanding（“复合查询应覆盖所有子目标”）覆盖；“不得猜保单或编造数值”“对象不唯一应澄清”由 knowledge_data（对象/产品版本/数据时点、泛化规则不得冒充已核实条款）与 tool_execution（“区分参数错误、工具业务失败和合理错误处理”）覆盖；“真实下游不可用”的处理路径由 tool_execution 与 planning_routing（“失败分支与重试策略是否合理”）覆盖；“仅提供办理

</details>

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

## policy-with-data（1856s）

| 轴 | 预期(v3) | 实判 | 一致 | status | 汇总规则 / 一句话 |
|---|---|---|---|---|---|
| fulfillment | fulfilled_with_disclosed_gap | fulfilled_with_disclosed_gap | yes | succeeded |  fulfilled_with_disclosed_gap · Judge 判各 blocking 期望已兑现，但 F4 显示数据源有未命中/报错：direct:policy_svc/policy/full→对象/字段不存在或未命中；policy_search→对象/字段不存在或未命中 · fulfilled · 5 blocking expectations all met · 本次用户目标是查询保单 P260000000000001  |
| intent_understanding | sound | sound | yes | succeeded | all_applicable_pass 用户原文只有一个对象（保单号 P260000000000001）和一个目标字段（保单状态）。gate 的 route.decision 把对象解析为 policy_no=P260000000000001、字段解析为 fields=["policy_status"]，reason 明确写“显式保单号 P260000000000001 × 字段词典 ['policy_status'] × 完全解析”；agent_input 步骤把用户原句“ |
| planning_routing | sound | sound | yes | succeeded | all_applicable_pass 本轮用户问题是带显式保单号的单字段查询（“保单 P260000000000001 的保单状态是什么？”）。gate 依据 G-4a（显式保单号 × 字段词典 policy_status × 完全解析）选择 DIRECT_TOOL，resolved_args 与问题类型相称，实际路径 assemble→gate→to_direct(if 分支)→direct 与决策一致；Direct 返回 status=EMPTY（已命中保单、目标字段未 |
| tool_execution | sound | sound | yes | succeeded | all_applicable_pass 本轮工具执行范围内共 3 次调用（工作流直连 policy_svc /policy/full、agent 侧 get_skill_instructions、agent 侧 policy_search），逐条读取正文后未发现执行层问题：两次后端调用均正常返回且信封字段齐全（ok/status/facts/evidence/gaps/hint/source/request_id/latency_ms/error），error 与 error |
| context_memory | problematic | problematic | yes | succeeded | any_fail 本轴只覆盖可见的 agent_input/步骤 content、session_state 与两次已验证重建输入（token 校验 match）。Direct 调用结果投影到步骤 content 再拼进 agent_input 时，把信封里的 hint 整段丢掉：源结果含“已命中保单 P260000000000001，返回 3 条险种记录（服务报告 3 条）；接口未明确提供产品名称、保单状态……未生成保单级断言”，但 /records/ |
| knowledge_data | problematic | problematic | yes | succeeded | any_fail 本轴唯一的数据源 policy_svc（/policy/full）没有撑住子问题。用户只问一个事实：保单 P260000000000001 的保单状态。Direct 调用与 agent 的 policy_search 都返回 ok=false / status=EMPTY，facts=[]、evidence=[]，gaps 明确写“字段未返回:policy_status”“已命中保单 P260000000000001，但目标资料未提供， |
| model_capability | sound | problematic | **NO** | succeeded | any_fail 两次模型调用的输入均为 verified 重建（spans/1: messages/0+1，token 4648/4648；spans/4: messages/0..4，token 8549/8549），可逐跳对照。核心业务结论层面模型表现正常：没有把 EMPTY 说成保单不存在、没有编造保单状态值、缺口如实写入 gaps 且 needs_user_input=false。但定位到三个本轴问题：(1) call#0 在输入已声明“同保单 |

一致性：**consistent** — 结果 fulfilled_with_disclosed_gap，由 ['context_memory', 'knowledge_data', 'model_capability'] 解释

<details><summary>fulfillment 期望逐条</summary>

- fulfilled `返回保单状态或如实披露状态不可得` 用户能够获知本次无法确认保单状态的真实原因，不会被误导为状态已查询成功
- fulfilled `不编造保单状态或数值` 避免用户基于虚构状态作出错误决策
- fulfilled `具体说明无法确认状态的缺口` 用户能够区分未查询到状态与保单不存在或系统成功返回状态
- fulfilled `提供可行动下一步` 用户在无法直接获得状态时仍有可执行的核实路径
- fulfilled `保留输入对象与数据源数量事实` 保证回答针对用户指定保单，且数量事实不被改写
- fulfilled `不将咨询表述为已办理业务` 避免用户误以为系统已经执行退保、变更或其他业务操作
- fulfilled `交付结构化缺口信息` 下游消费者可以机读方式识别答案主体和缺口

</details>

<details><summary>intent_understanding 检查项</summary>

- pass `objects_and_fields_match`  用户原文为“保单 P260000000000001 的保单状态是什么？”（/records/run/run_input，29 字符完整）。gate 内部表达与之逐项一致：route.decision 的 resolved_args={"policy_no":"P260000000000001","fields":["policy_status"]}，reason=“显式保单号 P260000000000001 × 字段词典 ['policy_status'] × 完全解析”，与 /records/run/step_results/1/content 的 gate 输出同源同值；agent_in
- pass `subquestions_all_identified`  用户原文（/records/run/run_input）只含一个子问题：查该保单的“保单状态”，无并列或复合提问。该唯一子问题在三处内部表达中被分别识别：①gate 的 resolved_args.fields=["policy_status"] 与 reason 中的“字段词典 ['policy_status'] × 完全解析”（/records/run/step_executor_runs/0/session_state/route/decision）；②agent_input 任务表述保留完整问句并列出未完成项“字段未返回:policy_status”（/records/run/step
- not_applicable `constraints_kept`  用户原文“保单 P260000000000001 的保单状态是什么？”（/records/run/run_input）未给出时间范围、附加条件、比较关系、结果范围或显式输出格式要求，因此本项没有可被弱化或替换成默认口径的用户约束。可核对的是仅有的隐式限定（指定保单号、指定单一字段）在内部表达中未被放宽：route.decision 的 resolved_args 只带 policy_no 与 fields=["policy_status"]（/records/run/step_executor_runs/0/session_state/route/decision），agent_input 亦
- not_applicable `reference_resolution`  本样本为单轮，不存在“它/这个/上面那张”类跨轮指代需要解析：agent 侧用户消息 /records/run/step_executor_runs/0/messages/1/content 就是本轮原句本身，其 from_history=false，system 消息 from_history 也为 false，且采集事实显示本轮无同 session 历史 run（history_runs=0）。因此本项无触发情形，不据此加减分。
- not_applicable `ambiguity_handled`  用户问题已给出显式保单号与唯一目标字段，实体与意图均已锁定，不存在需要澄清的歧义或缺参情形：gate 判定为“完全解析”，resolved_args 两项齐全、candidates_for_agent=[]（/records/run/step_executor_runs/0/session_state/route/decision）。系统也没有做多余澄清：agent 首批调用为 get_skill_instructions 与 policy_search（/records/run/step_executor_runs/0/messages/2/tool_calls），未出现 ask_clari

</details>

<details><summary>planning_routing 检查项</summary>

- pass `route_choice_justified`  用户原文只有一个子问题且保单号显式：/records/run/run_input 为“保单 P260000000000001 的保单状态是什么？”。/records/run/step_results/1/content 显示 gate 决策 action=DIRECT_TOOL、matched_check=G-4a、capability_id=null、resolved_args={policy_no:P260000000000001, fields:[policy_status]}、reason=“显式保单号 P260000000000001 × 字段词典 ['policy_status']
- pass `work_coverage`  唯一子问题“P260000000000001 的保单状态”有对应取数调用：/records/run/step_executor_runs/0/session_state/budget/direct_tool_results/{"fields":["policy_status"],"policy_no":"P260000000000001"} 是对 policy_svc /policy/full 的定向取字段调用，参数即目标保单与目标字段；未命中后 /records/run/step_executor_runs/0/tools/1/tool_args 显示 agent 改以 policy_sea
- pass `failure_branch_productive`  Direct 的 status=EMPTY（/records/run/step_results/2/steps/0/content 的 gaps=[“字段未返回:policy_status”“已命中保单 P260000000000001，但目标资料未提供，未完成目标字段查询”]）之后，分支有实质动作而非空转：facts.failure_followups 记录 then=[read_skill:get_skill_instructions, switched_tool:policy_search]、ended_with=escalated_to_agent，对应 /records/run/st
- not_applicable `retry_policy`  本项前置由采集事实判定为未触发：facts.cache.repeats 与 failure_replays 均为空，即不存在同名同参的重复调用；/records/run/step_executor_runs/0/session_state/budget 相关计数显示 backend_retries=0、deduplicated_tool_calls=1，说明系统未做后端级重试。两次取数分别是不同入口（direct:policy_svc/policy/full 与 policy_search），后者 /records/run/step_executor_runs/0/tools/1/metric
- pass `sensible_termination`  收尾发生在必要工作已做完之后：/records/run/step_results/1/content 的 Direct 决策、/records/run/step_results/2/steps/0/content 的定向取字段、/records/run/step_executor_runs/0/tools/0/result 与 /records/run/step_executor_runs/0/tools/1/result 的 skill 读取与换工具补查，均已覆盖“保单状态”这一唯一子问题，之后才进入 finalize。缺口被如实标记而非掩盖：/records/run/content 的 g

</details>

<details><summary>tool_execution 检查项</summary>

- pass `calls_executed_without_error`  三次调用均执行完成、无报错或超时：Direct 调用返回的信封正文中 error 为 null、status 为 EMPTY（业务未命中而非执行异常），其步骤 span 记录 status=OK、duration 1.36s；agent 侧 policy_search 的持久化 result 同样 error:null，且 tool_call_error 记录为 false；get_skill_instructions 的 tool_call_error 也为 false，result 正常返回 skill 说明 JSON。health 事实显示 policy_svc 两次调用 error=0
- pass `result_shape_complete`  两次 policy_svc 调用的信封字段齐全且与参数相符：result 正文含 ok、status、facts、evidence、gaps、hint、source.system=policy_svc、source.endpoint=/policy/full、request_id、latency_ms=1359、error 全部字段，未出现半截 JSON 或缺字段；hint 明确写“已命中保单 P260000000000001，返回 3 条险种记录（服务报告 3 条）”，与 Direct 参数 policy_no=P260000000000001 及 policy_search 参数 quer
- pass `latency_acceptable`  三次调用耗时均有记录且在正常量级：Direct 调用的 raw span duration_ms=1360（span 自身记 1.36s，start 14:49:52.344200Z、end 14:49:53.704642Z，信封 latency_ms=1359 与之吻合），get_skill_instructions 的 metrics duration=0.00841s（约 8ms），policy_search 的 metrics duration=0.00642s（约 6ms，其 span 记 3ms，因后端结果被去重复用）；三者都远低于超时阈值，无异常慢调用。整轮 24980ms 与 
- pass `non_envelope_results_usable`  本轮唯一的非信封调用 get_skill_instructions（参数 skill_name=“policy-query”）返回内容可用：result 正文共 6197 字符，已完整读取，含 skill_name、description、instructions（职责边界、工具白名单、领域纪律 1–6、工作流、输出结构、正反例，末尾以“反例：……越权探测，禁止。”正常收尾，无中途截断）以及 available_scripts、available_references 两个空数组，是预期的 skill 说明文本而非错误页或空串。附带说明：session_state 的 tool_metrics

</details>

<details><summary>context_memory 检查项</summary>

- fail `projection_keeps_result_fields` [precheck] Direct 结果 /records/run/step_executor_runs/0/session_state/budget/direct_tool_results 中键 {"fields":["policy_status"],"policy_no":"P260000000000001"} 的信封完整含 hint（“已命中保单 P260000000000001，返回 3 条险种记录（服务报告 3 条）；目标资料未提供，未完成目标字段查询；接口未明确提供产品名称、保单状态、当前保费、现金价值、币种和业务时点；原始金额及累计值不作为当前金额事实；insured_name 未完整提供、存在冲突或
- not_applicable `cache_reuse_valid` [precheck] 本轮没有同名同参重复调用，缓存没有被命中的机会（Judge 原判 pass：cache.repeats 为空、failure_replays 为空，即没有同名同参调用回放上一次结果的情形；本轮实际发生的复用是跨名去重：session_state/budget/backend_rpc_calls=1、deduplicated_tool_calls=1，说明 agent 的 policy_search（arguments {"query":"保单 P260000000000001 的保单状态"}）没有新打后端，而是拿到 Direct 的同一次结果。该复用对象一致（同一保单 P26000000000
- pass `per_call_context_has_goal`  两次模型调用的 reconstructed_input 均为 verified 且 token 校验 match（spans/1：message_input_tokens=4648=span_input_tokens；spans/4：8549=8549），可据其 message_refs 判断输入消息。首调（spans/1，message_refs=messages/0、messages/1）：messages/0 是常驻红线与输出契约（含“缺口必披露”“EMPTY 不为同一意图反复猜别名重试”“answer_draft/gaps 不得出现内部状态枚举”等约束与 skills 列表，已完整读完
- not_applicable `history_injected_faithfully`  本样本为单轮：business_trace_facts.scope.turn 为 history_runs=0、multi_turn=false，collection 的 history 状态为 empty（count=0），且可见消息 messages/0、messages/1、messages/2、messages/3、messages/5 的 from_history 均为 false，session_state/evidence/by_turn 只有本轮 trace_id TR-862ead18b2b4485e8c668145fd32f9b8 一个键，route.last_result
- pass `no_contamination`  可见上下文里出现的业务对象只有本用户本轮询问的保单：user message（messages/1/content）与 agent_input（step_results/3/steps/0）均为保单 P260000000000001 的 policy_status；Direct 结果键、tool_result_cache、direct_policy_attempts 的键也都是同一保单号；policy_search 参数为“保单 P260000000000001 的保单状态”（messages/2/tool_calls）。session_state 中 ledger={}、entities={

</details>

<details><summary>knowledge_data 检查项</summary>

- fail `data_available_per_subquestion` [precheck] 子问题“保单 P260000000000001 的保单状态”需要的字段值未从数据源获得。Direct 调用 direct:policy_svc/policy/full {"fields":["policy_status"],"policy_no":"P260000000000001"} 的结果信封为 {"ok":false,"status":"EMPTY","facts":[],"evidence":[],"gaps":["字段未返回:policy_status","已命中保单 P260000000000001，但目标资料未提供，未完成目标字段查询"]}，hint 明确“接口未明确提供产品名称
- insufficient_evidence `object_version_timepoint`  命中内容只带对象标识（hint 中“已命中保单 P260000000000001，返回 3 条险种记录”，与用户显式保单号一致），但两次 EMPTY 结果信封中均无版本、数据时点（as_of）或适用条件字段，facts=[] 也没有任何带时点的值可比对；hint 自身声明“接口未明确提供……业务时点”。因此无法判断命中数据是否对应正确版本/时点，也不得据此推断为最新数据。policy-query 技能纪律第 4 条要求“金额类答案必须带数据时点(as_of)”，但本次根本没有可用于核对时点的返回值。
- pass `answer_facts_traceable`  最终答案（finalize 输出与 assistant 终稿）陈述的数据事实均可回溯到工具返回：①“已定位到保单 P260000000000001（该保单下有 3 条险种记录）”对应 policy_search/Direct 结果 hint 的“已命中保单 P260000000000001，返回 3 条险种记录（服务报告 3 条）”；②“「保单状态」这一项资料当前未能从系统查询到，暂时无法确认该保单的准确状态”对应 gaps[0]“字段未返回:policy_status”与 gaps[1]“目标资料未提供，未完成目标字段查询”；③答案未给出任何保单状态值、金额或条款内容，fact_refs=[

</details>

<details><summary>model_capability 检查项</summary>

- insufficient_evidence `output_faithful_to_input` [unread_evidence_refs] fail 引用了未读取正文的 ref: ['/records/run/step_executor_runs/0/messages/4']（Judge 原判 fail：call#0 输出只有工具调用：get_skill_instructions(“policy-query”) 与 policy_search(query=“保单 P2600000000001 的保单状态”，实为 P260000000000001) 的保单号与字段与 messages/1 的用户原问及已查询参数 {"policy_no":"P260000000000001","fields":["policy_status"]} 逐
- fail `tool_call_decisions_consistent`  输入已有确定结果仍换名重复检索：messages/1（= /records/run/step_results/3/steps/0 的内容）已把 Direct 结果交给模型——“状态=EMPTY;已查询参数={policy_no:P260000000000001,fields:[policy_status]};未完成项=[字段未返回:policy_status, 已命中保单 P260000000000001，但目标资料未提供，未完成目标字段查询]。相同保单与相同字段的 policy_detail 结果已经确定，不要再次请求后端；可使用其他能力补充，否则把未完成项写入 gaps。”messages
- fail `output_contract_followed`  格式与字段面符合：messages/5 为 JSON 且 answer_draft 是第一个字段，含契约要求的 answer_draft/fact_refs/gaps/needs_user_input/task_updates 五字段；fact_refs=[] 与证据池 facts=[]（messages/4 的 "facts":[]）一致，未虚构 fact_id；needs_user_input=false 且未调 ask_clarify，符合“本轮取得可用事实时先答已确认部分、未完成项写 gaps”；gaps 用业务语言“保单 P260000000000001 的保单状态字段未返回，当前无

</details>

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
