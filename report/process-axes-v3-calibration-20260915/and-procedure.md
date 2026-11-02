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
