# 盲测问题清单 pass2（89 条，已打乱，不含臂标签）

## Q01  case=smoke-customer-profile-fuyunping
- 主张：工具 customer_detail 第一次调用执行失败报错，未返回客户详情及出生年月数据。
- 观察：工具 customer_detail 第一次调用执行失败，返回错误状态 ERROR 及错误提示。
对接的工具 customer_detail 执行报错，未正常完成调用。
工具 customer_detail 调用执行失败，未能获取客户伏云平的出生年月。
工具 customer_detail 执行失败，未返回客户伏云平的出生年月结果。
工具 customer_detail 执行报错，未返回请求的客户详情及出生年月数据。
- 证据：turn1/records/run/step_executor_runs/0/tools/1
- 归属（模型自述）：local

## Q02  case=smoke-customer-profile-fuyunping
- 主张：agent_bridge 函数步骤在解析 Agent 输出并向后传递时，注入了前序工具投影结果与模型输出中均未记录的客户年龄与手机号信息（33岁·手机19909224628），改动了 answer_draft 内容并导致 session 产生 citation_anomaly。
- 观察：agent_bridge 函数步骤在解析 Agent 输出并向后传递时，注入了前序工具投影结果与模型输出中均未记录的客户年龄与手机号信息（33岁·手机19909224628），改动了 answer_draft 内容并导致 session 产生 citation_anomaly。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/session
- 归属（模型自述）：local

## Q03  case=smoke-customer-profile-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q04  case=main-A01-fuyunping-list-aggprem
- 主张：模型第三次调用的输出未遵循系统提示词关于输出纯 JSON 及 claims 渲染的协议，未输出 claims 字段，并在 answer_draft 中自行填充了金额、状态和姓名。
- 观察：模型在第三次调用输出中输出了大段前置自由文本与 Markdown 代码块，且在代码块内的 JSON 中完全缺少 claims 字段，并在 answer_draft 中直接硬编码了金额 1320.0、6300.0、保单状态“到期终止”“交费有效”及姓名“伏云平”。
- 证据：turn1/records/run/step_executor_runs/0/messages/6, turn1/records/traces/0/tree/0/spans/3/spans/6
- 归属（模型自述）：local

## Q05  case=main-A01-fuyunping-list-aggprem
- 主张：第 3 次模型调用在输出契约 JSON 之外包裹了多余的自由文本与 markdown 代码块标记，未能严格以 answer_draft 首字段纯 JSON 返回
- 观察：模型输出格式未能完全遵循系统提示词中“输出 JSON：answer_draft:string 必须是首字段”的纯 JSON 契约要求，增加了下游解析处理负担
- 证据：exp-6-json-output-contract, turn1/records/run/step_executor_runs/0/messages/6, turn1/records/traces/0/tree/0/spans/3/spans/6
- 归属（模型自述）：本轴

## Q06  case=main-A01-fuyunping-list-aggprem
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q07  case=main-B01-meeting-prep-fuyunping
- 主张：编排的 finalize 收尾整合环节未能将模型构思好的三个开场问题交付到最终 answer 中，用户诉求中的核心交付物缺失。
- 观察：用户提出的开场问题准备诉求未能在最终回答中完成交付。
- 证据：exp_plan_integration_and_delivery, turn1/records/run/content, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## Q08  case=main-D01-same-surname-clarify
- 主张：初始步骤产出仅为 assembled，首个工具调用参数遗漏了我名下归属范围限定及按客户号升序排列的输出约束。
- 观察：首个步骤 assemble 输出仅为 assembled，首个工具调用 customer_search 参数仅包含姓名、生日、性别及客户号字段，遗漏了用户明确说明的我名下归属范围对象。
用户给出了我名下范围约束与按客户号升序输出约束，首批工具调用参数未包含我名下限定，亦未对排序约束做内部结构化保留。
针对查找名下姓平、12月生日女性客户的期望，内部表达遗漏了我名下归属限定与客户号升序要求，未完整表达用户期望。
首批工具参数仅保留姓名、生日、性别及客户号，未能完整表达我名下归属对象范围。
对查找名下符合条件客户的期望，工具参数弱化了我名下与排序约束。
首批工具参数丢失了我名下限定，且未对按客户号升序这一输出要求予以内部保留。
- 证据：turn1/records/run, turn1/records/run/step_results/0
- 归属（模型自述）：local

## Q09  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/3, 程序-工具返回-3
- 归属（模型自述）：本轴

## Q10  case=smoke-multi-policy-anjinning
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：个别保单被保人姓名未完整返回，如需可进一步查询单张保单详情
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q11  case=smoke-multi-policy-anjinning
- 主张：模型回复在输出规定的 JSON 结构体之前，前置输出了大段 Markdown 表格与自然语言文本，未遵守“answer_draft:string 必须是首字段”的纯 JSON 输出契约要求。
- 观察：可能导致下游依赖严格 JSON 解析的渲染或状态机组件解析失败或需额外降级容错。
- 证据：exp_t1_call2_output_contract, turn1/records/run/step_executor_runs/0/messages/3
- 归属（模型自述）：本轴

## Q12  case=smoke-policy-list-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：该客户名下有多张保单，请选择要查询的保单：
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q13  case=smoke-agg-paid-prem-fuyunping
- 主张：步骤 agent_bridge 在转换上游 agent 输出时，丢弃了模型已查得的保单 P260922000011415 累计已交保费 1320，错误替换为年缴保费 0.00 并重渲染文本，导致关键业务事实被篡改。
- 观察：步骤 agent（step_results/2/steps/1）输出中明确给出了保单 P260922000011415 的累计已交保费为 1320 及 P260922000011416 为 6300，但在经由 agent_bridge 转换至 step_results/2/steps/2 时，关键事实被篡改，保单 P260922000011415 的保费被改为 0.00，事实引用也被替换为 year_pay_prem，发生了关键事实丢失与改义。
- 证据：content#13, content#39, turn1.final_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/traces/0/tree/0/spans/4
- 归属（模型自述）：local

## Q14  case=main-D01-same-surname-clarify
- 主张：首批内部表达与工具调用仅涵盖第一阶段筛选，未识别、对应并保留确定选中客户后查询详细资料与保单状态的后续子问题与多阶段期望。
- 观察：用户输入包含查找客户供选与确定后查询详情及保单状态的多阶段子问题，首个内部步骤及工具调用仅表达了客户筛选，未在内部表达中对应并保留后续查询子问题。
首个步骤 assemble 仅输出 assembled，未建立对名下客户查找期望的完整内部表达结构。
内部表达未将查找并排序供选择作为一个独立的阶段性子任务进行结构化保留。
期望中关于名下客户查找的内部表达存在对象与约束遗漏。
名下客户筛选期望在首批内部表达中未能完整保留关键约束。
系统在首个步骤与首个工具调用中完全未表达确定后查询选中客户详细资料的期望。
详细资料查询涉及的对象与字段在首批内部表达中完全缺失。
内部表达未包含查询详细资料这一后续期望意图。
用户明确提出的确定后再查详细资料子问题未在内部表达中对应保留。
确定选中客户后再查详情的条件约束未在内部表达中体现。
确定后这一执行前置条件及范围约束未在系统内部任务表达中保留。
查询详细资料的期望在系统内部表达中未被识别与建立。
查询详细资料期望未在首批内部表达中呈现。
系统在首个步骤与首个工具调用中完全未表达确定后查询保单状态的期望。
保单状态对象与字段在首批内部表达中完全遗漏。
内部表达未建立查询保单状态这一阶段性期望。
用户明确提出的确定后再查保单状态子问题在内部表达中无对应保留。
保单状态查询期望及其前置条件未在内部表达中体现。
确定后再查的前置条件与范围约束未在内部表达中
- 证据：turn1/records/run, turn1/records/run/step_results/0
- 归属（模型自述）：local

## Q15  case=main-D01-same-surname-clarify
- 主张：系统向检索工具转换查询条件时，遗漏了“我名下”（当前用户归属）这一核心约束条件。
- 观察：导致客户检索范围脱离当前用户管辖，可能查出非名下客户或扩大数据范围。
- 证据：exp_filter_constraints, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## Q16  case=main-D01-same-surname-clarify
- 主张：ask_clarify 工具执行返回时产生系统级错误标识（tool_call_error 为 true，span status 为 ERROR）
- 观察：导致澄清工具调用在链路监控中被标记为执行失败/异常，未能以正常的无错状态完成挂起注册
- 证据：tool_exec_tools_4_no_error, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/traces/0/tree/0/spans/3/spans/10
- 归属（模型自述）：本轴

## Q17  case=smoke-customer-profile-fuyunping
- 主张：customer_detail 工具在两次接收客户 ID 查询详情时均发生执行异常（tool_call_error=true，status=ERROR），未能返回目标客户详情数据。
- 观察：导致下游无法获取客户伏云平的生日等详情信息，直接影响出生年月的回答。
- 证据：exp_tool_detail_call_1_match, exp_tool_detail_call_1_no_error, exp_tool_detail_call_2_match, exp_tool_detail_call_2_no_error, turn1/records/run/step_executor_runs/0/tools/1/result, turn1/records/run/step_executor_runs/0/tools/1/tool_call_error, turn1/records/run/step_executor_runs/0/tools/2/result, turn1/records/run/step_executor_runs/0/tools/2/tool_call_error
- 归属（模型自述）：本轴

## Q18  case=main-A01-fuyunping-list-aggprem
- 主张：在 agent_bridge 步骤中，系统未采纳下游步骤产出的累计已交保费事实（agg_paid_prem 1320.0），而是错误绑定年缴保费字段（year_pay_prem 0），导致保单 P260922000011415 的保费金额在交付给 finalize 及用户时被篡改为 0.00。
- 观察：最终交付给用户的答案中存在错误的保费金额（0.00 代替 1320.0），无法满足用户获取各保单真实累计已交保费的需求。
- 证据：exp-context-delivery-faithful, exp-context-tool-accumulated-premium, turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## Q19  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/2, 程序-工具返回-2
- 归属（模型自述）：本轴

## Q20  case=smoke-multi-policy-anjinning
- 主张：policy_search 查得6张保单，但在写入会话状态的 facts 与集合时仅记录了前5张，遗漏了第6张保单 P260922000007861。
- 观察：工具 policy_search 实际查得6张不同保单，但系统在存入会话状态的 facts、last_policy_set 和 card 时仅写入了前5张保单，遗漏了第6张保单 P260922000007861。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_results/2/steps/2, turn1/records/session, turn1/records/traces/0/tree/0/spans/3/spans/2
- 归属（模型自述）：local

## Q21  case=main-A01-fuyunping-list-aggprem
- 主张：finalize 步骤直接透传了上游 agent_bridge 篡改后的错误保费数值（保费:0.00），未能交付正确的累计已交保费。
- 观察：用户最终接收到的答案中保单 P260922000011415 的保费错误地展示为 0.00。
- 证据：exp_delivery_keep_original_meaning, turn1.delivered_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：上游:context_memory

## Q22  case=smoke-multi-policy-anjinning
- 主张：会话状态更新时，entities.last_policy_set、turns[0].answer_refs 及 card 仅写入了前 5 张保单标识，与实际检索出的 6 张保单不一致，丢失了 P260922000007861。
- 观察：会话状态中的最近保单集合与卡片引用产生事实偏差，后续多轮对话若基于 last_policy_set 或 card 继承上下文将丢失该保单。
- 证据：exp_session_state_policy_set_consistency, shared#45, shared#82, turn1/records/session
- 归属（模型自述）：本轴

## Q23  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q24  case=smoke-policy-detail-renyanlin
- 主张：模型输出包含自然语言前置文本，未遵循纯 JSON 首字段格式，且未按 claims 契约要求声明业务事实，直接在 answer_draft 中填充了姓名和保单状态。
- 观察：模型在输出中先生成了多段 Markdown 文本，随后给出的 JSON 缺失了 claims 字段，并在 answer_draft 中直接填充了姓名“任言琳”与保单状态“交费有效”。
- 证据：turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：local

## Q25  case=main-D01-same-surname-clarify
- 主张：customer_search 第 4 次调用被预算保护机制（BUDGET）拦截并报错，未执行实际查询。
- 观察：因连续未取得新信息而触发 BUDGET 熔断，彻底阻断了后续检索尝试。
- 证据：exp-tool3-no-error, turn1/records/run/step_executor_runs/0/tools/3/result
- 归属（模型自述）：上游:planning_routing

## Q26  case=main-B01-meeting-prep-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q27  case=smoke-customer-profile-fuyunping
- 主张：工具 customer_detail 第二次调用执行失败报错，未能获取相关信息。
- 观察：工具 customer_detail 第二次调用执行失败，返回错误状态 ERROR 及错误提示。
- 证据：turn1/records/run/step_executor_runs/0/tools/2
- 归属（模型自述）：local

## Q28  case=smoke-multi-policy-anjinning
- 主张：agent_bridge 步骤在结构化处理 agent 产出并向 finalize 传递时，采用模板渲染仅提取前 5 条 facts 并覆盖草稿，遗漏了查得的第 6 张保单 P260922000007861。
- 观察：下游 finalize 与最终用户收到的保单清单中缺失平安e生保（加享版）医疗保险（P260922000007861），信息不完整。
- 证据：exp_agent_bridge_facts_retention, shared#6, shared#8, turn1/records/run/step_results/2/steps/2, turn1/records/traces/0/tree/0/spans/4
- 归属（模型自述）：本轴

## Q29  case=smoke-agg-paid-prem-fuyunping
- 主张：最终交付给调用方的回答中，保单 P260922000011415 的累计已交保费被错误展示为 0.00，未能如实交付工具查询到的累计已交保费 1320.00。
- 观察：最终交付给调用方的内容中，保单 P260922000011415 的保费被错误展示为 0.00，未能如实告知该保单查询到的累计已交保费 1320.00。
交付给调用方的内容中关键事实发生改义与失真，保单 P260922000011415 的累计已交保费 1320.00 被替换为 0.00，关键业务事实未完好交付。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## Q30  case=smoke-policy-detail-renyanlin
- 主张：模型调用输出未遵守系统提示词约定的“输出 JSON 且 answer_draft 必须是首字段”规范，先生成了 Markdown 自然语言回复，后在尾部附带 JSON 对象
- 观察：输出不符合单一 JSON 格式定义，给下游解析或确定性渲染造成格式解析阻碍
- 证据：exp_call2_output_contract, turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：本轴

## Q31  case=smoke-policy-detail-renyanlin
- 主张：agent_bridge 函数步骤在 agent 模型输出无缺口的情况下，自行注入了缺口信息“部分内容未能在本轮证据中对应，请结合原始资料核实。”并标记 status 为 PARTIAL，透传至 finalize 及最终交付结果中。
- 观察：使交付内容中带有不符合实际取数情况的缺口与局限提示，降低了回答的确定性与完整性表象。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, unexp_bridge_synthetic_gaps
- 归属（模型自述）：本轴

## Q32  case=main-D01-same-surname-clarify
- 主张：在调用参数明确设置 tool_choice 为 none 的情况下，模型在 span 7 和 span 9 中均无视该强制约束，违规生成了工具调用（span 7 发起 customer_search，span 9 发起 ask_clarify），未直接按要求输出文本/JSON 格式收尾响应。
- 观察：导致系统在强制要求结束工具交互、进行结果收尾时无法按预期获得文本输出，甚至引发不合时宜的额外工具调用或澄清中断。
- 证据：exp_span7_tool_choice_none, exp_span9_tool_choice_none, shared#48, shared#58, turn1/records/traces/0/tree/0/spans/3/spans/7, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴

## Q33  case=main-D01-same-surname-clarify
- 主张：[程序判定] 执行余量提示随用量更新：7 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/7, turn1/records/traces/0/tree/0/spans/3/spans/9, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q34  case=smoke-customer-profile-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 597 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/7, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q35  case=smoke-multi-policy-anjinning
- 主张：用户明确要求只列出安锦宁名下的保单清单，满足单独调用 present_policy_search_card 的规则条件，但模型调用了 policy_search 并追加查询多个字段。
- 观察：用户明确要求“安锦宁名下有哪些保单？先列清单就行。”，目标明确且自足，模型违规调用了 policy_search 并主动追加查询多个字段。
- 证据：turn1/records/run/step_executor_runs/0/messages/1, turn1/records/traces/0/tree/0/spans/3/spans/1
- 归属（模型自述）：local

## Q36  case=smoke-customer-profile-fuyunping
- 主张：agent_bridge 在组装阶段向答案草稿注入未经模型引用的客户摘要事实（33岁、手机号），引发引用异常并在 gaps/limitations 中产生未对应证据的局限声明。
- 观察：最终交付答案中额外包含了未经模型显式认领的客户属性字段，并伴随产生合规核实警告文本。
- 证据：turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/session, unexp_agent_bridge_injected_facts
- 归属（模型自述）：本轴

## Q37  case=smoke-policy-detail-renyanlin
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q38  case=main-B01-meeting-prep-fuyunping
- 主张：用户明确要求基于客户资料和已有保单准备三个开场问题，系统虽完成客户和保单查询，但最终答复中完全缺失开场问题内容。
- 观察：整轮路径执行收尾时未输出用户明确要求的三个开场问题，子需求工作覆盖不完整。
最终答复内容仅展示了客户与保单摘要及条款参考，未提供为会面准备的三个开场问题。
准备开场问题的子需求未在整轮执行产出中覆盖交付。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_executor_runs/0/tools/5, turn1/records/run/step_results/0
- 归属（模型自述）：local

## Q39  case=smoke-agg-paid-prem-fuyunping
- 主张：agent_bridge 将 agent 输出中保单 P260922000011415 的累计已交保费 1320 篡改替换为 0.00，发生严重数值改义与混淆。
- 观察：最终交付给用户的保单保费数值被错误改写为 0.00，导致回答错误。
- 证据：exp_1, turn1.final_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2
- 归属（模型自述）：本轴

## Q40  case=smoke-agg-paid-prem-fuyunping
- 主张：agent_bridge 遗漏了 agent 显式引用的累计已交保费事实 ID，错误替换为年缴保费及摘要事实 ID。
- 观察：破坏了事实引用的可溯源性与一致性，导致上下文引用的事实对象发生错位。
- 证据：exp_2, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2
- 归属（模型自述）：本轴

## Q41  case=smoke-agg-paid-prem-fuyunping
- 主张：在工具 policy_detail 成功返回两张保单累计已交保费（1320 与 6300）后，编排收尾步骤 agent_bridge 与 finalize 未整合交付该事实，而是降级触发模板渲染并输出错误的年缴保费（0.00 与 6300.00）及保单摘要，且声称证据未对应。
- 观察：工具 policy_detail 已成功返回两张保单累计已交保费 agg_paid_prem 分别为 1320 和 6300，但系统编排在 agent_bridge 及 finalize 收尾环节剥夺了交付该事实的机会，将其替换为模板渲染出的 year_pay_prem（保费 0.00 与 6300.00）及保单摘要，未向用户交付所查保单的累计已交保费。
流程在工具已获取完整业务事实后收尾，但系统确定性收尾步骤（agent_bridge 与 finalize）未能将已有的累计已交保费整合进最终答复，反而改写为无关的年缴保费并降级为 PARTIAL 且声称部分内容未能在证据中对应。
系统在工具调用后未能将伏云平每张保单的累计已交保费交付给用户，最终输出被 agent_bridge 替换为保单摘要及年缴保费。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_results/0, turn1/records/run/step_results/1, turn1/records/run/step_results/2
- 归属（模型自述）：local

## Q42  case=main-A01-fuyunping-list-aggprem
- 主张：agent_bridge 步骤在处理和向下游传递事实时，把保单 P260922000011415 的累计已交保费（1320.0）错误替换为年缴保费（0），生成并传递了错误的 facts 和 answer_draft。
- 观察：保单 P260922000011415 的累计已交保费被篡改为 0.00，导致最终向用户交付的保单保费数据失真。
- 证据：exp_metric_semantic_preservation, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2
- 归属（模型自述）：本轴

## Q43  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/0, 程序-工具返回-0
- 归属（模型自述）：本轴

## Q44  case=main-A01-fuyunping-list-aggprem
- 主张：Agent 在 step_results/2/steps/1 产出的草稿已正确整合每张保单的累计已交保费（1320.0 与 6300.0），但后续编排执行的 finalize 步骤在整合交付时将最终 answer 覆盖为保费 0.00 与 6,300.00（取成了年缴保费），破坏了可用事实向用户的准确交付。
- 观察：Agent 在 step_results/2/steps/1 产出的草稿已正确整合每张保单的累计已交保费（1320.0 与 6300.0），但后续编排执行的 finalize 步骤在整合交付时将最终 answer 覆盖为保费 0.00 与 6,300.00（取成了年缴保费），破坏了可用事实向用户的准确交付。
- 证据：turn1.final_output, turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_results/0, turn1/records/run/step_results/1, turn1/records/run/step_results/2
- 归属（模型自述）：local

## Q45  case=main-B01-meeting-prep-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：8 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/10, turn1/records/traces/0/tree/0/spans/3/spans/12, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/6, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：本轴

## Q46  case=main-B01-meeting-prep-fuyunping
- 主张：在已有完整客户详情的情况下，编排调用序列中无依据地二次调用了 customer_detail 查询已获得的 clientNo 字段。
- 观察：增加了不必要的工具调用开销，打乱了收尾流程节奏。
- 证据：exp_plan_avoid_redundant_detail_call, turn1/records/run/step_executor_runs/0/messages/8, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/4
- 归属（模型自述）：本轴

## Q47  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/4, 程序-工具返回-4
- 归属（模型自述）：本轴

## Q48  case=main-D01-same-surname-clarify
- 主张：customer_search 返回 AMBIGUOUS 无法解析条件后，系统未及时终止或澄清，而是连续改写 query 盲目重试 4 次，最终触发系统 BUDGET 拦截
- 观察：浪费模型调用额度与工具预算，增加了轮次延迟，并因反复失败触发了系统防御性拦截
- 证据：exp-no-blind-retry, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3
- 归属（模型自述）：本轴

## Q49  case=smoke-agg-paid-prem-fuyunping
- 主张：系统为历次模型调用组装的系统提示词中存在两套冲突的格式约束：前段要求输出五字段 JSON 且金额在 answer_draft 呈现，末段又要求使用 claims 格式声明并禁止在 answer_draft 中填写金额和状态。
- 观察：系统组装给模型的系统提示词前段规定输出仅含 answer_draft、fact_refs、gaps、needs_user_input、task_updates 的 JSON 且金额在 answer_draft 中表达，末段又规定业务回答契约须使用 claims 声明且禁止在 answer_draft 填写金额或状态，输出格式要求存在前后冲突。
系统组装的系统提示词前段五字段输出要求与末段 claims 声明契约并存，且对 answer_draft 是否填写金额给出相互矛盾的指令，格式要求存在前后冲突。
系统组装的系统提示词前段五字段规范与末段 claims 契约冲突，关于 answer_draft 是否自行填写金额与状态的约束前后矛盾。
系统在收尾调用前组装的系统提示词中，前段五字段规范与末段 claims 契约要求持续冲突，存在前后自相矛盾的输出格式约束。
- 证据：turn1/records/run/step_executor_runs/0, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：local

## Q50  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/1, 程序-工具返回-1
- 归属（模型自述）：本轴

## Q51  case=smoke-policy-list-fuyunping
- 主张：在所需保单信息已全部通过 policy_search 和 policy_detail 获取充分后，编排流程未及时结束工具调用，而是多余触发了 run_policy_field_lookup 查询伏云平名下所有保单，导致工具返回 NEEDS_CLARIFICATION 报错并将冗余澄清提示混入最终交付结果中。
- 观察：造成额外的工具耗时与模型调用开销（工具耗时增加约 8.5 秒），且使最终交付结果中附带了不必要的“该客户名下有多张保单，请选择要查询的保单：”冗余澄清内容。
- 证据：exp-4, turn1/records/run/step_results/3/content, turn1/records/traces/0/tree/0/spans/3/spans/8, turn1/records/traces/0/tree/0/spans/3/spans/9, unexp-1
- 归属（模型自述）：本轴

## Q52  case=smoke-agg-paid-prem-fuyunping
- 主张：上下文在 agent_bridge 至 finalize 传递阶段发生指标混淆与数值篡改，将“累计已交保费”混淆为“年缴保费”，导致保单 P260922000011415 累计已交保费 1320 被改写为 0.00。
- 观察：导致下游 finalize 接收到被篡改的事实数据，生成错误的回答内容并误导用户。
- 证据：exp-agent-to-finalize-transmission, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## Q53  case=smoke-agg-paid-prem-fuyunping
- 主张：最终向用户交付的文本中累计已交保费数据严重失真，保单 P260922000011415 的保费被错误展示为 0.00。
- 观察：用户获取到错误的保费信息，业务回答准确性受损。
- 证据：exp-delivered-output-fidelity, turn1.delivered_output, turn1/records/run/step_results/3
- 归属（模型自述）：上游:context_memory

## Q54  case=smoke-multi-policy-anjinning
- 主张：步骤 agent_bridge 向 finalize 传递输出时，输入端 output 包含 6 条业务证据项，但终结交付输出中 sources 字段为空列表，导致全部证据溯源信息丢失。
- 观察：上游步骤 agent_bridge 输出中明确包含 6 条证据项（evidence），但在传递至 finalize 及最终交付输出时，sources 被置为空列表，输入端所承载的全部证据溯源事实均被丢弃，未原义到达交付端。
- 证据：turn1.final_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5
- 归属（模型自述）：local

## Q55  case=smoke-policy-list-fuyunping
- 主张：保单查询与详情获取已完整完成，收尾环节却将冗余调用返回的 NEEDS_CLARIFICATION 作为缺口写入 gaps，并在最终答复末尾向用户发起不必要的澄清要求。
- 观察：伏云平保单查询的必要工作已在前序步骤全部完成，但在流程收尾时未如实标记完成，而是将冗余调用 run_policy_field_lookup 返回的 NEEDS_CLARIFICATION 错误沉淀为缺口，并将 completeness 标记为 partial 向用户索要不必要的澄清。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/0, turn1/records/run/step_results/1
- 归属（模型自述）：local

## Q56  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/6, 程序-工具返回-6
- 归属（模型自述）：本轴

## Q57  case=smoke-multi-policy-anjinning
- 主张：模型未按系统提示词要求输出以 answer_draft 为首字段的纯 JSON 并使用 claims 声明业务值，而是直接输出了 Markdown 表格和段落，并在 answer_draft 中直接填写保单号及状态。
- 观察：模型输出先输出了 Markdown 表格及总结正文，后拼接了 JSON 文本；并在 answer_draft 中直接写入了保单号、产品名和状态，未声明 claims 字段，fact_refs 也为空数组。
- 证据：turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：local

## Q58  case=smoke-multi-policy-anjinning
- 主张：agent_bridge 依据会话状态中的5条 facts 进行模板重建并覆盖了模型原本包含6张保单的草稿，导致后续步骤传递与最终交付给用户的清单均缺失了第6张保单 P260922000007861。
- 观察：agent 步骤输出草稿完整包含了6张保单，但 agent_bridge 步骤依据会话状态中仅有的5条 facts 按模板覆盖重建了 answer_draft，导致向后传递时丢失了第6张保单 P260922000007861。
最终交付给用户的保单清单仅展示了5张保单，丢失了第6张保单 P260922000007861，未完整交付安锦宁名下的保单清单。
已确认查得的关键业务事实在最终交付时发生遗漏，未能完整无损交付给调用方。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/session, turn1/records/traces/0/tree/0/spans/4
- 归属（模型自述）：local

## Q59  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## Q60  case=main-B01-meeting-prep-fuyunping
- 主张：最终交付给调用方的内容中丢失了三个开场问题建议，未能满足用户要求。
- 观察：最终交付内容中未呈现针对伏云平准备的三个开场问题，需求未达成。
最终交付内容中丢弃了上游生成的三个开场问题，产出未完整交付给调用方。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## Q61  case=main-D01-same-surname-clarify
- 主张：系统在客户搜索内部表达中未保留用户要求的“按客户号升序”排序规则。
- 观察：无法按用户指定的客户号升序排列搜索结果供用户选取，影响后续选择交互体验。
- 证据：E2, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## Q62  case=smoke-policy-list-fuyunping
- 主张：信息已齐备时模型未收敛并按契约输出最终保单答复，而是冗余并错误调用了 run_policy_field_lookup 工具导致报错挂起。
- 观察：导致系统未能在获取完整保单数据后直接作答，反而因工具报错而中断或进入不必要的澄清流程，降低了问答效率和用户体验。
- 证据：exp-output-contract-compliance, exp-output-faithfulness-policies, exp-tool-call-no-redundant-lookup, turn1/records/traces/0/tree/0/spans/3/spans/8, turn1/records/traces/0/tree/0/spans/3/spans/9, unexp-run-policy-field-lookup-multi
- 归属（模型自述）：本轴

## Q63  case=main-D01-same-surname-clarify
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status=None，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：本轮已停止继续查询，以下答复仅依据已取得的资料；未完成部分仍需补充核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/3, 程序-缺口-3
- 归属（模型自述）：本轴

## Q64  case=smoke-customer-profile-fuyunping
- 主张：在首次 customer_detail 工具执行失败后，系统编排未终止无效尝试或改用其他有效策略，而是以相近参数再次调用 customer_detail 并再次失败，导致出生年月子任务未能获取有效事实。
- 观察：针对客户的出生年月查询，在首次 customer_detail 报错失败后，系统未采用其他有效策略或据实收尾，而是继续调度了第二次 customer_detail 调用并再度失败，未能完成出生年月的数据获取工作覆盖。
在首次 customer_detail 工具执行失败并返回明确错误提示后，系统未终止无效重试或切换有效分支策略，仅在 fields 中微调添加 clientbirthday 再次调用 customer_detail 并再次失败。
客户伏云平的出生年月在 customer_search 中未返回，随后两次 customer_detail 调用均失败，最终答复未能告知客户的出生年月。
在出生年月的查询路径上，未能成功获取到有效数据，且在失败后无有效替代分支推进完成覆盖。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_results/0, turn1/records/run/step_results/1, turn1/records/run/step_results/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## Q65  case=main-B01-meeting-prep-fuyunping
- 主张：在获取到客户资料与已有保单事实后已具备完整输入，但 Agent 未及时结束取数，追加调用了未受委托的 entity_lookup 与 product_knowledge 工具
- 观察：超范围检索产品条款知识，违背了证据充足时停止取数的编排原则，延长交互延迟
- 证据：exp-planning-stop-timing-on-sufficient-facts, turn1/records/traces/0/tree/0/spans/3/spans/10, turn1/records/traces/0/tree/0/spans/3/spans/6
- 归属（模型自述）：本轴

## Q66  case=smoke-customer-profile-fuyunping
- 主张：首次调用 customer_detail 失败并收到“本轮不要以相同参数重试同一工具”提示后，系统仍通过微调 fields 参数对同一客户ID重复调用已失败的 customer_detail 工具。
- 观察：造成无意义的重复调用和连续报错，浪费单轮调用额度与执行时间。
- 证据：exp_avoid_duplicate_call_on_failure, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2
- 归属（模型自述）：本轴

## Q67  case=smoke-policy-list-fuyunping
- 主张：run_policy_field_lookup 工具执行被记录为 ERROR，返回 NEEDS_CLARIFICATION 且未继续执行后续字段提取流程
- 观察：复合工具执行中断，未能直接产出详情字段，但该行为符合该工具在多保单场景下需澄清的既定业务逻辑，由上游路由选择单保单复合工具所致。
- 证据：turn1/records/run/step_executor_runs/0/tools/4, turn1/records/traces/0/tree/0/spans/3/spans/9, unexp-exec-001
- 归属（模型自述）：上游:planning_routing

## Q68  case=smoke-policy-list-fuyunping
- 主张：在已经成功获取伏云平名下全部2张保单及其完整详情后，编排仍冗余调用了仅适用于单张保单字段查询的 run_policy_field_lookup，工具选择与问题类型不符。
- 观察：用户意图为查询伏云平名下的全部保单，流程在已通过 policy_search 查得2张保单并通过 policy_detail 取得完整详情后，编排仍调用了专用于单张保单详情查询的 run_policy_field_lookup，所选调用路径与问题类型不相称。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/0, turn1/records/run/step_results/1
- 归属（模型自述）：local

## Q69  case=smoke-multi-policy-anjinning
- 主张：[程序判定] 执行余量提示随用量更新：4 处提示逐字相同（剩余 10 次调用、约 596 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/messages/0, turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q70  case=main-D01-same-surname-clarify
- 主张：customer_search 在接收包含“姓平、12月份生日、女性”等组合条件时，连续多次（tools/0、tools/1、tools/2）在解析层失败并返回 AMBIGUOUS，未能成功解析并执行客户数据查询，亦无法返回请求字段数据结构。
- 观察：导致客户检索未能真正进入底层数据库执行，无法获取符合条件的目标客户信息。
- 证据：exp-tool0-match-fields, exp-tool0-no-error, exp-tool1-no-error, exp-tool2-no-error, turn1/records/run/step_executor_runs/0/tools/0/result, turn1/records/run/step_executor_runs/0/tools/1/result, turn1/records/run/step_executor_runs/0/tools/2/result
- 归属（模型自述）：本轴

## Q71  case=smoke-policy-detail-renyanlin
- 主张：[程序判定] 执行余量提示随用量更新：4 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q72  case=main-B01-meeting-prep-fuyunping
- 主张：在已有 customer_detail 结果已包含 clientNo 的情况下，编排中再次对同一客户 ID 重复调用 customer_detail 获取 clientNo 字段
- 观察：造成无意义的冗余工具调用，增加系统耗时与 token 开销
- 证据：exp-planning-no-redundant-customer-detail, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：本轴

## Q73  case=smoke-agg-paid-prem-fuyunping
- 主张：agent 产出完整答复草稿后，系统在 agent_bridge 节点触发了非预期的模板回退编排分支，降级为 PARTIAL 状态并用模板替换了原有答复草稿。
- 观察：导致最终输出被降级为模板拼接文本，放弃了模型已提炼的准确累计保费草稿，且产生多余的证据缺口提示。
- 证据：turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/4, unexp_plan_001
- 归属（模型自述）：本轴

## Q74  case=smoke-customer-profile-fuyunping
- 主张：customer_detail 接口在传入客户 ID 及性别、生日等字段后连续两次执行失败，返回“本次工具调用失败，未能获取相关信息，请稍后再试。”
- 观察：导致下游无法通过详情接口获取客户画像补充字段（如生日），使得该客户的相关信息查询受阻。
- 证据：tool_exec_detail_1_no_error, tool_exec_detail_2_no_error, turn1/records/run/step_executor_runs/0/tools/1/result, turn1/records/run/step_executor_runs/0/tools/2/result
- 归属（模型自述）：本轴

## Q75  case=main-A01-fuyunping-list-aggprem
- 主张：agent_bridge 步骤在接收 agent 步骤输出时，未采纳保单 P260922000011415 的累计已交保费事实（1320.0），改义替换为年缴保费（0），导致最终交付给用户的保单累计已交保费错误呈现为 0.00。
- 观察：上游 agent 步骤产出中已明确包含保单 P260922000011415 的累计已交保费 1320.0，但 agent_bridge 步骤未采纳该累计已交保费事实，反而生成并绑定了年缴保费字段（year_pay_prem 0），将保单保费事实篡改为 0.00。
最终交付内容中保单 P260922000011415 的保费显示为 0.00，系年缴保费而非累计已交保费，未如实告知该保单实际的累计已交保费 1320.0。
最终交付给调用方的回答中，保单 P260922000011415 的累计已交保费被错误替换改义为 0.00，关键业务事实发生改义与丢失。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## Q76  case=main-D01-same-surname-clarify
- 主张：ask_clarify 工具虽然业务内容正常返回 NEEDS_CLARIFICATION，但底层 span 和 tool_call 状态均被判定为 ERROR / error: true。
- 观察：工具调用层面产生了系统级报错标记，影响工具执行的正常健康度判定。
- 证据：exp-tool4-no-error, turn1/records/run/step_executor_runs/0/tools/4/tool_call_error, turn1/records/traces/0/tree/0/spans/3/spans/10/status_code
- 归属（模型自述）：本轴

## Q77  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/0, 程序-工具返回-0
- 归属（模型自述）：本轴

## Q78  case=smoke-multi-policy-anjinning
- 主张：policy_search 搜索结果包含 6 张保单，但 execution.gaps 漏列第 6 张保单 P260922000007861 未完整提供被保人姓名，且适配层生成写入会话的 policy_brief 事实遗漏了该保单。
- 观察：policy_search 返回的 8 条记录涵盖 6 张保单，但 execution.gaps 仅列出前 5 张保单未完整提供被保人姓名而漏列第 6 张保单 P260922000007861；同时适配层写入会话的 policy_brief 事实遗漏了该保单，导致结果残缺。
工具调用执行结果与适配层写入事实中遗漏了保单 P260922000007861 的 policy_brief，且 execution.gaps 漏列该保单姓名缺失信息，未能完整交付安锦宁名下的完整保单清单事实。
policy_search 返回 8 条记录包含 6 张保单，但 execution.gaps 漏列第 6 张保单 P260922000007861，且写入会话状态的 policy_brief 事实中丢失了该保单，返回结果残缺。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/session
- 归属（模型自述）：local

## Q79  case=smoke-policy-detail-renyanlin
- 主张：agent_bridge 步骤在转换 agent 输出时，将完备状态置为 PARTIAL 并凭空引入了未在 agent 输出中存在的缺口说明“部分内容未能在本轮证据中对应，请结合原始资料核实。”，导致状态与事实改义。
- 观察：agent 步骤输出中明确 gaps 为空且回答已覆盖全部问题，但下游 agent_bridge 步骤将状态置为 PARTIAL 并凭空新增缺口说明“部分内容未能在本轮证据中对应，请结合原始资料核实。”，导致状态与事实改义。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2
- 归属（模型自述）：local

## Q80  case=smoke-policy-list-fuyunping
- 主张：系统在已获取伏云平全部保单及详情后，错误调用了专用于单张保单详情查询的 run_policy_field_lookup，导致结束时机滞后且触发不合理的澄清阻断状态。
- 观察：保单信息齐备的情况下仍发起多余查询，并因工具报错将已获取的结果带入多保单澄清阻断提示，损害了问答流程的完整性与准确性。
- 证据：PR-01, PR-03, PR-04, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴

## Q81  case=main-D01-same-surname-clarify
- 主张：在收到系统受控动作 finish_with_evidence 及连续查询未取得新信息的预算终止控制后，模型未按现有证据据实收尾输出回答，而是违规生成了 ask_clarify 工具调用。
- 观察：未能遵照系统受控收尾指令据实完成兜底输出，导致流程未能在该次调用中达成规范的证据收尾文本输出。
- 证据：exp-4-finish-with-evidence-handling, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴

## Q82  case=main-D01-same-surname-clarify
- 主张：系统内部表达完全丢弃了“按客户号升序”的排序约束。
- 观察：后续返回给用户的候选客户列表无法保证符合客户号升序的展现要求。
- 证据：exp_sort_constraint, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## Q83  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/1, 程序-工具返回-1
- 归属（模型自述）：本轴

## Q84  case=main-D01-same-surname-clarify
- 主张：系统在首次调用的客户搜索内部表达中遗漏了用户指定的“我名下”客户归属范围约束。
- 观察：导致搜索范围可能偏离用户本人名下客户，带来查询结果归属性不准确的问题。
- 证据：E1, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## Q85  case=main-B01-meeting-prep-fuyunping
- 主张：系统在最终交付给用户的正文中弄丢了用户明确要求的三个开场问题。模型在 agent 内部已成功生成了三个开场问题，但在经过 agent_bridge 组装为 answer_draft 及 finalize 交付时被丢弃，正文中完全未呈现。
- 观察：导致交付内容缺失用户核心任务目标（帮我准备三个开场问题），回答不完整，影响用户实际展业使用。
- 证据：exp_deliver_opening_questions, turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## Q86  case=main-B01-meeting-prep-fuyunping
- 主张：product_knowledge 工具执行检索时，输入产品为平安安佑福重大疾病保险，但返回正文及来源却为平安爱满分（2026）两全保险，返回结果与请求目标产品对象不符。
- 观察：工具调用入参请求平安安佑福重大疾病保险的保险责任，返回正文和来源文档却属于平安爱满分（2026）两全保险，返回结果与请求目标产品不一致。
- 证据：turn1/records/run/step_executor_runs/0/tools/5
- 归属（模型自述）：local

## Q87  case=smoke-policy-list-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 597 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q88  case=main-A01-fuyunping-list-aggprem
- 主张：[程序判定] 执行余量提示随用量更新：5 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/6, 程序-执行余量提示
- 归属（模型自述）：本轴

## Q89  case=main-D01-same-surname-clarify
- 主张：模型在 invocation_parameters 明确指定 tool_choice 为 none 的情况下，依然违反调用参数约束产生工具调用（span 7 调用了 customer_search，span 9 调用了 ask_clarify）。
- 观察：破坏了系统通过 tool_choice 强制模型收尾或输出纯文本的控制机制，导致本应结束或收尾的轮次继续产生工具调用行为。
- 证据：exp-2-respect-tool-choice-none-span7, exp-3-respect-tool-choice-none-span9, turn1/records/traces/0/tree/0/spans/3/spans/7, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴
