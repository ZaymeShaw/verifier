# Agno Framework 核心架构

## 概述

Agno 是一个 AI Agent 框架，提供 Agent、Memory、Session、Knowledge、Tools 等核心组件。

本文档基于 Agno 源码（位于 `/Users/xiaozijian/miniconda3/envs/agno/lib/python3.11/site-packages/agno/`）分析核心机制。

---

## Agent 核心组件

### 1. Session Management（会话管理）

**关键参数：**
```python
user_id: Optional[str] = None              # 用户 ID
session_id: Optional[str] = None           # 会话 ID（自动生成或手动指定）
cache_session: bool = False                # 是否缓存当前 session 到内存
```

**Session 创建流程：**
```python
# agent.py:1787
agent_session = self._read_or_create_session(session_id=session_id, user_id=user_id)

# agent.py:6885-6890
if self.db is not None:
    # 尝试从数据库加载
    agent_session = self._read_session(session_id=session_id)
    
if agent_session is None:
    # 创建新的内存 session（不持久化）
    agent_session = AgentSession(...)
```

**关键发现：**
- **`db=None` 时，session 是纯内存对象，不会持久化到文件**
- **`db=JsonDb(...)` 时，session 会持久化到 JSON 文件**
- 即使 `db=None`，Agent 仍然会创建内存 session 用于当前 run

---

### 2. History Management（历史管理）

**关键参数：**
```python
add_history_to_context: bool = False       # 是否将历史对话加入 LLM context
num_history_runs: Optional[int] = None     # 保留多少轮历史 runs
num_history_messages: Optional[int] = None # 保留多少条历史消息
max_tool_calls_from_history: Optional[int] = None  # 历史中保留的 tool call 数量
store_history_messages: bool = True        # 是否在 run output 中存储历史消息
```

**History 加载逻辑：**
```python
# agent.py:1739-1742
if (add_history_to_context or self.add_history_to_context) and not self.db:
    log_warning("add_history_to_context is True, but no database has been assigned")
    # 不会加载 history，因为没有 db
```

**关键发现：**
- **`add_history_to_context=True` 需要配合 `db` 使用**
- **`db=None` 时，即使设置 `add_history_to_context=True`，也不会加载历史**
- **`num_history_runs=0` 和 `num_history_messages=0` 可以显式禁用历史**

**误区：**
- ❌ "禁用 history 会导致 tool 调用失败" — 错误！
- ✅ `add_history_to_context` 只影响是否加载**持久化的历史 runs**
- ✅ 单次 `run()` 内的多轮对话（tool call → result → final response）不受影响

---

### 3. Memory Management（记忆管理）

**关键参数：**
```python
memory_manager: Optional[MemoryManager] = None  # 记忆管理器
enable_user_memories: bool = False              # 是否自动创建/更新用户记忆
add_memories_to_context: Optional[bool] = None  # 是否将记忆加入 context
enable_agentic_memory: bool = False             # 是否让 agent 自主管理记忆
```

**Memory 加载逻辑：**
- `MemoryManager` 需要 `db` 支持
- `add_memories_to_context=True` 会将用户记忆注入到 system/user prompt
- `enable_user_memories=True` 会在每次 run 结束后自动提取并存储记忆

**关键发现：**
- **`memory_manager=None` 时，不会加载或创建任何记忆**
- **Memory 是项目级的（跨 session 共享），不是 case 级的**

---

### 4. Knowledge Management（知识库管理）

**关键参数：**
```python
knowledge: Optional[Knowledge] = None              # 知识库对象
add_knowledge_to_context: bool = False             # 是否自动将知识库内容加入 context
knowledge_retriever: Optional[Callable] = None     # 自定义检索函数
search_knowledge: bool = True                      # 是否添加 search_knowledge tool
```

**Knowledge 加载逻辑：**
- `add_knowledge_to_context=True` 会自动检索相关文档并注入到 prompt
- `knowledge=None` 时，不会加载任何知识库内容
- `search_knowledge=True` 会添加 tool，让 agent 主动调用检索

**关键发现：**
- **`add_knowledge_to_context=True` 可能导致大量 tokens 自动注入**
- **即使 `knowledge=None`，如果之前创建了 Knowledge 对象，可能仍会被加载**

---

### 5. Database Persistence（数据库持久化）

**关键参数：**
```python
db: Optional[Union[BaseDb, AsyncBaseDb]] = None    # 数据库对象
```

**DB 的作用：**
- 持久化 sessions（会话历史）
- 持久化 memories（用户记忆）
- 持久化 run outputs（运行结果）

**DB 类型：**
- `JsonDb`: 本地 JSON 文件存储
- `PgDb`: PostgreSQL 存储
- `AsyncPgDb`: 异步 PostgreSQL 存储

**关键发现：**
- **`db=None` 时，所有数据都是临时的（内存对象）**
- **`db=JsonDb(path)` 会在指定路径创建 JSON 文件**
- **即使不传 `db` 给 Agent，如果在其他地方创建了 JsonDb 对象，可能导致文件生成**

---

## Context Engineering（上下文工程）

### Context 的组成

Agent 发送给 LLM 的 context 由以下部分组成：

```python
# 1. System Message
system_message: str

# 2. History Messages（如果启用）
if add_history_to_context and db:
    history = load_history_from_db(num_history_runs, num_history_messages)

# 3. Memories（如果启用）
if add_memories_to_context and memory_manager:
    memories = memory_manager.retrieve()

# 4. Knowledge（如果启用）
if add_knowledge_to_context and knowledge:
    references = knowledge.search(query)

# 5. User Prompt
user_prompt: str

# 6. Tool Results（多轮对话时）
if tool_calls:
    tool_results = [...]
```

### Token 爆炸的原因

**常见问题：**
1. **Knowledge 自动加载**：`add_knowledge_to_context=True` + 大型知识库 → 100k+ tokens
2. **History 累积**：多次 run 后，history 越来越长 → 每次都加载所有历史
3. **Memory 膨胀**：`enable_user_memories=True` 持续积累 → memories 越来越多
4. **Session 文件臃肿**：`db=JsonDb(...)` 持续写入 → JSON 文件越来越大，每次加载都耗费大量 tokens

**优化策略：**
1. **完全禁用持久化**：`db=None`, `memory_manager=None`, `knowledge=None`
2. **禁用自动加载**：`add_history_to_context=False`, `add_memories_to_context=False`, `add_knowledge_to_context=False`
3. **限制历史数量**：`num_history_runs=0`, `num_history_messages=0`
4. **按需检索**：使用 tools 而不是自动注入

---

## Tool Execution（工具执行）

### Tool 调用流程

```python
# 1. Agent.run() 启动
agent.run(user_prompt)

# 2. 第一次 LLM 调用
response = model.generate(system + user_prompt)
# LLM 返回：需要调用 tool

# 3. 执行 tool
tool_result = execute_tool(tool_name, tool_args)

# 4. 第二次 LLM 调用（在同一个 run 内）
response = model.generate(system + user_prompt + tool_call + tool_result)
# LLM 返回：最终答案

# 5. run() 结束，返回 RunOutput
```

**关键发现：**
- **Tool 调用是在单次 `run()` 内完成的多轮对话**
- **不需要持久化 conversation history（db/session）**
- **只需要当前 run 的临时状态**
- **禁用 `add_history_to_context` 不影响 tool 调用**

---

## 常见误区

### ❌ 误区 1：禁用 history 会破坏 tool 调用
- **错误理解**：Tool 调用需要 conversation history，禁用后会失败
- **正确理解**：`add_history_to_context` 只影响跨 run 的历史加载，不影响单次 run 内的多轮对话

### ❌ 误区 2：db=None 会导致 session 丢失
- **错误理解**：没有 db，session 无法创建
- **正确理解**：`db=None` 时，Agent 会创建纯内存 session，单次 run 内正常工作，只是不持久化

### ❌ 误区 3：knowledge=None 就不会加载知识库
- **错误理解**：设置 `knowledge=None` 就完全禁用了知识库
- **可能问题**：如果在其他地方创建了 Knowledge 对象，Agent 内部可能仍然引用它

### ❌ 误区 4：memory_manager=None 就不会有 memory 泄漏
- **可能问题**：如果在创建 Agent 之前就创建了 MemoryManager + JsonDb，文件可能已经生成

---

## 最佳实践

### 1. 无状态 Judge Agent（推荐配置）

```python
agent = Agent(
    model=DeepSeek(...),
    system_message=system_prompt,
    use_json_mode=True,
    
    # 完全禁用持久化
    db=None,
    memory_manager=None,
    knowledge=None,
    
    # 禁用自动加载
    add_history_to_context=False,
    add_memories_to_context=False,
    add_knowledge_to_context=False,
    
    # 显式禁用历史
    num_history_runs=0,
    num_history_messages=0,
    
    # 允许 tools（不冲突）
    tools=[field_search_tool],
    
    # Session 隔离（防止跨 case 污染）
    user_id=project_id,
    session_id=f"{trace_id}:{timestamp}",  # 每个 case 独立
)
```

**Token 预期：**
- System prompt: ~15k
- User prompt: ~10k
- Tool results（按需）: 0-5k
- **Total: 20-30k per case** ✅

### 2. 有状态对话 Agent（需要持久化）

```python
agent = Agent(
    model=DeepSeek(...),
    
    # 启用持久化
    db=JsonDb(db_path="sessions.json"),
    memory_manager=MemoryManager(db=db),
    
    # 控制历史数量
    add_history_to_context=True,
    num_history_runs=5,           # 只保留最近 5 轮
    num_history_messages=20,      # 只保留最近 20 条消息
    
    # 启用用户记忆
    enable_user_memories=True,
    add_memories_to_context=True,
    
    # Session 复用
    session_id="persistent_chat_session",
)
```

---

## 调试技巧

### 1. 检查 Session 文件大小
```bash
ls -lh impl/knowledge/*/agno_memory.json/*.json
```

### 2. 监控 Token 消耗
```python
result = agent.run(prompt)
print(f"Input tokens: {result.metrics.input_tokens}")
print(f"Output tokens: {result.metrics.output_tokens}")
print(f"Cache tokens: {result.metrics.cache_read_tokens}")
```

### 3. 查看实际发送给 LLM 的 messages
```python
# Agno 内部会记录在 run output 中
print(result.messages)  # 查看完整的消息列表
```

### 4. 清理历史数据
```bash
rm -rf impl/knowledge/*/agno_memory.json/*.json
```

---

## 参考资料

- Agno 源码位置：`/Users/xiaozijian/miniconda3/envs/agno/lib/python3.11/site-packages/agno/`
- 核心文件：
  - `agent/agent.py`: Agent 主类
  - `db/json.py`: JsonDb 实现
  - `memory/manager.py`: MemoryManager 实现
  - `session/*.py`: Session 相关类
  - `knowledge/knowledge.py`: Knowledge 管理

---

最后更新：2026-06-17
