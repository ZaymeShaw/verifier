# 过程六轴实施进展与待评审问题

日期：2026-10-06。用途：供未参与此前讨论的评审者理解现状、核对证据并提出改进建议。

## 1. 当前结论与评审范围

**第一轮协议改造已经落地，真实样本 B 完成了三轮重判，但语义验收尚未通过。最新一轮六轴运行成功，仍漏判输出格式违约；“该做却没做”的覆盖也没有得到保证。**

这里有两层系统，全文严格区分：

- **被测业务系统**：接收用户问题、调用工具并生成答案。B 是它的一条已冻结业务 trace。
- **评测器 verifier**：读取业务 trace，以模型和程序配合评六项过程能力。此次优化的对象是这个评测器。

还涉及两种 llmtracing 记录：业务侧记录被转换为 transcript（带编号的对话稿），作为待评资料；评测器自身的调用记录保存它实际收到的提示词、取证返回、提交及反馈，用于检查评测为什么判错。本次已经查阅后者，不能将两者混为一谈。

本次请评审的重点是：

1. 已发现的上下文材料和引用缺陷，是否足以解释漏判；还应检查哪些因素？
2. 如何借鉴主轴，让六个过程轴各自通过 schema 显式分析期望、再逐项判断，从而发现遗漏行为？
3. 如何验收这项改动确实改善判断质量，而不是仅让输出格式合法、运行完成？

**最新优化尚未实施。** 最近两轮仅做只读诊断和方案讨论；本轮只新增交接文档及证据摘录，不改实现、不重跑模型。以下“已落地”“已确认”“假设”“建议”分别标明，避免把讨论当成实现。

## 2. 原始需求与必须保留的口径

权威依据是文末列出的需求与方案文档。用户明确要求不得修改二者；实际方案文件名是 `process-axes.md`（连字符），不是最初口述的 `process_axes.md`。本轮及此前实施均保持二者字节不变。

业务 trace 的六项过程能力是：意图理解、规划路由、工具执行、知识数据、模型能力、上下文管理。目标不只是生成六个分数，还要支持能力汇总、单案问题与原文下钻、按独立问题聚类，以及追溯评测器自己的依据。

关键协议：

| 概念 | 含义及约束 |
|---|---|
| 判定单位 | 子能力 × 一次行使，例如“第 3 次模型调用 × 输出契约遵循” |
| 能力归属 | 比较实际产出与“在实际拿到的输入下本应产出什么”；不能把上游造成的坏结果直接算成本轴能力差 |
| 两种发现来源 | 从运行中召回偏差；从请求、期望和设计倒推应发生的行为，再到运行中核对 |
| 单位取值 | `pass / fail / input_invalid / insufficient_evidence / contract_missing / not_applicable` |
| 上游关系 | `input_invalid` 必须引用已记录、有证据的具体上游问题；不能只写“是别的轴的问题” |
| 轴结论 | `problematic / not_evaluable / sound / untested / not_applicable`，同时保留各单位取值的组成 |
| 原子问题 | 有具体预期、实际、出处及两端证据、归因和最终影响；聚类成员是问题，不是整段轴 reason |
| 评测运行失败 | 格式错误、超时、预算耗尽等记为评测 error，不能伪装成业务证据不足 |

“该做没做”不等于“日志里没看到”：如果规划实际收到任务，却在可核实的安排中漏了工作，可以记录规划问题；下游应有的取数没有有效输入，则引用上游问题。缺少足够证据时应记缺证，不能推断业务一定没执行。

需求中的 P1–P7 分别针对：未发查询与数据源缺失的区别、工具/数据归因不明、上游丢提示造成模型答错、已知问题与缺证并存、通过与缺判准并存、评测失败混成业务缺证，以及整段 reason 无法按问题聚类。新改动不能破坏这些已经确定的口径。

## 3. 已实施的内容与完成边界

| 部分 | 已落地 | 尚未证明或尚未完成 |
|---|---|---|
| 统一判定协议 | 六种单位取值、`untested`、组成、上游问题引用及案内校验 | 程序检查通过不代表业务判断正确 |
| 问题结构 | 原子问题、归因候选轴、影响、证据引用；原子问题进入聚类材料 | 实际模型仍可能错归因、过度声明影响 |
| 义务与归属 | 按方案调整工具、知识、模型、上下文义务；坏输入不豁免独立的不编造检查 | 需更多真实样本校准 |
| 普通案卷路径 | 分析阶段增加 `expected_exercises`，把预期的编排/取数加入后续覆盖 | 模型是否把预期清单拆全仍需语义验收；并非已实现六轴各自完整的期望分析 |
| transcript 路径 | 允许 `expected:<id>` 行使及期望来源；提示模型倒推编排与取数 | 没有强制期望清单；只检查每条义务至少有一组结果，不能保证所有应做单位都被覆盖 |
| 运行错误 | 删除预算失败后补业务结论的 salvage；共享运行失败不发布中途部分 verdict | 真实 high 轮仍会耗尽预算 |
| 展示与回查 | 组成、问题、判准原文、trace 证据、上游跳转进入页面；聚类使用问题 | 页面正常展示不能证明内容判断正确 |
| 冻结重判 | 新增旧/新结果与错误并排的 replay 脚本；留存模型调用记录 | 本次只重判 B，没有扩展到 A/C/D/E |

另在 B 重判后修复了两项证据校验：模型收到的 tool 消息不能冒充工具侧独立原始产出；调用元数据不能冒充到达正文。传递无损的正面核验限定为有独立两端的模型 response → 后续请求 assistant 消息。相同传递两端不能重复计数。

去重最初加得过宽，误伤“不同子问题共用同一段证据”，已收窄到传递义务并补回归。不能重新加入跨义务、跨子问题的笼统去重。

本次实施范围由根目录 manifest 的 32 个 `implementation_files` 条目及哈希界定；整理本文时全部匹配。工作区还有大量原有修改和未跟踪文件，不能把整个 `git diff` 当作本次交付；本次没有创建提交或 PR。

## 4. B 样本是什么，三轮发生了什么

B 用户请求是查询某客户的性别和出生年月。为便于转交，本文不复制客户姓名、标识符或完整个人资料。

业务侧共有三次模型调用：c1 发客户搜索，c2 根据结果发客户详情查询，c3 汇总回答。详情中的 birthday 字段说明明确提醒年份口径不能直接视为出生年份，需先确认。c3 却把它当成已确认的出生年月；同时输出了普通正文和 Markdown 围栏内 JSON。最终业务实收记录 `t1.final` 为 null，不能用 c3 输出替代最终交付。

重判只读取同一份冻结 trace，没有重新调用业务系统。用户已明确授权将 B trace 和判准发送至记录列明的主/备用评测端点；三次新运行实际均使用 fallback1 的 `qwen3.8-flash`。旧基线使用 `gemini-3.8-flash-medium`，模型不同；第三轮推理参数也不同，不能把新旧 verdict 变化直接解释成代码改进效果。

| 运行 | 参数与耗时 | 结果与用途 |
|---|---|---|
| `B/` | 默认 high；10 次请求；约 9 分 32 秒 | 六轴运行成功，但发现传递证据方向绕过、重复计数；保留为诊断资料，不采纳为验收结果 |
| `B-r2/` | 证据校验修复后 high；15 次请求；约 20 分 27 秒 | 超过实例 20 分钟预算，六轴全部运行失败；没有发布已在中途接受的部分业务结果 |
| `B-r3-low/` | 收窄去重后；仅本进程 judge 改为 low；14 次请求；约 8 分 27 秒 | 六轴运行成功，但 JSON 契约漏判；期望倒推未显式覆盖；语义验收不通过 |

low 是隔离实验，未改项目默认配置。没有证据证明“调低推理参数”改善了判断质量。

最新六轴结论：意图 sound、规划 sound、工具 sound、知识 not_evaluable、模型 problematic、上下文 not_evaluable。模型轴已经因生日口径问题为 problematic，**仍然漏了另一个独立的 JSON 问题**；只比较轴级 verdict 会掩盖这种漏判。

## 5. 核心问题一：JSON 契约为什么漏判

### 5.1 已确认的事实链

1. **契约可见。** 第一批取证返回包含 c1 参数中的 `response_format.type=json_schema`、AgentOutput schema 及 `strict=true`。业务 system 原文也要求“输出 JSON”，并规定字段。
2. **违约形态可见。** 同一批返回包含完整 c3 响应：前置业务正文 + Markdown JSON 围栏。取证回执 `next_offset=null`。不是响应被截掉，也不是只提供了 JSON 片段。
3. **契约继承关系表达不完整。** c3 调用参数被压缩成字符串“同 t1.c1”。system/tools 有显式 canonical 引用，参数继承却没有同等的可校验关系。
4. **首次判断已经漏判。** 评测器把 output_contract 写成 pass，理由集中在字段齐全、answer_draft 首字段和正文表达；没有核对“整个响应是 JSON”。它此时引用了 `t1.c1` 与 `t1.c1.system`。
5. **程序拒绝了合法契约来源的表达方式。** c3 的输入成员索引没有 t1.c1 调用记录，校验报“引用不属于该次已记录输入：['t1.c1']”。整个旧调用记录当然不应当被视为当前输入，但程序也没有给被继承的参数提供独立、有效的引用方式。
6. **模型删除了出处，没有重新展开契约。** 后续提交只保留 t1.c1.system，继续以字段齐全为由判 pass，程序接受。

证据附录 E1–E6 给出了实际提示词、取证内容、输入成员索引、两次提交和拒绝反馈。它们来自模型实际调用记录，而不只是当前代码中的提示词常量。

### 5.2 能得出什么，不能得出什么

**已确认的实现缺陷：** 参数复用采用了人可读“同前次”，但引用校验没有对应语义，导致模型看得到契约，却无法用正确粒度引用它。应修复参数材料与引用绑定，不应通过简单允许整个旧调用进入本次输入来绕过限制。

**已确认的判断遗漏：** 输出契约被缩成“字段是否齐全”等部分要求，没有逐条检查完整契约。不能把“包含一个结构正确的 JSON 对象”当作“整个响应符合 JSON 输出契约”。

**已确认的提示词差异：** 普通材料路径的 `_MATERIAL_SYSTEM` 含完整输出逐项核对、判准规范强度等要求；本次 transcript 实际 system 没有这些详细要求，主要是简短义务、统一协议及取证/提交规则。代码中的更完整提示词没有进入本次调用，不能据它声称已指导模型。

**尚未证实的成因：** 参数引用缺陷、期望拆分不足、长上下文中的注意分配、六轴共用会话，以及模型/推理参数都可能影响结果。目前没有保持模型参数一致的对照实验，不能分配各因素的因果贡献。

尤其是，首次提交在引用被拒之前就已判 pass，故“引用校验导致全部漏判”不成立；修引用是必要修复，也不等于能单独消除漏判。实际 system 已明确“accepted 不代表语义正确”，但模型在后续自然语言中强调生日问题并继续推进剩余轴，这只能作为注意范围收窄的线索，不能证明内部推理原因。

## 6. 核心问题二：“该做没做”目前为什么会漏

transcript 提示词确实要求从 criterion、用户原文与设计倒推子问题，并在 `work_coverage`、`data_per_subquestion` 提交 `origin=expectation_deduction`。但现有 schema 是：

```text
ProcessAssessment
  reason
  scope_note
  results[]
    obligation_id, link_ids, outcome
    expected: string, observed: string
    source_refs, input_refs, output_refs, missing
    problems, upstream_issue_ids
    origin（默认 runtime_recall）
```

这意味着模型可以先挑一个已有步骤，给每条义务写一组结果，就满足程序“每条义务至少回答一次”的检查。`expected` 只是结果里的一个字符串，不是必须单独列齐并逐项覆盖的期望清单。任意 expected ID 也没有预先登记的集合供程序核对。

最新 B 的规划/知识输出全部是 runtime_recall，没有 expectation_deduction。但应准确理解：**这证明期望来源和覆盖机制没有落实，不证明 B 一定发生了漏查询。** B 实际有两次查询，本身不是“该查却完全没查”的充分验收样本。

普通案卷路径已有 `expected_exercises`，只是 transcript 路径没有同等的结构要求；此前把二者统称为“期望倒推已完成”过于宽泛。并且，现有普通路径主要覆盖编排/取数，并没有实现最新讨论中“六轴分别分析本轴期望”的方案。

## 7. 另外两个尚未解决的判断问题

- **工具归因不稳定：** 返回载荷中有客户本人性别值，但 execution.gaps 又按家庭成员性别字段声明缺失。载荷不一致可观察；究竟由工具、适配层还是其他生成层造成，现有记录未充分定位。首轮归工具问题、后轮判正常，不能把任一次结果当作已确认根因。
- **最终影响过度断言：** 最新两个模型问题均标 impact=yes，但最终实收不可见。当前人工复核只能支持“模型输出存在偏差”，不能证明用户最终收到的内容受损。影响应保留未知，除非有进一步交付证据。

这两项应纳入评审，但不宜把本次优化扩大成另造归因体系或更改既定六轴协议。

## 8. 讨论如何转向，以及当前待评审方案

实施者最初提出：增加独立的应做清单前置阶段，并用 JSON 解析/schema 检查拒绝错误 pass。用户随后指出两个方向：应先通过评测器 llmtracing 原文检查上下文工程；可以模仿主轴，让六过程轴自己做期望分析，并用 schema 表达。

查阅实际记录后，当前建议调整为：**先修材料与引用、让六轴显式分析并逐项评期望，再观察是否仍需额外机械核验。** 这属于建议，尚未获得最终方案确认，也未修改代码。

主轴已有可参考的结构：`business_expectations` 含独立期望与 acceptance_criteria，`fulfillment_assessments` 按 expectation_id 对应；提示词要求原子拆分，程序检查未知/漏判的期望 ID。过程轴借用这种组织形式，不照搬主轴 fulfilled 枚举或 blocking 汇总规则。

### 8.1 schema 的建议方向，字段尚未定稿

```text
每个过程轴的提交
  expectations[]
    expectation_id
    obligation_id / 子能力
    exercise / 行使对象（可以是应发生但无 trace 步骤的对象）
    origin / 发现来源
    applicable_when / 适用条件
    expected_outcome / 单一、可核验的预期
    source_refs / 判准出处
  assessments[]
    expectation_id
    observed / 实际观察
    input_refs, output_refs
    outcome / 沿用既有六值及归属规则
    missing, problems, upstream_issue_ids
```

每个轴从本轴职责、适用契约与输入推导期望，而不是统一要求六轴都发明一次查询。无相关行使时也要说明适用性与依据，不能用空清单默认为正常。

以模型轴为例，同一次 c3 输出契约可以拆为“响应全文符合 JSON 格式”“字段和类型符合 schema”“正文遵守表达要求”。每项分别对照，但最终仍聚合回“c3 × 输出契约”这一次行使。不能把拆成三个验收项变成三次行使、膨胀组成。

以遗漏查询为例，先从请求识别两个子问题，再按本轴职责推导应有安排/取数。未找到第二项实际行为时，该期望仍在清单里，必须得到有证据的判断。一次真实查询满足两个子问题、已有有效数据无需再查，也应允许表达，不能强制“一子问题一工具调用”。

### 8.2 程序和模型的分工

模型负责理解适用规则、拆期望、核对事实与解释归属；程序检查结构、有效引用、期望与判断的对应、重复/漏判、上游问题引用及单位汇总。

需要明确的限制：schema 能检查“列出的期望都评了”，不能证明“期望没有漏列”；在同一次模型生成中把 expectations 放在 assessments 前，也不能保证模型没有根据 actual 倒推 expected。是否需要同一会话分两次提交，或真正隔离期望阶段材料，是本次请评审者帮助判断的问题，不能默认增加模型调用就有效。

提示词优化应聚焦判准逐项展开、完整输出范围、实际输入边界和两种来源，避免继续叠加 B 专用规则。参数继承应以可验证的结构化关系交付，不能放宽所有历史引用。

JSON 机械核验仍是备选补充，不是已决定删除或实施的方案。若引入，应验证正确的原始正文和适用契约，区分中间工具调用，并保存独立检查依据；不能从围栏抽取一块 JSON 后宣布整段响应合规，也不能静默篡改原始模型结果。

## 9. 希望评审者具体回答的问题

| 问题 | 希望得到的意见 |
|---|---|
| 材料引用 | 参数复用的证据身份该如何表达，既能引用 c3 实际契约，又不把整个 c1 当作 c3 输入？ |
| 提示词与上下文 | 哪些已观察因素最可能造成契约缩减？还需要查哪些实际消息或设计什么对照，才能区分材料问题与模型不稳定？ |
| 六轴期望分析 | 每轴自己产 expectations 是否合适？应如何表示行使对象、适用条件、原子判准及来源，避免重复和凭空加义务？ |
| 防漏项 | 如何防止模型只列自己已经检查过的期望？同次结构化输出、同会话先提交期望、独立材料阶段三者如何取舍？ |
| 聚合 | 一个子能力行使拆多个期望后，如何保持原有单位组成、问题粒度与上游无效范围？ |
| 上下游依赖 | 六轴各自产期望时，如何保证上游问题引用有效，避免提交顺序或过早接受结论导致下游无法判断？ |
| 机械核验 | JSON 等确定性检查应在哪一步引入？应提供事实、拒绝矛盾提交，还是直接产生受限单位结果？ |
| 验收 | 最少哪些样本与重复运行，足以说明改善来自本次修改而不是换模型、换参数或对 B 的特化？ |

建议反馈采用“问题/建议—证据位置—预期改善—可能副作用—验证办法”的格式。可以反对当前建议；本文并不把它作为定案。

## 10. 建议的后续验证与现有测试证据

后续如决定实施，建议先固定模型、推理参数、冻结 trace 和预算，保留实际选中端点，分阶段比较材料修复和 schema/提示词改动；原始结果与人工复核并列，不追求 sound 比例升高。

最小验收应覆盖：完整合法 JSON、围栏/前置正文、schema 字段错误、中间工具调用的适用范围；遗漏子问题、已有数据无需再查、一次调用满足多项、采集缺失、上游未给输入；以及影响未知的交付边界。B 可以验格式和材料引用，不能独自承担“应发生未发生”的验收。

验收要看原子问题、期望覆盖及引用，而不只看 axis verdict。schema 输出不合法属于评测失败；业务过程不可见才是业务缺证。超时轮不得用中途结果补成“成功”。

已有验证按运行分别列示，**不能相加为一个总通过数，也不是一次最终全量通过的报告**：

| 阶段 | 已记录结果 |
|---|---|
| 初始 20 个相关模块 | 328 passed；2 条已有依赖弃用警告 |
| 初始最后受影响模块 | 113 passed |
| B 修复后的 20 模块 | 330 passed、1 个浏览器就绪等待竞态失败 |
| 浏览器等待修正后单独复验 | 1 passed |
| 最终收窄去重后的边界相关模块 | 41 passed，含不同子问题共享证据 |
| 最新真实 B 页面 | 六轴、组成、问题与证据展开通过浏览器检查；无 JS 错误 |

这些测试支持协议、引用、接线和页面行为；真实 B 仍证明语义验收未通过。最新聚类材料含 2 个原子问题，未再做真实聚类模型调用。

## 11. 证据与代码导航

正文可独立用于讨论；需要核对时先读同目录证据摘录，其中包含实际 system 全文及关键取证/提交片段。完整原始 trace 可能包含客户资料，本文未复制这些内容。

- [证据摘录（建议与本文一起转交）](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/review-evidence-excerpts.md)
- [需求原文](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/demand/process_axes.md)
- [协议方案原文](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/spec/alg/process-axes.md)
- [实施文件及哈希清单](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/manifest.json)
- [此前 B 人工复核](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/B-review.md)
- [最新旧新对照页面](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/B-r3-low/comparison.html)
- [最新问题及证据页面](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/B-r3-low/case.html)
- [20 模块测试日志](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/B-full-tests.log)
- [最终边界回归日志](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/report/process-axes-protocol-20261006/B-final-boundary-tests.log)

主要代码职责：

- [transcript 构建：参数去重及 input_refs](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py)
- [取证、读取回执及实际输入成员校验](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py)
- [transcript 实际提示词、提交与完成检查](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/llmtracing.py)
- [过程轴当前 schema 及普通材料提示词](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_common.py)
- [统一问题、取值、组成和引用协议](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/eval_axes/adapters/process_protocol.py)
- [普通路径 expected_exercises 提交](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/projects/llm_probe/process_loop/analysis.py)
- [主轴期望拆分提示词及自检](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/core/judge.py)
- [主轴期望与 assessment schema](/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier/impl/core/schema/judge.py)

整理时确认：根 manifest 的 32 个实现文件哈希全部匹配，未发生本轮分析期间的实现变更。业务 B trace SHA-256 为 `69e8a0513dec857fab62e3c5db92709782cc9e8ea7ccd8faec664de314ef3831`。

受保护文件 SHA-256：

- 需求：`f2e489c48f8edc2f16a41e3c5c8c7bf8f284aeb8c929efaf0cd3b07c55d1e46f`
- 方案：`53c8a11ac5388a86adb7ff8f2ca9a0f2fcaac87e2f85a5e31f89c92887fa157e`
