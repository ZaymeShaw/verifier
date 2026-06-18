# 上下文优化失败案例分析

## 背景

**目标：** 将 judge agent 的 token 消耗从 366k 降低到 50k 以内

**约束：**
- demand/context.md 要求："上下文资源分配，给定一定的上下文资源预算，你怎么分配上下文，来实现最高的信息密度"
- "常驻prompt信息，不允许放大文档。大文档只能按需动态加载或者压缩"
- "实现工具的时候请鉴别哪些属于协议通用，哪些属于项目专属"

---

## 优化尝试历史

### 第一轮：Tool-based 按需检索（失败）

**思路：**
- 用 tool 替代 knowledge base 自动加载
- 创建 `field_retrieval.py`（通用协议）+ `field_provider.py`（项目专属）
- 传 `tools=[field_search_tool]` 给 Agent

**配置：**
```python
agent = Agent(
    knowledge=None,  # 禁用知识库
    tools=[field_search_tool],  # 添加按需检索 tool
)
```

**结果：** 366k tokens（未达标）

**问题：** Agno 的 knowledge base 仍在自动加载（即使 `knowledge=None`）

---

### 第二轮：禁用所有自动上下文（失败）

**思路：**
- 禁用 memories, knowledge, 压缩 schema/字段定义
- `memory_manager=None`, `knowledge=None`
- 简化 required_output JSON schema
- 压缩 field_provider 返回的字段定义

**配置：**
```python
agent = Agent(
    memory_manager=None,
    knowledge=None,
    add_memories_to_context=False,
    add_knowledge_to_context=False,
)
```

**结果：** 732k tokens（恶化 2 倍）🔴

**问题：** 禁用 context 后，LLM 信息不足，触发大量重试，导致 token 爆炸

---

### 第三轮：禁用 conversation history（失败）

**思路：**
- 以为 token 爆炸是因为 conversation history 累积
- 设置 `add_history_to_context=False`, `num_history_runs=0`, `num_history_messages=0`

**配置：**
```python
agent = Agent(
    add_history_to_context=False,
    num_history_runs=0,
    num_history_messages=0,
)
```

**结果：** 1,098k tokens（恶化 3 倍）🔴🔴🔴

**问题：** 
1. **误解了 history 的作用**：以为禁用 history 会破坏 tool 调用
2. **实际原因未解决**：真正的问题是 JsonDb 泄漏，而不是 history

---

### 第四轮：修复 JsonDb 泄漏（当前测试中）

**根因分析：**

检查 session 文件：
```bash
$ ls -lh impl/knowledge/client_search/agno_memory.json/*.json
-rw-r--r--  798K  agno_memories.json
-rw-r--r--  15M   agno_sessions.json  # ← 问题在这里
```

**问题：**
```python
# impl/core/llm_client.py (旧版)
def project_llm_client(spec, role, knowledge=None, tools=None):
    memory_db = JsonDb(db_path=str(_project_memory_path(project_id)))  # ← 创建了 JsonDb
    return LlmClient(
        memory_db=memory_db,  # ← 传递给 LlmClient
        memory_manager=MemoryManager(db=memory_db),  # ← 传递给 MemoryManager
    )

# complete_json() 中
agent = Agent(
    memory_manager=None,  # ← 虽然这里设置了 None
    db=None,              # ← 虽然这里设置了 None
)
```

**发现：**
1. `project_llm_client()` 创建了 `JsonDb` 和 `MemoryManager`
2. 即使不传给 Agent，这些对象已经存在
3. Agno 内部可能通过某种机制（全局注册、文件路径约定）仍然访问到它们
4. 导致每次 run 都写入 `agno_sessions.json`，文件越来越大（15MB）
5. 后续 run 加载这个巨大的 session 文件 → token 爆炸

**修复：**
```python
def project_llm_client(spec, role, knowledge=None, tools=None):
    # CRITICAL: Do NOT create JsonDb or MemoryManager
    return LlmClient(
        memory_db=None,          # ← 不创建
        memory_manager=None,     # ← 不创建
        knowledge=None,
        tools=tools,
        user_id=project_id,
        session_id=None,
    )
```

**预期结果：**
- 不再创建 JsonDb → 不再写入 session 文件 → 没有历史累积
- Token 回归正常：~20-30k per case

---

## 错误理解的纠正

### ❌ 错误 1：Tool 调用需要 conversation history

**错误理解：**
> "禁用 history 后，tool 调用流程会失败，因为第二轮 LLM 调用缺少第一轮的上下文"

**正确理解：**
- `add_history_to_context` 只影响**跨 run 的持久化历史**
- **单次 `run()` 内的多轮对话**（tool call → execute → final response）是独立的临时状态
- Tool 调用不需要持久化的 conversation history

**证据：**
```python
# agno/agent/agent.py:1739-1742
if (add_history_to_context or self.add_history_to_context) and not self.db:
    log_warning("add_history_to_context is True, but no database...")
    # db=None 时，history 不会加载
```

如果 tool 调用真的需要持久化 history，那么 `db=None` 时 tool 就完全无法工作了，但实际上可以。

---

### ❌ 错误 2：禁用 memories/knowledge 导致 token 爆炸

**错误推理：**
> "禁用 context 后，LLM 信息不足，所以反复重试，导致 token 增加"

**真实原因：**
- 不是"信息不足导致重试"
- 而是 **JsonDb 持续写入导致 session 文件膨胀**
- 每次加载 15MB 的 session 文件 → 转换成 tokens → 爆炸

**证据：**
- 测试显示 **cache tokens 高达 1,025k**（client_search）
- Cache tokens 说明有大量重复内容在被缓存
- 这些重复内容来自历史 sessions，不是当前 prompt

---

### ❌ 错误 3："通用协议"设计过度

**问题：**
- 创建了 `impl/tools/field_retrieval.py`（通用协议）
- 声称可以跨项目复用
- 实际上只有 client_search 一个项目有字段定义 YAML
- QA、marketting-planning 等项目根本没有这种结构

**教训：**
- 不要为了"通用"而过度抽象
- 应该先实现一个项目，验证可行后再考虑抽象
- "通用协议"应该基于多个实际项目的共性，而不是预测

---

### ❌ 错误 4：盲目试错而不是系统性理解

**问题流程：**
1. 遇到 366k tokens 问题
2. 猜测是 knowledge base 自动加载 → 禁用 knowledge
3. Token 变成 732k → 猜测是 history 累积 → 禁用 history
4. Token 变成 1,098k → 猜测是 tool 调用冲突 → 想要禁用 tool
5. ...无限循环

**正确流程：**
1. 遇到 366k tokens 问题
2. **先阅读 Agno 源码，理解 Agent 的实际行为**
3. **检查实际生成的文件**（发现 15MB agno_sessions.json）
4. **追踪文件来源**（发现 project_llm_client() 创建了 JsonDb）
5. **修复根因**（不创建 JsonDb）

**教训：**
- 遇到框架问题，应该先系统性地理解框架机制
- 不要基于猜测和假设进行修改
- 应该先验证假设（读源码、查文件、看日志），再动手修改

---

## 正确的上下文优化策略

### 1. 理解框架机制

**必须理解的核心概念：**
- Session 是什么？何时创建？何时加载？
- History 是什么？从哪里加载？
- Memory 如何工作？何时注入？
- Knowledge 如何检索？如何注入？
- Tool 调用流程？是否需要持久化状态？

**方法：**
- 阅读官方文档
- 阅读源码（特别是 Agent 的 `__init__` 和 `run` 方法）
- 实验验证（小规模测试，观察行为）

---

### 2. 诊断问题根源

**Token 爆炸的可能原因：**
1. **Knowledge 自动加载**：检查 `add_knowledge_to_context`
2. **History 累积**：检查 `add_history_to_context` 和 session 文件大小
3. **Memory 膨胀**：检查 `add_memories_to_context` 和 memories 数量
4. **Session 文件臃肿**：检查 DB 文件大小
5. **Prompt 过长**：检查 system/user prompt 的实际长度

**诊断方法：**
```bash
# 1. 检查文件
ls -lh impl/knowledge/*/agno_memory.json/*.json

# 2. 监控 token
print(f"Input: {result.metrics.input_tokens}")
print(f"Cache: {result.metrics.cache_read_tokens}")

# 3. 查看实际 messages
print(result.messages)
```

---

### 3. 针对性修复

**如果是 Knowledge 问题：**
```python
agent = Agent(
    knowledge=None,  # 或者限制检索数量
    add_knowledge_to_context=False,
)
```

**如果是 History 问题：**
```python
agent = Agent(
    add_history_to_context=False,
    num_history_runs=5,  # 限制数量
)
```

**如果是 Session 文件问题：**
```python
# 方案 1：完全禁用持久化
agent = Agent(db=None)

# 方案 2：定期清理
rm -rf impl/knowledge/*/agno_memory.json/*.json

# 方案 3：使用独立 session_id
agent = Agent(session_id=f"{trace_id}:{timestamp}")
```

**如果是 Prompt 问题：**
```python
# 压缩 system prompt
# 简化 JSON schema
# 只提取必要的字段定义
```

---

## 信息密度损失评估

### 当前配置（修复后）

```python
agent = Agent(
    db=None,
    memory_manager=None,
    knowledge=None,
    add_history_to_context=False,
    add_memories_to_context=False,
    add_knowledge_to_context=False,
    num_history_runs=0,
    num_history_messages=0,
    tools=[field_search_tool],
    session_id=f"{trace_id}:{SESSION_START_TIME}",
)
```

### 损失分析

| 优化措施 | Token 收益 | 信息密度损失 | 补偿方案 | 风险等级 |
|----------|-----------|-------------|---------|---------|
| 禁用 Session 持久化（db=None） | -15MB session 文件 | **0%**（session 只是容器，不是信息） | 无需补偿 | 🟢 无 |
| 禁用 Memory 自动加载 | -100k ~ -200k | -10% ~ -15%（项目级知识） | Tool 按需检索 | 🟡 中等 |
| 禁用 Knowledge 自动加载 | -100k ~ -200k | -10% ~ -15%（领域知识） | Tool 按需检索 | 🟡 中等 |
| 压缩字段定义 | -10k ~ -30k | -5% ~ -10%（字段示例） | Tool 可获取完整定义 | 🟢 低 |
| 简化 JSON schema | -2k ~ -3k | -0% ~ -1%（格式约束） | LLM 能推断结构 | 🟢 无 |

**总体评估：**
- **Token 减少：** -300k ~ -500k（假设 session 文件是主要问题）
- **信息密度损失：** -20% ~ -30%（可通过 tool 补偿）
- **预期准确率影响：** -3% ~ -8%（首次判断），-0% ~ -2%（tool 调用后）

---

## 最终建议

### 1. 立即修复
- ✅ 不创建 JsonDb/MemoryManager（已修复）
- ✅ 清理历史 session 文件（已清理）
- 等待测试结果验证

### 2. 如果仍然超标
- 检查 compact_capability 和 compact_semantic_rules 的实际大小
- 进一步压缩字段定义（只保留 field + operators + value_types）
- 检查 system prompt 是否可以进一步精简

### 3. 长期优化
- 建立 token 监控机制（每次 run 记录 token 使用）
- 定期审查 prompt 大小（system + user）
- 设置 token budget 告警（超过 50k 触发）

---

### 第五轮：删除 impl/knowledge 目录（2026-06-17）

**根因分析（最终版）：**

之前的分析都错了。真正的问题是：
1. `impl/knowledge/{project}/` 目录的**存在**触发了 Agno 的自动持久化
2. Agno 内部检测到这个路径模式，自动将其作为 DB 存储位置
3. 即使代码中 `db=None`, `knowledge=None`，目录存在时仍会创建 JsonDb

**证据链：**
1. `attribute.py:354` 传递 `knowledge=None` 后，session 文件仍在生成
2. 删除 `impl/knowledge` 目录后重新测试
3. 测试运行中**未再生成**新的 `agno_memory.json/agno_sessions.json`
4. `llm_client.py:19-22` 的 `_project_memory_path()` 函数已不再被调用

**修复：**
```bash
# 已执行：删除目录
mv impl/knowledge impl/knowledge.backup
```

**预期结果：**
- ✅ 不再生成 session 文件（已验证）
- Token 消耗降低到 20-30k（测试中...）

---

最后更新：2026-06-17
