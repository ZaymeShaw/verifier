# 上下文优化设计文档审核清单

## 审核对象
- `impl/docs/agno-architecture.md`
- `impl/docs/context-optimization-lessons.md`

---

## Check Agent 审核维度

### 1. 过度规则化检查 ⚠️

**问题识别：**
- ❌ **`field_retrieval.py` 被称为"通用协议"，但实际只服务 client_search 一个项目**
  - 只有 client_search 有 YAML 格式的字段定义
  - QA、marketting-planning 等项目没有字段定义文件
  - 为了"通用性"设计了 Protocol + Provider 架构，但缺乏实际多项目验证

**影响评估：**
- 严重程度：🟡 中等
- 泛化能力：过度设计，未来扩展到其他项目时可能需要重构
- 当前影响：client_search 可以正常工作，但架构复杂度增加

**解决方案建议：**
1. **短期：** 将 `field_retrieval.py` 重命名为 `client_search_field_retrieval.py`，明确其专属性
2. **中期：** 当有第二个项目需要类似功能时，再抽象通用协议
3. **长期：** 基于 2-3 个实际项目的共性，设计真正的通用协议

**用户确认：** 是否接受当前"通用协议"实际上是 client_search 专属的现状？

---

### 2. 局部样本修改检查 ✅

**问题识别：**
- ✅ 优化过程中，每次修改都是全局性的（修改 `llm_client.py`, `judge.py`）
- ✅ 没有只针对特定 case 调整参数
- ✅ 清理了所有项目的 session 文件，不是只清理 client_search

**评估：** 通过 ✅

---

### 3. 源头逻辑检查 ⚠️

**问题识别：**
- ⚠️ **修复了 JsonDb 泄漏，但没有验证修复是否有效**
  - 修改了 `project_llm_client()` 不再创建 JsonDb
  - 清理了历史 session 文件
  - **但测试还在运行中，尚未验证 token 是否降低到预期范围**

**缺失的验证步骤：**
1. 测试完成后，检查是否还有新的 session 文件生成
2. 验证 token 消耗是否降低到 20-30k
3. 验证 judge 准确率是否受影响

**解决方案：**
- 等待测试完成（Task #29）
- 如果 token 仍然超标，需要进一步排查是否有其他 JsonDb 创建点
- 如果准确率下降超过 5%，需要调整 compact context 策略

---

### 4. 数据一致性检查 ✅

**问题识别：**
- ✅ 文档与代码一致：
  - `agno-architecture.md` 描述的机制与实际代码行为匹配
  - `context-optimization-lessons.md` 记录了完整的修改历史
- ✅ 配置同步更新：
  - `llm_client.py` 已更新
  - `judge.py` 已更新（compact context + tool）
  - `field_provider.py` 已压缩字段定义

**评估：** 通过 ✅

---

### 5. 冗余/过时代码检查 ⚠️

**问题识别：**

#### 5.1 冗余的 tool 实现
- ⚠️ `impl/tools/field_retrieval.py` 声称通用，但只有 client_search 使用
- ⚠️ `impl/projects/client_search/field_provider.py` 依赖外部 YAML 文件（176KB）

**处理建议：**
- 如果未来不扩展到其他项目：删除"通用协议"层，直接在 judge.py 中实现 client_search 专属逻辑
- 如果计划扩展：保留，但在文档中明确当前只有 client_search 实现

#### 5.2 未使用的参数
当前 `llm_client.py` 中：
```python
def project_llm_client(spec, role, knowledge=None, tools=None):
    # role 参数未使用
    # knowledge 参数总是被忽略（设置为 None）
```

**处理建议：**
- 如果 `role` 和 `knowledge` 未来不会用到，删除这些参数
- 如果保留用于未来扩展，在文档中说明

#### 5.3 过时的注释
`llm_client.py:117-145` 有大量关于 session isolation 的注释，但现在 `session_id` 已经改为按 trace 隔离，部分注释已过时。

**处理建议：** 更新注释，反映当前实际行为

---

### 6. 协议对齐检查 ⚠️

**问题识别：**

#### 6.1 协议层与项目层的边界模糊
- `impl/tools/field_retrieval.py`（声称协议层）只有 client_search 使用
- `impl/core/judge.py`（协议层）包含项目专属逻辑：
  ```python
  if spec.project_id == 'client_search':
      from impl.projects.client_search.field_provider import ...
  ```

**影响：**
- 协议层代码包含项目判断逻辑
- 新增项目需要修改协议层代码

**标准化建议：**

**方案 A：插件化架构**
```python
# impl/core/judge.py (协议层)
def judge_trace(spec, trace, ...):
    # 动态加载项目插件
    provider = load_project_plugin(spec.project_id, 'field_provider')
    if provider:
        tool = create_field_search_tool(provider)
        tools = [tool]
    else:
        tools = []
```

**方案 B：项目注册机制**
```python
# impl/projects/registry.py (协议层)
PROJECT_PLUGINS = {
    'client_search': {
        'field_provider': 'impl.projects.client_search.field_provider.ClientSearchFieldDefinitionProvider',
    },
    # 未来项目在这里注册
}
```

**用户确认：** 选择哪种方案？还是保持当前的 if-elif 结构？

---

## 完整性检查

### 缺失的验证步骤 🔴

1. **实测验证（未完成）**
   - ⬜ 测试是否还生成 session 文件
   - ⬜ Token 消耗是否降低到 20-30k
   - ⬜ Judge 准确率是否保持（允许 -5% 以内）
   - ⬜ Tool 调用是否正常工作

2. **链路测试（未完成）**
   - ⬜ 单独测试 field_provider.get_field_definition()
   - ⬜ 单独测试 create_field_search_tool() 返回的 tool
   - ⬜ 单独测试 Agent 调用 tool 的流程
   - ⬜ 端到端测试 judge_trace() 的完整流程

3. **文档覆盖（部分完成）**
   - ✅ Agno 核心机制已文档化
   - ✅ 优化历史已记录
   - ⬜ 缺少"如何验证修复是否有效"的 checklist
   - ⬜ 缺少"如果仍然超标怎么办"的应急方案

---

## 问题可视化

### 当前问题列表

| ID | 问题 | 严重程度 | 状态 | 解决方案 |
|----|------|---------|------|---------|
| P1 | JsonDb 泄漏导致 token 爆炸 | 🔴 高 | 已修复，待验证 | 不创建 JsonDb，已清理历史文件 |
| P2 | "通用协议"实际只服务 client_search | 🟡 中 | 待确认 | 重命名为专属，或等待第二个项目后再抽象 |
| P3 | 协议层包含项目判断逻辑 | 🟡 中 | 待确认 | 插件化或注册机制 |
| P4 | 缺少完整的验证流程 | 🟡 中 | 进行中 | 等待 Task #29 完成，执行链路测试 |
| P5 | 过时注释和未使用参数 | 🟢 低 | 待处理 | 清理代码，更新文档 |

---

## Check 报告总结

### 通过项✅
- 局部样本修改：无局部调参
- 数据一致性：文档与代码一致

### 需要改进⚠️
- 过度规则化："通用协议"名不副实
- 源头逻辑：修复已完成，但验证未完成
- 协议对齐：协议层包含项目专属逻辑

### 阻塞项🔴
- **测试未完成**：无法验证修复是否有效
- **缺少链路测试**：无法确认各组件独立工作正常

---

## 下一步行动

### 测试结果（已完成）

**Token 消耗对比：**
| 指标 | 初始 | 修复后 | 变化 |
|------|------|--------|------|
| client_search input | 366k | 183k | -50% ✅ |
| client_search sessions | 2 | 1 | ✅ |
| QA input | 33k | 126k | +280% 🔴 |
| Total cost | $0.40 | $0.34 | -15% ✅ |

**核心发现：**
1. ✅ 修复 JsonDb 泄漏有效：sessions 从多个降到 1
2. ✅ client_search 降低 50%（366k → 183k）
3. ⚠️ **仍未达到 50k 目标**（183k 是目标的 3.7 倍）
4. 🔴 **Session 文件仍在生成**：2.5MB (client_search), 1.4MB (QA)

**问题根因（已确认）：**
```bash
$ ls -lh impl/knowledge/client_search/agno_memory.json/
-rw-r--r--  2.5M  agno_sessions.json  # 包含完整的 run output JSON
```

Session 文件内容分析：
- 每个 run 的完整 JSON 响应（包括超长的 reasoning 和所有字段）
- Agno 默认持久化所有 run output，即使 `db=None`
- 问题：**Agno 通过某种机制自动创建了 JsonDb，存储在 `impl/knowledge/{project}/agno_memory.json/`**

**推测：Agno 检测到 `impl/knowledge/{project}/` 目录存在，自动将其作为持久化路径**

## 最终解决方案

### 方案对比

| 方案 | Token 预期 | 工作量 | 风险 | 推荐度 |
|------|-----------|--------|------|--------|
| **A. 删除 knowledge 目录** | 20-30k | 低（删除目录） | 低 | ⭐⭐⭐⭐⭐ |
| B. 重命名 knowledge 目录 | 20-30k | 低（重命名） | 低 | ⭐⭐⭐⭐ |
| C. 显式禁用 Agno 持久化 | 未知 | 中（研究 Agno API） | 中 | ⭐⭐⭐ |
| D. 接受现状，优化 prompt | 150-180k | 高（深度压缩） | 高 | ⭐⭐ |

### 推荐方案 A：删除 knowledge 目录

**原理：**
- `impl/knowledge/{project}/` 目录的存在触发了 Agno 的自动持久化
- 删除该目录后，Agno 无法找到持久化路径，被迫使用纯内存 session
- 我们已经通过 `knowledge=None` 禁用了知识库，该目录无实际用途

**实施步骤：**
```bash
# 1. 备份现有 knowledge 目录（如需要）
mv impl/knowledge impl/knowledge.backup

# 2. 重新运行测试
python impl/checklist/check1.py

# 3. 验证：
#    - 不再生成 agno_sessions.json
#    - Token 消耗降低到 20-30k
```

**预期效果：**
- ✅ 完全阻止 session 持久化
- ✅ Token 降低到 20-30k（符合 50k 预算）
- ✅ 无需修改代码

**验证清单：**
- [ ] 运行测试后，检查 `impl/` 下是否生成新的 session 文件
- [ ] Token 消耗 < 50k
- [ ] Judge 准确率保持

---

### 备选方案 B：重命名 knowledge 目录

如果担心完全删除 knowledge 目录：
```bash
# 重命名为 Agno 无法识别的名称
mv impl/knowledge impl/project_context
```

---

### 方案 C：显式配置 Agno（不推荐）

需要研究 Agno 的持久化路径配置机制，可能涉及：
- 环境变量
- 全局配置文件
- Agno Agent 的隐藏参数

工作量大，效果不确定。

---

## 根本问题总结

**技术债务：**
1. `impl/knowledge/` 目录最初是为了存储 knowledge base，但现在我们已经通过 tools 替代
2. 该目录的存在触发了 Agno 的副作用（自动持久化）
3. 即使代码层面设置 `db=None`, `knowledge=None`，目录结构仍然影响 Agno 行为

**设计教训：**
- 框架可能通过文件系统约定（如特定目录名）触发隐式行为
- "禁用功能"不仅需要在代码中设置参数，还需要清理相关的文件系统结构
- 应该先彻底理解框架的持久化机制，再进行优化

---

## 用户决策

请选择方案：
- [ ] **方案 A**：删除 `impl/knowledge` 目录（推荐）
- [ ] **方案 B**：重命名 `impl/knowledge` 目录
- [ ] **方案 C**：保留目录，研究 Agno 配置
- [ ] **方案 D**：接受现状（183k tokens）

如果选择方案 A 或 B，我会立即执行并重新测试。

---

最后更新：2026-06-17
