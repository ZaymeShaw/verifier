# Audit Gates

安全检查，防止 meta-verifier 偷懒。用 `MetaVerifierDemandCoverageAuditor` 执行。

## Planned-run gates（执行前）

| Gate | 触发条件 |
|---|---|
| `missing_goal_decomposition` | 没有拆解用户目标为 requirements |
| `missing_layer_mapping` | 没有记录可见/不可见面 |
| `missing_source_backed_checklist` | checklist item 没有 source |
| `missing_requirement_link` | checklist item 没有关联 requirement |
| `missing_browser_evidence_plan` | frontend/browser 可见但没有 browser evidence plan |
| `missing_higher_level_probe` | broad/business route 没有 higher-level probe |

## Completed-run gates（执行后）

| Gate | 触发条件 |
|---|---|
| `unsupported_confirmed_finding` | confirmed finding 的 evidence_refs 无对应 evidence，或来自 reviewer 没有独立验证 |
| `missing_browser_evidence` | browser-required 项没有 browser evidence |
| `pass_theater_risk` | no confirmed findings 且没有 higher-level probe evidence |
| `invisible_layer_risk` | 有不可见面但没有体现在 confidence impact 中 |
| `reviewer_critique_as_confirmed` | reviewer critique 被标为 confirmed |

## 反 pass theater 规则

以下情况必须标记 `pass_theater_risk`：
- 报告没有 confirmed finding
- 且没有执行 higher-level demand-side probe
- 且没有说明不可见面如何降低了置信度

如果判定为 pass theater，报告必须改为：
- 说明探了什么
- 为什么没有确认问题
- 哪些不可见面降低了置信度
- 哪些假设或压力路径最值得下一步调查
