# 8021 首批四条 LLM Trace 诊断

导出批次：`b9712b378fba4f1cbb08e4ca22d94293`；实例：`inst-16fa340ac786414f`；首批执行身份仅限该批次 `:0/:1/:2/:3`。批次北京时间 2026-10-06 17:33:37 启动，首批最后一条的主判上下文在 18:46:21 落盘。18:49 查询确认四条全部进入终态后即导出，没有等待后续 28 条。

## 结论

慢和报错主要集中在评测器的上下文交付与输出契约工程，而不是“工具调用次数还不够”。四条业务执行 10 秒至 2 分 53 秒，评测却各耗 52 分 52 秒至 72 分 34 秒；24 个过程轴执行中 13 个失败。即便程序接口全部成功返回，也不能将其理解为六轴语义验收通过。

已经确认三类实施问题：μ 的来源匹配把配置容器与实际消息正文作结构比较，产生可复核的误拒；归因字段没有枚举约束，中文提示使用希腊轴符号而校验器要求英文 ID；承诺覆盖没有变成显式待提交单元，最后才发现漏项且无法走现有纠错。实际与期望材料拆成串行请求、跨请求重复全文，以及失败后整批重判进一步放大延迟。真实上游长时间生成和一次 600 秒超时也有贡献。

业务本身另有问题：保单列表内部取到了数据但 JSON 输出/桥接失败后未交付；客户资料遭到工具容量拒绝，只返回繁忙提示。这两条主判为 not_fulfilled。它们与评测器协议错误必须分开；本报告不把主判本身当作人工语义金标。

## 数据与口径

导出了 93 次评测网关请求：92 次网关终态成功、1 次失败、0 次未结束，无身份冲突；86 份完整 context_store 记录（82 份轴阶段 + 4 份主判）。86 个逻辑调用对齐到 88 次网关尝试，多出的两次是客户资料 σ 的主备端点切换。另 5 次网关请求属于承载性判定，未计入下表的 86 个上下文逻辑调用。网关成功只说明传输/模型响应完成；业务语义和下游 validator 可以仍然失败。

这里的网关是 verifier 的评测请求，不是对被测业务全部模型调用的网络重采集。被测业务调用原文来自本批 trace/案卷里的插桩记录；两种来源均保留。

| 首批用例 | 业务执行 | 评测 | 端到端约计 | 主判状态 | 失败过程轴 | 上下文逻辑调用 | 整批纠错次数 / 追加耗时 |
|---|---:|---:|---:|---|---:|---:|---:|
| 保单列表（付云平） | 2分53秒 | 62分44秒 | 65分37秒 | not_fulfilled | 4/6 | 22 | 3 / 11分18秒 |
| 保单详情（任艳琳） | 0分14秒 | 62分35秒 | 62分48秒 | fulfilled | 4/6 | 20 | 5 / 20分55秒 |
| 客户业务号（何成琪） | 0分21秒 | 52分52秒 | 53分14秒 | fulfilled | 1/6 | 23 | 2 / 4分11秒 |
| 客户资料（付云平） | 0分10秒 | 72分34秒 | 72分44秒 | not_fulfilled | 4/6 | 21 | 5 / 22分08秒 |

端到端约计为存档 stage_timings 的 live_ms + judge_ms，不包含可能的调度间隙。评测耗时以 stage_timings.judge_ms 为准；模型耗时以 context.elapsed_ms、网关 latency_ms 各自统计，两者不重复相加。四条并行，表中时长不能相加当成用户等待时间。四条累计评测约 250 分 45 秒，其中 15 次显式纠错重判累计 58 分 32 秒（23.34%）；这包含纠错那次内部的 600 秒端点超时，不能再把超时重复加到纠错总计。

| 阶段 | 逻辑调用次数（四条合计） | 模型上下文累计耗时 |
|---|---:|---:|
| 需求期望 E | 4 | 13分23秒 |
| 案卷整理 | 16 | 15分03秒 |
| 六轴消费投影 | 4 | 7分26秒 |
| κ 上下文 | 11 | 31分15秒 |
| ι 意图 | 10 | 20分35秒 |
| ρ 编排 | 10 | 49分09秒 |
| χ 工具 | 9 | 33分54秒 |
| σ 数据 | 9 | 26分08秒 |
| μ 模型 | 9 | 42分39秒 |
| 主判 | 4 | 10分33秒 |

需求 E 和消费投影四条合计 20 分 49 秒，平均每条约 5 分 12 秒。案卷整理实际只用了 3/5/5/3 轮；保单列表使用 14 次工具调用、业务号 13 次，均在 8 轮 LLM 预算内完成。预算优化已生效，当前主要耗时不在案卷工具计数上。不能把扩展轴 usage 中个别计数当作整案请求总数；call-stats.json 提供逻辑调用与网关尝试的独立口径。

## 1. μ 来源匹配存在确定性的结构误拒

代码：[/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:210](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:210)，尤其 `contains` 与第 248–250 行。

定格 E 的 system 来源 value 是 `{"instructions":[原文A,原文B]}`；插桩记录的该次实际请求则是 `{"messages":[{"role":"system","content":"…原文A…原文B…"},…]}`。校验器寻找整个来源 dict，不会把声明型 instructions 容器解析成应核对的规则文本。请求里没有 instructions 这个配置键，于是不能匹配，即便文本已进入本次输入。

离线核对四条各自首个 μ 请求的 exact_request：字段 status=available、scope=current，注释为“插桩在模型调用处记录的请求消息”；每条 E 的两段 instructions 都逐字存在于该次 system content，结果都是 2/2。证明见 [mu-instructions-proof.json](mu-instructions-proof.json)。该证明只确认这四个请求中的系统规则文本，不声称所有工具定义、所有期望或后续调用都有效匹配；更不能依据采集时定义推断其他调用。对业务号 final μ 拒绝可参照 `f1c218b9-921d-4fc5-bc01-4a884eca6156` 的响应，以及 contract-audit.json 的逐项失配记录。

建议：按声明的类型做确定性、带出处的投影，将 instructions 模板元素与本次 system 消息正文对应；保留版本、轮次、调用输入边界，不用外部定义直接补齐输入。错误回执应列具体 expectation_id、source_ref、目标输入 ref 和失配原因，让模型能针对缺证正确作答。不能让模型改写业务结论来绕过程序比较错误。

## 2. 归因 ID、schema 与提示词不一致

代码：[process_protocol.py:21](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_protocol.py:21) 的 `attribution_axes: list[str]` 允许任意字符串；[同文件:69](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_protocol.py:69) 只接受六个英文轴 ID。system 用 `ι/ρ/χ/σ/μ/κ` 说明归属，却没有在问题归因字段明确列出允许值。

10 个响应中实际出现希腊符号归因。客户资料 χ 第一次和重判都填 `["χ"]`；σ 首次备用响应和重判备用响应都填 `["σ"]`。错误回执只有“问题归因必须是已知且不重复的轴”，没有允许值，第二遍仍然原样犯错。这不是“再多给一轮”能保证解决的问题。

证据：客户资料 χ 重判 `7d6e2028-5135-4e54-a048-ae3cbd371e92`；σ 重判备用 `a49c8d2e-3f27-4c4f-9308-3ba848f62180`；保单详情 χ 重判 `d4323e89-e636-4364-aafc-a7dba9dc7d78`。call-stats.json 的 bad_attribution_axes 保留字段值和 problem_id。

建议：在类型/schema 中枚举六个合法英文 ID，字段说明明确希腊符号只用于展示；校验回执返回字段路径、实际值、允许值。当前 93 次 wire 请求均没有 response_format，schema 作为 system 中的文字约束传递；[llm_client.py:888](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/core/llm_client.py:888) 显式关闭 native/json_schema 输出支持。因此“有 dataclass/schema”不等于“模型端原生强约束已生效”。先修现有文本/schema 契约一致性；若引入原生约束，需单独验证当前主、备用端点确实支持，不能静默假设支持。

## 3. 承诺覆盖直到轴尾才检查，模型没有显式工作清单

代码：[required_units:102](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:102) 只按 data_needs/want 展开应发生单位；[contracts_for:125](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/expectation_projection.py:125) 给本轴承诺列表，但没有为每条 commitment 分派一次确定的检查责任。prompt 要求全部核对，pending 却仅枚举义务×环节；模型完成 pending 并不保证覆盖所有承诺。

[process_common.py:523](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_common.py:523) 在所有批次完成后才调用 validate_contract_coverage。这个检查在单批 ask 的 try/except 之外，因此“承诺侧期望未核对”不进入那一次纠错，而直接让整轴失败并清空输出。保单详情 σ 漏掉 29 项；保单列表 χ、σ 与客户资料 κ、ι 也在这里失败。缺项清单见 first-wave-results.json 的最终 error，原请求及已返回检查见 contexts/。

建议：在批次规划时把每条本轴 commitment 的适用性/条件检查显式分派给有证据的单位，形成完整、唯一的待提交清单和所需 source refs。条件不成立应有明确检查结果，不能删除要求来通过覆盖。轴尾保留总覆盖门禁；可修复的缺项在提交前进入有界纠错，而不是付完全部请求成本才丢弃整轴。必要的缺证仍应显式表达，程序运行失败不能降格成业务缺证。

## 4. 证据引用的粒度与模型自然写法不一致

[process_common.py:277](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_common.py:277) 只接受已交付记录 ID/特殊 ref；例如业务号 χ 的资料里已经交付 tools/0、tools/1 的 arguments、result、error、metrics，但模型写 `tools/0/result`、`tools/0/metrics` 等子路径，被判“引用未交付正文”。重判 `d2b2ced4-ba14-4544-a549-eeb9ead02fad` 额外用了 1 分 53 秒。

不是所有该类错误都是误拒：`run_input` 与案卷 `input`、`tool_args` 与 `arguments` 等名称也不一致；某些 messages 的正文确实没随该批交付。不能统一容忍任意子路径。contract-audit.json 区分了已交付父记录及具体字段；它是定位资料，不是自动认定所有子路径都合法。

建议：给模型显式可引用 ID 清单和字段级合法地址；选择一种稳定引用契约：record_id + field/path，或确定性验证子路径映射。对确实没交付的内容继续拒绝，允许已交付且真实存在的字段被准确定位，避免为了指向更细原文被误当缺证。

## 5. 材料规划导致重复全文和批次变大

[process_common.py:424](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_common.py:424) 分别准备实际环节批次和应发生单位批次，再串行拼接；第 445–447 行在应发生批次里追加同轮所有候选，重新生成 view，却没有按扩展后的实际体量重新规划。[business_trace/materials.py:149](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/business_trace/materials.py:149) 的 80,000 字符只约束初次分组，且单个不可拆环节允许超额；重复 extra_refs 和后加候选使最终请求远大于最初 batch.chars。

实际 58 个过程轴逻辑请求中，39 个属于实际环节批次（含纠错）、19 个属于期望批次（含纠错）。客户资料 κ actual 第一批有 21 条 records；期望第二批也有这 21 条、45 个相同正文 hash，只新增两个应发生单位，却再发送约 10.1 万字的 user prompt，耗时 5 分 53 秒。业务号 ρ 的实际和期望批次都含 16 条 records，122 个正文 hash 相同。去重只在单个 view 内，不会跨请求省 token。

过程请求累计重复发送 expectation_sources 877,211 字符；最长 dossier_view 达 197,200 字符（保单列表 κ batch3，`1d092519-a6ab-4502-bd77-d135523d789d`）。86 个评测上下文累计 prompt_size 为约 917 万字符；评测 wire 消息实际 content 累计约 855 万字符，二者有约束注入/编码等口径差异，不能当作相同量。没有截断或取消必要证据来换速度的建议。

建议：先按真实证据并集统一规划实际+应发生单位；在保留每条完整输入输出和覆盖检查的前提下，能同批就同批。候选扩展、判准原文、问题上下文都纳入最终批次成本计算；只交付该批负责核对及引用所需的原文，不能按关键词裁剪规则。对于不可拆的大调用仍完整交付并明确标记。不要简单把两份大批次拼到一起。

## 6. 全量纠错、长时间生成和超时使延迟叠加

[process_common.py:491](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_common.py:491) 捕获一个 ValueError 后把整个 user prompt 加一行错误再发送，之前的结果和精确字段诊断没有作为局部修复输入。15 次纠错共 58 分 32 秒。单位 outcome 与逐项 expectation_checks 的归并优先级是程序已知的确定性关系，却让模型两处重复生成并在不一致时整批重做；应先消除这种可计算的冗余，保留原始检查和违规证据。

93 次请求的首帧全为 thinking；首帧延迟中位数 12.389 秒，最大 141.657 秒。几次 7–9 分钟请求在约 10–14 秒就收到 thinking 首帧，后面仍有很长的流式生成，不能解释成一直排队未响应。例如客户资料 ρ expected 请求 `c7603a79-53bd-46a7-af72-891af6cd73d7`：low effort、首帧 11.886 秒、总 544.524 秒；保单列表 ρ 第一批 `3d683f3c-501f-4243-9c23-0e87b99f054a`：首帧 13.995 秒、总 538.798 秒。日志保存的 reasoning 文本累计约 138 万字符，最终 content 约 74 万字符。由此可确认长推理/生成存在，不能从这些数据进一步把网络、排队、prefill、reasoning、最终 JSON 各自精确计时，也没有证明纯粹减输入就能按比例缩短耗时。

客户资料 σ 的两次逻辑请求都切到备用：首次 primary 24.245 秒后报“COMPLETED 但无正文”，随后 fallback1 64.562 秒成功；纠错请求 primary 达 600.010 秒墙钟限额后转 fallback1 31.178 秒成功。后一请求网关留下 failed/incomplete 记录 `27fd9fed-f181-47a4-9812-a17139e37b44`。因此此前根据顶层 context.error 为空、已有早期请求单次成功得出的“没有端点重试”只适用于当时已完成的记录，不能外推至最终整批。

65 次请求声明 low effort、16 次 medium、12 次 high；需求 E、投影、主判也有 high。应优先修协议矛盾和冗余工作，随后用冻结输入、固定端点验证 reasoning 策略、输出规模和有界局部纠错的效果，不能直接降模型/降质量来掩盖验收失败。

Token 原样累计：prompt_tokens=4,250,607；completion_tokens=286,691；reasoning_tokens=1,051,034；total_tokens=4,537,298。92 次有 usage，1 次失败无 usage；89 次上游报告的 reasoning_tokens 大于 completion_tokens，且 total_tokens=prompt+completion，口径不自洽。call-stats.json 明确标记此问题；不能用这些字段相减算“可见 token”、计算推理占比或账单。输入 token 总计也仅是接口报告值，未做独立 tokenizer 核验。

## 优先实施顺序与验收方式（本轮未改代码）

1. 修 μ 对声明容器的确定性原文投影、轴 ID 枚举和字段级错误反馈；用此次冻结请求复现误拒，再验证真正缺输入时仍拒绝。
2. 把 commitment 条件检查和 want 单位一起变成显式覆盖清单；每条检查分派一次，确保遗漏在有界提交修复内可被补齐，轴尾仍保留整案门禁。
3. 明确记录/字段引用契约，允许细粒度真实引用，拒绝未交付内容。把可计算的 outcome 归并从模型重复输出中移除；对不可计算问题采用定位到字段/单位的有界纠错，修复结果必须经过全部相关校验，不能随意拼接。
4. 在最终证据并集上统一分批，减少实际与期望两路重复；对 matched 候选、完整判准、重用的正文计算真实预算。
5. 再验证执行并发与 reasoning 策略。当前 [runner.py:331](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/runner.py:331) 顺序执行六轴，并把成功轴问题放入后续 recorded_issues；盲目六轴并行会改变依赖语义。可以先研究同轴独立批次并行或明确依赖的 DAG，但要验证问题引用闭合和合并一致性，不能把并行当作第一步掩盖协议失败。

后续验证应分别统计：协议成功/拒绝、逐项语义覆盖、业务结论正确性、请求数、重判次数、墙钟与 token 口径。保留 JSON 整段契约、实际输入边界、条件不成立显式检查和缺证结果。先用冻结数据做程序复现；真实模型重判需要后续明确授权，本轮没有发新请求。

## 逐次纠错索引

下表记录收到第一轮校验拒绝后发出的整批重判。其错误列是触发原因，不等于第二轮最终错误；最终轴状态以 first-wave-results.json 为准。fallback 两次已纳入逻辑请求 elapsed，不重复算。

| 用例后缀 | 阶段 | 追加耗时 | 网关 call_id | 触发错误 |
|---|---|---:|---|---|
| policy-list-fuyunping | llm_probe_process_planning_routing_batch1 | 7分23秒 | `7e093265-7614-49e9-a39d-24ac7af10755` | 单位结论必须保留期望逐项核对中的偏差/缺证 |
| policy-list-fuyunping | llm_probe_process_knowledge_data_batch1 | 0分43秒 | `d4656e7f-5e3a-4715-81ff-7662074d6427` | 引用未交付正文 |
| policy-list-fuyunping | llm_probe_process_model_capability_batch1 | 3分11秒 | `a74cb64b-a66b-4f09-8824-c7a0d906b0d9` | 单位结论必须保留期望逐项核对中的偏差/缺证 |
| policy-detail-renyanlin | llm_probe_process_context_memory_batch1 | 2分13秒 | `5ee083ff-2b7d-429d-8171-aa035a5a79f6` | 引用未交付正文 |
| policy-detail-renyanlin | llm_probe_process_intent_understanding_batch2 | 1分35秒 | `a9469c2b-2f43-4908-8902-8bba150d55fe` | 引用未交付正文 |
| policy-detail-renyanlin | llm_probe_process_planning_routing_batch1 | 2分53秒 | `77d78ec3-29d7-4440-954e-e40933ee1051` | 没有已定格判准不能判通过或违约；应报告缺判准 |
| policy-detail-renyanlin | llm_probe_process_tool_execution_batch1 | 7分53秒 | `d4323e89-e636-4364-aafc-a7dba9dc7d78` | 问题归因必须是已知且不重复的轴 |
| policy-detail-renyanlin | llm_probe_process_model_capability_batch1 | 6分21秒 | `223eafba-8407-4942-89a6-a17889525230` | 单位结论必须保留期望逐项核对中的偏差/缺证 |
| customer-bizno-hechengqi | llm_probe_process_tool_execution_batch2 | 1分53秒 | `d2b2ced4-ba14-4544-a549-eeb9ead02fad` | 引用未交付正文 |
| customer-bizno-hechengqi | llm_probe_process_model_capability_batch1 | 2分18秒 | `f1c218b9-921d-4fc5-bc01-4a884eca6156` | 模型引用不属于该次实际输入端点 |
| customer-profile-fuyunping | llm_probe_process_intent_understanding_batch2 | 1分43秒 | `75d24b50-2bfb-406c-b390-c36fdb9598ab` | 引用未交付正文 |
| customer-profile-fuyunping | llm_probe_process_planning_routing_batch1 | 5分16秒 | `d3535146-8a99-4364-8733-443ef00577bb` | 没有已定格判准不能判通过或违约；应报告缺判准 |
| customer-profile-fuyunping | llm_probe_process_tool_execution_batch1 | 1分16秒 | `7d6e2028-5135-4e54-a048-ae3cbd371e92` | 问题归因必须是已知且不重复的轴 |
| customer-profile-fuyunping | llm_probe_process_knowledge_data_batch1 | 10分31秒 | `27fd9fed-f181-47a4-9812-a17139e37b44` | 问题归因必须是已知且不重复的轴 |
| customer-profile-fuyunping | llm_probe_process_model_capability_batch1 | 3分22秒 | `fa7d06d2-b3da-4f8e-8f3f-5e30f4a91088` | 期望原文未证实进入本次模型输入；采集时定义不能替代调用原文 |

## 交付文件与复核

- [llm_trace.html](llm_trace.html)：现成 llmtrace 导出的 93 次请求/响应浏览报告。
- [raw-pairs.jsonl](raw-pairs.jsonl)、[gateway-events.json](gateway-events.json)：按四个 execution_id 精确过滤的原始网关配对/事件（CLI 自动脱敏）。
- [first-wave-results.json](first-wave-results.json)：四条完整终态、业务 trace、轴输出/失败原因、usage。
- [call-stats.json](call-stats.json)：每个网关 call、上下文阶段、原文区块字符数、修复原因、case/phase 聚合。
- contexts/：四条案卷评测与主判上下文原文；contract-audit.json 和 mu-instructions-proof.json 为离线证据审计。
- export-manifest.json、analysis-manifest.json：身份、导出 argv、返回码、原文及诊断文件的哈希；source-snapshot/ 保存此次定位实现的版本。
- reproduction/：生成与审计脚本，全部只读源记录并写报告，没有模型/业务调用。

文档里的时间均为本次日志测量；优化方向尚未实施，也不承诺消除纠错就能节省全部 58 分半（部分重判是必要的真实语义修复）。没有修改需求/方案文档、代码或运行数据；没有重启/停批次。首批导出后保留该目标批次的只读监控。
