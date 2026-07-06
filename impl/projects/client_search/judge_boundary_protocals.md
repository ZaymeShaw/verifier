# Judge Boundary Implementation - client_search

本文件是 AI 根据 `projects/client_search/judge_boundary-template.md` 落地的 client_search judge 边界接入说明。用户侧标准是源头；本文件只负责把该标准接入 `impl` 的 judge/check/frontend 链路。

## Source standard

用户侧标准声明：client_search 的核心目标是判断当前 parser 能不能从依赖 ES 数据库中搜索到用户想要查询的客户。上游 ES 数据库字段、枚举值或实际数据缺失等当前系统无法直接控制的限制，不直接视为当前系统输出错误；模型、项目配置、prompt、项目代码、字段映射和后处理等当前系统可优化部分做得不好，应纳入评估范围。

## Runtime standard for judge

限制：有些用户需求受限于当前上游依赖的 ES 数据库中没有相应字段、枚举值或数据，可能无法完全满足用户意图；这类限制按业务系统能力边界判定，不直接视为当前系统输出错误。

评价范围：如果是当前系统可以优化的部分做得不好，比如大模型理解、项目配置、prompt、项目代码、字段映射、值归一化、后处理或条件组合错误，就应该纳入衡量范围，按实际错误判定。

核心依据：ES 数据库是核心判断依据，根据 ES 的表结构、查询规则、里面字段的枚举值来进行判断（数据库信息从原项目的配置文件/枚举值文件中获取）。原业务项目的字段定义、枚举、值映射和规则配置是系统外部/上下游能力边界的重要来源。`projects/client_search/prompt.md` 和静态 `config.md` 只是辅助参考，用于理解字段、枚举、操作符和格式要求。

**关键原则：**
- 因为上下游的 ES 数据库能力不是由本系统强弱决定的，所以评估只评价当前系统做得怎么样，不评估由于上游限制导致的偏差（无法控制的 ES 数据库）。
- 如果是本系统可优化的部分（大模型、项目配置 prompt.md/config、项目代码、后处理逻辑、pipeline、模型能力本身等）做得不好，纳入衡量范围。
- 由于 prompt、项目配置、后处理逻辑、pipeline 等系统内部内容都有可能出错，所以它们不能成为绝对标准。只有系统外部的约束（如下游 ES 依赖、下游数据）才是硬标准。
- Judge 的核心：看 API 结果输出，从下游配置文件/枚举值文件中了解 API 输出的搜索字段与客户输入的搜索意图是否一致。具体字段不完全是重点，因为标准答案可能不止一个，核心是业务语义正确，在规定的枚举值内根据 API 结果能搜出正确客户列表即可。
- 我们最终需要能从数据库中搜索到正确客户的 parser。如果 judge 发现数据库搜索结果等价，即便和 prompt.md/config.md/后处理逻辑/pipeline 的要求稍有不同也是可以接受的。
- 什么情况下会出现等价查询，取决于用户搜索语义和 ES 查询语法。当下游不可用时，必须做好这点的判断。如果无法判断，尝试看能否做模拟查询，看查出来的数据是不是用户意图想要的。

**特别注意：** 不要纠结 CONTAINS 和 MATCH 的问题，因为原项目会通过后处理处置，涉及输出为 CONTAINS 应改成 MATCH，或输出为 MATCH 应改成 CONTAINS 这种说法都是不必要的。

下游不可用时的要求：不能因为无法调用 8081 就退化成机械比对 prompt/config 字段形态。judge 仍必须基于当前 parser 条件、ES 查询语法、字段语义、操作符语义、枚举能力和业务意图，尽可能判断搜索语义是否等价；只有条件语义或 ES 查询语义无法可靠判断时才返回 `uncertain`。

## Implementation mapping

- judge 输入读取本文件作为 `judge_boundary_spec`。
- judge 同时读取 `projects/client_search/judge_boundary-template.md` 作为用户侧边界源头。
- judge 同时读取 `projects/client_search/readme.md`、`config.md`、`prompt.md` 作为业务规则和能力边界辅助来源。
- client_search adapter 会把 parser 返回的 `conditions` 和 `query_logic` 组装成下游搜索请求格式，并按项目配置尝试调用 `application.downstream_search`。
- 下游搜索证据写入 `RunTrace.extracted_output.downstream_search` 和 `execution_trace` 的 `client_search.downstream_search` 节点。
- 如果下游搜索成功，judge 可结合实际搜索返回判断是否能搜到用户意图客户，并在 `boundary_decision.result_set_verified=true` 时说明结果集已验证。
- 如果下游搜索不可用、未配置或 parser 无条件导致跳过，judge 必须标记 `result_set_verified=false`，但仍要做好 ES 查询语义等价判断；不能只因为没有结果集就直接 `uncertain` 或只做字符串级条件比对。
- 如果 parser 条件形态与 prompt/config 略有不同，但 ES 查询语义或结果集等价，judge 可以按等价查询判 `correct`。
- judge 输出使用 fulfillment-first `JudgeResult` 协议字段：`business_expectations`、`fulfillment_assessments`、`overall_fulfillment`、`evaluation_boundary`、`boundary_decision`、`quality_flags`。
- check agent 需要检查 judge 是否保留了下游搜索证据状态、是否把不可用结果集误当成已验证、是否在下游不可用时仍执行了 ES 查询语义等价判断、是否出现第二套 correct/incorrect 口径。
