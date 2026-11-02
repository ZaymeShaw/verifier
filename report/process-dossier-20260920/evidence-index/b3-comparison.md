# B3 同批对比（30 个共同样本）

主轴 fulfillment 与基线一致：18/30

| 轴 | 结论与基线一致 | 检查项 现在/基线 | 缺证项 现在→基线 | 缺证率 现在→基线 | 视图字符 现在/不限单条/基线 |
|---|---|---|---|---|---|
| trace_analysis | 27/30 | 0/0 | 0→0 | —→— | — / — / — |
| intent_understanding | 22/30 | 135/130 | 5→0 | 4%→0% | 34330（中位 33485，最大 50968） / 52175（中位 44544，最大 118011） / 75226（中位 70413，最大 193454） |
| planning_routing | 23/30 | 135/129 | 6→0 | 4%→0% | 40266（中位 37508，最大 75559） / 54643（中位 50148，最大 129096） / 88638（中位 80960，最大 219068） |
| tool_execution | 13/30 | 108/84 | 32→8 | 30%→10% | 37389（中位 34170，最大 58467） / 58703（中位 58467，最大 123310） / 83998（中位 67976，最大 239582） |
| context_memory | 9/30 | 179/101 | 100→22 | 56%→22% | 45916（中位 43688，最大 71124） / 54032（中位 50029，最大 106190） / 102668（中位 90969，最大 246621） |
| knowledge_data | 21/30 | 54/50 | 6→2 | 11%→4% | 34250（中位 32490，最大 60113） / 53691（中位 43673，最大 118505） / 78935（中位 71382，最大 231073） |
| model_capability | 15/30 | 81/64 | 30→13 | 37%→20% | 45163（中位 43638，最大 73393） / 45163（中位 43638，最大 73393） / 80894（中位 70349，最大 214321） |

## 整理阶段

- selected_refs: 平均 45.0，中位 47，合计 1216
- read_ids: 平均 33.0，中位 33，合计 890
- tool_calls: 平均 54.5，中位 48，合计 1471
- manifest_chars: 平均 84996.5，中位 75985，合计 2294905
- llm_attempts: 平均 1.7，中位 1，合计 45
- llm_failed_attempts: 平均 0.6，中位 0，合计 15
- 端点分布: {'primary': 8, 'fallback2': 18, 'fallback2/primary': 1, 'None': 3}
- 审计合计: {"reads": 864, "unread": 59, "shape_only": 26, "unknown": 0}
- 触发「轴缺依赖类别」的样本: 11/30
  - clean--llm-probe-insurance-real-ctx-cache: {"intent_understanding": ["messages", "tool_calls"], "knowledge_data": ["tool_calls"], "model_capability": ["messages"], "planning_routing": ["tool_calls", "steps"]}
  - clean--llm-probe-insurance-real-ctx-ellipsis: {"intent_understanding": ["tool_calls"]}
  - clean--llm-probe-insurance-real-data-cash-value-unavailable: {"intent_understanding": ["tool_calls"], "knowledge_data": ["tool_calls"], "planning_routing": ["tool_calls"], "tool_execution": ["tool_calls"]}
  - clean--llm-probe-insurance-real-data-status-field-missing: {"context_memory": ["model_calls"], "intent_understanding": ["messages", "tool_calls"], "knowledge_data": ["tool_calls"], "model_capability": ["model_calls", "messages"], "planning_routing": ["tool_calls"], "tool_execution": ["tool_calls"]}
  - clean--llm-probe-insurance-real-direct-policy-status: {"context_memory": ["model_calls"], "intent_understanding": ["messages", "tool_calls"], "knowledge_data": ["tool_calls"], "model_capability": ["model_calls", "messages"], "planning_routing": ["tool_calls"], "tool_execution": ["tool_calls"]}
  - clean--llm-probe-insurance-real-policy-status-authorized: {"intent_understanding": ["tool_calls"], "knowledge_data": ["tool_calls"], "planning_routing": ["tool_calls"], "tool_execution": ["tool_calls"]}
  - clean--llm-probe-insurance-real-routing-name-then-status: {"intent_understanding": ["tool_calls"], "knowledge_data": ["tool_calls"]}
  - clean--llm-probe-insurance-real-scenario-customer-profile: {"intent_understanding": ["tool_calls"], "knowledge_data": ["tool_calls"]}

## 结论变化（80 处）


### 全部变化
- clean--llm-probe-insurance-real-baseline-insured-name tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-baseline-insured-name context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-baseline-insured-name knowledge_data: sound → not_evaluable
- clean--llm-probe-insurance-real-baseline-insured-name model_capability: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache intent_understanding: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache planning_routing: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache knowledge_data: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-cache model_capability: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-clarify intent_understanding: problematic → sound
- clean--llm-probe-insurance-real-ctx-clarify planning_routing: sound → problematic
- clean--llm-probe-insurance-real-ctx-clarify tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-clarify knowledge_data: problematic → sound
- clean--llm-probe-insurance-real-ctx-clarify model_capability: sound → not_evaluable
- clean--llm-probe-insurance-real-ctx-ref knowledge_data: not_evaluable → sound
- clean--llm-probe-insurance-real-ctx-ref model_capability: problematic → not_evaluable
- clean--llm-probe-insurance-real-data-cash-value-unavailable context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-data-cross-identity context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-data-cross-identity knowledge_data: sound → problematic
- clean--llm-probe-insurance-real-data-unknown-policy trace_analysis: complete → None
- clean--llm-probe-insurance-real-data-unknown-policy intent_understanding: sound → None
- clean--llm-probe-insurance-real-data-unknown-policy planning_routing: sound → None
- clean--llm-probe-insurance-real-data-unknown-policy tool_execution: sound → None
- clean--llm-probe-insurance-real-data-unknown-policy context_memory: sound → None
- clean--llm-probe-insurance-real-data-unknown-policy knowledge_data: problematic → None
- clean--llm-probe-insurance-real-data-unknown-policy model_capability: sound → None
- clean--llm-probe-insurance-real-general-qa intent_understanding: sound → problematic
- clean--llm-probe-insurance-real-general-qa model_capability: sound → problematic
- clean--llm-probe-insurance-real-intent-compound-insured-applicant context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-intent-negation-not-other-policy tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-model-format-only-name tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-model-format-only-name context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-model-format-only-name model_capability: sound → not_evaluable
- clean--llm-probe-insurance-real-model-pressure-confirm-without-query context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-policy-status-authorized tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-policy-status-authorized context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-routing-name-search tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-routing-name-then-status tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-routing-name-then-status context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-routing-name-then-status knowledge_data: sound → not_evaluable
- clean--llm-probe-insurance-real-routing-suffix-locate trace_analysis: complete → None
- clean--llm-probe-insurance-real-routing-suffix-locate intent_understanding: sound → None
- clean--llm-probe-insurance-real-routing-suffix-locate planning_routing: sound → None
- clean--llm-probe-insurance-real-routing-suffix-locate tool_execution: sound → None
- clean--llm-probe-insurance-real-routing-suffix-locate context_memory: problematic → None
- clean--llm-probe-insurance-real-routing-suffix-locate knowledge_data: sound → None
- clean--llm-probe-insurance-real-routing-suffix-locate model_capability: sound → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service trace_analysis: complete → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service intent_understanding: sound → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service planning_routing: sound → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service tool_execution: sound → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service context_memory: not_evaluable → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service knowledge_data: problematic → None
- clean--llm-probe-insurance-real-scenario-benefit-health-service model_capability: sound → None
- clean--llm-probe-insurance-real-scenario-customer-profile context_memory: sound → not_evaluable
- clean--llm-probe-insurance-real-scenario-customer-profile model_capability: sound → not_evaluable
- clean--llm-probe-insurance-real-scenario-faq-policy-loan model_capability: not_evaluable → sound
- clean--llm-probe-insurance-real-scenario-policy-plus-product tool_execution: sound → problematic
- clean--llm-probe-insurance-real-scenario-policy-plus-product context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-scenario-product-clause-term planning_routing: sound → not_evaluable
- clean--llm-probe-insurance-real-scenario-product-clause-term tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-scenario-product-clause-term context_memory: problematic → not_evaluable
- clean--llm-probe-insurance-real-scenario-product-waiting-period intent_understanding: sound → problematic
- clean--llm-probe-insurance-real-scenario-product-waiting-period planning_routing: sound → problematic
- clean--llm-probe-insurance-real-scenario-product-waiting-period tool_execution: sound → not_evaluable
- clean--llm-probe-insurance-real-scenario-product-waiting-period context_memory: sound → problematic
- frozen--snap-and-procedure tool_execution: sound → problematic
- frozen--snap-and-procedure context_memory: sound → not_evaluable
- frozen--snap-and-procedure model_capability: sound → problematic
- frozen--snap-cash-value tool_execution: sound → not_evaluable
- frozen--snap-cash-value context_memory: sound → not_evaluable
- frozen--snap-cash-value model_capability: sound → not_evaluable
- frozen--snap-multi-turn context_memory: sound → not_evaluable
- frozen--snap-policy-with-data context_memory: sound → not_evaluable
- frozen--snap-policy-with-data model_capability: sound → not_evaluable
- frozen--snap-unknown-policy intent_understanding: sound → problematic
- frozen--snap-unknown-policy tool_execution: sound → not_evaluable
- frozen--snap-unknown-policy context_memory: sound → not_evaluable
- frozen--snap-unknown-policy model_capability: not_evaluable → sound