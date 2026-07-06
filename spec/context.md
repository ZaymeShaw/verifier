messages信息分层存储，按需加载这个方向还不错


-------


## 完整方案总结

### 核心理念

**两层结构 + 按需构建**：概念层存全量对话信息，实际层每次 LLM 调用前按当前意图按需构建。

### 两层结构

**概念层**：`[{role, content, name, description}]`

- `role`、`content`：原样不动，就是 messages 的原文
- `name`：唯一标识（tool_call_id、trace_id 等）
- `description`：一句话描述，供构建器做语义匹配

**实际层**：`[{role, content}]`，标准 messages 格式，每次 LLM 调用前从概念层按需构建出来。

### 构建器

每次 LLM 调用前，构建器根据当前意图（轻量 LLM 判断）从概念层挑出相关消息，原样复制 `role` 和 `content` 进实际层。预算不够时优先裁掉已被充分消化过的消息。

### 机制泛化性

- `role` 和 `content` 不变，只在外面加元信息
- 不解析 content 内容，不假设 tool 返回结构
- 构建器只做"放不放"的决策，不修改内容
- 换项目、换 tool、换阶段，机制不变

### 需要改的地方

1. **概念层数据结构**：在现有 messages 基础上加扩展字段（name、description），定义在通用 schema 层
2. **构建器**：独立模块，输入概念层 + 当前意图，输出实际层 messages。内部用轻量 LLM 做语义匹配，不依赖项目结构
3. 应该有一个独立的"概念层管理器"（或者叫 conversation store 之类），所有消息——不管来源是 system/user/assistant/tool——都经过它进概念层，统一填扩展字段。
4. **LLM 调用点**：所有调 LLM 的地方（attribute、judge、check），调用前走构建器拿到实际层，不再直接传全量 messages
5. **外部存储**：概念层本身不存完整 full_data，content 原文就是全量。裁消息只是"不放进去"，不是"删掉"





-------


## 完整解决方案总结

### 核心理念

两层结构 + 按需构建：概念层存全量对话信息（带元数据），实际层每次 LLM 调用前从概念层按当前意图按需构建。`role` 和 `content` 始终是 messages 原文不动，扩展字段全是附加元信息。

### Schema 设计

**概念层 Message（扩展 messages）**：
```
role: string              # 不动，system/user/assistant/tool
content: string           # 不动，原文
name: string              # 唯一标识（tool_call_id、trace_id 等）
description: string       # 一句话描述，构建器做语义匹配用
```
扩展字段只有这2个——标识、语义摘要。不解析 content 内容，不假设结构，泛化。

**实际层 Message**：标准 `[{role, content}]`，不扩展。

**ConceptLayer（概念层容器）**：
```
messages: list[Message]    # 全量对话
project_id: string
session_id: string
```

**ActualLayerBuild（构建产物）**：
```
messages: list[{role, content}]  # 实际传给 LLM 的
budget_used: int
dropped: list[name]              # 这次没放进去的，调试用
```

### 模块归属

- **概念层管理器**（独立通用模块）：所有消息（system/user/assistant/tool）统一进出，统一填扩展字段。不绑 tool。
- **构建器**（独立模块）：输入概念层 + 当前意图，输出实际层 messages。用轻量 LLM 做 description 语义匹配，按 len 做预算控制，原样复制 role/content 不改内容。
- **ToolOrchestrator**：回归薄层，只执行 tool 调用返回 ToolResult，调完把结果交给概念层管理器，不背概念层写入职责。

### 后端 API 接口建议

**需要构建**，因为概念层是持久状态、实际层是临时构建产物，前端/调试/跨阶段都需要访问。建议这几个：

1. `POST /api/concept_layer` — 写入消息（所有来源统一入口），自动填 name/description/len
2. `GET /api/concept_layer/{session_id}` — 读全量概念层（调试/前端展示用）
3. `POST /api/concept_layer/{session_id}/build` — 入参当前意图，触发构建器产出实际层 messages，返回 `[{role, content}]` + 预算/丢弃信息
4. `GET /api/concept_layer/{session_id}/message/{name}` — 按 name 回查单条消息原文（按需加载的底层支撑）

**不必须**做成 REST 的部分：构建器内部那次轻量 LLM 调用、预算裁剪逻辑——这些是构建器内部实现，不暴露 API。

### 需要改的地方（泛化层）

1. 通用 schema 层加 `Message`（概念层扩展）+ `ConceptLayer` 定义
2. 新增概念层管理器模块（统一写入入口）
3. 新增构建器模块（按意图构建实际层）
4. 所有 LLM 调用点（attribute/judge/check）调用前走构建器，不再直接传全量 messages
5. 后端 routes 加上面四个 API

### 泛化性保证

- `role`/`content` 不变，只加三个元信息字段
- 不解析 content，不假设 tool 返回结构
- 概念层管理对所有消息一视同仁，不为 tool 单独写逻辑
- 构建器只看 description（语义）和 len（预算），不看内容
- 测评系统代码改了，只要消息还是 `[{role, content}]` 格式，这套机制照常工作





---------


好，逐一回答：

## 1. 跟 context.html 怎么配合

context.html 现在展示的是 LLM 调用的原始记录（system prompt、user prompt、assistant 输出、tool 调用），从 `context_store` 读。概念层引入后：

- **概念层变成 context.html 的数据源**：概念层存全量对话，带 name/description/len 扩展字段，context.html 可以直接从概念层读，展示更结构化——每条消息除了原文还有标识、语义摘要、长度
- **实际层构建过程也可以展示**：构建器每次构建时，哪些消息被挑中、哪些被丢弃、预算使用情况，这些产物可以挂到概念层上，context.html 展示"为什么这次 LLM 看到了这些消息"
- **不冲突，是升级**：context.html 现在的核心功能（查看 LLM 上下文）不变，只是数据源从 `context_store` 变成概念层，展示更丰富

## 2. 需要改哪些模块，改动大吗

**核心改动**：

| 模块 | 改动 | 大小 |
|------|------|------|
| 通用 schema 层 | 加 `Message`（含扩展字段）定义 | 小 |
| 概念层管理器 | 新增模块，统一消息写入入口 | 中 |
| 构建器 | 新增模块，每次 LLM 调用前构建实际层 | 中 |
| LLM 调用点（attribute/judge/check） | 调用前走构建器，不再直接传全量 messages | 小（只改调用方式，不改逻辑） |
| ToolOrchestrator | 回归薄层，不再背概念层职责 | 小 |
| 后端 routes | 加 3-4 个 API，context.html 数据源切换 | 小 |
| context_store | 保留但数据源切到概念层 | 小 |

**改动不大**：核心是加两个新模块（概念层管理器 + 构建器），现有模块改调用方式。schema 层加几个字段定义。LLM 调用逻辑不变，只是传参方式从"全量 messages"变成"构建器产出的 messages"。

## 3. 是不是不能无限制追加历史了 + 怎么传参给 agno

**对，不能无限制追加了**。概念层存全量，但实际层每次构建都有预算控制，超出预算的消息会被裁剪（不放进实际层）。观念上从"追加历史"变成"每次构建当前需要看到的消息"。

**传参方式**：agno 的 `Agent.run(user)` 接受的 `user` 是单条 user message。现在 LLM 的 `tools` 参数照常传（VerifiableTool 的 execute_fn 列表），但 `system_message` 和 `user` 的构建方式变了：

- `system_message`：从概念层按当前意图构建，包含 system prompt + 裁剪后的历史摘要
- `user`：当前 case 的上下文（trace + judge + 归因目标），从概念层按需构建
- agent 内部的多轮 tool 调用由 agno 自己管理（agno 管 agent 内部的 messages 循环），**概念层/构建器管的是"每次 agno Agent.run() 之前"的 messages 构建**

换句话说：agno 负责 agent 内部一轮 run 里的 tool calling 循环（这是 agno 自己的事），构建器负责"每次 run 开始前，给 agno 什么样的 system_message 和 user"。两者不冲突，构建器管的是 agno 的入口，不干涉 agno 内部的 tool calling 循环。




--------


你说得对，我后面那段传参方式确实不对。

## 错在哪

我说"system_message 和 user 从概念层按需构建，agent 内部 tool calling 循环归 agno 自己管"——这把 agno 当成了一个"只接收 system_message + user、然后自己内部跑 tool 循环"的黑盒。但实际上归因是**多轮的**：LLM 调一个 tool，消化结果，再决定调下一个 tool，这个循环本身就是归因推理的进行过程。如果这个循环归 agno 内部管、概念层只在"每次 run 开始前"介入，那 tool 之间的多轮推理上下文根本没被概念层管理——agno 内部 messages 还是无限制追加的，问题没解决。

## 真正的矛盾

概念层要管"所有消息"，但 agno 的 `Agent.run()` 内部自己维护 messages 循环（system + user + assistant + tool 的多轮），这部分概念层插不进去。我前面想用"构建器管入口、agno 管内部循环"来回避这个矛盾，但回避不了——agent 内部那几轮 tool calling 的 messages 才是 context 膨胀最严重的地方，恰恰是概念层最该管的。

## 实际该怎么配合

概念层要真正起作用，不能只在 agno 入口介入，得在 agno 的 **每轮 tool 调用之间** 也介入。但 agno 内部的 messages 循环不暴露给外部——所以要么：

1. **不用 agno 的 Agent.run 整体托管，自己实现 tool calling 循环**：每轮 LLM 调用前走构建器拿实际层 messages，调完一条 tool 把结果写回概念层，下一轮再构建。这样概念层全程管控。
2. **用 agno 但把它降级成"单次 LLM 调用 + tool 执行"的薄封装**：不让它自动跑多轮，自己在外层控制循环。

我前面回避了这个核心选择，导致传参方式自相矛盾。这是需要先定的：**到底是自己实现 tool calling 循环，还是压着 agno 用它单轮能力**。这个不定，概念层怎么介入 agno 就讲不清。


--------

## 现在 agno 的循环构建有什么可取之处

没有可取之处。现在 agno 的 `Agent.run()` 内部就是"LLM 调 → 返回 tool call → 执行 tool → 结果塞回 messages → 再调 LLM"，直到 LLM 说不用调了。这个循环没有预算控制、没有上下文裁剪、没有消息分层——messages 就是扁平追加，tool result 全量进 messages 永远不裁。这就是为什么 context 会膨胀到不可控。

## 你选的方案

用 agno 但降级成"单次 LLM 调用 + tool 执行"的薄封装。这个方案的核心是：**不再用 agno 的 Agent.run 托管多轮循环，每次只让 agno 做一次 LLM 调用**。外层自己控制循环，每轮之间走概念层构建器。

具体做法：agno 只负责"给 messages → 调 LLM → 返回 response（可能是文本，也可能是 tool call）"。拿到 response 后，外层判断：如果是文本（归因结论），结束；如果是 tool call，交给 ToolOrchestrator 执行，结果写回概念层，下一轮调用前走构建器重新构建实际层 messages，再交给 agno 做下一次单次调用。

概念层在这个循环里全程介入：每轮开始前构建实际层，每轮 tool 执行完写回概念层，完全控制 messages 的可见性和体积。