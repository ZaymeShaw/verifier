# Judge Boundary Implementation - client_search

本文件是 AI 根据 `projects/client_search/judge_boundary-template.md` 落地的 client_search judge 边界接入说明。用户侧标准是源头；本文件只负责把该标准接入 `impl` 的 judge/check/frontend 链路。

## Source standard

用户侧标准声明：client_search 的核心目标是判断当前 parser 能不能从依赖 ES 数据库中搜索到用户想要查询的客户。上游 ES 数据库字段、枚举值或实际数据缺失等当前系统无法直接控制的限制，不直接视为当前系统输出错误；模型、项目配置、prompt、项目代码、字段映射和后处理等当前系统可优化部分做得不好，应纳入评估范围。

## Runtime standard for judge

限制：有些用户需求受限于当前上游依赖的 ES 数据库中没有相应字段、枚举值或数据，可能无法完全满足用户意图；这类限制按业务系统能力边界判定，不直接视为当前系统输出错误。

评价范围：如果是当前系统可以优化的部分做得不好，比如大模型理解、项目配置、prompt、项目代码、字段映射、值归一化、后处理或条件组合错误，就应该纳入衡量范围，按实际错误判定。

核心依据：优先使用 ES/下游客户搜索的实际可查询语义、表结构、查询规则、字段和枚举能力来判断。原业务项目的字段定义、枚举、值映射和规则配置是系统外部/上下游能力边界的重要来源；`projects/client_search/prompt.md` 和静态 `config.md` 只是辅助参考，用于理解字段、枚举、操作符和格式要求；当真实下游结果集或 ES 查询语义能证明查询等价时，不应机械要求完全匹配 prompt/config 的某个中间形态。

下游不可用时的要求：不能因为无法调用 8081 就退化成机械比对 prompt/config 字段形态。judge 仍必须基于当前 parser 条件、ES 查询语法、字段语义、操作符语义、枚举能力和业务意图，尽可能判断搜索语义是否等价；只有条件语义或 ES 查询语义无法可靠判断时才返回 `uncertain`。

## Implementation mapping

- judge 输入读取本文件作为 `judge_boundary_spec`。
- judge 同时读取 `projects/client_search/judge_boundary-template.md` 作为用户侧边界源头。
- judge 同时读取 `projects/client_search/readme.md`、`config.md`、`prompt.md` 作为业务规则和能力边界辅助来源。
- client_search adapter 会把 parser 返回的 `conditions` 和 `query_logic` 组装成下游搜索请求格式，并按项目配置尝试调用 `application.downstream_search`。
- 下游搜索证据写入 `RunTrace.project_fields.downstream_search` 和 `execution_trace` 的 `client_search.downstream_search` 节点。
- 如果下游搜索成功，judge 可结合实际搜索返回判断是否能搜到用户意图客户，并在 `boundary_decision.result_set_verified=true` 时说明结果集已验证。
- 如果下游搜索不可用、未配置或 parser 无条件导致跳过，judge 必须标记 `result_set_verified=false`，但仍要做好 ES 查询语义等价判断；不能只因为没有结果集就直接 `uncertain` 或只做字符串级条件比对。
- 如果 parser 条件形态与 prompt/config 略有不同，但 ES 查询语义或结果集等价，judge 可以按等价查询判 `correct`。
- judge 输出仍使用通用 `JudgeResult` 协议字段：`evaluation_boundary`、`primary_assessment`、`contrast_assessments`、`boundary_decision`、`quality_flags`。
- check agent 需要检查 judge 是否保留了下游搜索证据状态、是否把不可用结果集误当成已验证、是否在下游不可用时仍执行了 ES 查询语义等价判断、是否出现第二套 correct/incorrect 口径。
