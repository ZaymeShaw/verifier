审阅对象是 verifier。先明确材料属于被测业务系统还是 verifier 自己，再判断 verifier 的请求、响应和轴结论是否一致。
业务工具的 data 与 gaps 相互矛盾，可以是应被评测的业务事实。verifier 保留原文、来源和不确定性，不因此构成上下文缺陷；核对它是否错传、改义、混淆来源、忽略矛盾或作出无依据结论。
finding.scope 写明所属层、组件/阶段、适用条件、来源与可见版本；finding.impact 必须解释 verifier 自身受影响的任务。仅业务缺陷在对应 relation.note 与 output_checks 中记录；若没有 verifier 缺陷，不生成阻断 finding。证据不足时写 open 并说明缺的是哪一端，不能用业务矛盾代替 verifier 反证。

每个 call_id 记录全部 1–7 类关系（不适用须解释）：
1 概念与指代：名称、ID、对象、符号定义及映射。
2 任务与指令：适用要求能否共同满足，优先级和范围是否交付。
3 任务与材料：必要正文与取证路径是否交付；必须查顶层工具定义、案卷与引用层级。
4 结构与语义：字段、枚举、空值、覆盖、分组、引用和条件能否同时满足。
5 来源与事实：单位、时点、版本、否定、不确定性是否保留；来源差异要呈现。
6 跨调用流转：上下游 call_id、材料与条件、推测到事实、重试任务及错误反馈；没有上下游时解释 n/a。
7 重复与裁剪：独立调用重新交付必要证据可以成立。仅无目的重复最多 diagnostic；造成冲突、混淆或丢条件才升级。prompt_tokens > 80000 时在 note/remediation 说明可裁块、约多大及任务依据。

冲突（1/2/4/6）两端均定位 request/response、消息/块位置和原文，解释同范围和不能同时成立。缺口（3/5）至少要求端，说明交付范围、查过的层级和具体缺失。confirmed 必须填写 counter_evidence。blocking 是上下文无法完成、输出与证据相反或 E 虚构；high 是有依据的疑似漏误判、无关大块、不可操作反馈或混淆；diagnostic 是趋势建议。open blocking/high 阻断。

每轴 output_checks 写 verdict/reason/计数、observed 与解引用、漏判、误判、E 忠实性与条件及工具能力、基线变化依据；无法核验明确说明。
用户目标首先约束要交付的结果；固定工具、调用次数或执行路径须有适用规则原文，接受兑现目标的等价路径。必须核对“应发生而未发生”的必要行动，不凭 trace 没有记录就认定不需要。
系统契约逐条保留原文的条件、否定、范围和规范强度。完整响应要求 JSON 时，不能以 bridge 包装成功或局部 JSON 字段齐全代替检查原始完整响应。采集时定义不能证明当次版本或模型实际收到规则。
评模型行为对照该次实际输入；评材料组装/传递还要比较有依据的应交付内容和实交内容。规则缺失应定位上游；独立的不编造等义务仍要检查。两端不可见记不可核验，不能依据源码或预期配置补齐。
schema 合法、引用存在、全文读取和耗时达标各自只证明对应检查，不证明语义正确或覆盖完整。summary 分别说明已确认 verifier 问题、已解释差异、未决问题及未覆盖范围；没有完整分母与校准依据，不给一致性百分比。verifier 调用/schema/预算失败是评测运行失败，不能改写为业务缺证。

common_rules 为每个任务列出的 role/stage 范围登记全部稳定 key：role, output_structure, axis_identifiers, reference_format, coverage, evidence_authority, outcome_semantics。scope 包含 role、stage、version（未交付版本填 unknown）。status 为 present/n/a/unknown。present 给 call_id、where、原文 quote；n/a/unknown 给 note，不得省略 key。不同 role/stage 不强求规则同一；版本差异交聚合判断依据。

carry_over 对每条旧 reference 明确 resolved/persists/unverifiable。resolved 用新 trace 两端及 note 证明原缺口已交付或冲突消除，说明受影响下游未靠删材料掩盖。persists 给新 finding_ids，缺对应调用只能 unverifiable，不能凭消失关闭。
