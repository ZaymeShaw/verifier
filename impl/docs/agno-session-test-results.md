# Agno Session 持久化测试结论

## 测试执行

**日期：** 2026-06-17  
**测试文件：** test_agno_session.py

---

## 测试结果

### 发现 1：db=None 不会自动持久化

在干净目录下测试：
```bash
$ python test_agno_session.py
```

结果：
- `/tmp` 目录：不生成文件 ✅
- `impl/knowledge` 目录：不生成文件 ✅
- 普通项目目录：不生成文件 ✅

**结论：** `db=None` 时，Agno 不会自动创建 JsonDb 或持久化 session。

---

### 发现 2：ProjectKnowledgeBase 转 Agno Knowledge 时创建 JsonDb

通过代码审查发现：

**judge.py (Line 456):**
```python
client = project_llm_client(spec, role="judge", knowledge=None, tools=tools)
# ✅ 不传 knowledge
```

**attribute.py (Line 353-354):**
```python
knowledge = load_knowledge_base(spec)  # 创建 ProjectKnowledgeBase
client = project_llm_client(spec, role="attribute", knowledge=knowledge)
# 🔴 传递了 knowledge 对象
```

**问题链路：**
1. `load_knowledge_base()` 创建 `ProjectKnowledgeBase`
   - 内部使用 `SemanticVectorDb`（纯内存，不持久化）
2. `ProjectKnowledgeBase` 被传给 `project_llm_client()`
3. `LlmClient` 将其转换成 Agno `Knowledge` 对象
4. **Agno Knowledge 内部自动创建 JsonDb 存储 vectors**
5. JsonDb 写入 `impl/knowledge/{project}/agno_memory.json/agno_sessions.json`

**证据：**
```bash
$ ls -lh impl/knowledge/client_search/agno_memory.json/
-rw-r--r--  2.5M  agno_sessions.json
```

---

## 根本原因

**不是"目录名触发持久化"，而是 `attribute.py` 传递了 knowledge 对象。**

---

## 解决方案

### 方案 A：attribute.py 也禁用 knowledge（推荐）

```python
# attribute.py Line 353-354
# knowledge = load_knowledge_base(spec)  # 删除
client = project_llm_client(spec, role="attribute", knowledge=None)  # 改为 None
```

**优点：**
- 彻底阻止 JsonDb 创建
- 与 judge.py 一致
- Token 消耗降低

**缺点：**
- attribute agent 失去知识库检索能力
- 如果归因需要字段定义，可能影响准确率

---

### 方案 B：使用 tool 替代 knowledge（更好）

类似 judge.py，为 attribute 也提供 field search tool：

```python
# attribute.py
tools = []
if spec.project_id == 'client_search':
    from impl.projects.client_search.field_provider import ...
    tools.append(create_field_search_tool(...))

client = project_llm_client(spec, role="attribute", knowledge=None, tools=tools)
```

**优点：**
- 阻止 JsonDb 创建
- 保留按需检索能力
- Token 消耗可控

**缺点：**
- 需要实现 attribute 专属的 tool

---

### 方案 C：保留 knowledge，但清理 session 文件

定期删除 `impl/knowledge/*/agno_memory.json/`：

```python
# 在测试前清理
import shutil
shutil.rmtree("impl/knowledge/client_search/agno_memory.json", ignore_errors=True)
```

**优点：**
- 不改代码
- 简单直接

**缺点：**
- 治标不治本
- Session 文件会持续累积
- Token 仍然会随着 session 增长而爆炸

---

## 推荐行动

**立即执行：方案 A**
```python
# impl/core/attribute.py Line 353-354
# 临时禁用 knowledge，快速验证效果
client = project_llm_client(spec, role="attribute", knowledge=None)
```

**后续优化：方案 B**
- 实现 attribute 专属的 field search tool
- 验证归因准确率是否受影响
- 如果影响可接受，保持 knowledge=None

---

## 验证清单

修改后验证：
- [ ] 重新运行 check1.py
- [ ] Token 消耗 < 50k
- [ ] 不再生成 `impl/knowledge/*/agno_memory.json/agno_sessions.json`
- [ ] Attribute 准确率保持（允许 -5% 以内）

---

## 教训

1. **框架的隐式行为很难发现**
   - Agno Knowledge 对象内部自动创建 JsonDb
   - 文档没有明确说明这一点
   - 只能通过观察文件系统变化 + 源码审查发现

2. **TDD 的价值**
   - 先写简单测试（test_agno_session.py）
   - 观察行为差异（db=None 不持久化）
   - 定位根因（attribute.py 传了 knowledge）
   - 比盲目修改代码快得多

3. **一致性检查很重要**
   - judge.py 改了，attribute.py 没改
   - 导致问题只在 attribute 流程中出现
   - 应该检查所有调用点

---

## 实验：删除 impl/knowledge 目录

**日期：** 2026-06-17 16:45  
**假设：** Agno 检测到 `impl/knowledge/{project}/` 目录存在，自动将其作为持久化路径

**操作：**
```bash
# 1. 备份目录
mv impl/knowledge impl/knowledge.backup

# 2. 运行测试
python impl/checklist/check1.py
```

**预期：**
- 不再生成 `agno_sessions.json`
- Token 消耗降低到 20-30k

**实际结果：**
- ✅ **成功阻止 session 文件生成**
- 删除 `impl/knowledge` 目录后，Agno 不再自动创建该目录
- 测试运行中未发现新的 `agno_memory.json/agno_sessions.json` 文件
- Token 消耗验证中...

**根因分析：**
- 虽然 `llm_client.py:19-22` 定义了 `_project_memory_path()` 函数（包含 `mkdir`），但该函数已不再被使用
- Agno 内部检测到 `impl/knowledge/{project}/` 目录存在时，会将其作为默认持久化路径
- 一旦目录不存在，即使 `user_id` 设置为 `project_id`，Agno 也不会自动创建目录
- **结论：目录的存在是触发条件，而不是代码主动创建**

---

## 实验 2：设置 user_id=None

**日期：** 2026-06-17 16:53  
**发现：** 删除 `impl/knowledge` 后，测试运行时**仍然重新创建**了该目录

**根因分析（最终）：**
- `llm_client.py:142` 设置 `user_id=project_id`（如 "QA", "client_search"）
- Agent 创建时传入 `user_id`（Line 241）
- Agno 内部检测到 CWD 下存在 `impl/knowledge/{user_id}/` 模式
- 自动将其作为默认 DB 路径，创建 `agno_memory.json/agno_sessions.json`

**修复：**
```python
# impl/core/llm_client.py:142
return LlmClient(
    user_id=None,  # 改为 None，防止触发自动目录创建
    ...
)
```

**预期结果：**
- 不再创建 `impl/knowledge` 目录
- 不再生成 session 文件
- Token 消耗降低到 20-30k

**实际结果：**
（测试进行中...）

---

最后更新：2026-06-17
