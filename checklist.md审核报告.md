# checklist.md 审核完结报告

## 审核范围

对 client_search 项目的 checklist.md 全部 19 项进行审计，验证依据：
- 最新 E2E 批跑结果（`tmp/20260622-225553/`）中可验证的部分
- 当前代码静态分析
- 当前代码实时 `run_chain` 单 case 验证

## 各项结论

| # | 描述 | 结果 | 证据 |
|---|------|------|------|
| 1 | 8000 port API reachable | **PASS** | 全部 20 cases output_ok=True；batch report 无 API 级错误 |
| 2 | raw_response 保持原始输出 | **PASS** | core adapter 架构保证；frontend 使用 raw_response 字段 |
| 3 | extracted_output 包含通用摘要+结构化 | **PASS** | 所有 case 输出均含 summary + structured_output |
| 4 | 专有字段保留在 project_fields | **PASS** | adapter.py project_fields() 承载 downstream_search/application_boundary |
| 5 | judge 使用完整文档链 | **PASS** | evaluation.md, judge_boundary_protocals.md, judge.md, judge_boundary-template.md, prompt.md, config.md 均存在且路径正确 |
| 6 | judge 核心目标 = ES 检索能力 | **PASS** | 所有 fulfilled/not_fulfilled 判据一致基于条件语义和 ES 可执行性 |
| 7 | downstream_search 保留 | **PASS** | 所有 case quality_flags 含 application_boundary_parser_only |
| 8 | 下游不可用 → result_set_verified=false | **PASS** | judge 文本明确标注"下游ES搜索不可用" |
| 9 | 下游不可用 → 不应自动 uncertain | **FIXED** | 原 2 个 uncertain case（cs-age-sex-premium-correct-1, cs-premium-unit-error-1）已修复：`_apply_condition_comparison` + `_default_fulfillment_assessment` 正确处理 reference_fallback evaluable=True 无 gap 场景，当前代码 live run 输出 verdict=correct |
| 10 | 下游可用 → result_set_verified | N/A | 本轮批跑下游均不可用 |
| 11 | judge_boundary 文件位置 | **PASS** | 3 个文件均存在：impl/judge_boundary-template.md, projects/client_search/judge_boundary-template.md, impl/projects/client_search/judge_boundary_protocals.md |
| 12 | 用户层 boundary = 纯语言 | **PASS** | projects/client_search/judge_boundary-template.md 为纯语言标准 |
| 13 | attribute 使用当前 trace+judge+文档 | **PASS** | attr 输出含具体条件分析、ES 状态、query 文本 |
| 14 | frontend 仅展示扩展 | **PASS** | frontend_view.py 无 cs 专有硬编码 |
| 15 | 通用 core 不硬编码 cs 字段 | **PASS** | core/adapter.py, judge.py, schema.py, pipeline.py 均无 cs 专有字段 |
| 16 | 失败含证据+验证步骤+修改方向 | **PASS** | 4 个 not_fulfilled case 均有详细 reasoning，attr 含根因+验证+修改 |
| 17 | frontend 保持单 case 流程 | **PASS** | check1.py 使用单 case pipeline |
| 18 | 项目文档变化时 resync | N/A | 流程级约束 |
| 19 | 归因标记 trace 阶段状态 | **PASS** | chain_nodes/earliest_divergence 在 attr 结果中 |

## 审核中发现的修复

1. **checklist.md #5 更新**（前序迭代）— 明确 judge_boundary_protocals.md 是协议映射，judge_boundary-template.md 是用户层标准
2. **reconciliation flow 修复** — adapter.py `_apply_condition_comparison` 在 reference_fallback evaluable=True 且无 gap 时正确设置 why_verdict；`_default_fulfillment_assessment` 返回 "fulfilled" 而非 "not_evaluable"

## 结论

全部 19 项审核完成。15 项 PASS，1 项需修复后从 FAIL 变为 FIXED（#9），2 项 N/A。无剩余待修复问题。
