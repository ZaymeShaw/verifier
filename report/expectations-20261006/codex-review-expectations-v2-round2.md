**建议修改后定稿，暂不直接替换。** 核心方向已经吸收，剩下主要是缺料状态、必要行动归因和原文覆盖的边界。此次未修改文件。

**1．上轮意见的吸收情况**

以下位置均指 [spec/draft/expectations-v2.md](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md)。

| 上轮意见 | 结论 | 位置／说明 |
|---|---|---|
| 不同轴的设计规则适用边界要分开 | 已正确吸收 | 112–118 行 |
| 原文存在不证明运行版本、规则效力 | 已正确吸收 | 120–124 行 |
| live schema 不能自动作为下游要求 | 原则已吸收，但新增状态问题 | 54、74 行；见下文① |
| capability 由维护者拆分，不静默丢需求 | 部分吸收 | 56 行的“唯一需求描述”条件过窄；见① |
| 独立需求轴、主判共用 E | 已正确吸收 | 82、88 行 |
| 块覆盖不能冒充规则全部核实 | 原则已吸收，覆盖分母未明确 | 130–134 行；见③ |
| 必要行动分三步、保留用户 E ID | 已正确吸收 | 95–99 行 |
| 区分候选与已证实应发生单位 | 部分吸收，归因被写死 | 100 行；见② |
| 补原文消费契约、条件传到问题 | 主体已吸收，跨位置条件仍需补 | 110、124、138–140 行；见④ |
| 修改变更范围、删除无依据判断、补验收 | 基本吸收 | 25–32、148–163 行；统计出处有小问题，见⑤ |

**2．仍有的问题及最小修改**

① **缺料规则会同时产生误报和漏报。**  
[草稿:54](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:54)、74、162 行把“下游未登记”一律判 partial，但需求明确允许下游就是用户本人（[需求:73](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/expectations.md:73)）。应区分“已确认无独立下游要求”和“存在或可能存在要求但未取得”；同时确定登记位置、维护者。  
56 行则相反：即使已有用户原话，capability 中仍可能含**其他来源没有覆盖的验收要求**。不能只在它是唯一需求描述时才报缺料。应要求维护者确认拆分／覆盖完成，否则保留缺口。

② **“仍必需且未发生 → 规划问题”违反证据驱动归因。**  
[草稿:100](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:100)直接指定规划责任；实际也可能是需求漏传、意图漏识别，或者原因无法定位。[六轴协议:81](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/alg/process-axes.md:81)要求输入无效必须引用具体、有证据的上游问题。  
最小修改：必要性与发生情况分开记录；未发生后再定位责任，不能定位则缺证／归因未定位。另补98行“无法确定”如何进入覆盖和结果，不能让这类候选消失。“应发生”也不应仅在未发生后才成立。

③ **原文块覆盖的分母不能由判定者先筛掉。**  
[草稿:130](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:130)只要求记录“适用范围内”的块，却没有定义谁生成清单。若模型先挑适用块，再对挑出的块全部回执，仍可漏规则而通过覆盖。  
最小修改：材料交付方预先列出候选原文块清单，判定逐块标注已核对／不适用／无法确定；程序只证明清单交付与处理完整，适用性仍是语义判断。无需新增调用或逐规则登记。

④ **“完整规则句”仍不保证条件完整。**  
[草稿:110](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:110)、124、139 行没有明确处理条件、例外位于另一句、父级章节或关联 schema 的情况。程序不能从一个摘录自动恢复这些语义。  
最小修改：允许一条判准关联多个原文位置，分别保留规则及必要条件／例外；程序核对定位和原文一致性，再原样组成问题预期，不自行补写条件。

⑤ **统计引用有小偏差，不是架构阻塞。**  
[草稿:32](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:32)归引需求§5，但需求写的是166条，也未列“128条中64条挂到单位”。167条有[实施记录:198](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:198)支持。应分别标样本／报告来源，避免把不同运行拼成同一次统计。

**3．能否定稿替换**

**修完①–④，并同步六轴协议的候选行动、归因和原文引用口径后，可以定稿替换；⑤顺手校正。** 不需要再增加规则提取流水线，也不需要重做六轴架构。

当前代码仍要求 expectation ID、问题预期仍丢条件，与草稿所述一致，属于已明确的待改实现，不是草稿新增矛盾。定稿通过也不代表实现验收通过，仍须按实施文档做独立对照验证。