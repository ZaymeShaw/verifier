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
