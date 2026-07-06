# Check 报告: 项目命名标准化问题全面审查

**日期:** 2026-07-04
**范围:** 全项目（impl/core/、impl/server/、impl/frontend/、impl/projects/、impl/protocols/、impl/checklist/）

---

## 一、同名函数/工具函数的重复定义（严重 — P0）

以下函数在多个模块中独立定义，功能完全相同或高度相似，违反"最简化原则"：

### 1. `_item_value` — 4 处独立定义（完全相同）

| 文件 | 行号 |
|------|------|
| `impl/core/schema/judge.py` | 143 |
| `impl/core/attribute.py` | 336 |
| `impl/core/frontend_view.py` | 58 |
| `impl/core/state_machine.py` | 309 |

全部实现：`def _item_value(item, key, default=None): return item.get(key, default) if isinstance(item, dict) else default`

**建议:** 只保留 `schema/judge.py` 中的定义，其他 3 处改为 import 使用。

### 2. `_to_dict` / `to_public_dict` / `_as_dict` / `_dict_value` — 5 种不同命名，功能相同

| 函数 | 文件 | 行号 |
|------|------|------|
| `to_dict` + `_to_dict` | `schema/base.py` | 56, 67 |
| `to_public_dict` + `_to_public_dict` | `schema/occam.py` | 185, 195 |
| `_as_dict` | `schema/normalize.py` | 19 |
| `_as_dict` | `table_view.py` | 13 |
| `_dict_value` | `judge.py` | 292 |

**问题:** `schema/base.py` 和 `schema/occam.py` 各自独立实现了一对 dict 转换函数，`table_view.py` 和 `judge.py` 各自又写了 `_as_dict` 和 `_dict_value`。

**建议:** 统一为一个 `to_dict` 工具函数，`occam.py` 的 `to_public_dict` 继承 `base.py` 的 `to_dict`。

### 3. `_field_values` — 2 处定义，返回值类型不同

| 文件 | 行号 | 返回类型 |
|------|------|----------|
| `impl/core/check.py` | 325 | `set[str]` |
| `impl/core/cluster.py` | 9 | `list[str]` |

**问题:** 完全相同名称、完全相同逻辑，但返回类型不同。

### 4. `ToolRegistry` — 两个同名不同义的类

| 文件 | 类名 | 存储的 Tool 类型 |
|------|------|-----------------|
| `impl/tools/protocol.py:104` | `ToolRegistry` | `ProtocolTool` (agno 包装) |
| `impl/core/tool_registry.py:24` | `ToolRegistry` | `VerifiableTool` (注册表) |

**问题:** 两个 `ToolRegistry` 是完全不同的类，但同名。`adapter.py` 从 `impl.tools` 导入（ProtocolTool 版本），`tool_orchestrator.py` 从 `tool_registry.py` 导入（VerifiableTool 版本）。

---

## 二、状态/裁决值的协议不一致（严重 — P0）

### normalize 常量与实际代码使用的值不符

| 概念 | normalize 常量 | 实际代码中使用的值 |
|------|---------------|-------------------|
| VERDICTS | `{"correct", "incorrect", "uncertain", "not_evaluable"}` | `state_machine` 使用 `"partially_correct"`（不在 normalize 中） |
| FULFILLMENT_STATUSES | `{"fulfilled", "not_fulfilled", "not_evaluable"}` | 代码使用 `"partially_fulfilled"` 和 `"contested"`（不在 normalize 中） |

`_normalize_fulfillment_status` 的别名映射将 `"partially_fulfilled"` 映射为 `"not_fulfilled"`，`"contested"` 映射为 `"not_evaluable"`，但前端（`summary.html:320`）和多个核心文件使用 `"partially_fulfilled"` 和 `"contested"` 作为独立状态值。

---

## 三、前端命名不统一（严重 — P0）

### 1. 相同功能的函数在不同页面中命名不同

| 功能 | live.html | summary.html | context.html |
|------|-----------|--------------|--------------|
| HTML 转义 | `escapeHtml()` | `escapeHtml()` | **`esc()`** |
| 项目初始化 | `initProjects()` | `initProjects()` | **`loadProjects()`** |
| 项目切换 | `switchProject()` | `switchProject()` | 内联在 `loadSummary()` 中 |

**`esc` vs `escapeHtml`** 是最典型的不一致——三个页面完全相同的功能却用了两个不同的函数名。

### 2. `expected_intent` / `expectedIntent` 混用（同一文件内）

`summary.html` 中：
- 第 203 行：`function expectedIntent()` — camelCase
- 第 226 行：`const expected_intent = input?.expected_intent` — snake_case
- 第 481-482 行：`body.expected_intent = expected;` — 用 snake_case 字段名

### 3. `golden_answer` / `gold_answer` 同义多命名

`summary.html` 第 265 行：
```javascript
return item.reference || item.input?.reference || 
  (item.golden_answer || item.gold_answer ? {golden_answer: item.golden_answer || item.gold_answer} : null) || ...
```

### 4. id 命名风格混用（kebab-case vs camelCase）

`summary.html:26-30` 的 5 个统计 id 使用 kebab-case：
- `stat-total`、`stat-selected`、`stat-fulfilled`、`stat-not-fulfilled`、`stat-clusters`

而同一文件的其他所有 id 以及 `live.html`、`context.html` 全部使用 camelCase。**CSS class 全部统一使用 kebab-case（正确），但 id 混用了两种风格。**

---

## 四、前后端参数命名不一致（中等 — P1）

### 1. `project` vs `project_id` 混用

| 位置 | 字段名 | 备注 |
|------|--------|------|
| `summary.html` POST 请求 | `project` | `{project: project()}` |
| `live.html` | `project` | `{project: project()}` |
| `context.html` GET 请求 | `project_id` | URL 查询参数 |
| `context.html` POST 请求 | `project_id` | `{project_id: project}` |
| `live.html:85` | `projectId` | 函数参数 |
| `context.html:397` | `projectId` | 函数参数 |
| 后端 `models.py` | 同时支持 `project` 和 `project_id` | 两个字段 |

**问题:** 前端 `summary.html` 和 `live.html` 大部分用 `project`，但 `context.html` 用 `project_id`。后端同时接受两个字段名，保持了向后兼容，但这是冗余的。

### 2. `traceId` vs `trace_id` 混用

- `context.html` 使用 `traceId`（camelCase）作为 JS 变量名
- 后端路由和字段名使用 `trace_id`（snake_case）
- 其他核心代码统一使用 `trace_id`

### 3. 前端 JS 函数名与后端 API 路径不对齐

| 前端函数 | 后端 API 路径 | 不对齐 |
|----------|---------------|--------|
| `buildMockCases()` | `/api/mock_cases` | 函数名多了 `build` 前缀 |
| `saveNamedPool()` | `/api/case_pool/save` | 函数名 `NamedPool` vs 路径 `case_pool` |
| `runSelectedCases()` | `/api/batch_start` | 函数名 `SelectedCases` vs 路径 `batch_start` |
| `runAnalyze()` | `/api/context/analyze` | 函数名 `runAnalyze` vs 路径 `context/analyze` |

---

## 五、API 路径命名风格不一致（中等 — P1）

### 1. `case_pool` 单复数混合

| 路由 | 风格 |
|------|------|
| `/api/case_pools` | 复数 |
| `/api/case_pool/save` | 单数 |
| `/api/case_pool/load` | 单数 |
| `/api/case_pool/delete` | 单数 |

### 2. mock 路径风格混合

| 路由 | 风格 |
|------|------|
| `/api/mock_cases` | 扁平路径 |
| `/api/mock_datasets` | 扁平路径 |
| `/api/mock/build_intent` | 嵌套路径 |
| `/api/mock/build_interaction` | 嵌套路径 |

---

## 六、拼写不一致：`marketting` vs `marketing`（中等 — P1）

项目目录名使用 `marketting`（双 t），但注释中混用 `marketing`（单 t）：

| 位置 | 拼写 |
|------|------|
| 项目目录 | `marketting-planning`、`marketting-planning-intent` |
| `judge.py:84` 注释 | `marketing-planning stores raw SSE...` |
| `judge.py:566` 注释 | `marketing-planning 等问答类` |

**正确拼写应为 `marketing`（单 t），`marketting` 是拼写错误。** 但考虑到项目目录名已广泛使用，修改会影响大量路径引用，需要慎重评估。

---

## 七、相同概念多种命名总结（中等 — P1）

| 概念 | 命名变体 |
|------|----------|
| 项目 | `project`、`project_id`、`projectId`、`pid` |
| 会话 | `session_id`、`state_id` |
| 期望输入 | `expected_intent`、`expectedIntent`、`user_intent`、`goal` |
| 黄金答案 | `golden_answer`、`gold_answer`、`reference`、`expected` |
| 执行追踪 | `execution_trace`、`run_trace`、`trace` |
| 归因 | `attribute`、`attribution`（两个概念混用） |
| 将 dict 转换 | `_to_dict`、`to_public_dict`、`_as_dict`、`_dict_value`、`_as_text` |
| 从对象取值 | `_item_value`、`_assessment_value` |
| 状态机 | `state_machine`、`TraceStateMachineRunner`、`trace_runner` |
| 知识库 | `knowledge_base`、`KnowledgeBase`、`SemanticVectorDb`、`kb` |
| 前端视图 | `frontend_view`（统一使用 snake_case，无混用问题） |

---

## 八、checklist 目录命名不统一（低 — P2）

| 文件名 | 问题 |
|--------|------|
| `check1.py` | 数字后缀 `1` |
| `check1-min.py` | 使用连字符 `-`，与下划线 `_` 不一致 |
| `check1.sh` | 与 `check1.py` 共享前缀但不同扩展名 |
| `check_mock_data.sh` | 使用 `snake_case`，与 `check1.sh` 风格不一致 |
| `diagnose_cs1_llm_failure.py` | 使用 `_cs1_` 模式 |
| `diagnose_cs13.py` | 使用 `cs` 无下划线 |
| `diagnose_cs17_deep.py` | 同上 |
| `diagnose_llm_failures.py` | 通用诊断文件 |
| `test_deepseek_direct.py` | `test_` 前缀 |
| `verify_session_isolation_fix.py` | `verify_` 前缀 |

---

## 九、修复方案总结

| 优先级 | 问题 | 修复方案 | 影响范围 |
|--------|------|----------|----------|
| **P0** | 4 处 `_item_value` 重复定义 | 统一为 `schema/judge.py` 的版本，其他 import | 3 个文件修改 |
| **P0** | 状态值不一致（`partially_fulfilled` vs `partial`） | 将 `partially_fulfilled` 和 `contested` 加入 normalize 常量 | `normalize.py` + 全代码 |
| **P0** | 前端 `esc` vs `escapeHtml` 不一致 | 统一为 `escapeHtml` | `context.html` |
| **P0** | 前端 `expected_intent` vs `expectedIntent` 混用 | 统一为 `expectedIntent`（camelCase，与 JS 风格一致） | `summary.html` |
| **P1** | 两个 `ToolRegistry` 同名不同义 | 重命名 `protocol.py` 的为 `ProtocolToolRegistry` | `impl/tools/` + `adapter.py` |
| **P1** | `_to_dict` / `to_public_dict` 重复 | 统一为 `base.py` 的 `to_dict`，`occam.py` 复用 | `schema/base.py` + `schema/occam.py` |
| **P1** | 前后端 `project` vs `project_id` 混用 | 统一为 `project`（POST）或 `project_id`（GET query） | 多个前端文件 |
| **P1** | API 路径 `case_pool` 单复数混合 | 统一为复数 `case_pools` | `routes.py` |
| **P1** | `marketting` 拼写错误 | 改名为 `marketing`（需评估影响范围） | 全项目路径引用 |
| **P2** | 前端 `golden_answer` vs `gold_answer` 混用 | 统一为 `golden_answer` | `summary.html` |
| **P2** | 前端 id 混用 kebab-case 和 camelCase | 统一为 camelCase | `summary.html` |
| **P2** | checklist 文件命名不统一 | 整理为统一命名风格 | `impl/checklist/` |
| **P2** | 前端 JS 函数名与后端 API 不对齐 | 前端函数名对齐 API 路径 | 多个前端文件 |

---

## 十、请用户确认

以上问题中，**P0 和 P1 级别的修改需要您确认后执行**。P2 为建议性优化，可在 P0/P1 完成后逐步处理。

请逐一确认：
1. **P0:** 是否同意统一 `_item_value` 定义？
2. **P0:** 是否同意将 `partially_fulfilled` 和 `contested` 加入 normalize 常量？
3. **P0:** 是否同意将 `context.html` 的 `esc` 改为 `escapeHtml`？
4. **P0:** 是否同意统一 `expected_intent` / `expectedIntent` 为 camelCase？
5. **P1:** 是否同意重命名 `protocol.py` 的 `ToolRegistry` 为 `ProtocolToolRegistry`？
6. **P1:** 是否同意统一 `_to_dict` / `to_public_dict`？
7. **P1:** 是否同意统一前后端 `project` vs `project_id`？
8. **P1:** 是否同意修改 `marketting` → `marketing` 拼写错误？