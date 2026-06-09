

根据config.md中的字段定义以及prompt.md的要求，判断模型的输出是否正确，是否能搜索出正确的客户
标准答案的答案结果由于数据库字段已经过时，跟api返回结果不一致，他的结果只能作为参考，请你需要根据最新的config.md/prompt.md要求进行实时标注。api返回的字段格式这种肯定是正确的，你重点关注的是他的值写的对不对，引用选择的字段合不合理，从语义上判断
通过start.md执行模型服务重启的流程

> 业务目标：产出正确的数据库搜索结果，从数据库中搜索出正确的客户
> 限制：有些用户受限于当前数据库中没有相应字段或枚举值的，可能无法完全满足用户意图搜索出正确字段，此时应该按照系统能力边界判定是否正确







## 现在要做什么
1. 构建 `impl/projects/client_search/judge.md` 的 judge agent，用来统一判断客户搜索测试用例的 API 输出是否正确。
2. live页、归因总结等judge判定统一对齐到 judge agent 口径。
3. 用 check agent 的口径复核：judge 只负责判定“输出是否正确”，attribute-analyzer 负责不正确后的归因，check agent 负责审查判定/归因/页面/数据机制是否一致、可信、不过拟合。

## judge agent 的构建原则
1. 重点：judge agent 不是简单比较标准答案，也不是看 API 是否返回 200，而是判断“自然语言 query 是否被解析成了正确、可执行、符合当前配置的结构化搜索条件”。
2. 以当前项目配置、prompt 和业务 QA 为准：`标准答案.xlsx` 只能作为 query 和历史参考，不是最终真值；字段、枚举、操作符、值归一化必须按当前仓库实际配置判断。
3. judge 必须从当前 query 重新推导核心意图，不能继承旧 case、上一轮归因、历史聚簇或页面状态中的 expected conditions；出现无关字段污染时应判定为 judge/归因质量问题。
4. judge 的输出必须是稳定二值：`correct` / `incorrect`，同时给出置信度、expected-vs-actual 证据和判定理由；不确定时也要落到二值，并把不确定性写入 `probability` 和 `evidence`。
5. judge 只判“是否正确”和“哪里与期望不一致”；不承担完整根因定位。若判定为 `incorrect`，再交给 attribute-analyzer 做链路证据、根因、影响和修复方向。
6. judge 要保持泛化能力：不能为了当前少数 case 增加硬编码判定，也不能把来源标签、页面状态、match agent 状态、归因状态当成正确性依据。
7. judge 必须能被页面和服务端复用：归因总结、live query、大模型归因等的判定口径都应一致。
8. judge 判定对象是 API 最终 actual output：如果当前项目后处理会把中间条件转成等价可执行形态（如单值 `CONTAINS [x]` 归并为同字段 `MATCH x`，或家庭成员年龄转为等价生日边界），应判断业务语义是否仍能搜出正确客户，而不是机械要求保留中间字段/操作符。

## judge agent 做什么
judge agent 的主要职责是对一条客户搜索 API 输出进行正确性判定，包括但不限于：

a) 重新理解 query 的核心筛选意图：哪些条件必须满足，哪些只是弱修饰，哪些当前字段不支持。
b) 根据当前配置判断字段是否语义正确：字段名本身不机械质疑，但要判断 API 选择的字段是否承载了用户表达的业务含义。
c) 判断操作符是否符合字段类型和 prompt 规则：例如数组/枚举集合、存在性、否定购买、区间、精确值、日期窗口、AND/OR 等不能只看字面相似。
d) 判断值是否正确归一化：枚举值、别名、单位换算、金额边界、年龄/日期范围、相对时间窗口都必须按当前配置和 prompt 规则处理。
e) 判断条件覆盖是否完整：缺少用户核心意图、加入用户未表达的额外强约束、把多个必须条件错误合并/拆分，都应判为 `incorrect`。
f) 输出可被机器和页面稳定消费的判定结构：`verdict`、`probability`、`expected`、`actual`、`missing_conditions`、`wrong_conditions`、`extra_conditions`、`evidence`、`judge_basis`。
g) 对已支持但输出不正确的 case，给出最小定位提示，例如更可能是规则召回、prompt、配置/枚举、后处理、字段不支持或评估口径问题；但不要替代 attribute-analyzer 的完整根因分析。

## judge agent 不做什么
1. 不直接修改业务 parser/config。
2. 不为了通过当前 case 修改标准答案或静态结果。
3. 不把 `review_verdict`、`root_cause_cluster`、`source`、`run_status`、`MATCH_AGENT_REALTIME_INCORRECT` 等来源/状态字段当作正确性依据。
4. 不把 attribute-analyzer 的根因结论反推成 judge 结论；正确性必须先从 query 与 actual API output 判断。
5. 不输出“可能正确/需要人工看”作为最终 verdict；这些只能体现在低置信度和 evidence 中。

## 为什么需要 judge.md
当前评估链路中存在多处会产生或展示 `correct/incorrect` 的位置：

请该项目的judge都使用同一个逻辑。如果这些位置各自使用不同逻辑，就会出现：conditions 其实正确但被归为 incorrect、归因内容说正确但 verdict 仍是不通过、旧 case 的 expected conditions 污染新 query、页面统计和归因聚簇不一致等问题。因此需要一个 judge agent 作为统一判断口径。
- 后续归因总结流程中所有“是否正确”的前置判断

## 与其它 agent 的分工
- judge agent：判断 API 输出对不对，并给出 expected-vs-actual 证据。
- attribute agent：当 judge 判为 `incorrect` 时，定位为什么错、错在哪条链路、影响是什么、怎么修。
- check agent：审查 judge、归因、页面、数据、生成机制是否一致、可复现、不过拟合，是否存在第二套口径或 data-only patch。

## check agent 对齐要求
构建或修改 judge 相关逻辑后，需要按 check agent 口径检查：

1. 是否所有 judgement 都从当前 query 和 current actual output 推导，没有旧 case 污染。
2. 是否所有页面/产物使用相同 `correct/incorrect` 语义。
3. 是否 conditions 正确但归因/summary 仍显示 incorrect 的冲突被标为需要复核。
4. 是否未把来源、状态、批次、聚簇名当成正确性依据。
5. 是否默认用例池聚簇仍是语义 root cause，不是 judge 来源标签。
6. 是否上传/生成用例不会覆盖默认池，也不会绕过 judge 直接进入归因聚簇。
7. 是否新增机制可以用小样例复现并回归，不是只改当前 JSON 结果。

