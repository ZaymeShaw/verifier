# 8036 Langfuse 历史 Trace 复评

- 状态：已完成
- 项目：`llm_probe_loop`；场景：`verify-insurance-langfuse`
- 来源：8036 已有 mock 数据集中的 11 条 `from_trace` 用例
- 首轮批次：`c5333392bdeb42788fc2fe92062e0aeb`，并发 4
- 补跑批次：`e4866b6b605d476d85a57f1a165caa22`，并发 1
- 首条因 MCP 启动竞争未进入评测，原 trace 串行补跑一次；首轮失败记录完整保留。
- 最终结论：{'满足需求': 6, '未满足需求': 5}
- 最终执行错误：0
- 全部使用 `provided` 模式，未重新调用被测业务；评测过程使用配置的模型和核验工具。

结论为当前评测器对历史 trace 中记录交付的判定，不代表本次现场重新执行业务的结果。

## 逐条结果

| 用例 | 结论 | 本次评测耗时（秒） |
|---|---|---:|
| from-trace-fuyunping-policies | 满足需求 | 572.8 |
| from-trace-bizno | 未满足需求 | 366.3 |
| from-trace-smoke-policy-detail-renyanlin | 满足需求 | 533.9 |
| from-trace-smoke-neg-unknown-policy | 未满足需求 | 410.5 |
| from-trace-main-A02-yuxinya-status | 满足需求 | 648.8 |
| from-trace-main-B02-policy-plus-waiting | 未满足需求 | 657.6 |
| from-trace-main-C08-two-customers-parallel | 满足需求 | 901.4 |
| from-trace-main-D16-near-name-split | 满足需求 | 774.0 |
| from-trace-main-E01-ref-product-knowledge | 未满足需求 | 665.8 |
| from-trace-main-F01-name-correction | 未满足需求 | 987.5 |
| from-trace-main-G01-short-answer | 满足需求 | 383.0 |

## 详细原因

### from-trace-fuyunping-policies

Trace：`748b268f3f724c199471f60bdef19eb3`；执行批次：`e4866b6b605d476d85a57f1a165caa22`。

fulfilled · 1 blocking expectations all met · 本次评测最终结论为全部兑现（verdict: fulfilled）。其中显式期望 t1.policies_of_fu_yunping 兑现（fulfilled），交付在 answer 中明确给出了伏云平名下的两张保单及摘要，关联的 13 条过程条目全部达到；隐性期望 t1.implicit_correct 兑现（fulfilled），交付中的各项事实陈述均忠实于输入且无虚假事实，关联的 10 条过程条目全部达到。无未兑现期望。

### from-trace-bizno

Trace：`da9e51d3542e4aadbc4247f12d3c20e2`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

not_fulfilled · blocking=[t1.customer_name_by_id] · 本轮整体结论为 not_fulfilled。显性期望 t1.customer_name_by_id 未兑现（not_fulfilled），原因为交付回复未查询到记录，交付本身没给目标客户身份信息；隐性期望 t1.implicit_correct 为无法核评（not_evaluable），原因为交付虽如实反馈未命中，但底层数据源真实性在 knowledge_data.E1 无法核。

### from-trace-smoke-policy-detail-renyanlin

Trace：`f77ec8c117c24cb6b00427d5800ecde4`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

fulfilled · 3 blocking expectations all met · 四项期望全部兑现（总体判定 fulfilled）。保单P260922000005855的投保人（任言琳）、被保人（任言琳）、当前状态（交费有效）以及顺带回答的险种与保额详情均在交付中明确且准确地给出。所有对应的过程条目（前三项各16条、隐性期望5条）在trace证据组中均达标，无未达标项，因此全部兑现。

### from-trace-smoke-neg-unknown-policy

Trace：`ea528ab964da41018de5fba925b91ee0`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

not_fulfilled · blocking=[t1.insured_person] · 最终整体判定为未兑现（not_fulfilled）。其中显式期望 t1.insured_person 最终结论为未兑现（not_fulfilled），因交付仅提示未检索到保单而未告知被保人是谁，判定为交付没给；隐式期望 t1.implicit_correct 最终结论为无法核（not_evaluable），因过程项 knowledge_data.E1 缺乏外部底表真值判定为无法核，导致 trace 组无法核验回答事实是否正确。

### from-trace-main-A02-yuxinya-status

Trace：`2c21568d576b4f5488bace685ed1b482`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

fulfilled · 2 blocking expectations all met · 本次评测的全部3项期望均已完全兑现（最终 verdict 为 fulfilled）：1. 保单数量核实期望（t1.verify_policy_count）兑现，交付给出了2张保单的明确结果，trace 组21条过程条目全达到；2. 保单状态查看期望（t1.check_policy_status）兑现，交付分别列出各保单当前为交费有效状态，trace 组21条过程条目全达到；3. 隐性正确期望（t1.implicit_correct）兑现，交付事实忠实于工具结果且格式规范，trace 组6条过程条目全达到。所有过程条目均达成，无挑战项。

### from-trace-main-B02-policy-plus-waiting

Trace：`b4781ff3bdea44ae82f966db67b1a9c4`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

not_fulfilled · blocking=[t1.explain_waiting_period] · 最终整单结论为 not_fulfilled。兑现情况为：核实余昕雅投保情况（t1.check_yuxinya_insurance）成功兑现（fulfilled），交付明确确认且 20 项 trace 过程条目全部达到；解释等待期（t1.explain_waiting_period）因知识库未查到、交付未给出等待期具体内容而判定没给，期望未兑现（not_fulfilled）；隐性正确性（t1.implicit_correct）因过程条目 knowledge_data.KD-3 判定为无法核，trace 组无法闭环核实，状态为无法核验（not_evaluable）。

### from-trace-main-C08-two-customers-parallel

Trace：`602f859d508a476481e123c490c7b9f0`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

fulfilled · 3 blocking expectations all met · 本轮回答能力兑现判定结论为全部兑现（fulfilled）。具体情况如下：1. 伏云平保单查询（t1.fuyunping_policies）兑现，交付包含其名下2张保单，19条过程条目全部达到（trace组过）；2. 余昕雅保单查询（t1.yuxinya_policies）兑现，交付包含其名下2张保单及险种明细，19条过程条目全部达到（trace组过）；3. 保单列表分组（t1.policies_grouped）兑现，按两组独立表格呈现，交付直接满足无需额外证据；4. 投保人概念解释（t1.explain_policyholder）兑现，全面说明概念、权利义务及主体资格，14条过程条目全部达到（trace组过）；5. 事实准确性隐性期望（t1.implicit_correct）兑现，所有断言均有据可依，23条过程条目全部达到（trace组过）。5项期望均已完全兑现，无未兑现项目。

### from-trace-main-D16-near-name-split

Trace：`68074eb8273f4650a73068687d390d1a`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

fulfilled · 1 blocking expectations all met · 1 non-blocking gaps · 本轮评估共包含 3 项期望，最终判定结果为 2 项兑现（fulfilled）、1 项未兑现（not_fulfilled），总体验收结果为 fulfilled：\n1. t1.verify_two_clients 兑现：交付明确核对并确认严言琳与严言雅为两位客户，引用的 20 条过程条目均达到，trace 组通过；\n2. t1.separate_profile_summaries 兑现：交付分别列出了两人的完整档案摘要且未合并展示，引用的 29 条过程条目均达到，trace 组通过；\n3. t1.implicit_correct 未兑现：交付给出了回答，但因过程条目 model_capability.E4 没达到（模型在发起工具调用时输出了旁白），导致 trace 组未通过，按规则判定为 not_fulfilled。

### from-trace-main-E01-ref-product-knowledge

Trace：`c04862877f854a01a4fdc8ea24439307`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

not_fulfilled · blocking=[t1.liability_exemption,t1.waiting_period] · 本次评测整体结论为 not_fulfilled，三项期望均未兑现。其中显性期望 t1.waiting_period（等待期规定）与 t1.liability_exemption（免责条款）因知识库未收录条款正文，模型在答复中说明无法给出确切天数与范围，交付本身没给，最终状态判定为 not_fulfilled（状态依据为交付没给）；隐性正确性期望 t1.implicit_correct 虽然交付本身给出了未查到的说明，但因 trace 组中过程条目 model_capability.E3（未收录后违规改写别名重复查询）和 model_capability.E6（答复夹杂内部自言自语和 EMPTY 状态词）没达到，导致 trace 组不过，最终状态亦为 not_fulfilled。

### from-trace-main-F01-name-correction

Trace：`80a022ea801046f6b5d71fc21b07acf1`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

not_fulfilled · blocking=[t1.answer_original_question_for_yuxinya] · 本轮两项期望最终均未兑现（verdict: not_fulfilled）：1. 显性期望 t1.answer_original_question_for_yuxinya 因未能提供平安安佑福重疾险的具体免责条款，判定为交付没给（not_fulfilled）；2. 隐性期望 t1.implicit_correct 虽交付了回答事实，但因过程轴 knowledge_data.KD5（检索召回无关医疗险文档）和 model_capability.MC7（正文出现内部技术术语及草稿）均没达到，trace 证据链未通过，判定为 not_fulfilled。

### from-trace-main-G01-short-answer

Trace：`1665f548e4f445c7be0d51d77bbb0629`；执行批次：`c5333392bdeb42788fc2fe92062e0aeb`。

fulfilled · 1 blocking expectations all met · 本次交互中三项期望均已兑现：保单P260922000009116的累计已交保费数额1089.1元已准确给出，trace 组14条过程条目全部达到，期望 t1.cumulative_paid_premium 判定为 fulfilled；答复仅给出金额数值无多余闲聊，满足格式要求，期望 t1.format_amount_only 凭交付判定为 fulfilled；陈述事实准确无误导，trace 组13条过程条目全部达到，期望 t1.implicit_correct 判定为 fulfilled。总体结论为 fulfilled。

## 留存文件

- `openapi.json`：8036 接口定义。
- `datasets.json`：8036 数据集快照。
- `workspace-before.json`：启动前候选区与原有 22 条结果。
- `batch-request.json`、`batch-start.json`：首轮请求与启动回执。
- `first-batch-final.json`、`first-workspace.json`：首轮完整结果，含原始 MCP 错误。
- `retry-request.json`、`retry-start.json`、`retry-final.json`：串行补跑记录。
- `workspace-final.json`：最终 11 条结果。
- `summary.json`：机器可读汇总。
