整体方向一致，**建议修改后定稿**。关键是不要把“模型轴只能依据实际输入”扩大成所有轴的规则。此次未修改文件。

**1．与需求或代码事实不一致的地方**

- **设计规则的适用边界过窄。** 草稿把所有设计判准限定为“该次行使实际收到的输入”。这会让“应该送达、实际上漏传的规则”无法用于上下文轴归因。应分开：模型轴核对实际收到的规则；传递轴比较有依据的应交付端和实收端；工具、规划核对已确认适用于当次执行的规则。现有代码也只对模型轴实施输入成员检查。依据：[草稿:109](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:109)、[代码:295](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:295)、[实施:212](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:212)。

- **“设计规则本来就在运行前存在”不能证明拿到的是当次版本。** 调查中的 13 份声明都未经运行版本核验；引文出现也不自动证明它具有规则效力，例如被引用的数据、示例。应保留来源、角色、版本和适用范围核对。依据：[草稿:37](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:37)、[实施:198](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:198)。

- **`live schema` 不能自动升级为下游需求。** 必须确认它代表消费方要求，而非业务系统自身声明或 verifier 的传输封装。需求文档尚未确定下游要求的登记位置和维护者，草稿这里属于新增提案，应明确标注。依据：[草稿:47](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:47)、[需求:25](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/expectations.md:25)、[需求:73](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/expectations.md:73)。

**2．三个 ⟡ 的建议**

- **`capability`：由配置维护者明确拆分，不在每个 case 中让模型重新分类。** “用户办什么事、怎样算办成”放场景需求／判准；业务背景作理解材料；自身能力声明留在需求之外。可以暂不交付混写原文，但不能因此静默丢失其中唯一存在的需求并报告 complete。当前代码确实排除了 `capability`，但这只能说明现状，不能证明符合新需求。依据：[草稿:53](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:53)、[需求:70](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/expectations.md:70)、[代码:120](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/business_trace/expectation_material.py:120)。

- **产出方：保留独立需求轴。** 已有实现，且最容易保证先定格、多方复用。主判只引用同一份 E 的 ID／内容指纹，不能重写另一份。挪到主判内部没有明显收益，反而需要重新证明输入隔离。依据：[草稿:89](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:89)、[需求:38](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/expectations.md:38)。

- **“挑漏了”：支持原文块覆盖，但不恢复逐条规则登记流水线。** 同一次判定记录块的处理情况，至少允许“已核对／不适用及原因／无法确定”。程序证明块没有漏交付、漏处理；块内语义漏检靠独立原文审阅和对照样本检验。不能把“每块有回执”表述为“规则全部核实”。依据：[草稿:115](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:115)、[实施:226](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:226)、[实施:308](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:308)。

**3．§5.1 还不够，建议明确分成三个判断**

- **是否需要额外事实**：依据 E、时效要求及任务性质判断，不能由“工具存在”推出。
- **有哪些可用实现方式**：工具说明只证明候选能力；工具目录缺失不取消用户目标的工作覆盖检查。
- **当时是否仍必须行动**：结合已有有效数据、缓存、等价路径和刷新规则，形成“已满足／仍必需／无法确定”的有证据结论。

第 99 行已经补了候选概念，但第 97 行“有工具能提供→应取数”仍应删除；“不引用期望编号”应改为“能力出处不再引用 commitment 编号”，**对应用户需求的 E ID 仍须保留**。依据：[草稿:96](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:96)、[实施:236](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:236)。

还必须同步区分**候选单位与已证实应发生单位**：现行协议和代码禁止应发生单位用 `not_applicable` 跳过，直接沿用会误伤有效缓存；直接删除禁令又会放过遗漏。依据：[协议:75](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/alg/process-axes.md:75)、[代码:255](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:255)。

**4．建议删补的段落**

- **改掉“变化只有一处”。** 主判从“将来接入”变成此次共用 E，下游要求来源和消费者引用协议也发生变化。依据：[草稿:23](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:23)、[现行方案:270](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/alg/expectations.md:270)。

- **补一个原文判准消费契约。** 至少明确引用身份与定位、条件／例外如何保留、单位结果到问题记录如何传递。仅删 `contracts` 不够：当前 `bind_results` 仍要求 expectation ID，且问题 `expected` 只复制 statement，丢 condition。依据：[草稿:119](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:119)、[代码:231](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:231)、[代码:278](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:278)。

- **删掉无证据的“一半无关”；把“秒级到一分钟”改为待实测目标。** 补验收：规则漏传、仅采集版本不同、有效缓存与强制刷新、下游要求来源，以及条件保留到最终问题记录。现有 B、P1-A 两例不足以覆盖这些变化。依据：[草稿:29](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:29)、[草稿:125](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/draft/expectations-v2.md:125)、[实施:265](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/implementation/process-axes.md:265)。