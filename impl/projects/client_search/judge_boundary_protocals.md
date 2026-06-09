# Judge Boundary Implementation - client_search

本文件是 AI 根据 `projects/client_search/judge_boundary-template.md` 落地的 client_search judge 边界接入说明。用户侧标准是源头；本文件只负责把该标准接入 `impl` 的 judge/check/frontend 链路。

## Source standard

用户侧标准声明：client_search 的评估按业务系统能力边界判定。上游 ES 数据库字段或枚举缺失等当前系统无法直接控制的限制，不直接视为当前系统输出错误；模型、项目配置、prompt、项目代码等当前系统可优化部分做得不好，应纳入评估范围。

## Runtime standard for judge

限制：有些用户需求受限于当前上游依赖的 ES 数据库中没有相应字段或枚举值，可能无法完全满足用户意图搜索出正确字段；这类限制按业务系统能力边界判定，不直接视为当前系统输出错误。

评价范围：如果是当前系统可以优化的部分做得不好，比如大模型理解、项目配置、prompt、项目代码、字段映射或后处理错误，就应该纳入衡量范围，按实际错误判定。

边界依据：数据库和字段/枚举相关信息从 `projects/client_search/readme.md`、`config.md`、`prompt.md` 和原项目 ES 信息中确认；资料冲突时，优先相信最新 config 和 prompt。

## Implementation mapping

- judge 输入读取本文件作为 `judge_boundary_spec`。
- judge 同时读取 `projects/client_search/judge_boundary-template.md` 作为用户侧边界源头。
- judge 同时读取 `projects/client_search/readme.md`、`config.md`、`prompt.md` 作为业务规则和能力边界来源。
- judge 同时读取 `impl/projects/client_search/judge.md` 作为 client_search 项目 judge 构建逻辑，确保边界协议能约束 expected-vs-actual 判定。
- judge 输出仍使用通用 `JudgeResult` 协议字段：`evaluation_boundary`、`primary_assessment`、`contrast_assessments`。
- check agent 只检查 judge 是否按该最终评估边界输出结构化结果，不要求用户侧标准填写内部字段。
