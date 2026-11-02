# 盲测问题清单 pass1（86 条，已打乱，不含臂标签）

## P01  case=smoke-agg-paid-prem-fuyunping
- 主张：最终交付给用户的保单保费信息被错误改义，保单 P260922000011415 的累计已交保费（实际为 1320.0）被篡改为 0.00，未能如实分别告知每张保单的累计已交保费。
- 观察：交付给调用方的最终答复中，保单 P260922000011415 的保费被展示为 0.00，未能如实分别告知伏云平每张保单的累计已交保费（该保单实际累计已交保费为 1320.0）。
交付给调用方的事实发生改义与替换：上游查询到的累计已交保费事实被替换为年缴保费字段，导致保单 P260922000011415 交付的保费金额错误变为 0.00。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：local

## P02  case=smoke-agg-paid-prem-fuyunping
- 主张：系统为模型调用的系统提示词组装了互相冲突的输出契约：前段规定输出包含 answer_draft 等五字段的 JSON 并表达金额，末段又要求使用 claims 格式且严禁在 answer_draft 中填写金额、状态等业务值。
- 观察：系统提示词前段要求输出包含 answer_draft 等五字段的 JSON 且按规定表达金额，末段又要求使用 claims 格式且严禁在 answer_draft 中填写金额与状态，格式要求前后冲突。
系统提示词前段五字段 JSON 要求与末段 claims 契约要求并存且在字段填写约束上直接矛盾，格式要求前后冲突。
系统提示词中同时包含五字段 JSON 输出规范与禁止在正文填值的 claims 契约，存在自相冲突的格式约束。
系统组装的系统提示词前段要求输出五字段 JSON 且结论先行，末段却要求业务回答必须用 claims 声明并禁止在正文中填写金额及状态，格式要求前后冲突。
- 证据：turn1/records/run/step_executor_runs/0, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：local

## P03  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/6, 程序-工具返回-6
- 归属（模型自述）：本轴

## P04  case=main-A01-fuyunping-list-aggprem
- 主张：模型在最终回复中未生成 claims 契约字段，且在 answer_draft 中直接填充了累计已交保费金额、保单状态与客户姓名。
- 观察：模型在输出中未提供 claims 数组，且在 answer_draft 中直接填写了累计已交保费 1320.0 与 6300.0、保单状态以及投被保人姓名伏云平。
- 证据：turn1/records/run/step_executor_runs/0/messages/6, turn1/records/traces/0/tree/0/spans/3/spans/6
- 归属（模型自述）：local

## P05  case=main-A01-fuyunping-list-aggprem
- 主张：保单 P260922000011415 的累计已交保费在 agent_bridge 步骤中被篡改为年缴保费字段与数值 0.00，且保单 P260922000011416 的保费口径也被混淆为年缴保费
- 观察：最终交付给用户的保费金额与业务口径失真，保单 P260922000011415 的累计已交保费被错误回答为 0.00 元。
- 证据：exp-context-02-prem-transfer-p415, exp-context-03-prem-transfer-p416, exp-context-04-delivered-integrity, turn1.delivered_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## P06  case=smoke-policy-detail-renyanlin
- 主张：模型在终轮输出时未遵循纯 JSON 及 claims 渲染规范，先输出了前置 Markdown 文本，且 JSON 对象中缺失 claims 字段并在 answer_draft 中直接填充了姓名与保单状态。
- 观察：模型实际输出了前置 Markdown 文本，其后的 JSON 中缺失 claims 字段，且直接在 answer_draft 中填充了客户姓名任言琳和保单状态交费有效。
- 证据：turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：local

## P07  case=main-B01-meeting-prep-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P08  case=smoke-agg-paid-prem-fuyunping
- 主张：agent_bridge 节点在结构化转换与渲染过程中，未忠实传递 agent 产出的 answer_draft 和累计已交保费 fact_refs，而是错误提取了年缴保费（year_pay_prem）及摘要信息，将保单 P260922000011415 的累计保费 1320 改义为 0.00 并重写了答复草稿。
- 观察：导致下游最终输出给用户的保单累计保费数据发生严重事实篡改，保单 P260922000011415 累计已交保费被错误交付为 0.00。
- 证据：EXP-CTX-001, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2
- 归属（模型自述）：本轴

## P09  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/3, 程序-工具返回-3
- 归属（模型自述）：本轴

## P10  case=smoke-multi-policy-anjinning
- 主张：模型未遵循仅输出 JSON 的格式契约，在 JSON 对象前输出了大段游离的 Markdown 表格与说明文本。
- 观察：游离文本破坏了下游对结构化 JSON 输出的解析，可能导致下游反序列化失败或需要额外容错清洗。
- 证据：exp_output_contract_format, turn1/records/run/step_executor_runs/0/messages/3/content
- 归属（模型自述）：本轴

## P11  case=smoke-policy-detail-renyanlin
- 主张：中间胶水环节 agent_bridge 向上下文传递链路注入了无事实依据的 PARTIAL 状态与虚假 gaps 提示
- 观察：导致工作流及最终交付结果携带非必要的缺口警告和未完全解答标记，损害了上下文中状态与元数据传递的保真度。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, unexp_bridge_injected_partial_gaps
- 归属（模型自述）：本轴

## P12  case=smoke-policy-list-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 597 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8, 程序-执行余量提示
- 归属（模型自述）：本轴

## P13  case=main-D01-same-surname-clarify
- 主张：模型调用最终未按用户冻结需求输出姓平、12月份生日的女性客户升序候选列表
- 观察：因 customer_search 工具查询连续返回 AMBIGUOUS 并在预算耗尽后停止取数，模型最终未输出名下姓平、12月份生日的女性客户升序列表供用户选择
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：local

## P14  case=main-D01-same-surname-clarify
- 主张：在前序三次工具调用均返回 AMBIGUOUS 提示无法解析筛选条件后，模型依然违规改写 query 进行了第四次重复调用，最终触发连续无进展预算拦截
- 观察：前序 3 次调用 customer_search 均返回 AMBIGUOUS 且提示未能可靠解析本次筛选条件或排序，模型在第 4 次调用中仍然构造包含‘姓平’等类似条件的 query 重复调用 customer_search
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/7
- 归属（模型自述）：local

## P15  case=main-B01-meeting-prep-fuyunping
- 主张：在已有充分客户画像与保单状态可支持组织开场问题的情况下，未及时结束取证，继续调度词典查询与宽泛的产品条款 RAG 检索。
- 观察：导致结束时机滞后，引入了与用户目标关系较弱的条款知识，甚至导致最终产出中混入了无关产品条款片段。
- 证据：exp_plan_finish_timing, turn1/records/run/step_executor_runs/0/messages/8, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/5, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## P16  case=main-D01-same-surname-clarify
- 主张：customer_search 工具内部解析适配层在接收包含姓名、生日月份、性别等符合规范的查询条件时，误判为未能可靠解析并返回 AMBIGUOUS 拒绝执行查询，导致未能返回请求中指定的字段数据结构。
- 观察：导致下游无法获取所需的客户基础字段数据，引发模型后续重复尝试查询并最终中断走向澄清。
- 证据：exp_customer_search_0_fields_match, exp_customer_search_1_fields_match, turn1/records/run/step_executor_runs/0/tools/0/result, turn1/records/run/step_executor_runs/0/tools/1/result
- 归属（模型自述）：本轴

## P17  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/1, 程序-工具返回-1
- 归属（模型自述）：本轴

## P18  case=smoke-policy-list-fuyunping
- 主张：在已完整获取客户名下所有保单详情后，编排路径仍冗余调用了仅适用于单张保单字段查询的工具，导致最终交付被引入了不必要的追问与缺口标记。
- 观察：执行编排在已通过 policy_search 及 policy_detail 完整获取伏云平名下全部两张保单的详情事实后，未按任务结束取数，反而选择了仅适用于无保单号且针对单张保单查字段的 run_policy_field_lookup 工具，所选工具路径与查询名下全部保单的问题类型及多保单的已知状态严重不相称，导致触发 NEEDS_CLARIFICATION。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/0, turn1/records/run/step_results/1
- 归属（模型自述）：local

## P19  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/2, 程序-工具返回-2
- 归属（模型自述）：本轴

## P20  case=smoke-agg-paid-prem-fuyunping
- 主张：第4次模型调用输出未遵守纯JSON及业务回答契约，在JSON外夹带自由文本，遗漏必填的claims字段，并在answer_draft中自行填入金额与状态。
- 观察：第4次模型调用输出在JSON代码块外部生成了大量自由文本说明，且输出的JSON中完全缺失claims字段，并在前缀文本与answer_draft中自行填写了金额数值（1320、6300）与保单状态。
- 证据：turn1/records/run/step_executor_runs/0/messages/8, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：local

## P21  case=smoke-multi-policy-anjinning
- 主张：policy_search 返回 8 条记录（涉及 6 张保单），所有记录的投被保人姓名均为密文，但 execution.gaps 仅列出前 5 张保单未完整提供被保人姓名，遗漏了第 6 张保单 P260922000007861，未完整如实披露缺失。
- 观察：policy_search 返回 8 条记录对应 6 张保单，所有记录的投被保人姓名均为密文未提供明文，但 execution.gaps 仅列出前 5 张保单“未完整提供被保人姓名”，遗漏了第 6 张保单 P260922000007861，未完整如实披露缺失。
policy_search 返回结果中全部 6 张保单被保人姓名均返回密文未提供明文，但 execution.gaps 仅披露前 5 张保单未完整提供被保人姓名，漏列第 6 张保单 P260922000007861。
对接的 policy_search 工具执行返回中，execution.gaps 仅列出前 5 张保单未完整提供被保人姓名，遗漏了第 6 张保单 P260922000007861，披露残缺。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/traces/0/tree/0/spans/3/spans/2
- 归属（模型自述）：local

## P22  case=main-D01-same-surname-clarify
- 主张：ask_clarify 正常完成挂起澄清并输出 NEEDS_CLARIFICATION，但工具自身执行结果与 Span 状态被错误记录为 ERROR
- 观察：正常的业务交互澄清被系统误报为工具执行异常，污染调用监控指标
- 证据：tool_ask_clarify_execution_status_normal, turn1/records/run/step_executor_runs/0/tools/4/tool_call_error, turn1/records/traces/0/tree/0/spans/3/spans/10/status
- 归属（模型自述）：本轴

## P23  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/8, 程序-执行余量提示
- 归属（模型自述）：本轴

## P24  case=smoke-multi-policy-anjinning
- 主张：agent_bridge 步骤使用仅含5条保单 facts 的模板覆盖了模型输出中包含6张保单的草稿，导致最终交付给用户的清单中丢失了第6张保单 P260922000007861
- 观察：agent 产出的文本及草稿中完整列出了6张保单，但在 agent_bridge 步骤中被仅含5条 facts 的模板重新渲染覆盖，导致输出的 answer_draft 丢失了第6张保单 P260922000007861。
最终交付内容因上游模板覆盖丢失了有效保单实体 P260922000007861，核心业务事实未完整交付。
最终交付给用户的保单清单中仅包含5张保单，遗漏了安锦宁名下的第6张保单 P260922000007861（平安e生保（加享版）医疗保险），未能完整列出安锦宁名下的保单清单。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/session, turn1/records/traces/0/tree/0/spans/4
- 归属（模型自述）：local

## P25  case=smoke-customer-profile-fuyunping
- 主张：模型最终答复未直接以 JSON 输出且 answer_draft 未作为首字段，而是在外部输出了大段 CoT 思考过程及多次 JSON 代码块包裹的内容，违反了输出契约。
- 观察：下游结构化解析器可能无法直接解析输出，或需额外兜底逻辑提取 JSON 块，增加了解析失败风险。
- 证据：exp-model-05, turn1/records/run/step_executor_runs/0/messages/7, turn1/records/traces/0/tree/0/spans/3/spans/7
- 归属（模型自述）：本轴

## P26  case=main-A01-fuyunping-list-aggprem
- 主张：[程序判定] 执行余量提示随用量更新：5 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/6, 程序-执行余量提示
- 归属（模型自述）：本轴

## P27  case=smoke-agg-paid-prem-fuyunping
- 主张：在查询目标明确为保单及保费信息时，第1次模型调用未遵守工具说明中“目标是保单本身→policy_search”的禁令，发起了customer_search。
- 观察：用户明确要求查询伏云平每张保单的累计已交保费，查询目标直接指向保单本身，但模型在第1次调用中发起了customer_search查询“伏云平的客户”。
- 证据：turn1/records/run/step_executor_runs/0/messages/1, turn1/records/traces/0/tree/0/spans/3/spans/1
- 归属（模型自述）：local

## P28  case=smoke-customer-profile-fuyunping
- 主张：customer_detail 接口两次调用均在极短时间内（<10ms）执行报错，返回“本次工具调用失败，未能获取相关信息，请稍后再试”
- 观察：导致下游无法从客户详情接口获取伏云平的生日等进一步详情信息
- 证据：item_customer_detail_1_execution, item_customer_detail_2_execution, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/traces/0/tree/0/spans/3/spans/4, turn1/records/traces/0/tree/0/spans/3/spans/6
- 归属（模型自述）：本轴

## P29  case=main-D01-same-surname-clarify
- 主张：面对 customer_search 工具连续返回 AMBIGUOUS 且未执行查询，编排未能及时调整策略，持续改写 query 重复调用同一工具直至触发预算守卫无进展拦截，导致确需外部数据的第一阶段客户名单未能成功查出并列出。
- 观察：编排面对 customer_search 连续返回 AMBIGUOUS 无法解析条件时，未及时调整策略或改换路径，连续盲目改写 query 重复调用同一工具 4 次直至触发预算拦截，确需外部数据时未能完成客户取数。
编排多次无效重试 customer_search 触发无进展预算拦截，未能查出名下姓平、12月份生日的女性客户并按客户号升序列出。
确需外部客户数据时，编排因盲目重试导致预算耗尽拦截，未能完成取数。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/0, turn1/records/run/step_results/1
- 归属（模型自述）：local

## P30  case=smoke-policy-list-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：该客户名下有多张保单，请选择要查询的保单：
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P31  case=smoke-policy-detail-renyanlin
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P32  case=main-D01-same-surname-clarify
- 主张：系统在内部表达及工具调用参数中未体现“按客户号升序”排列的要求。
- 观察：未能保留用户对返回结果按客户号升序呈现的排序需求。
- 证据：exp-client-list-sort-order, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## P33  case=main-B01-meeting-prep-fuyunping
- 主张：在已取得完整客户画像（包含 clientNo 等字段）的情况下，对同一客户ID无依据重复调用 customer_detail。
- 观察：造成冗余工具调用，增加了执行延迟与 Token 消耗，违反了证据足够不再重复调用的系统策略。
- 证据：exp_plan_avoid_redundant_detail, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/4
- 归属（模型自述）：本轴

## P34  case=smoke-customer-profile-fuyunping
- 主张：在工具返回已明确提示失败且告诫本轮不要以相同参数重试后，模型依然追加相似字段对 customer_detail 发起微调重试。
- 观察：额外消耗了一次模型与工具调用额度，增加了端到端耗时。
- 证据：turn1/records/run/step_executor_runs/0/messages/4, turn1/records/traces/0/tree/0/spans/3/spans/5, unexp-model-01
- 归属（模型自述）：本轴

## P35  case=smoke-customer-profile-fuyunping
- 主张：模型最终输出未遵循纯业务 JSON 契约，包含了长篇内部思考分析文本、夹杂 Markdown 代码块并在正文和 gaps 中出现内部工具名
- 观察：模型在输出中输出了长篇思考分析过程并夹杂两处 Markdown 代码块，且在正文及 gaps 中包含了 customer_detail 等内部工具名称，未遵循纯业务 JSON 输出契约。
- 证据：turn1/records/run/step_executor_runs/0/messages/7, turn1/records/traces/0/tree/0/spans/3/spans/7
- 归属（模型自述）：local

## P36  case=smoke-customer-profile-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：6 处提示逐字相同（剩余 10 次调用、约 597 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/7, 程序-执行余量提示
- 归属（模型自述）：本轴

## P37  case=smoke-policy-detail-renyanlin
- 主张：[程序判定] 执行余量提示随用量更新：4 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, 程序-执行余量提示
- 归属（模型自述）：本轴

## P38  case=main-B01-meeting-prep-fuyunping
- 主张：product_knowledge 工具执行入参查询的是“平安安佑福重大疾病保险”，但返回的条款正文及文档来源实际为“平安爱满分（2026）两全保险”，返回内容与请求对象不一致。
- 观察：入参 query 为“平安安佑福重大疾病保险的保险责任是什么？”，但工具返回的 facts 及 sources 为“寿险-平安爱满分（2026）两全保险-OCR原文.md”，返回对象与请求产品不一致。
- 证据：turn1/records/run/step_executor_runs/0/tools/5
- 归属（模型自述）：local

## P39  case=smoke-agg-paid-prem-fuyunping
- 主张：步骤 agent_bridge 将上游模型产出的保单 P260922000011415 累计已交保费 1320 篡改为年缴保费 0.00，关键事实原义被破坏并直接带入最终回答。
- 观察：步骤 agent（step_results/2/steps/1）输出中包含保单 P260922000011415 累计已交保费 1320 及 P260922000011416 累计已交保费 6300，但在 agent_bridge（step_results/2/steps/2）输出中被篡改为年缴保费字段，导致保单 P260922000011415 保费变为 0.00，关键事实发生改义与损坏。
- 证据：content#13, content#39, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/traces/0/tree/0/spans/4
- 归属（模型自述）：local

## P40  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/0, 程序-工具返回-0
- 归属（模型自述）：本轴

## P41  case=main-D01-same-surname-clarify
- 主张：customer_search 工具在入参具备声明支持的姓名（姓平）、生日月份（12月）、性别（女性）等条件时，自身解析层持续返回 AMBIGUOUS 且未执行查询，导致未能返回请求的客户数据。
- 观察：工具入参 query 为“姓平、12月份生日、女性的客户”，所含条件均在工具声明支持的维度内，但工具返回 execution.status='AMBIGUOUS' 并说明未能可靠解析筛选条件且未执行客户查询，未返回请求的目标客户对象。
工具入参 query 调整为“姓名姓平开头的女性客户且生日在12月”，工具仍返回 execution.status='AMBIGUOUS' 且未执行客户查询，未按请求返回匹配客户。
工具入参 query 调整为“平姓女性客户，生日12月”，工具仍返回 execution.status='AMBIGUOUS' 且未执行客户查询，未能返回目标对象。
对接的客户搜索工具执行返回 AMBIGUOUS 且未执行查询，未能查出并列出名下姓平、12月份生日的女性客户供用户选择。
对接的客户搜索工具执行返回 AMBIGUOUS 且未执行查询，未能检索出符合条件的客户列表。
对接工具未按请求条件执行查询，返回 AMBIGUOUS 声明尚未执行客户查询，未返回请求的对象。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2
- 归属（模型自述）：local

## P42  case=smoke-multi-policy-anjinning
- 主张：模型输出未遵循以 answer_draft 为首字段的纯 JSON 输出契约，而是先输出了 Markdown 表格与汇总文本，后拼接 JSON 字符串；并在文本与 answer_draft 中直接写入保单状态、保单号等业务值，未按要求输出 claims。
- 观察：模型未输出纯 JSON 而是先输出了 Markdown 表格再拼接 JSON 字符串；且在正文及 answer_draft 中直接输出了保单状态和保单号，未按契约输出 claims。
- 证据：turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：local

## P43  case=smoke-customer-profile-fuyunping
- 主张：customer_detail 工具在两次调用中均发生执行异常，状态为 ERROR 并返回工具调用失败报错
- 观察：导致未能获取客户伏云平的详细画像数据（如出生日期等信息）
- 证据：exp_customer_detail_call_1_no_error, exp_customer_detail_call_2_no_error, turn1/records/run/step_executor_runs/0/tools/1/result, turn1/records/run/step_executor_runs/0/tools/2/result, turn1/records/traces/0/tree/0/spans/3/spans/4/error, turn1/records/traces/0/tree/0/spans/3/spans/6/error
- 归属（模型自述）：本轴

## P44  case=main-B01-meeting-prep-fuyunping
- 主张：系统向调用方交付的最终答复中未包含针对伏云平准备的三个开场问题，该内容在上游 agent 生成后被下游步骤替换丢失。
- 观察：交付给调用方的最终结果中仅包含客户资料与保单摘要，未包含针对伏云平准备的三个开场问题。
交付给调用方的最终结果丢失了上游模型已生成的开场问题建议，未能完整交付用户要求的内容。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## P45  case=main-A01-fuyunping-list-aggprem
- 主张：保单 P260922000011415 的累计已交保费在 agent_bridge 环节传递组装时被混淆替换为年缴保费字段（0），导致保费数值被改义为 0.00 并最终交付。
- 观察：向用户交付了与底层数据不符的错误保费数值，导致用户获取的保费信息失真。
- 证据：exp_agg_premium_field_fidelity, turn1.delivered_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## P46  case=main-A01-fuyunping-list-aggprem
- 主张：agent_bridge 传递环节无中生有追加“部分内容未能在本轮证据中对应，请结合原始资料核实”的缺口信息并置 PARTIAL 状态。
- 观察：给最终交付输出增加了未经核实的通用免责提示，干扰了上下文真实状态传递。
- 证据：turn1/records/run/step_results/2/steps/2, turn1/records/traces/0/tree/0/spans/5, unexp_bridge_synthetic_gap
- 归属（模型自述）：本轴

## P47  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/4, 程序-工具返回-4
- 归属（模型自述）：本轴

## P48  case=main-D01-same-surname-clarify
- 主张：customer_search 连续返回 AMBIGUOUS 报错且未取得新信息时，系统未及时切换策略或发起澄清，而是仅改写自然语言问法连续重试 4 次，最终触发系统预算守卫拦截。
- 观察：造成无意义的多次模型往返与工具调用，增加延迟与 token 消耗，编排决策缺乏有效的失败重试控制机制。
- 证据：PR-02, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3
- 归属（模型自述）：本轴

## P49  case=main-D01-same-surname-clarify
- 主张：工具返回 finish_with_evidence 收尾控制动作后，模型未按规则用现有证据进行最终作答收尾，而是发起了 ask_clarify 工具调用
- 观察：工具返回 BUDGET 错误并带有 control.action='finish_with_evidence' 指令，要求基于已有证据回答收尾，模型在思考中识别了该指令并计划给出答案草稿，但最终输出依然生成了 ask_clarify 工具调用
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：local

## P50  case=smoke-customer-profile-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P51  case=smoke-policy-list-fuyunping
- 主张：在已知客户拥有多张保单且已获取详情的情况下，错误调用了专用于单张保单查询的 run_policy_field_lookup，导致工具返回 NEEDS_CLARIFICATION 异常，未能合理控制结束时机与调用路径。
- 观察：造成无意义的额外调用延迟和异常返回，且将不必要的澄清提问带入了最终交付文本中。
- 证据：exp-planning-stop-timing, exp-planning-tool-routing-lookup, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴

## P52  case=smoke-multi-policy-anjinning
- 主张：[程序判定] 执行余量提示随用量更新：2 处提示逐字相同（剩余 10 次调用、约 596 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/messages/0, turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, 程序-执行余量提示
- 归属（模型自述）：本轴

## P53  case=smoke-agg-paid-prem-fuyunping
- 主张：Agent 执行原本正确输出了两张保单的“累计已交保费”（1320 与 6300），但在流转进入 agent_bridge / finalize 组装时被篡改为 year_pay_prem，导致 P260922000011415 的保费被呈现为 0.00，指标原义丢失且数值错误。
- 观察：向用户最终呈现的业务数据失真，将到期终止保单的累计已交保费 1320 错报为 0.00，严重影响保单信息准确性。
- 证据：exp_field_semantic_preservation, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：本轴

## P54  case=smoke-customer-profile-fuyunping
- 主张：前序 customer_detail 工具执行失败后，模型未遵循不得重复调用已失败来源的规则，再次发起相同参数的 customer_detail 调用
- 观察：前序 customer_detail 工具执行失败且已提示本轮不要重试，模型在本次调用中仍对同一 customer_id 再次发起了 customer_detail 调用。
- 证据：turn1/records/run/step_executor_runs/0/messages/5, turn1/records/traces/0/tree/0/spans/3/spans/5
- 归属（模型自述）：local

## P55  case=smoke-multi-policy-anjinning
- 主张：用户明确要求“安锦宁名下有哪些保单？先列清单就行”，完整目标为保单清单且原话写全条件，但模型未按规则单独调用 present_policy_search_card，而是调用了 policy_search。
- 观察：用户明确表达“安锦宁名下有哪些保单？先列清单就行。”，目标完全满足卡片展示条件，但模型调用了 policy_search 并传入多项字段参数。
- 证据：turn1/records/run/step_executor_runs/0/messages/1, turn1/records/traces/0/tree/0/spans/3/spans/1
- 归属（模型自述）：local

## P56  case=smoke-customer-profile-fuyunping
- 主张：工具 customer_detail 首次调用执行报错，未能完成调用并返回客户伏云平的出生年月。
- 观察：工具 customer_detail 首次调用执行报错，Agno 标记 tool_call_error 为 true 且返回失败提示。
工具 customer_detail 调用执行报错，未能成功获取客户伏云平的出生年月。
工具 customer_detail 调用执行报错（tool_call_error 为 true），未完成自身调用职责。
工具 customer_detail 调用执行报错，未能返回客户伏云平的出生年月数据。
工具 customer_detail 调用报错中断，返回内容未包含所请求的出生年月字段结果。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1
- 归属（模型自述）：local

## P57  case=smoke-customer-profile-fuyunping
- 主张：agent_bridge 步骤在解析 Agent 输出并组装事实时，注入了前序工具投影与模型输出中均未记录的客户年龄与手机号信息（33岁·手机19909224628），并在交付草稿中追加该摘要，导致 session 产生 citation_anomaly 及未对应证据声明。
- 观察：agent_bridge 步骤在解析 Agent 产出并传递给下游时，擅自注入了上游模型及工具投影均未提供的客户年龄与手机号（33岁·手机19909224628），导致事实改义并引发 session 引用异常。
- 证据：turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/session
- 归属（模型自述）：local

## P58  case=smoke-agg-paid-prem-fuyunping
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P59  case=main-B01-meeting-prep-fuyunping
- 主张：在 tools/1 已返回包含 clientNo 的完整客户画像以及 policy_search 已返回保单全称后，编排中仍发起了冗余的 tools/3（entity_lookup 查平安安佑福）及 tools/4（customer_detail 重复查询 clientNo）。
- 观察：在 tools/1 已返回包含 clientNo 的完整客户画像以及 policy_search 已返回保单全称后，编排中仍发起了冗余的 tools/3（entity_lookup 查平安安佑福）及 tools/4（customer_detail 重复查询 clientNo）。
- 证据：turn1/records/run, turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2, turn1/records/run/step_executor_runs/0/tools/3, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_executor_runs/0/tools/5, turn1/records/run/step_results/0
- 归属（模型自述）：local

## P60  case=main-D01-same-surname-clarify
- 主张：系统在将用户意图转化为客户检索工具输入时遗漏了“我名下”这一归属约束。
- 观察：导致查询范围未能限定在坐席本人名下，扩大了潜在筛选范围，并在最终答复中将归属范围作为缺失信息向用户发起反问。
- 证据：exp_filter_constraints, turn1/records/run/content, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## P61  case=smoke-policy-list-fuyunping
- 主张：在 policy_detail 已完整返回伏云平名下 2 张保单的全部事实后，模型在思维内容中声称“I have all the information needed to answer”，却未按契约生成结构化答案，而是错误调用了仅适用于单张保单且无保单号场景的 run_policy_field_lookup，导致工具返回 NEEDS_CLARIFICATION 报错。
- 观察：导致模型未能及时收口回答用户问题，发起无意义且不适用的工具调用，产生下游异常并拖慢整轮响应流程。
- 证据：exp_t1_model4_no_redundant_lookup, exp_t1_model4_output_contract, exp_t1_model_faithful_policy_data, shared#49, shared#53, turn1/records/traces/0/tree/0/spans/3/spans/8, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：本轴

## P62  case=main-D01-same-surname-clarify
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status=None，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：本轮已停止继续查询，以下答复仅依据已取得的资料；未完成部分仍需补充核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/3, 程序-缺口-3
- 归属（模型自述）：本轴

## P63  case=main-D01-same-surname-clarify
- 主张：系统内部表达完全遗漏了用户明确提出的后续阶段子问题（确定选中客户后查详细资料和保单状态）及其对象字段与前置条件约束。
- 观察：系统内部任务表达仅对应了第一阶段客户检索，未建立确定后再查详细资料和保单状态这两个后续子问题的内部表达。
内部表达及首批工具参数完全遗漏了选中客户的详细资料相关对象与字段。
内部表达未保留详细资料相关对象与字段。
系统内部表达未对查询选中客户详细资料这一子问题建立任务表述或调用意图。
系统内部表达完全遗漏了查询详细资料的子问题。
内部表达未保留确定选中客户后再执行的前置条件约束。
内部表达未保留确定客户后的前置条件约束。
内部表达及首批工具参数完全遗漏了保单状态相关对象与字段。
内部表达未保留保单状态相关对象与字段。
系统内部表达未对查询保单状态这一子问题建立任务表述或调用意图。
系统内部表达完全遗漏了查询保单状态的子问题。
内部表达未保留确定选中客户后查询保单状态的前置条件约束。
- 证据：turn1/records/run, turn1/records/run/step_results/0
- 归属（模型自述）：local

## P64  case=main-B01-meeting-prep-fuyunping
- 主张：模型最终回复未直接输出合法纯 JSON 对象且首字段未严格为 answer_draft，而是在前置大量思维与文本内容后输出了 Markdown 代码块格式的 JSON。
- 观察：可能导致下游依赖直接 JSON 解析的系统解析失败或需额外提取处理。
- 证据：exp_contract_json_structure, turn1/records/run/step_executor_runs/0/messages/12/content
- 归属（模型自述）：本轴

## P65  case=smoke-customer-profile-fuyunping
- 主张：customer_detail 首次调用明确失败并返回“本轮不要以相同参数重试同一工具”后，编排调用链路仍对同一客户ID重复发起了 customer_detail 调用。
- 观察：违背了系统规定的失败不重试策略，产生了无效的工具调用开销，增加了整轮响应时延。
- 证据：exp_pr_retry_policy, turn1/records/run/step_executor_runs/0/messages/4, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/2
- 归属（模型自述）：本轴

## P66  case=smoke-policy-list-fuyunping
- 主张：保单详情取证完成之后未及时终止工具调用，产生冗余调用 run_policy_field_lookup 并导致多张保单冲突报错
- 观察：增加了无谓的调用延迟与 token 消耗，且工具返回的 NEEDS_CLARIFICATION 错误污染了最终 bridge 与 finalize 输出，使答复尾部夹带了不必要的澄清追问
- 证据：exp-termination-timing, turn1/records/run/step_executor_runs/0/tools/4, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/3/spans/8, unexp-redundant-field-lookup
- 归属（模型自述）：本轴

## P67  case=smoke-multi-policy-anjinning
- 主张：agent_bridge 产出的 6 条 evidence 溯源信息传递到 finalize 后被置空，最终输出的 sources 字段丢失全部凭证。
- 观察：上游子步骤 agent_bridge（turn1/records/run/step_results/2/steps/2）输出中包含 6 条 evidence 溯源凭证，但在 finalize 步骤（turn1/records/run/step_results/3）及最终落库输出（turn1.final_output）中，sources 字段被置为空数组，导致任务相关的关键凭证信息丢失。
- 证据：turn1.final_output, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5
- 归属（模型自述）：local

## P68  case=smoke-multi-policy-anjinning
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status=None，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：个别保单被保人姓名未完整返回，如需可进一步查询单张保单详情
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/3, 程序-缺口-3
- 归属（模型自述）：本轴

## P69  case=main-D01-same-surname-clarify
- 主张：customer_search 工具内部条件解析层将支持的查询维度（姓名、生日月份、性别）误判为无法可靠解析，返回 AMBIGUOUS 且未执行实际查询
- 观察：合法查询未能进入底层检索，阻断了正常客户信息的获取并引发后续无效重试
- 证据：tool_customer_search_parse_supported_query, turn1/records/run/step_executor_runs/0/tools/0/result
- 归属（模型自述）：本轴

## P70  case=smoke-policy-detail-renyanlin
- 主张：模型在输出最终回答时，未严格遵循纯 JSON 结构协议，而是在 JSON 前输出了自然语言 Markdown 说明，破坏了“answer_draft 必须是首字段”的输出格式约定。
- 观察：导致下游解析器无法直接将消息整体反序列化为 JSON 对象，需额外进行字符串清洗或正则提取，降低了接口健壮性。
- 证据：exp_call2_output_contract, turn1/records/run/step_executor_runs/0/messages/3, turn1/records/traces/0/tree/0/spans/3/spans/3
- 归属（模型自述）：本轴

## P71  case=main-B01-meeting-prep-fuyunping
- 主张：[程序判定] 执行余量提示随用量更新：8 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/10, turn1/records/traces/0/tree/0/spans/3/spans/12, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/6, turn1/records/traces/0/tree/0/spans/3/spans/8
- 归属（模型自述）：本轴

## P72  case=smoke-customer-profile-fuyunping
- 主张：agent_bridge 步骤组装事实时越过模型视图私自拼接了未暴露的手机号与年龄信息，导致最终交付引入未经模型确认的敏感画像字段并触发证据未对应缺口。
- 观察：交付文本中被夹带未请求的手机号和年龄信息，导致系统标记 PARTIAL 且在 gaps 中追加了证据不对应的局限提示。
- 证据：turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3, turn1/records/session, unexp-cm-01
- 归属（模型自述）：本轴

## P73  case=main-A01-fuyunping-list-aggprem
- 主张：步骤 agent_bridge 在处理传递 agent 输出时，将保单 P260922000011415 的累计已交保费 1320.0 错误替换为年缴保费 0，导致交付给用户的该保单保费金额被错误展示为 0.00。
- 观察：上游 agent 步骤产出的累计已交保费事实（保单 P260922000011415 对应 agg_paid_prem 1320.0）在 agent_bridge 处理时被丢弃，错误替换并绑定为年缴保费（year_pay_prem 0），导致保费金额被篡改为 0.00。
交付给用户的保单 P260922000011415 保费展示为 0.00，未能提供该保单实际对应的累计已交保费金额 1320.0。
交付内容中保费事实被错误替换改义为 0.00，关键业务事实未完整准确交付。
- 证据：turn1.delivered_output, turn1/records/run/step_results/2/steps/1, turn1/records/run/step_results/2/steps/2, turn1/records/run/step_results/3
- 归属（模型自述）：local

## P74  case=main-D01-same-surname-clarify
- 主张：customer_search 因反复微调措辞重试被工具预算控制拦截，返回 BUDGET ERROR
- 观察：造成额外的工具调用开销，耗尽连续查询预算并迫使流程转向澄清
- 证据：turn1/records/run/step_executor_runs/0/tools/3/result, unexpected_customer_search_repeated_calls_budget_error
- 归属（模型自述）：上游:planning_routing

## P75  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/0, 程序-工具返回-0
- 归属（模型自述）：本轴

## P76  case=smoke-customer-profile-fuyunping
- 主张：工具 customer_detail 第二次调用执行报错，返回调用失败信息。
- 观察：工具 customer_detail 第二次调用执行报错，Agno 标记 tool_call_error 为 true 且返回失败提示。
- 证据：turn1/records/run/step_executor_runs/0/tools/2
- 归属（模型自述）：local

## P77  case=smoke-multi-policy-anjinning
- 主张：工具 policy_search 返回6张保单，但会话状态在登记 facts 及保单集合时仅记录前5张保单，遗漏了第6张保单 P260922000007861
- 观察：工具 policy_search 查得6张不同保单（含 P260922000007861），但在转换为会话状态中的 facts 及 last_policy_set、card、answer_refs 时仅写入前5张保单，遗漏了第6张保单 P260922000007861（到期终止）。
- 证据：turn1/records/run/step_executor_runs/0/tools/0, turn1/records/run/step_results/2/steps/2, turn1/records/session, turn1/records/traces/0/tree/0/spans/3/spans/2
- 归属（模型自述）：local

## P78  case=smoke-policy-list-fuyunping
- 主张：在已获得客户伏云平两张保单及明细后，出现冗余工具 run_policy_field_lookup 调用并触发 NEEDS_CLARIFICATION 状态返回。
- 观察：导致额外的接口耗时与错误状态返回，但不影响前序已就绪的保单及客户数据的真实有效性。
- 证据：turn1/records/run/step_executor_runs/0/tools/4, turn1/records/traces/0/tree/0/spans/3/spans/9, unexp-lookup-multiple-policies
- 归属（模型自述）：上游:planning_routing

## P79  case=main-D01-same-surname-clarify
- 主张：系统在工具入参 query 中仅保留了姓氏、生日月份与性别条件，丢失了“我名下”这一归属范围约束。
- 观察：导致客户检索范围偏离当前用户名下，底层查询无法准确定位，并引发后续多余的归属范围澄清反问。
- 证据：exp-client-query-constraints, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴

## P80  case=main-B01-meeting-prep-fuyunping
- 主张：在首次 customer_detail 已返回包含寿险客户号 clientNo 等核心档案信息的情况下，系统在后续轮次中再次对同一 customer_id 发起 customer_detail 仅请求 clientNo 字段，存在冗余重复查询。
- 观察：消耗额外工具调用预算与执行时间，违反重复调用控制与证据足够时不重复检索的系统策略规范。
- 证据：exp-plan-05, turn1/records/run/step_executor_runs/0/messages/8, turn1/records/run/step_executor_runs/0/tools/1, turn1/records/run/step_executor_runs/0/tools/4
- 归属（模型自述）：本轴

## P81  case=main-D01-same-surname-clarify
- 主张：[程序判定] 工具返回原样进入下一次模型输入：该调用之后的所有请求侧正文里找不到返回正文，也找不到返回里的取值
- 观察：程序逐字比对
- 证据：turn1/records/run/step_executor_runs/0/tools/1, 程序-工具返回-1
- 归属（模型自述）：本轴

## P82  case=main-D01-same-surname-clarify
- 主张：[程序判定] 执行余量提示随用量更新：7 处提示逐字相同（剩余 10 次调用、约 598 秒），期间已有新的调用与结果，提示未刷新
- 观察：程序逐字比对
- 证据：turn1/records/run/step_results/2/steps/0, turn1/records/traces/0/tree/0/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/1, turn1/records/traces/0/tree/0/spans/3/spans/3, turn1/records/traces/0/tree/0/spans/3/spans/5, turn1/records/traces/0/tree/0/spans/3/spans/7, turn1/records/traces/0/tree/0/spans/3/spans/9, 程序-执行余量提示
- 归属（模型自述）：本轴

## P83  case=main-A01-fuyunping-list-aggprem
- 主张：[程序判定] 交付链未新增缺口：该环节产出带 status='PARTIAL'，新增缺口说明（本轮所有模型产出里都找不到出处，是包裹步骤自己加的）：部分内容未能在本轮证据中对应，请结合原始资料核实。
- 观察：程序逐字比对
- 证据：turn1/records/run, turn1/records/run/step_results/2, turn1/records/run/step_results/3, turn1/records/traces/0/tree/0/spans/5, 程序-缺口-3, 程序-缺口-5
- 归属（模型自述）：本轴

## P84  case=main-D01-same-surname-clarify
- 主张：系统首批工具调用参数遗漏了用户明确要求的“我名下”归属限定以及“按客户号升序”排序约束。
- 观察：内部表达及首批工具调用参数中仅包含姓平、12月份生日、女性，遗漏了“我名下”客户归属对象，且未包含后续子问题涉及的详细资料与保单状态对象。
首批工具调用参数中未保留用户明确要求的“按客户号升序”排序约束与“我名下”归属约束。
首批工具调用参数遗漏了“我名下”客户归属对象限定。
内部表达工具参数未完整保留用户指定的“我名下”客户归属对象与字段。
内部表达工具参数中未保留“按客户号升序”排序要求及“我名下”范围约束。
内部表达工具参数未保留用户指定的排序及归属约束。
- 证据：turn1/records/run, turn1/records/run/step_results/0
- 归属（模型自述）：local

## P85  case=smoke-policy-list-fuyunping
- 主张：模型在已完整查得伏云平名下两张保单详情并自称具备全部回答所需信息的情况下，未输出保单答复，反而违背工具定义调用只针对单张保单详情查询的 run_policy_field_lookup 工具导致流程中断
- 观察：模型输入中已查得客户名下2张保单的完整详情且模型在正文中声明具备所有回答所需信息，但仍发起调用了针对单张保单详情查询的 run_policy_field_lookup，违反工具适用规则
模型在已获取客户名下两张保单完整信息后，未输出答复告知伏云平名下的保单
模型在已掌握所需保单事实的情况下未忠实整合输入输出保单结果，而是发起多余且错误的工具调用
- 证据：turn1/records/traces/0/tree/0/spans/3/spans/8, turn1/records/traces/0/tree/0/spans/3/spans/9
- 归属（模型自述）：local

## P86  case=main-D01-same-surname-clarify
- 主张：系统在内部表达第一阶段检索需求时丢失了“按客户号升序”的排序约束。
- 观察：排序条件在表达环节被遗漏，无法确保候选列表按用户要求的顺序呈现。
- 证据：exp_sort_order, turn1/records/run/step_executor_runs/0/tools/0/tool_args
- 归属（模型自述）：本轴
