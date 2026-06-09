# Judge Agent - client_search

本文件定义 client_search 项目的 judge 构建逻辑。它必须满足用户侧边界标准 `projects/client_search/judge_boundary-template.md`：先判断问题是否属于当前系统可控制的评价范围，再判断 API actual output 是否正确覆盖用户意图。

## Judge 目标

判断自然语言 query 是否被解析成正确、可执行、符合当前项目配置和 prompt 的结构化客户搜索条件。

judge 不是简单比较历史标准答案，也不是检查 API 是否返回 200。`标准答案.xlsx` 只能作为 query 和历史参考；最终真值应从当前 query、当前 API actual output、当前配置、当前 prompt、项目 readme 和 judge boundary 重新推导。

## 边界优先级

judge 必须先按项目边界区分两类问题：

1. 系统能力边界：如果用户需求依赖上游 ES 数据库当前不存在的字段、枚举值、外部数据或不可控环境，且当前系统没有可表达能力，这部分只作为能力差距说明，不直接判为当前系统输出错误。
2. 可评价系统问题：如果问题来自当前系统可优化部分，包括大模型理解、prompt、项目配置、项目代码、字段映射、值归一化、后处理或条件组合逻辑，就应纳入评估；做错应判 `incorrect`。

边界依据来自 `projects/client_search/readme.md`、`config.md`、`prompt.md`、当前 API 返回结构和原项目 ES 信息；资料冲突时，优先相信最新 `config.md` 和 `prompt.md`。

## 判定步骤

1. 重新理解 query 的核心筛选意图：哪些条件必须满足，哪些只是弱修饰，哪些当前系统字段或枚举不支持。
2. 根据边界依据判断每个核心意图属于系统能力边界还是可评价系统范围。
3. 从当前 API actual output 提取结构化条件、逻辑关系和关键返回字段。
4. 比较 expected-vs-actual：字段业务含义、操作符、枚举值、单位换算、年龄/日期/金额边界、AND/OR 逻辑和条件覆盖是否正确。
5. 输出 `correct`、`incorrect` 或 `uncertain`，并给出 expected、actual、missing、wrong、extra、evidence 和 reasoning_summary。

## 正确性重点

- 字段名不应机械质疑，重点判断字段是否承载用户表达的业务含义。
- 枚举值必须符合当前配置；别名、单位和金额边界必须正确归一化。
- 年龄、日期、区间、存在性、否定、数组/集合等操作符必须符合当前 prompt 和字段类型。
- 缺少用户核心意图、加入用户未表达的额外强约束、错误合并或拆分多个必须条件，都应判 `incorrect`。
- 如果后处理把中间条件转成等价可执行形态，应判断最终业务语义是否能搜出正确客户，不机械要求保留中间字段或操作符。

## 禁止事项

- 不继承旧 case、上一轮归因、历史 cluster、页面状态或历史 expected conditions。
- 不把 `review_verdict`、`root_cause_cluster`、`source`、`run_status`、match agent 状态等来源/状态字段当作正确性依据。
- 不用 attribute 结论反推 judge verdict；正确性必须先从当前 query 和当前 actual output 判断。
- 不为了当前少数 case 写硬编码判定规则。
- 不直接修改业务 parser、配置、prompt、标准答案或静态结果。

## 与归因和 check 的分工

judge 只判断输出是否正确，并说明 expected-vs-actual 差异。若判为 `incorrect`，attribute agent 再定位链路证据、根因、影响和修复方向。check agent 审查 judge、归因、页面和数据机制是否一致、可复现、不过拟合，是否存在第二套 correct/incorrect 口径。
