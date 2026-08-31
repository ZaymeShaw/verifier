# Authority Investigation Report: client_search-judge-authority-report

- report_id: `client_search-judge-authority-report`
- investigation_snapshot_id: `803ed4579670792771870aa13b2523177f96f146`
- business_scope: Judge 在外部业务验收时对外部契约、完整值空间、责任边界、口语映射与查询形式等价性的权威裁决依赖。本报告只登记资料直接决定的事项与未决方向，不包含单个 case 的 actual、score、confidence 或 verdict。

## Materials

### current-project-config

- source_location: `project_package:project.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — parser 当前声明的字段、枚举与映射配置集合（哪些值当前可表达、可执行）
   - statement: project.yaml 声明当前 parser 的字段/枚举/规则资产路径与启用状态，是判断 actual 是否使用清单外字段或清单外值时的当前行为基线。
   - locator: `verifier.assets 配置资产路径`
   - scenario: client_search_parser_current_configuration
   - conditions: `project.yaml 对应资产路径启用`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际合法值全集（不由本项目配置决定）

#### Limitations

- 只能证明当前 parser 行为，不能证明外部业务真实值空间或业务认可口径。

### project-judge-boundary

- source_location: `project_package:judge_boundary_protocals.md`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — parser 与外部数据库/搜索服务之间的责任划分（什么归 parser、什么不自动归 parser）
   - statement: judge_boundary 模板说明 parser 可优化部分在范围内，数据库记录缺失不自动归责 parser，外部约束不能归责 Live。
   - locator: `全文`
   - scenario: client_search_evaluation_boundary
   - conditions: `该文档代表项目当前正式责任边界`

#### Related（仅相关，不由该资料决定）

- 外部数据库实际可用性（不由 Judge 边界决定）

#### Connections

- upstream → project-judge-boundary-source (`judge_boundary-template.md 全文`) [derived_from]: AI 落地的责任边界协议由用户原文投影而来；责任边界裁决以用户原文（normative_rule）为准，本稿不独立构成规范依据。

#### Limitations

- 本稿是 AI 落地投影；责任边界与信任模型裁决以用户原文 project-judge-boundary-source 为准。

### project-judge-boundary-source

- source_location: `project_package:judge_boundary-template.md`

#### Decisions（该资料在下列范围内直接决定）

1. **normative_rule** — parser 与外部数据库/搜索服务之间的责任边界（评价范围归责）
   - statement: 用户原文：可评价范围是请求解析、字段和枚举选择、操作符、查询逻辑及系统内部可优化行为；下游 Elasticsearch 中不存在的字段/数据不可评价；数据库缺字段或枚举值时按业务系统能力边界判定是否正确；外部依赖责任上，下游数据能力只定义业务边界，服务连接失败必须单独记录。
   - locator: `judge_boundary-template.md 可评价范围/不可评价范围/外部依赖责任/限制条款`
   - scenario: client_search_evaluation_boundary
   - conditions: `用户原文，业务方显式确认边界`
2. **normative_rule** — 信任模型登记（M1 受控输出空间：配置/枚举资料为下游能力边界代理）
   - statement: 用户原文声明：上下游 es 数据库能力不是由系统能力强弱决定的；只有系统外部的约束才是硬标准；数据库信息从原项目的配置/枚举值文件中获取；判断 api 输出的搜索字段与客户搜索意图是否一致要在规定的枚举值内进行。据此，配置/枚举类资料的空间陈述可标 inlive_boundary（material-positioning.md §5 C1-C6）。
   - locator: `judge_boundary-template.md 外部依赖责任/judge 核心条款`
   - scenario: client_search_evaluation_boundary
   - conditions: `用户原文，业务方显式声明代理=下游空间`

#### Limitations

- 信任模型以空间不漂移为前提；漂移出现时按 material-positioning.md §5.3 失效/降级处理。

### project-evaluation-contract

- source_location: `project_package:evaluation.md`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — Judge 判断的输入重建方式（按当前请求、actual 和可用下游证据判断）
   - statement: 评估合同要求按当前请求、actual 和可用下游证据重建判断，不继承历史答案。
   - locator: `全文`
   - scenario: client_search_evaluation_rebuild
   - conditions: `作为 Judge mandatory context 加载`

#### Related（仅相关，不由该资料决定）

- 单个 case 的最终 verdict（由 Judge 运行时按证据作出）

#### Limitations

- 只规定判断方式，不提供具体外部业务事实。

### current-judge-standard

- source_location: `project_package:judge.md`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — Judge 三态判断与证据要求的标准（fulfilled/not_fulfilled/not_evaluable 边界）
   - statement: judge.md 定义 Judge 从用户和业务消费者视角判断可观察结果是否满足的标准，及缺失证据时保持 not_evaluable 的要求。
   - locator: `全文`
   - scenario: client_search_judge_standard
   - conditions: `作为 Judge mandatory context 加载`

#### Related（仅相关，不由该资料决定）

- 外部业务真实口径（不由 verifier 内部标准决定）

#### Connections

- peer → current-project-config (`verifier.assets 配置资产路径`) [dependency]: Judge 标准描述如何使用配置声明的能力进行判断，配置提供可执行字段/枚举基线。

#### Limitations

- verifier 内部标准不能替代业务方确认的正式规范。

### business-field-definitions

- source_location: `business_source:src/main/python/data/client_search_query_parse/field_definitions_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — 下游可承载的字段空间、字段搜索支持状态与操作符空间（字段是否存在、是否允许作为搜索条件、支持什么操作符与值类型）
   - statement: field_definitions_args.yaml 声明字段、is_supported、操作符和值类型。is_supported=false 表示该意图需要被识别以给出不支持提示，但当前不能作为客户搜索条件；is_supported=true 或未显式标 false 的字段才进入普通搜索能力判断。该空间由下游 es 决定，parser 不能扩充；配置文件是该空间的代理（信任模型 M1 登记）。
   - locator: `field_definitions_args.yaml field/is_supported/operator/value_type 声明`
   - scenario: client_search_parser_field_carrier_standard
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `field_definitions 为当前启用配置`; `is_supported 按字段声明读取；任一同字段声明显式 false 时不得按普通支持字段处理`; `无灰度覆盖`
2. **current_behavior** — 意图到查询条件的换算规则（字段值/操作符如何换算）
   - statement: field_definitions_args.yaml 中的换算与归一规则是 parser 当前实现行为，只解释系统现在如何换算，不构成裁决选择正确性的依据。当前行为包括：未指明地址类型（居住地址/住址/住在等）走 ANY_ADDRESS_FIELD；附近未给距离时默认 5 公里；综拓理赔有状态用 MATCH、仅“有过理赔”用 EXISTS；税优产品同时存在 CONTAINS 与 NOT_CONTAINS 两条 intent。
   - locator: `field_definitions_args.yaml 换算规则条目`
   - scenario: client_search_parser_field_carrier_standard
   - conditions: `field_definitions 为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际合法值全集（不由字段定义决定）
- 业务认可的正式术语口径（不由字段定义决定）

#### Limitations

- 空间类陈述在信任模型 M1 下作为下游能力空间代理；换算规则类陈述仍是当前行为，不裁决对错。
- familyInfo.familyclientbirthday 的字段定义 intent 现声明 RANGE/GT/GTE/LT；enhanced_rules 仍使用 LTE、EXISTS。操作符口径未完全对齐，未裁决。
- is_supported 只决定字段当前是否允许作为搜索条件；它不决定用户表达是否应映射到该字段，也不证明外部数据库存在具体记录。

### business-field-enums

- source_location: `business_source:src/main/python/data/client_search_query_parse/field_enums_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — 字段的可枚举值空间（哪些值在下游可表达、可执行）
   - statement: field_enums_args.yaml 声明各字段的可枚举值空间；其中 onlyShareClientFlag 仅登记合法值 Y。值空间由下游数据库决定，枚举文件是该空间的代理（信任模型 M1 登记）：parser 造不出空间外的值。
   - locator: `field_enums_args.yaml 字段枚举声明`
   - scenario: client_search_parser_field_enum_space
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `字段枚举为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际合法值全集（不由枚举文件决定）

#### Limitations

- 信任模型 M1 下枚举文件作为下游值空间代理；出现空间外漂移是发现信号（material-positioning.md §5.3），不是否认空间的理由。

### business-value-mappings

- source_location: `business_source:src/main/python/data/client_search_query_parse/value_mappings_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — 口语映射的目标值空间（映射可达哪些归一值）
   - statement: value_mappings_args.yaml 的映射目标值均落在下游合法值空间内。目标值空间由下游决定，映射配置是目标值空间的代理（信任模型 M1 登记）。
   - locator: `value_mappings_args.yaml 映射目标值`
   - scenario: client_search_parser_spoken_normalization
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `映射为当前启用配置`; `无灰度覆盖`
2. **current_behavior** — 口语别名到归一值的归一选择（某口语表达映射到哪个目标值）
   - statement: 口语别名映射到哪个归一值是 parser 当前归一选择，只解释现状，不构成裁决选择正确性的依据。
   - locator: `value_mappings_args.yaml 映射条目`
   - scenario: client_search_parser_spoken_normalization
   - conditions: `映射为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 业务认可的正式术语表（不由当前映射决定）

#### Limitations

- 目标值空间在信任模型 M1 下作为下游空间代理；具体口语→归一值的选择仍是当前行为。

### business-enhanced-rules

- source_location: `business_source:src/main/python/data/client_search_query_parse/enhanced_rules_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — 复杂口语模式的解析规则（年龄/时间/状态等模式如何落到字段与操作符）
   - statement: enhanced_rules 定义年龄、时间、状态、地址等复杂口语模式的正则与 merge_to_llm 行为；其中包含共享给我的客户组合规则（onlyShareClientFlag=Y）、地址解析模式、理赔险种有/无拆分、农历生日与保单数量（polNum）规则。它与 field_definitions 一起决定解析行为，是判断 actual 是否符合当前规则实现的行为基线。
   - locator: `enhanced_rules_args.yaml rules[模式名]`
   - scenario: client_search_parser_rule_patterns
   - conditions: `规则为当前启用配置`; `merge_to_llm 行为按配置生效`

#### Related（仅相关，不由该资料决定）

- 外部业务规范（不由正则模式决定）

#### Limitations

- 规则模式是当前实现行为，不是外部业务规范。

### business-time-knowledge

- source_location: `business_source:src/main/python/data/client_search_query_parse/time_knowledge_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — 相对时间口语（本周/上周/下月/未来N天等）到日期区间的换算口径
   - statement: time_knowledge 定义相对时间词的偏移与区间换算（current_week / week_offset、next_month、next_n_days 等），是时间窗口意图可执行性的当前基线；与 poleffdate 等日期字段定义共同决定时间条件是否可表达。
   - locator: `time_knowledge_args.yaml resolver`
   - scenario: client_search_parser_relative_time
   - conditions: `时间知识为当前启用配置`; `相对时间词命中 time_knowledge 条目`

#### Related（仅相关，不由该资料决定）

- 真实日历日期计算（跨年/闰年等需按实际日期验证）

#### Limitations

- 时间知识是当前实现口径，换算正确性需以真实日期计算验证。

### business-planfullname-enums

- source_location: `business_source:src/main/python/data/client_search_query_parse/polNoInfo.plancodeinfo.planfullname_enums_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — 产品全称的可枚举值空间（哪些产品全称在下游可表达）
   - statement: planfullname 枚举声明产品全称的可枚举空间。空间由下游数据库决定，枚举文件是该空间的代理（信任模型 M1 登记）。
   - locator: `polNoInfo.plancodeinfo.planfullname_enums_args.yaml 枚举声明`
   - scenario: client_search_parser_plan_fullname_space
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `产品全称枚举为当前启用配置`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际产品全集（不由枚举文件决定）

#### Limitations

- 信任模型 M1 下产品全称枚举作为下游值空间代理；出现空间外漂移是发现信号（material-positioning.md §5.3）。

### business-behavior-intents

- source_location: `business_source:src/main/python/data/client_search_query_parse/behavior_intent_definitions_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — 下游可承载的客户行为字段空间：customer_activity 字段是否存在、是否允许作为客户搜索条件、支持 MATCH 操作符，以及 activity 枚举值空间（哪些行为值下游可表达、可执行）。
   - statement: behavior_intent_definitions_args.yaml 声明 customer_activity 字段、activity 枚举值空间与 is_supported。该空间由下游决定，parser 不能扩充；配置文件是该空间的代理（信任模型 M1 登记）。
   - locator: `behavior_intent_definitions_args.yaml field/intents[].activity/is_supported`
   - scenario: client_search_parser_behavior_field_carrier_standard
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `behavior_intent_definitions 为当前启用配置`; `无灰度覆盖`
2. **current_behavior** — 自然语言到 customer_activity 枚举值的候选选择规则（aliases/activity_template/selection_notes/positive_examples/negative_examples/confusing_intents）。
   - statement: behavior_intent_definitions_args.yaml 中的 aliases、activity_template、selection_notes、示例与混淆意图是 parser 当前实现行为，只解释系统现在如何选择行为枚举，不构成裁决选择正确性的依据。
   - locator: `behavior_intent_definitions_args.yaml intents[].aliases/activity_template/selection_notes/examples/confusing_intents`
   - scenario: client_search_parser_behavior_selection
   - conditions: `behavior_intent_definitions 为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际合法行为值全集（不由 behavior_intent_definitions 决定）
- 业务认可的行为语义口径（不由该文件决定）

#### Limitations

- 空间类陈述在信任模型 M1 下作为下游能力空间代理；选择规则类陈述仍是当前行为，不裁决对错。
- 出现空间外 activity 漂移是发现信号（material-positioning.md §5.3），不是否认空间的理由。

### business-behavior-rules

- source_location: `business_source:src/main/python/data/client_search_query_parse/behavior_enhanced_rules_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **current_behavior** — 客户行为意图的规则解析与候选选择（patterns/priority/negative_patterns/suppressors/retrieval_synonyms 等）。
   - statement: behavior_enhanced_rules_args.yaml 中的规则、优先级和归一化是 parser 当前行为解析逻辑，只解释系统现在如何解析行为查询，不构成裁决选择正确性的依据。
   - locator: `behavior_enhanced_rules_args.yaml rules/text_processing/policies`
   - scenario: client_search_parser_behavior_rule_selection
   - conditions: `behavior_enhanced_rules 为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 客户行为意图的自然语言表达

#### Limitations

- 当前行为，不能证明应然选择；只能解释 parser 现在如何解析。

### business-abbrname-enums

- source_location: `business_source:src/main/python/data/client_search_query_parse/polNoInfo.plancodeinfo.abbrname_enums_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — polNoInfo.plancodeinfo.abbrname 的可枚举值空间（哪些产品简称在下游可表达、可执行）。
   - statement: abbrname_enums_args.yaml 声明 polNoInfo.plancodeinfo.abbrname 的产品简称枚举值空间。该空间由下游数据库决定，parser 不能扩充；配置文件是该空间的代理（信任模型 M1 登记）。
   - locator: `abbrname_enums_args.yaml polNoInfo.plancodeinfo.abbrname.values`
   - scenario: client_search_parser_abbrname_enum_space
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `abbrname_enums 为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际产品简称全集（不由 abbrname_enums 决定）

#### Limitations

- 信任模型 M1 下枚举文件作为下游值空间代理；出现空间外漂移是发现信号（material-positioning.md §5.3），不是否认空间的理由。

### business-claimplancodename-enums

- source_location: `business_source:src/main/python/data/client_search_query_parse/polNoInfo.claimdatainfo.claimplancodename_enums_args.yaml`

#### Decisions（该资料在下列范围内直接决定）

1. **inlive_boundary** — polNoInfo.claimdatainfo.claimplancodename 的可枚举值空间（哪些理赔险种名称在下游可表达、可执行）。
   - statement: claimplancodename_enums_args.yaml 声明 polNoInfo.claimdatainfo.claimplancodename 的理赔险种名称枚举值空间。该空间由下游数据库决定，parser 不能扩充；配置文件是该空间的代理（信任模型 M1 登记）。
   - locator: `claimplancodename_enums_args.yaml polNoInfo.claimdatainfo.claimplancodename.values`
   - scenario: client_search_parser_claimplancodename_enum_space
   - conditions: `trust_model: M1 受控输出空间（见 project-judge-boundary-source 信任模型登记）`; `claimplancodename_enums 为当前启用配置`; `无灰度覆盖`

#### Related（仅相关，不由该资料决定）

- 下游数据库实际理赔险种名称全集（不由 claimplancodename_enums 决定）

#### Limitations

- 信任模型 M1 下枚举文件作为下游值空间代理；出现空间外漂移是发现信号（material-positioning.md §5.3），不是否认空间的理由。

## Coverage Gaps（业务事项 × 条件缺少唯一决定资料）

### semantic-mapping-authority

- conclusion_kind: `normative_rule`
- governs: 口语表达在请求上下文中存在多个会改变目标客户集合的合理映射且无法唯一选择时，哪个映射代表业务认可的用户语义？
- dimension_ids: `search-intent-preservation`
- basis_source_ref_ids: `business-value-mappings`, `business-field-definitions`, `current-judge-standard`
- gap_reason: 现有口语映射规则、历史案例与字段能力清单的产生和生效流程不同；当前没有受治理术语表或业务确认记录，无法在冲突映射之间确定正式口径。
- required_evidence:
  - 业务方认可的澄清规则或标准术语表

### query-form-equivalence-authority

- conclusion_kind: `external_fact`
- governs: 用户要求与 actual 使用不同查询形式，且字段定义、值归一化和已确认封闭等价规则不能直接证明目标客户集合相同时，应以什么裁决两种查询形式是否等价？
- dimension_ids: `search-intent-preservation`, `downstream-query-consumability`
- basis_source_ref_ids: `business-field-definitions`, `business-enhanced-rules`, `current-judge-standard`
- gap_reason: 静态等价规则与真实查询结果分别由规则维护和数据运行链路产生；当前缺少固定数据快照上的双查询结果或业务确认的封闭规则，无法确定两种查询形式在当前系统中等价。
- required_evidence:
  - 固定数据快照上的只读双查询比较能力
  - 业务确认的封闭式等价规则

### responsibility-boundary-unsupported-field

- conclusion_kind: `normative_rule`
- governs: 字段在能力清单内但 is_supported=false 时，该不支持是产品职责外还是职责内能力缺失的正式裁定
- conditions: `字段在 business-field-definitions 清单内且 is_supported=false / is_supported_explicit=true`; `查询意图明确命中该字段语义`; `业务方未就该字段发布职责归属裁定`
- dimension_ids: `search-intent-preservation`, `downstream-query-consumability`
- basis_source_ref_ids: `business-field-definitions`, `project-judge-boundary-source`, `current-judge-standard`
- gap_reason: 现有资料只登记字段当前不能作为搜索条件（business-field-definitions 的 inlive_boundary，M1 信任模型代理下游可承载空间）；project-judge-boundary-source 的 normative_rule 只归责评价范围并登记信任模型，均未逐字段裁定不支持是有意不做（职责外）还是应实现未实现（职责内能力缺失）。authority.md §8.3 要求该边界由 authority 基于资料现场裁决，缺此裁定资料时同一语义（如 093 车牌、088 盘客）的落位依赖现场裁决而非业务背书。
- required_evidence:
  - 业务方对 is_supported=false 字段逐项确认的职责边界声明（职责外 vs 职责内能力缺失，含生效条件与版本）

### responsibility-boundary-entity-name-query

- conclusion_kind: `normative_rule`
- governs: 按公司/单位/机构名称查询客户的职责归属（产品职责外 vs 职责内能力缺失）
- conditions: `查询意图为按公司/单位/机构名称定位客户`; `字段定义、枚举与映射资料均未登记该查询维度`
- dimension_ids: `search-intent-preservation`, `downstream-query-consumability`
- basis_source_ref_ids: `business-field-definitions`, `business-value-mappings`, `project-judge-boundary-source`
- gap_reason: 公司/单位/机构名称类查询维度在字段定义、枚举与映射资料中均无能力声明，authority 只能依资料中不存在推定职责外；缺业务方确认的职责边界声明证明该维度有意不在产品职责内（而非应实现未实现）。fulfilled.md §9 任务 2 规定补齐前查不了一律按说不清。
- required_evidence:
  - 业务方确认的职责边界声明（公司/单位/机构名称查询维度是否属产品职责、下游接口是否支持该维度）

### silently-dropped-request-dimension

- conclusion_kind: `external_fact`
- governs: 请求中被静默丢弃的维度（如业务员归属）在下游是否有可承载字段及是否属产品职责
- conditions: `查询包含清单外且被 actual 静默忽略的维度`; `字段定义/枚举/映射均无该维度声明`; `actual 无 notice/标记暴露该维度被丢弃`
- dimension_ids: `search-intent-preservation`, `downstream-query-consumability`
- basis_source_ref_ids: `business-field-definitions`, `current-project-config`, `project-evaluation-contract`
- gap_reason: 业务员归属等请求维度被静默丢弃时（actual 仅输出客户姓名条件，无 unsupported notice、无清单字段、reference 为空），authority 无确定性候选信号可触发（authority.md §8.1 候选依赖清单内字段）；现有资料只覆盖已登记字段空间，未声明请求维度缺失的暴露机制，runtime 无法区分职责外与职责内应承载却静默丢弃。
- required_evidence:
  - 下游接口声明（业务员归属维度是否有可承载字段及搜索能力）
  - 业务方确认的职责边界声明（该维度应否被请求承载）

### enum-space-search-consumption-boundary

- conclusion_kind: `external_fact`
- governs: 已登记的可枚举值空间（如产品全称）是否代表产品承诺可搜索的能力边界
- conditions: `字段枚举已登记为 inlive_boundary（M1 受控输出空间）`; `查询意图精确命中枚举内值`; `无业务方确认的下游接口声明佐证该空间可被搜索消费`
- dimension_ids: `search-intent-preservation`, `downstream-query-consumability`
- basis_source_ref_ids: `business-planfullname-enums`, `project-judge-boundary-source`, `business-field-definitions`
- gap_reason: planfullname 枚举以 inlive_boundary 登记哪些产品全称在下游可表达（M1 信任模型代理受控输出空间），但 M1 只代理空间可表达，未声明该空间等于产品承诺可搜索的边界；枚举含精确值却只回姓名（如 148）是否属职责内能力缺失（本可支持却没给），缺下游接口声明佐证枚举空间与可搜索字段的对应关系。
- required_evidence:
  - 下游搜索接口声明（产品全称枚举值空间与可搜索字段的对应关系）
