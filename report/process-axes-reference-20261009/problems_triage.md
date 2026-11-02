# 盲写两遍所报问题的归类（我的判断，逐条可推翻）

## 真实问题清单（R1–R9）

- **R1** 保单·模型第二次输出违反系统提示词的输出契约（文字+JSON 混合、缺 claims、自填姓名/状态、自由文本含未引用的结论）｜程序可核，A/B1/B2/现行均有
- **R2** 保单·交付附带假缺口并标 partial（模型 gaps=[]，交付变成「部分内容未能在本轮证据中对应」）｜程序可核
- **R3** 两个 case·「本轮执行余量」不随用量更新（五次调用读数完全相同）｜程序逐字核对
- **R4** D01·「按客户号升序」「我名下」在所有查询里丢失，全程未交代｜程序可核
- **R5** D01·AMBIGUOUS 后换措辞重试（违反系统提示词「不得改写同一问题/重复调用已失败来源」）｜原文可核
- **R6** D01·「确定选中后再查详情和保单状态」没有保留在任何结构化状态里（账本只存了澄清问题）｜可争议：原话仍在会话历史
- **R7** D01·澄清/交付没说明真实原因，缺口说明笼统｜原文可核，程度低到中
- **R8** 保单·当前状态的 as_of 为 null，答案却当作当前值陈述，没披露时点未知（系统提示词 L6）｜有规则依据，但 L6 写的是「金额按 as_of」，是否适用于状态有争议
- **R9** D01·finalize 把 status 由 NEEDS_CLARIFICATION 变成 null｜事实成立，是否缺陷待查（两个 case 的 finalize 都输出 status:null，可能是既定形态）

## 归类计数

| 来源 | 总数 | 命中真实问题 | 重复拆分 | 过度断言 | 被案卷/规则反驳 | 无法判断 |
|---|---|---|---|---|---|---|
| B1 盲写 | 29 | 17 | 2 | 3 | 5 | 2 |
| B2 盲写 | 32 | 18 | 5 | 4 | 3 | 2 |

## 谁找到了哪些真实问题

| 真实问题 | A 手写 | B1 盲写 | B2 盲写 | 现行 21 单位流水线 |
|---|---|---|---|---|
| R1 | ✓ | ✓ | ✓ | ✓ |
| R2 | ✓ | ✓ | ✓ | — |
| R3 | ✓ | — | — | — |
| R4 | ✓ | ✓ | ✓ | ✓ |
| R5 | ✓ | ✓ | ✓ | ✓ |
| R6 | ～ | ✓ | ✓ | ✓ |
| R7 | ✓ | ✓ | ✓ | — |
| R8 | — | ✓ | ✓ | — |
| R9 | — | — | ✓ | — |

## 同一规则下 A 与现行流水线的问题归类

| 来源 | 问题记录数 | 命中真实问题 | 过度/错误 | 备注 |
|---|---|---|---|---|
| A 手写 | 8 | 8 | 0 | **我评我自己**，最不可信；另有 1 个待查项（IQ1）未计入 |
| 现行 21 单位流水线 | 7 | 6 | 1 | 同一问题的不同子点各记一条，与 B 的口径一致 |

## 逐条明细

| 轮 | case | 轴 | # | 归类 | 理由 |
|---|---|---|---|---|---|
| B1 | D01 | context_memory | 0 | UNSURE | 「未携带全部历史配对」没说清楚会造成什么，自己也标了影响 no |
| B1 | D01 | context_memory | 1 | REAL:R7 |  |
| B1 | D01 | intent_understanding | 0 | REAL:R6 |  |
| B1 | D01 | intent_understanding | 1 | FALSE | 澄清是工具连续失败后触发的，不是意图轴「制造」的歧义 |
| B1 | D01 | knowledge_data | 0 | OVER | 查询没有被执行，数据源无从说话，不应记为数据源问题 |
| B1 | D01 | knowledge_data | 1 | REAL:R5 | 归因写成上游 agent，处理正确 |
| B1 | D01 | model_capability | 0 | REAL:R4 |  |
| B1 | D01 | model_capability | 1 | REAL:R5 |  |
| B1 | D01 | model_capability | 2 | REAL:R7 |  |
| B1 | D01 | model_capability | 3 | UNSURE | 最后一次是 ask_clarify 工具调用，「answer_draft 首字段」的契约是否适用于它不清楚 |
| B1 | D01 | model_capability | 4 | OVER | 选项 2 是给用户选的出路，不是系统自己去掉条件 |
| B1 | D01 | planning_routing | 0 | REAL:R4 | 另含「姓平被改写」，那是 R5 |
| B1 | D01 | planning_routing | 1 | REAL:R5 |  |
| B1 | D01 | planning_routing | 2 | REAL:R7 |  |
| B1 | D01 | planning_routing | 3 | REAL:R6 |  |
| B1 | D01 | tool_execution | 0 | OVER | 断言「对受支持条件返回 AMBIGUOUS」，但没有字段登记，无法知道「姓氏筛选」是否受支持 |
| B1 | D01 | tool_execution | 1 | DUP | 同上，tools/1 |
| B1 | D01 | tool_execution | 2 | DUP | 同上，tools/2 |
| B1 | D01 | tool_execution | 3 | FALSE | BUDGET 是预算守卫拦截（0.005 秒，未执行），不是工具故障 |
| B1 | renyanlin | context_memory | 0 | REAL:R2 |  |
| B1 | renyanlin | intent_understanding | 0 | FALSE | 两行险种记录并无冲突，工具说明只在「多行字段冲突」时禁止合成保单级结论 |
| B1 | renyanlin | intent_understanding | 1 | REAL:R8* | 时点未知未披露成立，但这是输出内容问题，不是意图轴 |
| B1 | renyanlin | model_capability | 0 | FALSE | 「本应调用 run_policy_field_lookup」没有依据：工具说明明写已有完整保单号用 policy_detail |
| B1 | renyanlin | model_capability | 1 | REAL:R1 | 文字+JSON 混合、缺 claims |
| B1 | renyanlin | model_capability | 2 | REAL:R1 | 自填姓名/状态 |
| B1 | renyanlin | model_capability | 3 | REAL:R1 | 自由文本末尾的「有效」不在 facts 里，属契约问题的一个细点 |
| B1 | renyanlin | model_capability | 4 | REAL:R1 | 自由文本含未引用 fact 的结论 |
| B1 | renyanlin | planning_routing | 0 | FALSE | 「本应走 to_capability」没有依据：输入里只有分支名，没有任何一条规则把这类问题指向它 |
| B1 | renyanlin | planning_routing | 1 | REAL:R2 | 归因写成上游 finalize，合理 |
| B2 | D01 | context_memory | 0 | REAL:R9 |  |
| B2 | D01 | intent_understanding | 0 | OVER | 这是结果（没拿到名单），不是表达缺陷 |
| B2 | D01 | intent_understanding | 1 | REAL:R6 |  |
| B2 | D01 | intent_understanding | 2 | REAL:R4 |  |
| B2 | D01 | intent_understanding | 3 | OVER | 「客户号→clientNo 映射」没有规则依据 |
| B2 | D01 | intent_understanding | 4 | REAL:R6 | 「选中客户」指代没有被保留，是 R6 的一个侧面 |
| B2 | D01 | knowledge_data | 0 | OVER | 同上 |
| B2 | D01 | knowledge_data | 1 | REAL:R5 | 上游：预算/循环控制，处理正确 |
| B2 | D01 | model_capability | 0 | REAL:R4 |  |
| B2 | D01 | model_capability | 1 | DUP | 同上，第 2 次查询 |
| B2 | D01 | model_capability | 2 | DUP | 同上，第 3 次查询 |
| B2 | D01 | model_capability | 3 | REAL:R5 |  |
| B2 | D01 | model_capability | 4 | UNSURE | 同 B1：契约是否适用于澄清调用 |
| B2 | D01 | model_capability | 5 | REAL:R7 |  |
| B2 | D01 | model_capability | 6 | DUP | R4 的又一次拆分 |
| B2 | D01 | model_capability | 7 | DUP | R5 的又一次拆分 |
| B2 | D01 | planning_routing | 0 | REAL:R4 |  |
| B2 | D01 | planning_routing | 1 | REAL:R5 |  |
| B2 | D01 | planning_routing | 2 | DUP | 排序未说明，是 R4/R7 的又一次拆分 |
| B2 | D01 | planning_routing | 3 | UNSURE | present_agentos 没有执行记录：案卷只到 finalize，无法判断是否本该有 |
| B2 | D01 | planning_routing | 4 | REAL:R7 | 其中「按契约提供 claims」对一次澄清不成立 |
| B2 | D01 | tool_execution | 0 | FALSE | 同 B1：把预算守卫的拦截算成工具问题 |
| B2 | renyanlin | context_memory | 0 | REAL:R2 |  |
| B2 | renyanlin | intent_understanding | 0 | REAL:R8* | 同上，归错了轴 |
| B2 | renyanlin | model_capability | 0 | FALSE | 同 B1：run_policy_field_lookup 无依据 |
| B2 | renyanlin | model_capability | 1 | REAL:R1 | 文字+JSON 混合 |
| B2 | renyanlin | model_capability | 2 | REAL:R1 | 缺 claims |
| B2 | renyanlin | model_capability | 3 | REAL:R1 | 自填姓名/状态 |
| B2 | renyanlin | model_capability | 4 | REAL:R1 | 自由文本含未引用 fact 的结论 |
| B2 | renyanlin | planning_routing | 0 | FALSE | 「本应走 to_direct」同样没有依据 |
| B2 | renyanlin | planning_routing | 1 | REAL:R1 | 归因「未定位 agent/输出契约」合理 |
| B2 | renyanlin | planning_routing | 2 | OVER | 称「本轮证据」是被禁的内部词，但系统提示词列的是「工具返回/接口返回/EMPTY/BUDGET」，不含它 |
