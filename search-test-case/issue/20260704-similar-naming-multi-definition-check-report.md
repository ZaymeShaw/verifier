# Check 报告: 相似命名多套定义 & 数据/协议对齐审查

**日期:** 2026-07-04
**范围:** 全项目代码审查

---

## 一、同名函数/工具函数的重复定义（严重）

以下函数在多个模块中独立定义，功能完全相同或高度相似，违反"最简化原则"：

### 1. `_item_value` — 4 处独立定义（完全相同）
| 文件 | 行号 |
|------|------|
| `impl/core/schema/judge.py` | 95 |
| `impl/core/attribute.py` | 369 |
| `impl/core/frontend_view.py` | 58 |
| `impl/core/state_machine.py` | 309 |

全部是：`def _item_value(item, key, default=None): return item.get(key, default) if isinstance(item, dict) else default`

**建议:** 只保留 `schema/judge.py` 中的定义，其他 3 处全部 import 使用。

### 2. `_to_dict` / `to_dict` / `to_public_dict` / `_as_dict` / `_dict_value` — 5 种不同命名
| 函数 | 文件 | 行号 |
|------|------|------|
| `to_dict` + `_to_dict` | `schema/base.py` | 56, 67 |
| `to_public_dict` + `_to_public_dict` | `schema/occam.py` | 185, 195 |
| `_as_dict` | `schema/normalize.py` | 19 |
| `_as_dict` | `table_view.py` | 13 |
| `_dict_value` | `judge.py` | 319 |

**问题:** `schema/base.py` 和 `schema/occam.py` 各自独立实现了一对 `to_dict`/`_to_dict` 和 `to_public_dict`/`_to_public_dict`，且 `_json_safe_key` 也在两个文件中重复实现。`table_view.py` 和 `judge.py` 各自又写了 `_as_dict` 和 `_dict_value`。

**建议:** 统一为一个 `to_dict` 工具函数，`occam.py` 的 `to_public_dict` 可以继承 `base.py` 的 `to_dict`。

### 3. `_field_values` — 2 处定义，返回值类型不同
| 文件 | 行号 | 返回类型 |
|------|------|----------|
| `impl/core/check.py` | 325 | `set[str]` |
| `impl/core/cluster.py` | 9 | `list[str]` |

**问题:** 完全相同名称、完全相同逻辑，但返回类型不同（`set` vs `list`）。

### 4. `_trace_reference` — 2 处定义
| 文件 | 行号 |
|------|------|
| `impl/core/frontend_view.py` | 10 |
| `impl/core/judge.py` | 420 |

两个函数都是从 trace 中提取 reference 数据，逻辑相似但不完全相同。

### 5. `_score_0_1` vs `_score_in_range`
| 函数 | 文件 | 行号 |
|------|------|------|
| `_score_0_1` | `impl/core/judge.py` | 296 |
| `_score_in_range` | `impl/core/check.py` | 272 |

两个都是评分相关的辅助函数，命名不一致。

---

## 二、ToolRegistry 两套定义（严重）

| 文件 | 类名 | 存储的 Tool 类型 |
|------|------|-----------------|
| `impl/tools/protocol.py` | `ToolRegistry` | `ProtocolTool` (agno 包装) |
| `impl/core/tool_registry.py` | `ToolRegistry` | `VerifiableTool` (注册表) |

两个 `ToolRegistry` 是完全不同的类，但同名。`tool_orchestrator.py` 直接 re-export `tool_registry.ToolRegistry`，而 `adapter.py` 从 `impl.tools` 导入 `ToolRegistry`（protol 版本）。

**问题:**
- `impl/tools/__init__.py` 导出的是 `protocol.ToolRegistry`（ProtocolTool）
- `impl/core/tool_orchestrator.py` 导出的是 `tool_registry.ToolRegistry`（VerifiableTool）
- `adapter.py:211` 的 `protocol_tools()` 方法返回 `impl.tools.ToolRegistry`（ProtocolTool 版本）
- `tool_registry.py` 的 `ToolRegistry` 从 `impl.tools` 导入 `VerifiableTool`（协议版本的数据类）

**建议:** 重命名其中一个，或在 `impl/tools/__init__.py` 中明确区分命名导出。

---

## 三、状态/裁决值的协议不一致

### normalize 常量的规范值与实际使用的值不符

| 概念 | normalize 常量 | 实际代码中使用的值 |
|------|---------------|-------------------|
| VERDICTS | `{"correct", "incorrect", "partial", "uncertain", "not_evaluable"}` | `state_machine` 使用 `"partially_correct"`（不在 normalize 中） |
| FULFILLMENT_STATUSES | `{"fulfilled", "partial", "not_fulfilled", "not_evaluable"}` | 代码使用 `"partially_fulfilled"`（不在 normalize 中）和 `"contested"`（不在 normalize 中） |

`_normalize_fulfillment_status` 的别名映射中没有 `"partially_fulfilled"` 和 `"contested"`，但 `state_machine.py`、`attribute.py`、`check.py` 中大量使用这两个值。

**建议:** 要么将 `partially_fulfilled` 和 `contested` 加入 normalize 常量，要么统一所有代码使用 `"partial"`。

---

## 四、数据文件命名不一致

### 两套命名风格混杂

`data/client_search/` 目录下：
- `client_search_*` 前缀：`client_search_demographic_100.json`, `client_search_premium_policy_100.json` 等（5 个文件）
- `cs-*` 前缀：`cs-demographics_100.json`, `cs-policy-dates_100.json` 等（9 个文件）

部分文件有 `cs-*` 和 `client_search_*` 两套对应（如 `cs-demographics_100.json` 和 `client_search_demographic_100.json`），但结构不同（一个是 list，一个是 dict）。

### `index_upload_batches.json` 未被任何代码引用

`data/client_search/index_upload_batches.json` 在代码中没有任何引用，但 `index.json` 被 `pipeline.py` 的 mock 逻辑使用。

---

## 五、Protocol 文档零引用

以下 `impl/protocols/` 下的协议文档在代码中完全未被引用（0 处 Python 引用）：

| 文件 | 状态 |
|------|------|
| `attribute_protocol.md` | 未被引用 |
| `check_protocol.md` | 未被引用 |
| `cluster_protocol.md` | 未被引用 |
| `frontend_protocol.md` | 未被引用 |
| `judge_protocol.md` | 未被引用 |
| `mock_protocol.md` | 未被引用 |
| `project_protocol.md` | 未被引用 |
| `quality_gated_evidence_protocol.md` | 未被引用 |
| `run_trace_protocol.md` | 未被引用 |
| `subagent_state_execution_protocol.md` | 未被引用 |
| `trace_state_machine_protocol.md` | 未被引用 |
| `uat_protocol.md` | 未被引用 |

**建议:** 如果这些协议文档是设计文档（只读参考），应该放在 `spec/` 或 `docs/` 中。如果已过时，应清理。

---

## 六、根级零散文件

以下文件未被 git 跟踪，属于临时测试脚本，散落在根目录：

| 文件 | 用途 |
|------|------|
| `_check_schema.py` | agno schema 测试 |
| `_test_attr_full.py` | API 归因测试 |
| `_test_tcl_extract.py` | tool call log 测试 |
| `_test_force.py` | 强制 judge 修改测试 |
| `create_test_data.py` | 测试数据创建 |

**建议:** 移到 `tests/` 或 `impl/checklist/` 统一管理，或加入 `.gitignore`。

---

## 七、冗余共享代码

### `checklist/` 目录下多份诊断脚本

- `diagnose_cs1_llm_failure.py`
- `diagnose_cs13.py`
- `diagnose_cs17_deep.py`
- `diagnose_llm_failures.py`

这些是逐 case 的诊断脚本，缺乏复用结构。建议统一为一个诊断框架。

### `check1.py` vs `check1-min.py`

两个文件共享大量代码，`check1-min.py` 是 `check1.py` 的简化版。建议合并为一个可配置的脚本。

---

## 八、修复方案总结

| 优先级 | 问题 | 修复方案 | 影响范围 |
|--------|------|----------|----------|
| **P0** | 4 处 `_item_value` 重复定义 | 统一为 `schema/judge.py` 的版本，其他 import | 3 个文件修改 |
| **P0** | 状态值不一致（`partially_fulfilled` vs `partial`） | 统一常量定义，加入 `partially_fulfilled` 和 `contested` | `normalize.py` + 全代码 |
| **P1** | 两个 `ToolRegistry` 同名不同义 | 重命名 `protocol.py` 的为 `ProtocolToolRegistry` | `impl/tools/` + `adapter.py` |
| **P1** | `_to_dict` / `to_public_dict` 重复 | 统一为 `base.py` 的 `to_dict`，`occam.py` 复用 | `schema/base.py` + `schema/occam.py` |
| **P2** | 数据文件命名不一致 | 统一为 `client_search_*` 或 `cs-*` 一种风格 | `data/client_search/` |
| **P2** | 根级零散测试文件 | 移到 `tests/` 或加入 `.gitignore` | 根目录 |
| **P3** | 协议文档零引用 | 确认去留，移到 `docs/` 或清理 | `impl/protocols/` |
| **P3** | 诊断脚本冗余 | 合并为统一框架 | `impl/checklist/` |

---

## 九、请用户确认

以上所有修复方案中，**P0 和 P1 级别的修改需要您确认后执行**。P2/P3 为建议性优化，可在 P0/P1 完成后逐步处理。

请确认：
1. 是否同意 `_item_value` 统一？P0 级别
2. 是否同意将 `partially_fulfilled` 和 `contested` 加入 normalize 常量？P0 级别
3. 是否同意重命名 `protocol.py` 的 `ToolRegistry` 为 `ProtocolToolRegistry`？P1 级别
4. 对其他 P2/P3 问题的处理方式的偏好？