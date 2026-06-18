



<!-- ### 意图类问题怎么做好judge

当核心是对意图识别类业务API 输出进行正确性判定时，职责包括但不限于：

a) 重新理解 query 的核心筛选意图：哪些条件必须满足，哪些只是弱修饰，哪些当前的配置/数据/prompt不支持。
b) 根据当前配置判断输出是否语义正确：输出本身不机械质疑，但要判断 API 选择的字段是否承载了用户表达的业务含义。
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



 -->



