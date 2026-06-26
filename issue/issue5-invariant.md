---
id: 5
title: "中间数据流缺乏结构化约束（Types"
created_at: 2026-06-26
author: 此般浅薄
labels: []
status: open
---

# 中间数据流缺乏结构化约束（Types



---

### 💬 此般浅薄 · 2026-06-26 16:00

> **标记**：`提出者` · `验证者`

我觉得目前这个项目，缺少一些边界约束，导致它几乎都是基于文档进行开发，对齐协议的，这样很难保证长期稳定性，怎么解决呢，我觉得需要定义一些中间数据流的结构约束

agent的结构，然后前后端对齐、算法对齐等等。你先看demand/*下面的东西后理解当前项目后，在做判断

我不建议做具体的代码约束，你只做数据产出层的结构约束，比如pydantic格式、config格式，并且你的格式应该跟当前代码实现对齐，也要所有满足demand/*的需求（同步检验当前代码是否会存在多重标准的情况），配套对应的格式校验代码

judge/attribute/live（实时业务系统请求）/mock/view/trace/前端表格view。至少这几个的types(pydantic)和config，并且考虑demand/*和当前代码以及多轮的适配，关于多轮，你参考下最新的issue4

---

### 💬 Claude · 2026-06-19 09:30

> **标记**：`非提出者` · `开发` · ``


⏺ 你说得对，我漏了 live 层本身的数据结构——它不是页面渲染层的 LivePageViewModel，而是 live 
  请求的执行结果数据结构，包括 adapter 的输入输出、执行链路、多轮交互的执行过程等。
  
  让我重新完整汇总所有 7 个层：
  
  ---
  完整协议：7 层数据流结构约束

  总览

  ┌────────┬─────────────────────────────────┬─────────────────────────────────────────────────────────────┐
  │  层  │                定位                │                     对应现有代码/数据                      │
  ├──────┼────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Mock │ 测试输入/用户意图的构建            │ mock_cases.json、build_mock_cases()                        │
  │  层  │                                    │                                                            │
  ├──────┼────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ Live 层  │ 业务系统实时请求的执行与结果获取 │ adapter.build_request()、call_or_prepare()、extract_outp │
  │          │                                  │ ut()                                                     │
  ├──────────┼──────────────────────────────────┼──────────────────────────────────────────────────────────┤
  │ Trace 层 │ 一次完整执行链路的记录（单轮/多  │ RunTrace、execution_trace                                │
  │          │ 轮）                             │                                                          │
  ├──────────┼──────────────────────────────────┼──────────────────────────────────────────────────────────┤
  │ Judge 层 │ 评估业务系统输出是否正确         │ JudgeResult、fulfillment_assessments                     │
  ├──────────┼──────────────────────────────────┼──────────────────────────────────────────────────────────┤
  │ Attribut │ 问题归因                         │ AttributeResult、expectation_attributions                │
  │ e 层     │                                  │                                                          │
  ├──────────┼──────────────────────────────────┼──────────────────────────────────────────────────────────┤
  │ View 层  │ 前端渲染的完整 ViewModel         │ FrontendViewModel                                        │
  ├──────────┼──────────────────────────────────┼──────────────────────────────────────────────────────────┤
  │ 表格     │ 前端 Summary/表格的展示结构      │ TraceTableRow、ConversationTurn                          │
  │ View 层  │                                  │                                                          │
  └──────────┴──────────────────────────────────┴──────────────────────────────────────────────────────────┘

  ---
  一、Mock 层 — 测试数据构建

  定位：构建或加载测试输入/用户意图。单轮场景是 input，多轮场景需要 user_intent + interaction（mock_agent
  驱动多轮交互）
  
  1.1 单轮 case 结构
  
  # impl/schema_constraints/mock_schema.py
  from pydantic import BaseModel, Field
  from typing import Optional, Any
  from enum import Enum
  
  class CaseSource(str, Enum):
      user_written = "user_written"
      data_mock_seed = "data_mock_seed"
      mock_agent_seed = "mock_agent_seed"
      uploaded = "uploaded"
      regression = "regression"

  class CaseStatus(str, Enum):
      pending = "pending"
      running = "running"
      completed = "completed"
      error = "error"

  class SingleTurnCase(BaseModel):
      id: str = Field(..., description="case 唯一标识，如 'cs-age-001'")
      input: dict[str, Any] = Field(..., description="业务系统执行时的输入")
      scenario: str = Field(default="", description="业务场景标签，用于分类筛选")
      expected_intent: str = Field(default="", description="预期用户意图，中文描述")
      reference: Optional[dict[str, Any]] = Field(default=None, description="参考输出，用于 judge 对比")
      source: CaseSource = Field(default=CaseSource.user_written)
      status: CaseStatus = Field(default=CaseStatus.pending)
      metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

  1.2 多轮 case 结构

  class MultiTurnTurnExpectation(BaseModel):
      turn: int = Field(..., ge=1)
      stage: str = Field(default="", description="预期该轮的 stage，如 clarification/planning")
      missing_fields: list[str] = Field(default_factory=list)
      required_path_types: list[str] = Field(default_factory=list)
  
  class MultiTurnPolicy(BaseModel):
      max_turns: int = Field(default=5, ge=1, le=20)
      stop_when: list[str] = Field(default_factory=list)

  class MultiTurnInteraction(BaseModel):
      mode: Literal["interactive_intent", "static_turns"] = "interactive_intent"
      policy: MultiTurnPolicy = Field(default_factory=MultiTurnPolicy)
      turn_expectations: list[MultiTurnTurnExpectation] = Field(default_factory=list)

  class MultiTurnCase(SingleTurnCase):
      """多轮 case = 一个意图 + 多轮交互 + mock_agent 驱动"""
      user_intent: dict[str, Any] = Field(default_factory=dict)
      interaction: MultiTurnInteraction = Field(default_factory=MultiTurnInteraction)
      mock_agent: dict[str, Any] = Field(default_factory=dict)

  # 统一类型
  MockCase = SingleTurnCase | MultiTurnCase

  1.3 Mock 数据集

  class MockDataset(BaseModel):
      dataset_id: str
      name: str
      dimension_type: str
      description: str
      case_count: int = Field(..., ge=0)
      cases: list[MockCase]
  
  class MockSpec(BaseModel):
      input_modes: list[Literal["single_turn", "interactive_intent", "static_turns", "batch"]]
      case_sources: list[Literal["user_written", "generated", "uploaded", "regression"]]
      intent_generation_guidance: str = ""
      expected_intent_format: str = ""

  1.4 Mock config
  
  # projects/<project>/mock.yaml
  project_id: client_search
  mock_spec:
    input_modes:
      - single_turn
    case_sources:
      - user_written
      - generated
    intent_generation_guidance: |
      基于业务背景描述，构建多样化的客户搜索意图
    expected_intent_format: |
      business language first, then field-level conditions

  ---
  二、Live 层 — 业务系统实时请求

  定位：这是最关键的缺失。Live 层描述的是 adapter 如何将统一输入转化为业务系统请求、调用业务系统、获取并提取输出
  的全过程。这是 build_request → call_or_prepare → extract_output 的完整链路。
  
  2.1 核心结构
  
  # impl/schema_constraints/live_schema.py
  from pydantic import BaseModel, Field, field_validator
  from typing import Any, Optional, Literal
  from datetime import datetime, timezone
  
  class LiveRequest(BaseModel):
      """构建后的业务系统请求"""
      project_id: str
      case_id: str = ""
      raw_input: dict[str, Any] = Field(..., description="原始用户输入，来自 mock_case.input")
      turns: list[dict[str, Any]] = Field(default_factory=list, description="多轮时的对话历史")

      # adapter.build_request 的输出
      normalized_request: dict[str, Any] = Field(default_factory=dict, description="归一化后的业务请求体")

      # 执行控制
      execution_mode: Literal["live_service", "provided_output", "mock_response"] = "live_service"
      session_id: str = ""
      timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  
  class LiveMultiTurnState(BaseModel):
      """多轮交互执行时的中间状态"""
      session_id: str
      turn_index: int = 0
      transcript: list[dict[str, Any]] = Field(default_factory=list, description="完整对话记录")
      accumulated_fields: dict[str, Any] = Field(default_factory=dict)
      missing_fields: list[str] = Field(default_factory=list)
      stop_reason: str = ""

  class LiveExecutionResult(BaseModel):
      """一次 live 请求的完整执行结果"""
      project_id: str
      case_id: str = ""
      session_id: str = ""

      # 请求阶段
      raw_input: dict[str, Any] = Field(default_factory=dict)
      normalized_request: dict[str, Any] = Field(default_factory=dict)
  
      # 调用阶段
      call_status: Literal["succeeded", "failed", "skipped"] = "succeeded"
      raw_response: Optional[Any] = Field(default=None, description="业务系统的原始返回")
      call_error: Optional[str] = None
      runtime_ms: Optional[int] = None

      # 提取阶段
      extracted_output: dict[str, Any] = Field(default_factory=dict, description="adapter.extract_output 
  的结果")
      output_source: Literal["live_service", "provided_output", "mock_response", "error"] = "live_service"

      # 执行跟踪
      execution_trace: list[dict[str, Any]] = Field(default_factory=list, description="每个 stage 的执行记录")
      evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
  
      # 项目边界信息
      project_fields: dict[str, Any] = Field(default_factory=dict)
      application_boundary: dict[str, Any] = Field(default_factory=dict)
  
      # 多轮扩展
      interaction_mode: Literal["single_turn", "interactive_intent", "static_turns"] = "single_turn"
      multi_turn_state: Optional[LiveMultiTurnState] = None
  
  class LiveMultiTurnResult(BaseModel):
      """多轮交互的完整执行结果"""
      project_id: str
      case_id: str
      session_id: str
      turn_results: list[LiveExecutionResult] = Field(..., min_length=1, description="每一轮的执行结果")
      conversation_transcript: list[dict[str, Any]] = Field(default_factory=list, description="完整对话记录")
      stop_reason: str = ""
      final_output: dict[str, Any] = Field(default_factory=dict, description="最终输出汇总")

  2.2 Live config

  # projects/<project>/live.yaml
  project_id: client_search
  api:
    base_url: "http://localhost:8000"
    endpoint: "api/search"
    method: "POST"
    timeout: 30
  
  execution:
    retry_on_failure: true
    max_retries: 2

  multi_turn:
    enabled: false

  ---
  三、Trace 层 — 执行链路记录

  定位：一次完整 trace 的链路记录，可以是单轮（一次 live 结果）或多轮（多次 live 结果的聚合）。是
  judge/attribute 的输入。

  3.1 核心结构
  
  # impl/schema_constraints/trace_schema.py
  from pydantic import BaseModel, Field
  from typing import Any, Optional, Literal

  class ExecutionTraceNode(BaseModel):
      stage: str
      status: Literal["ok", "failed", "suspicious", "not_verified"]
      evidence: Optional[Any] = None

  class RunTrace(BaseModel):
      trace_id: str
      project_id: str
      input: dict[str, Any]                       # 原始输入（单轮 = mock_case.input，多轮 = 原始意图）
      normalized_request: dict[str, Any]          # adapter 归一化后的请求

      raw_response: Optional[Any] = None          # 业务系统原始返回（单轮）
      extracted_output: dict[str, Any] = Field(default_factory=dict)  # adapter 提取后的输出
  
      project_fields: dict[str, Any] = Field(default_factory=dict)
      runtime_logs: list[str] = Field(default_factory=list)
      evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

      status: Literal["ok", "error"] = "ok"
      error: Optional[str] = None

      execution_trace: list[ExecutionTraceNode] = Field(default_factory=list)

      # 多轮扩展（新增）
      interaction_mode: Literal["single_turn", "interactive_intent", "static_turns"] = "single_turn"
      session_id: str = ""
      turn_index: int = 0                          # 0 = 单轮或多轮的汇总 trace
      conversation_transcript: list[dict[str, Any]] = Field(default_factory=list)
      multi_turn_input: Optional[dict[str, Any]] = None  # 多轮场景的原始意图 + 交互配置

  3.2 多轮 Trace
  
  多轮场景下，RunTrace 有两种形态：

  1. 单轮 Trace：一次 live 调用的结果，interaction_mode="single_turn"，turn_index=0
  2. 聚合 Trace：整个多轮交互的汇总，interaction_mode="interactive_intent"，input
  是整个交互的原始意图，conversation_transcript 是完整对话记录
  
  class MultiTurnTraceSummary(BaseModel):
      """多轮 trace 聚合后的汇总"""
      trace_id: str
      project_id: str
      session_id: str
      input: dict[str, Any]                       # 原始意图
      turn_traces: list[RunTrace]                 # 每一轮的 trace
      conversation_transcript: list[dict[str, Any]]
      stop_reason: str = ""
      final_output: dict[str, Any] = Field(default_factory=dict)
  
  ---
  四、Judge 层 — 评估输出

  定位：对 trace 的评估。单轮评估最终 output，多轮基于完整对话链路评估。

  4.1 核心结构（对齐 judge_protocol.md）

  # impl/schema_constraints/judge_schema.py
  from pydantic import BaseModel, Field, field_validator
  from typing import Any, Optional, Literal
  from enum import Enum

  class FulfillmentStatus(str, Enum):
      fulfilled = "fulfilled"
      not_fulfilled = "not_fulfilled"
      partially_fulfilled = "partially_fulfilled"
      not_evaluable = "not_evaluable"
      contested = "contested"

  class Verdict(str, Enum):
      correct = "correct"
      incorrect = "incorrect"
      uncertain = "uncertain"
  
  class IntentModel(BaseModel):
      raw_user_request: str = ""
      explicit_intents: list[str] = Field(default_factory=list)
      implicit_business_intents: list[str] = Field(default_factory=list)
      constraints: list[str] = Field(default_factory=list)
      success_definition: str = ""
      blocking_requirements: list[str] = Field(default_factory=list)
      intent_evidence: list[Any] = Field(default_factory=list)
  
  class BusinessExpectation(BaseModel):
      expectation_id: str
      downstream_consumer: str = ""
      user_intent: str = ""
      expected_outcome: str = ""
      required_capabilities: list[str] = Field(default_factory=list)
      acceptance_criteria: list[Any] = Field(default_factory=list)
      boundary: dict[str, Any] = Field(default_factory=dict)
      priority: Literal["normal", "high", "critical"] = "normal"

  class FulfillmentAssessment(BaseModel):
      expectation_id: str
      status: FulfillmentStatus
      score: Optional[float] = Field(default=None, ge=0, le=1)
      expected_evidence: list[Any] = Field(default_factory=list)
      actual_evidence: list[Any] = Field(default_factory=list)
      boundary_decision: dict[str, Any] = Field(default_factory=dict)
      downstream_impact: str = ""
      blocking: bool = False
      confidence: Optional[float] = Field(default=None, ge=0, le=1)

  class BoundaryDecision(BaseModel):
      within_evaluable_scope: Optional[bool] = None
      uncontrollable_limits: list[str] = Field(default_factory=list)
      evaluable_errors: list[str] = Field(default_factory=list)
      reasoning: str = ""

  class JudgeResult(BaseModel):
      trace_id: str
      project_id: str
  
      # Fulfillment 核心域
      intent_model: IntentModel = Field(default_factory=IntentModel)
      consumer_contract: dict[str, Any] = Field(default_factory=dict)
      business_expectations: list[BusinessExpectation] = Field(default_factory=list)
      fulfillment_assessments: list[FulfillmentAssessment] = Field(default_factory=list)
      overall_fulfillment: dict[str, Any] = Field(default_factory=dict)  # {status, blocking_expectations, 
  downstream_impact}

      # 派生字段 — 由 verifier 代码计算，LLM 不输出
      verdict: Verdict = Verdict.uncertain
      score: Optional[float] = None
      confidence: Optional[float] = None
  
      # 边界域
      boundary_decision: BoundaryDecision = Field(default_factory=BoundaryDecision)
      evaluation_boundary: dict[str, Any] = Field(default_factory=dict)

      # 对比域
      expected: Any = None
      actual: Any = None
      wrong: list[Any] = Field(default_factory=list)
      missing: list[Any] = Field(default_factory=list)
      extra: list[Any] = Field(default_factory=list)
      evidence: list[Any] = Field(default_factory=list)
  
      # 推理域
      reconstructed_intent: str = ""
      judge_basis: str = ""
      judge_method: str = ""
      reasoning_summary: str = ""
      verdict_derivation: dict[str, Any] = Field(default_factory=dict)

      # 质量域
      quality_flags: list[str] = Field(default_factory=list)
      scenario: str = ""
      raw_model_output: Any = None
  
  4.2 Judge config

  # projects/<project>/judge.yaml
  project_id: client_search
  judge_boundary:
    primary_boundary_id: "client_search_parser"
    evaluation_boundary:
      judge_question: "actual conditions 能否正确表达 query 的目标客户群？"
      verdict_basis: "只评估 API 返回的条件是否语义覆盖 query"
      conflict_policy: "actual conditions 与 matched_level 冲突时以 conditions 为准"

  judge_standard:
    - 检查条件字段/操作符/值是否匹配 query
    - 范围：不评估下游结果集
    - 语义等价规则：MATCH=EQ、中文单位换算等价等

  multi_turn:
    enabled: false
    evaluate_on: "full_conversation"
    # full_conversation = 基于完整对话链路评估
    # last_turn_only = 仅基于最后一轮评估

  ---
  五、Attribute 层 — 问题归因

  定位：当 judge 判定不及预期时，定位问题发生的根因。多轮场景需要定位最早出现问题的那一轮。

  5.1 核心结构

  # impl/schema_constraints/attribute_schema.py
  from pydantic import BaseModel, Field
  from typing import Any, Optional, Literal

  class ExpectationAttribution(BaseModel):
      expectation_id: str
      fulfillment_status: FulfillmentStatus
      causal_category: Literal["no_issue", "implementation_bug", "model_capability_gap",
                                "boundary_limitation", "unclear_contract", "insufficient_evidence"] =
  "insufficient_evidence"
      earliest_divergence: dict[str, Any] = Field(default_factory=dict)
      causal_chain: list[dict[str, Any]] = Field(default_factory=list)
      local_verifications: list[dict[str, Any]] = Field(default_factory=list)
      suspected_locations: list[Any] = Field(default_factory=list)
      improvement_direction: list[str] = Field(default_factory=list)
      source_evidence: list[Any] = Field(default_factory=list)
      probe_evidence: list[Any] = Field(default_factory=list)
      incomplete_reason: str = ""

  class ChainNode(BaseModel):
      name: str
      status: Literal["normal", "suspicious", "failed", "not_verified"] = "not_verified"
      evidence: list[Any] = Field(default_factory=list)
      reason: str = ""

  class AttributeResult(BaseModel):
      trace_id: str
      project_id: str
      case_id: str = ""

      # 归因核心域
      expectation_attributions: list[ExpectationAttribution] = Field(default_factory=list)
      causal_category: Literal["no_issue", "implementation_bug", "model_capability_gap",
                                 "boundary_limitation", "unclear_contract", "insufficient_evidence"] =
  "insufficient_evidence"
      probe_results: list[dict[str, Any]] = Field(default_factory=list)

      # 证据链
      evidence_chain: list[Any] = Field(default_factory=list)
      trace_analysis: list[Any] = Field(default_factory=list)
      chain_nodes: list[ChainNode] = Field(default_factory=list)
      local_verifications: list[dict[str, Any]] = Field(default_factory=list)
      earliest_divergence: dict[str, Any] = Field(default_factory=dict)
      evidence_coverage: dict[str, Any] = Field(default_factory=dict)
  
      # 质量域
      analysis_quality: dict[str, Any] = Field(default_factory=dict)
      incomplete_reason: str = ""
      suspected_locations: list[Any] = Field(default_factory=list)
      root_cause_hypothesis: str = ""
      verification_steps: list[str] = Field(default_factory=list)
      patch_direction: list[str] = Field(default_factory=list)
      business_impact: str = ""
  
      # 错误分类
      primary_error_type: str = ""
      error_types: list[str] = Field(default_factory=list)
      severity: Literal["blocking", "high", "medium", "low", "unknown"] = "unknown"
      needs_human_review: bool = False
      quality_flags: list[str] = Field(default_factory=list)

  5.2 Attribute config
  
  # projects/<project>/attribute.yaml
  project_id: client_search
  attribution_standard:
    run_only_for:
      - incorrect
      - uncertain_with_gap
    minimum_evidence:
      - query
      - actual_output
      - judge_diff
      - execution_trace
      - project_code_or_config

  error_taxonomy:
    - implementation_bug
    - model_capability_gap
    - boundary_limitation
    - unclear_contract
    - insufficient_evidence
    - no_issue
  
  multi_turn:
    enabled: false
    attribute_strategy: "per_turn_then_aggregate"
    # per_turn_then_aggregate = 先逐轮归因，再聚合
    # full_trace = 基于完整 trace 统一归因
  
  ---
  六、View 层 — 前端渲染
  
  定位：前后端之间的渲染协议，定义好前端的渲染数据，确保前后端解耦。

  6.1 FrontendViewModel（Live 用 + Summary 通用）

  # impl/schema_constraints/view_schema.py
  from pydantic import BaseModel, Field
  from typing import Any, Optional, Literal

  class FrontendViewModel(BaseModel):
      """通用前端 ViewModel，Live 页和 Summary 页都基于此渲染"""
      project_info: dict[str, Any]  # project_id, name, description

      # Trace 面板
      trace_panel: dict[str, Any] = Field(default_factory=dict)
      # {input, output, reference, conversation_detail(多轮展开)}
  
      # Judge 面板
      judge_panel: dict = Field(default_factory=dict)
      # {verdict, score, overall_fulfillment.status, wrong/missing/extra,
      #  blocking_expectations, display_reason, raw_judge(折叠)}

      # Attribute 面板
      attribute_panel: dict = Field(default_factory=dict)
      # {causal_category, root_cause_hypothesis, verification_steps,
      #  patch_direction, chain_nodes, raw_attribute(折叠)}
  
      # 聚合面板
      cluster_panel: dict = Field(default_factory=dict)
      check_panel: dict = Field(default_factory=dict)
  
      # 项目扩展（协议式，非硬编码）
      project_extensions: dict[str, Any] = Field(default_factory=dict)

  ---
  七、表格 View 层 — Summary 页表格
  
  定位：Summary 页的核心——Case-pool 表格。多轮场景下一行 = 一个 trace，Input 是原始意图，Output
  默认收起最终结果。
  
  7.1 核心结构

  class ConversationTurn(BaseModel):
      turn_index: int
      role: Literal["user", "system", "mock"]
      content: str
      stage: str = ""
      extracted_summary: str = ""
  
  class TraceTableRow(BaseModel):
      """表格中的一行 = 一个 trace"""
      id: str
      input: str                              # Input 列：原始意图
      scenario: str = ""                      # 场景标签

      output_summary: str = ""                # Output 列：收起时显示的摘要
      reference_summary: str = ""             # Reference 列：收起时显示的摘要
  
      verdict: str = ""                       # correct / incorrect / uncertain
      score: Optional[float] = None
      fulfillment_status: str = ""            # fulfilled / not_fulfilled / ...

      needs_human_review: bool = False
      quality_flags: list[str] = Field(default_factory=list)

      # 多轮展开详情（默认收起，点击展开）
      interaction_mode: Literal["single_turn", "interactive_intent", "static_turns"] = "single_turn"
      conversation_detail: Optional[list[ConversationTurn]] = None

      # 原始数据的 trace_id（用于跳转到详情页）
      trace_id: str = ""
  
  class CasePoolTable(BaseModel):
      project_id: str
      rows: list[TraceTableRow]
      total: int
      summary: dict[str, Any] = Field(default_factory=dict)
      # {correct_count, incorrect_count, uncertain_count,
      #  by_scenario: {scenario_name: count}}
  
  7.2 表格的展示逻辑
  
  ┌───────────────────────┬─────────────┬─────────────────┬───────────────┬────────┬──────┬─────────────┐
  │         Input         │  Scenario   │  Output (收起)  │   Reference   │ Judge  │ Scor │  展开详情   │
  Output (收起): 已正确识别3个条件      
  Reference: 3个条件: age/sex/premium
  Judge: correct
  Score: 1.0              
  展开详情: —
  ────────────────────────────────────────                
  Input: 帮我找客户的所有下游关系
  Scenario: 多轮-客户关系 
  Output (收起): 已完成，定位到...
  Reference: 客户供应商关系
  Judge: correct
  Score: 1.0
  展开详情: ▶ 轮1: 你找哪个客户? → 客户A → 轮2: 关系类型? → 供应商关系
  ────────────────────────────────────────
  Input: 今年的采购计划
  Scenario: 多轮-计划查询
  Output (收起): 未完成，缺采购类型
  Reference: 采购计划
  Judge: incorrect
  Score: 0.0
  展开详情: ▶ 轮1: 你关注哪个品类? → → 轮2: mock卡住了

  ---
  八、整体数据流（多轮 vs 单轮）

  单轮:
    输入(mock_case.input)
      → Live: build_request() → call_api() → extract_output()
      → Trace: RunTrace
      → Judge: JudgeResult
      → Attribute: AttributeResult (仅当不及预期)
      → View: FrontendViewModel
      → 表格: TraceTableRow

  多轮:
    输入(mock_case.user_intent)
      → Live: build_request(turn=1) → call_api() → extract_output()
             → mock 根据结果决定下一轮输入
             → build_request(turn=2) → call_api() → extract_output()
             → ... 直到 stop or max_turns
      → Trace: Turn[1..N] → MultiTurnTraceSummary
      → Judge: JudgeResult (基于完整 transcript)
      → Attribute: AttributeResult (定位最早出问题的那一轮)
      → View: FrontendViewModel (对话展开)
      → 表格: TraceTableRow (conversation_detail 展开)
  
  ---
  九、文件结构

  impl/
    schema_constraints/          # 新增：类型约束层
      __init__.py
      mock_schema.py             # MockCase, MultiTurnCase, MockDataset
      live_schema.py             # LiveRequest, LiveExecutionResult, LiveMultiTurnResult
      trace_schema.py            # RunTrace, ExecutionTraceNode, MultiTurnTraceSummary
      judge_schema.py            # JudgeResult, BusinessExpectation, FulfillmentAssessment
      attribute_schema.py        # AttributeResult, ExpectationAttribution, ChainNode
      view_schema.py             # FrontendViewModel (通用 ViewModel)
      table_schema.py            # TraceTableRow, CasePoolTable, ConversationTurn
      config_schema.py           # 各层 config YAML 的 BaseModel
      validator.py               # 运行时校验器

    projects/<project>/
      mock.yaml                  # Mock 配置 (input_modes, intent_generation)
      live.yaml                  # Live 配置 (api endpoints, retry)
      judge.yaml                 # Judge 配置 (boundary, standard)
      attribute.yaml             # Attribute 配置 (attribution_standard, error_taxonomy)

  ---
  这次我把 Live 层补全了——LiveRequest（adapter 的输入）、LiveExecutionResult（一次 live
  调用的完整结果）、LiveMultiTurnResult（多轮交互的聚合结果）。现在 7 个层（mock / live / trace / judge /
  attribute / view / 表格）都有对应的类型约束和 config 格式，并且每个层都考虑了多轮适配。

  需要我深入到具体字段级别的 JSON Schema 定义，还是开始实现代码？

