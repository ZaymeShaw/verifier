# Check List 报告：项目命名标准化

**日期:** 2026-07-04
**检查范围:** 全项目命名标准化审查

---

## 检查项清单

| # | 检查项 | 状态 | 说明 |
|---|--------|------|------|
| 1 | `_item_value` 4处重复定义 | ❌ 未通过 | 4个文件各自定义，需统一 |
| 2 | `_to_dict` / `to_public_dict` / `_as_dict` / `_dict_value` 5种命名 | ❌ 未通过 | 功能相同但命名不同 |
| 3 | `_field_values` 2处定义且返回类型不同 | ❌ 未通过 | set vs list |
| 4 | `ToolRegistry` 同名不同义 | ❌ 未通过 | protocol.py 和 tool_registry.py 各有一个 |
| 5 | normalize 常量与实际代码状态值不一致 | ❌ 未通过 | partially_fulfilled 和 contested 不在常量中 |
| 6 | 前端 `esc` vs `escapeHtml` 不一致 | ❌ 未通过 | context.html 用 esc，其他用 escapeHtml |
| 7 | 前端 `expected_intent` vs `expectedIntent` 混用 | ❌ 未通过 | 同一文件内 snake_case 和 camelCase 混用 |
| 8 | 前端 `golden_answer` vs `gold_answer` 混用 | ❌ 未通过 | 同义双名 |
| 9 | 前端 id 命名风格混用（kebab-case vs camelCase） | ❌ 未通过 | summary.html 中 5 个统计 id 用 kebab-case |
| 10 | 前后端 `project` vs `project_id` 混用 | ❌ 未通过 | 前端混用两种命名 |
| 11 | 前端 `traceId` vs `trace_id` 混用 | ❌ 未通过 | context.html 用 camelCase |
| 12 | 前端 JS 函数名与后端 API 路径不对齐 | ❌ 未通过 | buildMockCases vs mock_cases 等 |
| 13 | API 路径 `case_pool` 单复数混合 | ❌ 未通过 | /api/case_pools vs /api/case_pool/save |
| 14 | API 路径 mock 风格混合 | ❌ 未通过 | 扁平路径 vs 嵌套路径 |
| 15 | `marketting` vs `marketing` 拼写不一致 | ❌ 未通过 | 目录名用 marketting，注释用 marketing |
| 16 | checklist 文件命名不统一 | ❌ 未通过 | check1-min.py 用连字符，其他用下划线 |
| 17 | `initProjects` vs `loadProjects` 不同命名 | ❌ 未通过 | live.html/summary.html vs context.html |
| 18 | core 目录中 `attribute` vs `attribution` 混用 | ❌ 未通过 | 核心概念命名摇摆 |
| 19 | 协议文档零引用 | ⚠️ 待确认 | 协议文档未被代码引用 |
| 20 | 数据文件两套命名风格 | ❌ 未通过 | client_search_* vs cs-* 前缀 |

---

## 汇总

| 类别 | 总数 | 未通过 | 通过 |
|------|------|--------|------|
| 严重 (P0) | 8 | 8 | 0 |
| 中等 (P1) | 8 | 8 | 0 |
| 低 (P2) | 4 | 3 | 1 (待确认) |
| **合计** | **20** | **19** | **1** |

**结论:** 项目存在大量命名标准化问题，需要逐项修复。建议按 P0 → P1 → P2 顺序逐步处理。

---

## 生成说明

本报告由 `/check` 命令自动扫描生成，扫描范围包括：
- `impl/core/` 全部 Python 文件
- `impl/server/` 全部 Python 文件
- `impl/frontend/` 全部 HTML 文件
- `impl/projects/` 全部项目实现
- `impl/protocols/` 全部协议文档
- `impl/checklist/` 诊断脚本