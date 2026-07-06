
❯ python -m impl.core.schema.fixture.show_fixture_flow                          
  通过运行这个函数，我发现当前schema中有很多schema/schema中的字段疑似是冗余/重  
  复/过时的，可能因为兼容历史实现/满足用户局部需求/ai设计不妥当等原因产生       
  我需要你对当前schema构建进行检视，仅从测评系统本身设计触发，思考从奥卡姆剃刀  
  的角度，相关的schema如何设计才是最优雅及合适的                                
  对于冗余/重复/过时的schema而言，我现在也没完全想好，我们先一起讨论下，出一个  
  审核报告。我建议几种处理方式：                                                
  1. 检查是否只是历史兼容问题，是否可以通过去除无用历史代码优化相关无用代码     
  2. 检查是否有输出必要，如果有必要说明其必要性                                 

⏺ Explore(audit schema fields) gpt-5.4
  ⎿  Done (30 tool uses · 140.5k tokens · 2m 34s)
  (ctrl+o to expand)

  Thought for 2m 59s, read 3 files (ctrl+o to expand)

⏺ 下面先给一版讨论用审核报告。我先不建议立刻改 schema，因为这里牵涉兼容、前端、
  历史数据、测试链路。我们先把“哪些是事实层、哪些是投影、哪些是历史包袱”分清楚。

  Schema 设计审核报告：从测评系统与奥卡姆剃刀出发

  0. 总体判断

  当前 schema 的问题不是“字段多”本身，而是同一个事实在多层重复存放，同一个结论有
  多套表达方式。

  从 fixture flow 看，测评系统的核心链路其实很清楚：

  SingleTurnCase
    -> LiveRequest
    -> LiveExecutionResult
    -> RunTrace
    -> JudgeResult
    -> AttributeResult
    -> TraceTableRow / FrontendViewModel

  但当前 schema 把这些东西混在一起：

  1. 运行事实；
  2. 评估事实；
  3. 归因事实；
  4. 前端展示投影；
  5. 历史兼容字段；
  6. LLM 原始输出；
  7. fallback / evidence / debugging 信息。

  它们现在很多都在核心 dataclass 中平级存在，所以显得冗余、重复、过时。

  我建议后续按这四类处理：

  canonical fact       核心事实，只保留一份
  derived projection   派生投影，可以重建，不作为事实源
  legacy alias         历史兼容字段，逐步废弃
  debug/evidence       调试、证据、fallback，不参与主判定

  ---
  1. 最核心的设计原则

  1.1 每个事实只应有一个 canonical source

  比如：

  - live 调用事实：应归 LiveExecutionResult
  - trace 链路索引：应归 RunTrace
  - judge 裁决事实：应归 JudgeResult
  - attribution 根因事实：应归 AttributeResult
  - view/table 展示：应归 FrontendViewModel / TraceTableRow

  现在的问题是：RunTrace 又复制了很多 LiveExecutionResult 的字段；TraceTableRow
  又复制了 RunTrace/JudgeResult/AttributeResult 的摘要；JudgeResult
  内部又有多套裁决表达。

  1.2 核心 schema 不应该为了前端方便变胖

  TraceTableRow、FrontendViewModel 这类东西是必要的，但它们是 view-only 
  DTO。它们不应该反过来成为 judge / attribute / check 的事实来源。

  1.3 兼容字段不能与主路径平级

  如果某字段只是为了兼容历史数据，那就应该明确标记：

  deprecated / alias / view-only / debug-only

  而不是继续放在主 schema 里让调用方误以为它仍是权威字段。

  ---
  2. 最明显的冗余：RunTrace 和 LiveExecutionResult 双写

  现状

  LiveExecutionResult 里有：

  raw_input
  normalized_request
  raw_response
  extracted_output
  output_source
  execution_trace
  project_fields
  application_boundary
  interaction_mode
  multi_turn_state
  fallbacks

  RunTrace 里又有：

  input
  normalized_request
  raw_response
  extracted_output
  live_result
  execution_mode
  output_source
  application_boundary
  project_fields
  execution_trace
  interaction_mode
  session_id
  conversation_transcript
  conversation_summary
  multi_turn_input
  fallbacks

  也就是说，RunTrace 同时：

  1. 内嵌了 live_result;
  2. 又把 live_result 的大部分字段平铺了一遍。

  这是当前最明显的重复。

  为什么会出现

  大概率是历史原因：

  - 早期没有 LiveExecutionResult，所以 RunTrace 承担所有运行事实；
  - 后来补了 live 层，但为了兼容旧消费方，又把字段保留在 RunTrace 顶层；
  - 前端、judge、attribute、check 为了方便继续读 trace.extracted_output。

  奥卡姆剃刀下的理想设计

  LiveExecutionResult 是运行事实原件。

  RunTrace 应该只保留：

  trace_id
  project_id
  case_id
  live_result
  status
  error
  state_history / gate_decisions / transition_decisions
  evidence_refs
  fallbacks

  以及少量高频索引：

  scenario
  interaction_mode
  session_id
  created_at

  其它字段如：

  raw_response
  extracted_output
  normalized_request
  output_source
  application_boundary
  project_fields

  都应该是：

  derived from live_result

  处理建议

  短期：

  - 保留字段，但标记为 derived / legacy alias;
  - check 中增加规则：RunTrace.extracted_output 必须等于
  RunTrace.live_result.extracted_output;
  - fixture 里也要体现这个关系。

  中期：

  - 所有新代码改读 trace.live_result.extracted_output;
  - 前端/table builder 负责投影；
  - 逐步减少对 trace.extracted_output 的直接依赖。

  长期：

  - 如果兼容成本可控，把这些顶层重复字段移除或变成 property。

  ---
  3. JudgeResult 内部存在“两套裁决系统”

  现状

  JudgeResult 里同时存在：

  新主路径

  business_expectations
  fulfillment_assessments
  overall_fulfillment

  旧/兼容路径

  primary_assessment
  condition_assessments
  intent_decomposition
  score_details
  missing
  wrong
  extra

  摘要路径

  verdict
  score
  confidence
  reasoning_summary
  judge_basis
  judge_method
  verdict_derivation

  这导致一个问题：到底哪个字段代表最终裁决？

  目前看，项目已经在向 fulfillment-first 迁移。check.py 里也能看出：

  business_expectations + fulfillment_assessments 是主信号
  primary_assessment / condition_assessments 是 legacy

  奥卡姆剃刀下的理想设计

  Judge 的核心应该只有三层：

  JudgeResult:
    trace_id
    project_id

    business_expectations: list[BusinessExpectation]
    fulfillment_assessments: list[FulfillmentAssessment]
    overall_fulfillment: OverallFulfillment

    expected
    actual
    gaps
    reasoning_summary
    raw_model_output

  其中：

  - verdict 可以保留，但必须由 overall_fulfillment.status 派生；
  - score 可以保留，但必须由 assessments 派生；
  - missing/wrong/extra 可以保留，但只作为 gap 解释，不作为另一套判定系统；
  - primary_assessment/condition_assessments 应该 deprecated。

  处理建议

  保留但说明必要性

  保留：

  expected
  actual
  missing/wrong/extra
  raw_model_output

  理由：

  - expected/actual 是 judge 当时看到的裁决快照，虽然和 trace
  有重复，但这是必要重复；
  - missing/wrong/extra 是可检查差异，不等同于最终 verdict；
  - raw_model_output 用于调试和审计。

  应该废弃或降级

  降级为 legacy：

  primary_assessment
  condition_assessments
  intent_decomposition
  score_details

  如果这些字段某些项目仍依赖，可以暂时保留，但应该明确：

  legacy judge compatibility fields

  ---
  4. AttributeResult 里根因表达过多

  现状

  AttributeResult 里同时有：

  failure_category
  failure_stage
  primary_error_type
  error_types
  causal_category
  root_cause_hypothesis
  earliest_divergence
  chain_nodes
  trace_analysis
  evidence_chain
  local_verifications
  probe_results
  suspected_locations
  verification_steps
  patch_direction
  expectation_attributions

  这里有几组明显重复：

  4.1 failure_category vs causal_category

  这两个字段语义高度接近。

  建议只保留一个 canonical：

  causal_category

  failure_category 可以作为人类展示摘要，或者 deprecated alias。

  4.2 failure_stage vs earliest_divergence.stage

  failure_stage 是摘要字段。真正结构化表达应该是：

  earliest_divergence

  所以：

  failure_stage = derived from earliest_divergence.stage

  4.3 evidence_chain vs trace_analysis vs chain_nodes

  这三者都在表达归因证据链：

  - trace_analysis: execution trace 的分析结果；
  - chain_nodes: 归因链路节点；
  - evidence_chain: 泛化证据列表。

  建议主路径保留：

  chain_nodes
  probe_results
  evidence_coverage

  trace_analysis 可以作为 execution_trace 的分析投影保留，但不要与 chain_nodes
  平级承担主事实。

  evidence_chain 太泛，容易变成垃圾桶，建议降级为 legacy/debug。

  4.4 local_verifications vs probe_results

  这两个也接近。

  建议：

  - probe_results 作为结构化探针结果；
  - local_verifications 作为兼容或人类可读摘要。

  处理建议

  理想的 AttributeResult 主结构应是：

  AttributeResult:
    trace_id
    project_id
    case_id

    expectation_attributions
    causal_category
    earliest_divergence
    chain_nodes
    probe_results
    evidence_coverage

    root_cause_hypothesis
    verification_steps
    patch_direction
    needs_human_review
    raw_model_output

  可以降级：

  failure_category
  failure_stage
  primary_error_type
  error_types
  evidence_chain
  trace_analysis
  local_verifications
  business_impact
  scenario

  其中不是都要删，但应该明确哪些是 summary，哪些是 canonical。

  ---
  5. 多轮 schema 存在明显重复

  现状

  多轮信息分散在：

  LiveMultiTurnState
  LiveMultiTurnResult
  RunTrace.conversation_transcript
  RunTrace.conversation_summary
  RunTrace.multi_turn_input
  MultiTurnTraceSummary
  TraceTableRow.conversation_detail

  其中 MultiTurnTraceSummary 的注释已经写了：

  兼容旧聚合输出；新消费方优先读取 RunTrace 的 conversation_* 字段

  这已经说明它是历史兼容对象。

  理想设计

  多轮事实最好只有一个事实源：

  LiveMultiTurnState

  它保存：

  session_id
  turn_index
  transcript
  accumulated_fields
  missing_fields
  stop_reason

  RunTrace 可以保留最小索引：

  interaction_mode
  session_id

  或者一个摘要：

  conversation_summary

  但不应同时保留：

  conversation_transcript
  multi_turn_input
  MultiTurnTraceSummary
  LiveMultiTurnResult

  所有都作为平级事实。

  处理建议

  - LiveMultiTurnState: 保留，作为运行事实；
  - RunTrace.conversation_transcript: 可保留短期兼容，但应标记 derived from
  live_result.multi_turn_state;
  - MultiTurnTraceSummary: deprecated;
  - TraceTableRow.conversation_detail: view-only;
  - conversation_summary: view/table 投影，不作为事实源。

  ---
  6. FrontendViewModel / TraceTableRow 应明确为 view-only

  当前 FrontendViewModel 有大量 panel：

  run_trace_summary
  raw_sections
  reference_panel
  judge_panel
  attribute_panel
  fulfillment_panel
  expectation_attribution_panel
  cluster_panel
  check_panel
  table_row
  project_extensions

  TraceTableRow 也重复了大量核心字段：

  input
  output_summary
  reference_summary
  verdict
  score
  fulfillment_status
  judge_summary
  attribution_summary
  check_summary
  fallback_summary
  failure_category
  failure_stage
  root_cause_summary
  conversation_detail

  这些字段不是错，它们对于前端展示很有用。

  但它们应该被标为：

  view-only projection

  也就是说：

  核心事实 -> build_frontend_view / build_trace_table_row -> view DTO

  不能反过来：

  view DTO -> judge/check/attribute 逻辑

  处理建议

  保留，但移动认知位置：

  - 不要和 core fact schema 混为一谈；
  - 文档中明确 view-only；
  - check 中如果发现 core 逻辑读 FrontendViewModel，应该报错。

  ---
  7. Evidence / Fallback 横切字段散落

  当前这些字段散落在多个对象里：

  evidence_refs
  fallbacks
  quality_flags
  raw_model_output
  runtime_logs
  gate_decisions
  transition_decisions

  它们都不是业务事实本身，而是：

  如何得出这个结果
  哪里失败了
  为什么需要人工复核

  这类东西很重要，但最好有统一归属。

  建议

  Evidence

  主锚点应该是：

  RunTrace.execution_trace
  RunTrace.evidence_refs

  Judge / Attribute 中如果需要证据，尽量引用 evidence ref，而不是复制证据对象。

  Fallback

  FallbackDecision 结构本身是必要的。

  但是否要每个对象都有：

  fallbacks

  值得重新评估。

  更优雅的做法可能是：

  RunTrace.fallbacks      # 运行阶段 fallback
  JudgeResult.fallbacks   # 裁决阶段 fallback
  AttributeResult.fallbacks # 归因阶段 fallback
  CheckReport.fallbacks   # 汇总 fallback

  这个可以保留，但必须定义清楚：每层 fallback 只记录本层，不跨层复制。

  ---
  8. 字段处理建议清单

  A. 优先检查是否可删除 / 废弃

  这些最像历史兼容：

  MultiTurnTraceSummary
  JudgeResult.primary_assessment
  JudgeResult.condition_assessments
  JudgeResult.intent_decomposition
  JudgeResult.score_details
  AttributeResult.evidence_chain
  AttributeResult.failure_category
  AttributeResult.failure_stage
  AttributeResult.primary_error_type
  AttributeResult.error_types

  不是说马上删，而是应该查：

  1. 还有没有核心代码读取；
  2. 是否只是前端展示；
  3. 是否可以由 canonical 字段派生；
  4. 是否只服务旧数据兼容。

  如果只服务旧数据，建议 deprecated。

  B. 保留但必须说明必要性

  JudgeResult.expected
  JudgeResult.actual
  JudgeResult.missing/wrong/extra
  JudgeResult.raw_model_output
  AttributeResult.raw_model_output
  FallbackDecision
  EvidenceRef
  ExecutionTraceEvent
  project_fields

  原因：

  - expected/actual 是 judge 快照；
  - gap 是差异证据；
  - raw_model_output 是审计/调试原件；
  - fallback/evidence 是测评系统必须保留的可追溯性；
  - project_fields 是防止 core 被项目特例污染的扩展槽。

  C. 应该转为 alias / derived

  RunTrace.normalized_request
  RunTrace.raw_response
  RunTrace.extracted_output
  RunTrace.output_source
  RunTrace.application_boundary
  RunTrace.project_fields
  RunTrace.conversation_transcript
  RunTrace.multi_turn_input
  RunTrace.conversation_summary
  JudgeResult.verdict
  JudgeResult.score
  AttributeResult.failure_stage

  这些不是没有用，而是不应作为独立事实源。

  D. 应该标为 view-only

  FrontendViewModel
  TraceTableRow
  CasePoolTable
  ConversationTurn

  保留，但只能从 core fact 派生。

  ---
  9. 我建议的审核报告结论

  9.1 当前 schema 最大问题

  不是缺 schema，而是：

  ▎ schema 太多字段承担了“兼容 + 展示 + 调试 + 主事实”的混合职责。

  9.2 最优雅的方向

  一个测评系统最干净的 schema 应该是：

  MockCase
    描述输入与参考预期

  LiveExecutionResult
    描述业务系统实际执行事实

  RunTrace
    描述一次测评链路的索引、状态、证据引用

  JudgeResult
    描述业务期望是否满足

  AttributeResult
    描述不满足时的根因与证据链

  CheckReport
    描述 schema / 协议 / 多重标准风险

  FrontendViewModel / TraceTableRow
    只做展示投影

  9.3 最优先处理顺序

  我建议分三步：

  第一步：标注 canonical / derived / legacy / view-only

  先不删代码，只在 schema 注释和审核报告里标清楚。

  第二步：写一个 schema audit check

  检查：

  - RunTrace.extracted_output 是否与 RunTrace.live_result.extracted_output
  分叉；
  - JudgeResult.verdict 是否与 overall_fulfillment.status 分叉；
  - AttributeResult.failure_stage 是否与 earliest_divergence.stage 分叉；
  - view/table 是否被 core 逻辑反向读取。

  第三步：逐步迁移调用方

  先迁移新代码读取 canonical 字段，再废弃旧字段。

  ---
  10. 我的建议

  现在不要马上删字段。

  更好的下一步是出一个正式报告文件，例如：

  report/schema-audit-occam.md

  里面把每个 schema 字段分成：

  canonical
  derived
  legacy
  view-only
  debug/evidence

  然后再基于这个报告决定改代码。

  如果你同意，我下一步可以把这份讨论稿整理成一个 repo
  内的审核报告文件，并补一个简单脚本/表格，把 RunTrace / JudgeResult / 
  AttributeResult / FrontendViewModel / TraceTableRow 的字段逐项标注出来。

✻ Cooked for 6m 27s